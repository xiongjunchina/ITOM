"""Transactional governance for WA0 providers and agent profiles.

The database stores configuration only. Executable assistant capabilities
remain owned by the fixed in-process registry.
"""

from datetime import datetime, timedelta, timezone
import inspect
from types import SimpleNamespace
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assistant.registry import registry as capability_registry
from app.assistant.types import RiskLevel
from app.assistant.providers import OpenAICompatibleProvider, ProviderConfigurationError, ProviderError
from app.core.config import settings
from app.core.errors import AppError
from app.models import AiAction, AiAgentProfile, AiAgentProfileVersion, AiProviderCall, AiProviderConfig, AuthUser
from app.services.audit import audit
from app.services.secrets_store import encrypt_secret


PROBE_MAX_AGE = timedelta(minutes=15)
PROFILE_AUDIENCES = {
    "requester": "requester",
    "bdo": "bdo",
    "it_staff": "it",
    "admin": "admin",
}
PROFILE_NAMES = {
    "requester": "业务用户助手",
    "bdo": "BDO 助手",
    "it_staff": "IT 员工助手",
    "admin": "管理员助手",
}
KNOWLEDGE_SCOPES = {
    "requester": frozenset({"public", "service_catalog", "own_records"}),
    "bdo": frozenset({"public", "service_catalog", "own_records", "own_requirements"}),
    "it": frozenset({"public", "service_catalog", "own_records", "internal_knowledge", "authorized_records"}),
    "admin": frozenset({
        "public", "service_catalog", "own_records", "own_requirements", "internal_knowledge",
        "authorized_records", "governance",
    }),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _provider_or_404(db: Session, provider_id: str) -> AiProviderConfig:
    row = db.get(AiProviderConfig, provider_id)
    if row is None or row.is_deleted:
        raise AppError("AI_PROVIDER_NOT_FOUND", "模型提供商不存在", 404)
    return row


def _safe_capability_probe(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "authentication",
        "supports_streaming",
        "supports_tools",
        "supports_json_schema",
        "error_code",
        "error_message",
    }
    return {key: value[key] for key in allowed if key in value and isinstance(value[key], (bool, str, type(None)))}


def provider_payload(row: AiProviderConfig) -> dict[str, Any]:
    """Return the explicit write-only-secret response allowlist."""
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "provider_type": row.provider_type,
        "api_base_url": row.api_base_url,
        "model": row.model,
        "timeout_seconds": row.timeout_seconds,
        "max_output_tokens": row.max_output_tokens,
        "temperature": row.temperature,
        "capability_probe": _safe_capability_probe(row.capability_probe),
        "probe_status": row.probe_status,
        "last_probed_at": row.last_probed_at,
        "is_primary": row.is_primary,
        "fallback_provider_id": row.fallback_provider_id,
        "enabled": row.enabled,
        "has_secret": bool(row.api_key_encrypted),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_providers(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.query(AiProviderConfig)
        .filter(AiProviderConfig.is_deleted.is_(False))
        .order_by(AiProviderConfig.created_at, AiProviderConfig.id)
        .all()
    )
    return [provider_payload(row) for row in rows]


def _validate_provider_config(values: dict[str, Any]) -> None:
    if values.get("provider_type") != "openai_compatible":
        raise AppError("AI_PROVIDER_TYPE_UNSUPPORTED", "首期仅支持 OpenAI-compatible 提供商")
    candidate = SimpleNamespace(
        api_base_url=values.get("api_base_url"),
        model=values.get("model"),
        max_output_tokens=values.get("max_output_tokens"),
        temperature=values.get("temperature"),
        api_key_encrypted=None,
    )
    try:
        OpenAICompatibleProvider(candidate, allowed_hosts=settings.ai_provider_allowed_hosts)
    except ProviderConfigurationError as exc:
        raise AppError("AI_PROVIDER_CONFIG_INVALID", str(exc)) from None


def _set_primary(db: Session, row: AiProviderConfig) -> None:
    db.query(AiProviderConfig).filter(
        AiProviderConfig.id != row.id,
        AiProviderConfig.is_primary.is_(True),
        AiProviderConfig.is_deleted.is_(False),
    ).update({AiProviderConfig.is_primary: False}, synchronize_session=False)


def _validate_fallback(db: Session, row: AiProviderConfig, fallback_id: str | None) -> None:
    if fallback_id is None:
        return
    if fallback_id == row.id:
        raise AppError("AI_PROVIDER_FALLBACK_INVALID", "提供商不能回退到自身")
    current = _provider_or_404(db, fallback_id)
    seen = {row.id}
    while current is not None:
        if current.id in seen:
            raise AppError("AI_PROVIDER_FALLBACK_INVALID", "提供商回退链不能形成循环")
        seen.add(current.id)
        current = db.get(AiProviderConfig, current.fallback_provider_id) if current.fallback_provider_id else None


def _probe_is_usable(row: AiProviderConfig) -> bool:
    if row.probe_status != "success" or row.last_probed_at is None:
        return False
    age = _utcnow() - row.last_probed_at
    probe = row.capability_probe if isinstance(row.capability_probe, dict) else {}
    return timedelta(0) <= age <= PROBE_MAX_AGE and probe.get("authentication") is True and probe.get("supports_streaming") is True


def create_provider(db: Session, values: dict[str, Any], actor: AuthUser) -> dict[str, Any]:
    if values.get("enabled"):
        raise AppError("AI_PROVIDER_PROBE_REQUIRED", "提供商通过安全探测后才能启用", 409)
    _validate_provider_config(values)
    secret = values.pop("api_key", None)
    row = AiProviderConfig(**values)
    row.api_key_encrypted = encrypt_secret(secret) if isinstance(secret, str) and secret.strip() else None
    try:
        db.add(row)
        db.flush()
        _validate_fallback(db, row, row.fallback_provider_id)
        if row.is_primary:
            _set_primary(db, row)
        audit(
            db,
            "ai_provider_config",
            row.id,
            "create",
            actor,
            {"code": row.code, "provider_type": row.provider_type, "has_secret": bool(row.api_key_encrypted)},
        )
        db.commit()
    except AppError:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise AppError("AI_PROVIDER_CODE_EXISTS", "模型提供商编码已存在", 409) from None
    return provider_payload(row)


def update_provider(db: Session, provider_id: str, values: dict[str, Any], actor: AuthUser) -> dict[str, Any]:
    row = _provider_or_404(db, provider_id)
    secret = values.pop("api_key", None)
    candidate = {
        "provider_type": values.get("provider_type", row.provider_type),
        "api_base_url": values.get("api_base_url", row.api_base_url),
        "model": values.get("model", row.model),
        "max_output_tokens": values.get("max_output_tokens", row.max_output_tokens),
        "temperature": values.get("temperature", row.temperature),
    }
    _validate_provider_config(candidate)
    if "fallback_provider_id" in values:
        _validate_fallback(db, row, values["fallback_provider_id"])

    changed_probe_inputs = any(
        key in values and values[key] != getattr(row, key)
        for key in ("provider_type", "api_base_url", "model")
    ) or (isinstance(secret, str) and bool(secret.strip()))
    if values.get("enabled") is True and (changed_probe_inputs or not _probe_is_usable(row)):
        raise AppError("AI_PROVIDER_PROBE_REQUIRED", "提供商通过安全探测后才能启用", 409)

    changed_fields = sorted(values)
    for key, value in values.items():
        setattr(row, key, value)
    if isinstance(secret, str) and secret.strip():
        row.api_key_encrypted = encrypt_secret(secret)
        changed_fields.append("api_key")
    if changed_probe_inputs:
        row.probe_status = "unverified"
        row.capability_probe = {}
        row.last_probed_at = None
        row.enabled = False
    if row.is_primary:
        _set_primary(db, row)
    audit(
        db,
        "ai_provider_config",
        row.id,
        "update",
        actor,
        {"fields": changed_fields, "probe_invalidated": changed_probe_inputs, "has_secret": bool(row.api_key_encrypted)},
    )
    db.commit()
    return provider_payload(row)


def delete_provider(db: Session, provider_id: str, actor: AuthUser) -> dict[str, str]:
    row = _provider_or_404(db, provider_id)
    profile_reference = db.query(AiAgentProfile.id).filter(
        AiAgentProfile.default_provider_id == row.id,
        AiAgentProfile.is_deleted.is_(False),
    ).first()
    fallback_reference = db.query(AiProviderConfig.id).filter(
        AiProviderConfig.fallback_provider_id == row.id,
        AiProviderConfig.is_deleted.is_(False),
    ).first()
    if profile_reference or fallback_reference:
        raise AppError("AI_PROVIDER_IN_USE", "模型提供商仍被档案或回退链引用", 409)
    row.is_deleted = True
    row.enabled = False
    row.is_primary = False
    audit(db, "ai_provider_config", row.id, "delete", actor, {"code": row.code})
    db.commit()
    return {"id": row.id}


def _provider_for_probe(row: AiProviderConfig):
    return OpenAICompatibleProvider(
        row,
        allowed_hosts=settings.ai_provider_allowed_hosts,
        connect_timeout_seconds=settings.ai_provider_connect_timeout_seconds,
        read_timeout_seconds=settings.ai_provider_read_timeout_seconds,
    )


async def probe_provider(db: Session, provider_id: str, actor: AuthUser) -> dict[str, Any]:
    """Run Task 3's exact sequential probe and persist one truthful atomic result."""
    row = (
        db.query(AiProviderConfig)
        .filter(AiProviderConfig.id == provider_id, AiProviderConfig.is_deleted.is_(False))
        .with_for_update()
        .first()
    )
    if row is None:
        raise AppError("AI_PROVIDER_NOT_FOUND", "模型提供商不存在", 404)

    adapter = None
    failure: tuple[str, str] | None = None
    checked_at = _utcnow()
    try:
        adapter = _provider_for_probe(row)
        probe = await adapter.probe()
        checked_at = probe.checked_at.astimezone(timezone.utc).replace(tzinfo=None) if probe.checked_at.tzinfo else probe.checked_at
        capabilities = {
            "authentication": bool(probe.success),
            "supports_streaming": bool(probe.supports_streaming),
            "supports_tools": bool(probe.supports_tools),
            "supports_json_schema": bool(probe.supports_json_schema),
        }
        if not probe.success:
            failure = ("PROVIDER_AUTH_FAILED", "provider authentication probe failed")
        elif not probe.supports_streaming:
            failure = ("PROVIDER_STREAM_UNSUPPORTED", "provider streaming probe failed")
    except ProviderError as exc:
        capabilities = {
            "authentication": False,
            "supports_streaming": False,
            "supports_tools": False,
            "supports_json_schema": False,
            "error_code": exc.code,
            "error_message": exc.message,
        }
        failure = (exc.code, exc.message)
    except ProviderConfigurationError:
        capabilities = {
            "authentication": False,
            "supports_streaming": False,
            "supports_tools": False,
            "supports_json_schema": False,
            "error_code": "PROVIDER_CONFIG_INVALID",
            "error_message": "provider configuration is invalid",
        }
        failure = ("PROVIDER_CONFIG_INVALID", "provider configuration is invalid")
    except Exception:
        capabilities = {
            "authentication": False,
            "supports_streaming": False,
            "supports_tools": False,
            "supports_json_schema": False,
            "error_code": "PROVIDER_INTERNAL_ERROR",
            "error_message": "provider probe failed safely",
        }
        failure = ("PROVIDER_INTERNAL_ERROR", "provider probe failed safely")
    finally:
        if adapter is not None:
            close = getattr(adapter, "aclose", None)
            if close is not None:
                result = close()
                if inspect.isawaitable(result):
                    await result

    if failure is not None and "error_code" not in capabilities:
        capabilities["error_code"] = failure[0]
        capabilities["error_message"] = failure[1]
    row.capability_probe = capabilities
    row.probe_status = "failed" if failure else "success"
    row.last_probed_at = checked_at
    if failure:
        row.enabled = False
    audit(
        db,
        "ai_provider_config",
        row.id,
        "probe_failed" if failure else "probe",
        actor,
        {
            "probe_status": row.probe_status,
            "capabilities": _safe_capability_probe(capabilities),
        },
    )
    db.commit()
    if failure:
        raise AppError("AI_PROVIDER_PROBE_FAILED", failure[1])
    return provider_payload(row)


def _require_profile_code(code: str) -> str:
    if code not in PROFILE_AUDIENCES:
        raise AppError("AI_PROFILE_NOT_FOUND", "智能体档案不存在", 404)
    return code


def _ensure_profiles(db: Session, actor: AuthUser) -> None:
    existing = {
        row.code
        for row in db.query(AiAgentProfile).filter(
            AiAgentProfile.code.in_(tuple(PROFILE_AUDIENCES)),
            AiAgentProfile.is_deleted.is_(False),
        )
    }
    created = []
    now = _utcnow()
    for code, audience in PROFILE_AUDIENCES.items():
        if code in existing:
            continue
        profile = AiAgentProfile(
            code=code,
            name=PROFILE_NAMES[code],
            audience=audience,
            max_risk_level="L1",
            status="draft",
            enabled=False,
        )
        db.add(profile)
        db.flush()
        draft = AiAgentProfileVersion(
            profile_id=profile.id,
            version=0,
            status="draft",
            enabled_capabilities=[],
            knowledge_scope=[],
            max_risk_level="L1",
            updated_at=now,
        )
        db.add(draft)
        db.flush()
        audit(db, "ai_agent_profile", profile.id, "bootstrap_draft", actor, {"code": code, "audience": audience})
        created.append(code)
    if created:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # A concurrent bootstrap may have won the unique keys. Verify the
            # fixed set now exists instead of creating a second profile.
            current = {
                row.code
                for row in db.query(AiAgentProfile).filter(
                    AiAgentProfile.code.in_(tuple(PROFILE_AUDIENCES)),
                    AiAgentProfile.is_deleted.is_(False),
                )
            }
            if current != set(PROFILE_AUDIENCES):
                raise AppError("AI_PROFILE_BOOTSTRAP_CONFLICT", "智能体档案初始化冲突，请重试", 409) from None


def _profile_and_draft(db: Session, code: str, *, lock: bool = False) -> tuple[AiAgentProfile, AiAgentProfileVersion]:
    _require_profile_code(code)
    query = db.query(AiAgentProfile).filter(
        AiAgentProfile.code == code,
        AiAgentProfile.is_deleted.is_(False),
    )
    if lock:
        query = query.with_for_update()
    profile = query.first()
    if profile is None:
        raise AppError("AI_PROFILE_NOT_FOUND", "智能体档案不存在", 404)
    draft_query = db.query(AiAgentProfileVersion).filter(
        AiAgentProfileVersion.profile_id == profile.id,
        AiAgentProfileVersion.version == 0,
        AiAgentProfileVersion.status == "draft",
        AiAgentProfileVersion.is_deleted.is_(False),
    )
    if lock:
        draft_query = draft_query.with_for_update()
    draft = draft_query.first()
    if draft is None:
        raise AppError("AI_PROFILE_DRAFT_NOT_FOUND", "智能体档案草稿不存在", 404)
    return profile, draft


def _latest_published(db: Session, profile_id: str) -> AiAgentProfileVersion | None:
    return (
        db.query(AiAgentProfileVersion)
        .filter(
            AiAgentProfileVersion.profile_id == profile_id,
            AiAgentProfileVersion.status == "published",
            AiAgentProfileVersion.is_deleted.is_(False),
        )
        .order_by(AiAgentProfileVersion.version.desc())
        .first()
    )


def profile_draft_payload(db: Session, profile: AiAgentProfile, draft: AiAgentProfileVersion) -> dict[str, Any]:
    latest = _latest_published(db, profile.id)
    return {
        "id": profile.id,
        "code": profile.code,
        "name": profile.name,
        "audience": profile.audience,
        "default_provider_id": profile.default_provider_id,
        "retention_days": profile.retention_days,
        "status": profile.status,
        "enabled": profile.enabled,
        "system_prompt_zh": draft.system_prompt_zh,
        "system_prompt_en": draft.system_prompt_en,
        "enabled_capabilities": list(draft.enabled_capabilities or []),
        "knowledge_scope": list(draft.knowledge_scope or []),
        "max_risk_level": draft.max_risk_level,
        "draft_updated_at": draft.updated_at,
        "latest_published_version": latest.version if latest else None,
    }


def get_profile_draft(db: Session, code: str, actor: AuthUser) -> dict[str, Any]:
    _require_profile_code(code)
    _ensure_profiles(db, actor)
    profile, draft = _profile_and_draft(db, code)
    return profile_draft_payload(db, profile, draft)


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _assert_revision(actual: datetime | None, expected: datetime, code: str = "AI_PROFILE_DRAFT_STALE") -> None:
    if actual is None or _naive_utc(actual) != _naive_utc(expected):
        raise AppError(code, "智能体档案已被其他管理员修改，请刷新后重试", 409)


def _risk(value: str) -> RiskLevel:
    try:
        risk = RiskLevel.coerce(value)
    except ValueError:
        raise AppError("AI_PROFILE_RISK_INVALID", "智能体档案风险等级无效") from None
    if risk is RiskLevel.L4:
        raise AppError("AI_PROFILE_RISK_INVALID", "智能体档案不得启用 L4 能力")
    return risk


def _validate_profile_limits(
    profile: AiAgentProfile,
    enabled_capabilities: object,
    knowledge_scope: object,
    max_risk_level: str,
) -> list[Any]:
    risk = _risk(max_risk_level)
    if not isinstance(enabled_capabilities, list) or any(not isinstance(code, str) for code in enabled_capabilities):
        raise AppError("AI_PROFILE_CAPABILITY_INVALID", "智能体档案能力列表无效")
    if len(enabled_capabilities) != len(set(enabled_capabilities)):
        raise AppError("AI_PROFILE_CAPABILITY_INVALID", "智能体档案能力代码不能重复")
    definitions = []
    for code in enabled_capabilities:
        definition = capability_registry.get(code)
        if definition is None or definition.risk is RiskLevel.L4:
            raise AppError("AI_PROFILE_CAPABILITY_INVALID", "档案只能选择服务端已注册的安全能力")
        if profile.audience not in definition.audiences:
            raise AppError("AI_PROFILE_AUDIENCE_INVALID", "档案能力超出该受众的服务端边界")
        if definition.risk.rank > risk.rank:
            raise AppError("AI_PROFILE_RISK_INVALID", "档案能力高于配置的最高风险等级")
        definitions.append(definition)
    if not isinstance(knowledge_scope, list) or any(not isinstance(scope, str) for scope in knowledge_scope):
        raise AppError("AI_PROFILE_KNOWLEDGE_INVALID", "智能体档案知识范围无效")
    if len(knowledge_scope) != len(set(knowledge_scope)) or not set(knowledge_scope).issubset(KNOWLEDGE_SCOPES[profile.audience]):
        raise AppError("AI_PROFILE_KNOWLEDGE_INVALID", "智能体档案知识范围超出受众边界")
    return definitions


def update_profile_draft(
    db: Session,
    code: str,
    values: dict[str, Any],
    expected_updated_at: datetime,
    actor: AuthUser,
) -> dict[str, Any]:
    _require_profile_code(code)
    _ensure_profiles(db, actor)
    profile, draft = _profile_and_draft(db, code, lock=True)
    _assert_revision(draft.updated_at, expected_updated_at)

    provider_id = values.get("default_provider_id", profile.default_provider_id)
    if provider_id is not None:
        _provider_or_404(db, provider_id)
    enabled_capabilities = values.get("enabled_capabilities", list(draft.enabled_capabilities or []))
    knowledge_scope = values.get("knowledge_scope", list(draft.knowledge_scope or []))
    max_risk_level = values.get("max_risk_level", draft.max_risk_level)
    _validate_profile_limits(profile, enabled_capabilities, knowledge_scope, max_risk_level)

    profile_fields = {"name", "default_provider_id", "retention_days", "enabled"}
    draft_fields = {
        "system_prompt_zh", "system_prompt_en", "enabled_capabilities", "knowledge_scope", "max_risk_level"
    }
    for key in profile_fields.intersection(values):
        setattr(profile, key, values[key])
    for key in draft_fields.intersection(values):
        setattr(draft, key, values[key])
    profile.max_risk_level = max_risk_level
    draft.updated_at = _utcnow()
    audit(
        db,
        "ai_agent_profile",
        profile.id,
        "update_draft",
        actor,
        {"code": profile.code, "fields": sorted(values), "capability_count": len(enabled_capabilities)},
    )
    db.commit()
    return profile_draft_payload(db, profile, draft)


def _validate_publishable(
    db: Session,
    profile: AiAgentProfile,
    version: AiAgentProfileVersion,
) -> None:
    if not (version.system_prompt_zh or "").strip() or not (version.system_prompt_en or "").strip():
        raise AppError("AI_PROFILE_PROMPT_REQUIRED", "发布前必须填写中英文系统指令")
    definitions = _validate_profile_limits(
        profile,
        version.enabled_capabilities or [],
        version.knowledge_scope or [],
        version.max_risk_level,
    )
    if not profile.default_provider_id:
        raise AppError("AI_PROFILE_PROVIDER_REQUIRED", "发布前必须选择模型提供商")
    provider = _provider_or_404(db, profile.default_provider_id)
    if not provider.enabled or not _probe_is_usable(provider):
        raise AppError("AI_PROFILE_PROVIDER_UNHEALTHY", "模型提供商未通过有效安全探测", 409)
    highest_risk = max((definition.risk.rank for definition in definitions), default=1)
    probe = provider.capability_probe if isinstance(provider.capability_probe, dict) else {}
    if highest_risk >= RiskLevel.L2.rank and (
        probe.get("supports_tools") is not True or probe.get("supports_json_schema") is not True
    ):
        raise AppError("AI_PROFILE_PROVIDER_INCOMPATIBLE", "L2/L3 档案需要工具与 JSON Schema 能力", 409)


def profile_version_payload(row: AiAgentProfileVersion) -> dict[str, Any]:
    return {
        "id": row.id,
        "version": row.version,
        "status": row.status,
        "system_prompt_zh": row.system_prompt_zh,
        "system_prompt_en": row.system_prompt_en,
        "enabled_capabilities": list(row.enabled_capabilities or []),
        "knowledge_scope": list(row.knowledge_scope or []),
        "max_risk_level": row.max_risk_level,
        "published_at": row.published_at,
    }


def publish_profile(
    db: Session,
    code: str,
    expected_draft_updated_at: datetime,
    actor: AuthUser,
) -> dict[str, Any]:
    _require_profile_code(code)
    _ensure_profiles(db, actor)
    profile, draft = _profile_and_draft(db, code, lock=True)
    _assert_revision(draft.updated_at, expected_draft_updated_at)
    _validate_publishable(db, profile, draft)
    latest = _latest_published(db, profile.id)
    now = _utcnow()
    row = AiAgentProfileVersion(
        profile_id=profile.id,
        version=(latest.version if latest else 0) + 1,
        status="published",
        system_prompt_zh=draft.system_prompt_zh,
        system_prompt_en=draft.system_prompt_en,
        enabled_capabilities=list(draft.enabled_capabilities or []),
        knowledge_scope=list(draft.knowledge_scope or []),
        max_risk_level=draft.max_risk_level,
        published_by=actor.id,
        published_at=now,
    )
    try:
        db.add(row)
        db.flush()
        profile.status = "published"
        profile.max_risk_level = draft.max_risk_level
        draft.updated_at = now
        audit(db, "ai_agent_profile", profile.id, "publish", actor, {"code": code, "version": row.version})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError("AI_PROFILE_VERSION_STALE", "智能体档案版本已变化，请刷新后重试", 409) from None
    return profile_version_payload(row)


def rollback_profile(
    db: Session,
    code: str,
    source_version: int,
    expected_latest_version: int,
    actor: AuthUser,
) -> dict[str, Any]:
    _require_profile_code(code)
    _ensure_profiles(db, actor)
    profile, _draft = _profile_and_draft(db, code, lock=True)
    latest = _latest_published(db, profile.id)
    if latest is None or latest.version != expected_latest_version:
        raise AppError("AI_PROFILE_VERSION_STALE", "智能体档案版本已变化，请刷新后重试", 409)
    source = (
        db.query(AiAgentProfileVersion)
        .filter(
            AiAgentProfileVersion.profile_id == profile.id,
            AiAgentProfileVersion.version == source_version,
            AiAgentProfileVersion.status == "published",
            AiAgentProfileVersion.is_deleted.is_(False),
        )
        .first()
    )
    if source is None:
        raise AppError("AI_PROFILE_VERSION_NOT_FOUND", "智能体档案历史版本不存在", 404)
    _validate_publishable(db, profile, source)
    row = AiAgentProfileVersion(
        profile_id=profile.id,
        version=latest.version + 1,
        status="published",
        system_prompt_zh=source.system_prompt_zh,
        system_prompt_en=source.system_prompt_en,
        enabled_capabilities=list(source.enabled_capabilities or []),
        knowledge_scope=list(source.knowledge_scope or []),
        max_risk_level=source.max_risk_level,
        published_by=actor.id,
        published_at=_utcnow(),
    )
    try:
        db.add(row)
        db.flush()
        profile.status = "published"
        profile.max_risk_level = source.max_risk_level
        audit(
            db,
            "ai_agent_profile",
            profile.id,
            "rollback",
            actor,
            {"code": code, "from_version": source_version, "version": row.version},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError("AI_PROFILE_VERSION_STALE", "智能体档案版本已变化，请刷新后重试", 409) from None
    return profile_version_payload(row)


def health_summary(db: Session) -> dict[str, Any]:
    providers = db.query(AiProviderConfig).filter(AiProviderConfig.is_deleted.is_(False)).all()
    profiles = db.query(AiAgentProfile).filter(
        AiAgentProfile.code.in_(tuple(PROFILE_AUDIENCES)),
        AiAgentProfile.is_deleted.is_(False),
    ).all()
    return {
        "providers": {
            "total": len(providers),
            "enabled": sum(row.enabled for row in providers),
            "healthy": sum(bool(row.enabled and _probe_is_usable(row)) for row in providers),
            "failed": sum(row.probe_status == "failed" for row in providers),
            "unverified": sum(row.probe_status not in {"success", "failed"} for row in providers),
        },
        "profiles": {
            "fixed_total": len(profiles),
            "published": sum(row.status == "published" for row in profiles),
            "enabled": sum(row.enabled and row.status == "published" for row in profiles),
        },
    }


def usage_summary(db: Session) -> dict[str, Any]:
    calls = db.query(AiProviderCall).filter(AiProviderCall.is_deleted.is_(False)).all()
    provider_codes = {
        row.id: row.code
        for row in db.query(AiProviderConfig).filter(AiProviderConfig.is_deleted.is_(False)).all()
    }
    by_provider: dict[str, dict[str, Any]] = {}
    by_result: dict[str, int] = {}
    for call in calls:
        code = provider_codes.get(call.provider_id, "deleted")
        bucket = by_provider.setdefault(
            code,
            {"provider_code": code, "calls": 0, "input_tokens": 0, "output_tokens": 0},
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += int(call.input_tokens or 0)
        bucket["output_tokens"] += int(call.output_tokens or 0)
        result_code = str(call.result_code or "UNKNOWN")
        by_result[result_code] = by_result.get(result_code, 0) + 1
    total = len(calls)
    return {
        "total_calls": total,
        "completed_calls": sum(call.status == "completed" for call in calls),
        "failed_calls": sum(call.status != "completed" for call in calls),
        "input_tokens": sum(int(call.input_tokens or 0) for call in calls),
        "output_tokens": sum(int(call.output_tokens or 0) for call in calls),
        "average_duration_ms": round(sum(int(call.duration_ms or 0) for call in calls) / total, 2) if total else 0,
        "by_provider": [by_provider[key] for key in sorted(by_provider)],
        "by_result_code": [{"result_code": key, "count": by_result[key]} for key in sorted(by_result)],
    }


def action_audits(
    db: Session,
    *,
    page: int,
    page_size: int,
    status: str | None = None,
    capability_code: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    query = db.query(AiAction).filter(AiAction.is_deleted.is_(False))
    if status:
        query = query.filter(AiAction.status == status)
    if capability_code:
        query = query.filter(AiAction.capability_code == capability_code)
    total = query.count()
    rows = (
        query.order_by(AiAction.created_at.desc(), AiAction.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [
        {
            "id": row.id,
            "capability_code": row.capability_code,
            "risk_level": row.risk_level,
            "status": row.status,
            "result_code": row.result_code,
            "result_entity_type": row.result_entity_type,
            "result_entity_id": row.result_entity_id,
            "created_at": row.created_at,
            "consumed_at": row.consumed_at,
        }
        for row in rows
    ], total
