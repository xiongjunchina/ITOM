"""Policy-compatible provider selection, fallback, and minimal call auditing."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import inspect
from time import perf_counter

from sqlalchemy.orm import Session

from app.assistant.providers import (
    ChatRequest,
    ModelProvider,
    OpenAICompatibleProvider,
    ProviderConfigurationError,
    ProviderError,
    ProviderPurpose,
)
from app.assistant.redaction import redact_for_log
from app.assistant.types import RiskLevel
from app.core.config import settings
from app.db import SessionLocal
from app.models import AiProviderCall, AiProviderConfig


class GatewayError(Exception):
    """A stable, secret-free gateway failure safe for client mapping."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class AssistantGateway:
    """Stream through one healthy provider and at most its declared fallback."""

    def __init__(
        self,
        db: Session | None,
        *,
        primary_provider_id: str | None = None,
        provider_factory: Callable[[AiProviderConfig], ModelProvider] | None = None,
        session_factory: Callable[[], Session] | None = None,
        audit_session_factory: Callable[[], Session] | None = None,
        probe_max_age_seconds: int = 900,
        now: Callable[[], datetime] | None = None,
    ):
        self.db = db
        self.primary_provider_id = primary_provider_id
        self.provider_factory = provider_factory or self._default_provider
        self.session_factory = session_factory or SessionLocal
        self.audit_session_factory = audit_session_factory or SessionLocal
        self.probe_max_age = timedelta(seconds=probe_max_age_seconds)
        self.now = now or (lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    async def stream(self, request: ChatRequest):
        purpose = _request_purpose(request)
        risk = _request_risk(request)
        if risk is RiskLevel.L4:
            raise GatewayError("GATEWAY_RISK_FORBIDDEN", "the requested risk level is not available")
        providers = self._provider_chain()
        attempted = False

        for position, config in enumerate(providers):
            if not self._compatible(config, request):
                continue
            attempted = True
            started = perf_counter()
            provider = None
            emitted = False
            terminal_event = None
            input_tokens = 0
            output_tokens = 0
            try:
                provider = self.provider_factory(config)
                async for event in provider.stream_chat(request):
                    if event.kind == "done":
                        if terminal_event is not None:
                            raise ProviderError(
                                "PROVIDER_STREAM_PROTOCOL_ERROR",
                                "provider stream protocol validation failed",
                            )
                        terminal_event = event
                        continue
                    if event.kind == "usage":
                        input_tokens = event.input_tokens
                        output_tokens = event.output_tokens
                    emitted = True
                    yield event
                if terminal_event is None:
                    raise ProviderError(
                        "PROVIDER_STREAM_PROTOCOL_ERROR",
                        "provider stream protocol validation failed",
                    )
            except (asyncio.CancelledError, GeneratorExit):
                self._audit(
                    config,
                    request,
                    purpose,
                    started,
                    result_code="PROVIDER_STREAM_CANCELLED",
                    status="cancelled",
                    error={
                        "code": "PROVIDER_STREAM_CANCELLED",
                        "message": "provider stream was cancelled by the caller",
                    },
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                raise
            except ProviderError as exc:
                self._audit(
                    config,
                    request,
                    purpose,
                    started,
                    result_code=exc.code,
                    status="failed",
                    error={"code": exc.code, "message": exc.message},
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                if emitted:
                    raise GatewayError("GATEWAY_STREAM_FAILED", "model stream failed after output began") from None
                continue
            except ProviderConfigurationError:
                self._audit(
                    config,
                    request,
                    purpose,
                    started,
                    result_code="PROVIDER_CONFIG_INVALID",
                    status="failed",
                    error={"code": "PROVIDER_CONFIG_INVALID", "message": "provider configuration is invalid"},
                )
                continue
            except Exception:
                self._audit(
                    config,
                    request,
                    purpose,
                    started,
                    result_code="PROVIDER_INTERNAL_ERROR",
                    status="failed",
                    error={"code": "PROVIDER_INTERNAL_ERROR", "message": "provider call failed safely"},
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                if emitted:
                    raise GatewayError("GATEWAY_STREAM_FAILED", "model stream failed after output began") from None
                continue
            else:
                audited = self._audit(
                    config,
                    request,
                    purpose,
                    started,
                    result_code="OK" if position == 0 else "OK_FALLBACK",
                    status="completed",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                if not audited:
                    raise GatewayError(
                        "GATEWAY_AUDIT_FAILED",
                        "provider call completed but its audit could not be persisted",
                    )
                yield terminal_event
                return
            finally:
                if provider is not None:
                    close = getattr(provider, "aclose", None)
                    if close is not None:
                        result = close()
                        if inspect.isawaitable(result):
                            await result

        if attempted:
            raise GatewayError("GATEWAY_ALL_PROVIDERS_FAILED", "all compatible model providers failed")
        raise GatewayError("GATEWAY_NO_COMPATIBLE_PROVIDER", "no compatible model provider is available")

    def _provider_chain(self) -> list[AiProviderConfig]:
        owns_session = self.db is None
        db = self.session_factory() if owns_session else self.db
        if db is None:
            return []
        try:
            if self.primary_provider_id:
                primary = db.get(AiProviderConfig, self.primary_provider_id)
            else:
                primary = db.query(AiProviderConfig).filter(
                    AiProviderConfig.is_primary.is_(True),
                    AiProviderConfig.is_deleted.is_(False),
                ).order_by(AiProviderConfig.created_at, AiProviderConfig.id).first()
            if primary is None:
                return []
            providers = [primary]
            if primary.fallback_provider_id and primary.fallback_provider_id != primary.id:
                fallback = db.get(AiProviderConfig, primary.fallback_provider_id)
                if fallback is not None:
                    providers.append(fallback)
            if owns_session:
                for config in providers:
                    db.expunge(config)
            return providers
        finally:
            if owns_session:
                try:
                    db.rollback()
                finally:
                    db.close()

    def _compatible(self, config: AiProviderConfig, request: ChatRequest) -> bool:
        if (
            config.is_deleted
            or not config.enabled
            or config.provider_type != "openai_compatible"
            or config.probe_status != "success"
            or not config.api_base_url
            or not config.model
            or config.last_probed_at is None
        ):
            return False
        probed_at = _naive_utc(config.last_probed_at)
        current = _naive_utc(self.now())
        age = current - probed_at
        if age < timedelta(0) or age > self.probe_max_age:
            return False
        if _request_risk(request) in {RiskLevel.L2, RiskLevel.L3}:
            capabilities = config.capability_probe if isinstance(config.capability_probe, dict) else {}
            if (
                capabilities.get("supports_streaming") is not True
                or capabilities.get("supports_tools") is not True
                or capabilities.get("supports_json_schema") is not True
            ):
                return False
        return True

    def _audit(
        self,
        config: AiProviderConfig,
        request: ChatRequest,
        purpose: ProviderPurpose,
        started: float,
        *,
        result_code: str,
        status: str,
        error: dict | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> bool:
        try:
            audit_db = self.audit_session_factory()
        except Exception:
            return False
        try:
            audit_db.add(
                AiProviderCall(
                    provider_id=config.id,
                    conversation_id=request.conversation_id,
                    message_id=request.message_id,
                    profile_version_id=request.profile_version_id,
                    model=str(config.model),
                    purpose=purpose.value,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    duration_ms=max(0, int((perf_counter() - started) * 1000)),
                    result_code=result_code,
                    status=status,
                    error_redacted=redact_for_log(error) if error else None,
                )
            )
            audit_db.commit()
            return True
        except Exception:
            try:
                audit_db.rollback()
            except Exception:
                pass
            return False
        finally:
            try:
                audit_db.close()
            except Exception:
                pass

    @staticmethod
    def _default_provider(config: AiProviderConfig) -> ModelProvider:
        return OpenAICompatibleProvider(
            config,
            allowed_hosts=settings.ai_provider_allowed_hosts,
            connect_timeout_seconds=settings.ai_provider_connect_timeout_seconds,
            read_timeout_seconds=settings.ai_provider_read_timeout_seconds,
        )


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _request_risk(request: ChatRequest) -> RiskLevel:
    try:
        return RiskLevel.coerce(request.risk_level)
    except (TypeError, ValueError):
        raise GatewayError("GATEWAY_RISK_FORBIDDEN", "the requested risk level is not available") from None


def _request_purpose(request: ChatRequest) -> ProviderPurpose:
    if not isinstance(request.purpose, ProviderPurpose):
        raise GatewayError("GATEWAY_PURPOSE_INVALID", "the provider request purpose is invalid")
    return request.purpose
