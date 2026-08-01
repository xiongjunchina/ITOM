"""Aily MCP 配置、外部身份映射和机器人消息管理 API。"""
from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.glid import new_glid
from app.db import get_db
from app.deps import require_roles
from app.models import AuthUser, ExternalIdentity
from app.schemas.common import ok
from app.services.aily import (
    deliver_aily_outbox_row,
    get_aily_config,
    queue_aily_text,
)
from app.services.audit import audit
from app.services.secrets_store import encrypt_secret

router = APIRouter(prefix="/api/admin/integrations/aily", tags=["aily-mcp"])


class AilyConfigIn(BaseModel):
    enabled: bool | None = None
    mcp_jwt_secret: str | None = Field(default=None, min_length=16, max_length=512)
    allowed_tenant_ids: list[str] | None = None
    allowed_agent_ids: list[str] | None = None
    allowed_origins: list[str] | None = None
    bot_app_id: str | None = Field(default=None, max_length=64)
    bot_app_secret: str | None = Field(default=None, max_length=512)
    api_base: str | None = Field(default=None, max_length=100)
    public_base_url: str | None = Field(default=None, max_length=300)
    message_enabled: bool | None = None
    card_callback_verification_token: str | None = Field(default=None, max_length=512)
    card_callback_encrypt_key: str | None = Field(default=None, max_length=512)


class ExternalIdentityIn(BaseModel):
    provider: str = Field(default="feishu", pattern="^feishu$")
    tenant_id: str = Field(min_length=1, max_length=128)
    app_id: str = Field(min_length=1, max_length=128)
    subject_type: str = Field(pattern="^(open_id|user_id|union_id)$")
    subject_id: str = Field(min_length=1, max_length=128)
    auth_user_id: str
    status: str = Field(default="active", pattern="^(active|disabled)$")


class ExternalIdentityUpdate(BaseModel):
    auth_user_id: str | None = None
    status: str | None = Field(default=None, pattern="^(active|disabled)$")


class AilyTestMessageIn(BaseModel):
    identity_id: str
    text: str = Field(default="ITOM Aily MCP 主动消息测试成功。", min_length=1, max_length=2000)


def _unique_strings(values: list[str] | None) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in (values or []) if v and v.strip()))


def _validate_origins(values: list[str]) -> list[str]:
    for value in values:
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise AppError("AILY_ORIGIN_INVALID", f"Origin 必须是仅含协议和主机的地址：{value}", 422)
    return values


def _normalize_public_base_url(value: str | None) -> str | None:
    """校验并规范化管理员填写的公网入口根地址。"""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        raise AppError(
            "AILY_PUBLIC_BASE_URL_INVALID",
            f"公网访问根地址的端口无效：{value}",
            422,
        )
    if (
        any(char.isspace() for char in value)
        or parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise AppError(
            "AILY_PUBLIC_BASE_URL_INVALID",
            "公网访问根地址必须是仅含 http/https、域名或 IP 和可选端口的地址，不能包含路径、查询参数或片段",
            422,
        )
    return parsed._replace(path="", params="", query="", fragment="").geturl().rstrip("/")


def _config_payload(cfg) -> dict:
    secret_present = bool(cfg.mcp_jwt_secret_encrypted)
    discovery_ready = bool(cfg.enabled and cfg.allowed_origins)
    tool_calls_ready = bool(
        discovery_ready
        and secret_present
        and cfg.allowed_tenant_ids
        and cfg.allowed_agent_ids
    )
    return {
        "enabled": cfg.enabled,
        "mcp_auth_mode": cfg.mcp_auth_mode,
        "has_mcp_jwt_secret": secret_present,
        "mcp_discovery_ready": discovery_ready,
        "mcp_tool_calls_ready": tool_calls_ready,
        "allowed_tenant_ids": cfg.allowed_tenant_ids or [],
        "allowed_agent_ids": cfg.allowed_agent_ids or [],
        "allowed_origins": cfg.allowed_origins or [],
        "bot_app_id": cfg.bot_app_id,
        "has_bot_app_secret": bool(cfg.bot_app_secret_encrypted),
        "api_base": cfg.api_base,
        "public_base_url": cfg.public_base_url or "",
        "message_enabled": cfg.message_enabled,
        "has_card_callback_verification_token": bool(
            cfg.card_callback_verification_token_encrypted
        ),
        "has_card_callback_encrypt_key": bool(cfg.card_callback_encrypt_key_encrypted),
        "interactive_cards_ready": bool(
            cfg.enabled
            and cfg.message_enabled
            and cfg.bot_app_id
            and cfg.bot_app_secret_encrypted
            and cfg.card_callback_verification_token_encrypted
            and cfg.card_callback_encrypt_key_encrypted
        ),
        "last_test_at": cfg.last_test_at,
        "last_test_status": cfg.last_test_status,
        "last_error_redacted": cfg.last_error_redacted,
        # Aily's custom-MCP save validation requires the canonical mounted path.
        # Keep the trailing slash in the operator-facing URL even though FastAPI
        # also accepts the mount prefix without it.
        "mcp_path": "/mcp/",
        "card_callback_path": "/api/integrations/feishu/card-actions",
    }


def _identity_payload(row: ExternalIdentity) -> dict:
    user = row.auth_user
    return {
        "id": row.id,
        "provider": row.provider,
        "tenant_id": row.tenant_id,
        "app_id": row.app_id,
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "auth_user_id": row.auth_user_id,
        "username": user.username if user else None,
        "display_name": user.person.name if user and user.person else None,
        "status": row.status,
        "verified_at": row.verified_at,
        "last_used_at": row.last_used_at,
    }


@router.get("")
def get_config(db: Session = Depends(get_db), _=Depends(require_roles("admin"))):
    cfg = get_aily_config(db)
    db.commit()
    return ok(_config_payload(cfg))


@router.put("")
def update_config(
    body: AilyConfigIn,
    db: Session = Depends(get_db),
    actor=Depends(require_roles("admin")),
):
    cfg = get_aily_config(db)
    data = body.model_dump(exclude_unset=True)
    tenants = _unique_strings(data.get("allowed_tenant_ids", cfg.allowed_tenant_ids or []))
    agents = _unique_strings(data.get("allowed_agent_ids", cfg.allowed_agent_ids or []))
    origins = _validate_origins(_unique_strings(data.get("allowed_origins", cfg.allowed_origins or [])))
    public_base_url = (
        _normalize_public_base_url(data.get("public_base_url"))
        if "public_base_url" in data
        else cfg.public_base_url
    )
    target_enabled = data.get("enabled", cfg.enabled)
    if target_enabled and not origins:
        raise AppError(
            "AILY_MCP_CONFIG_INCOMPLETE",
            "启用 MCP 协议发现前必须配置允许的 Origin；真实工具调用还需要 JWT Secret、租户 ID 和 Agent ID",
        )
    bot_secret_present = bool(data.get("bot_app_secret") or cfg.bot_app_secret_encrypted)
    bot_app_id = data.get("bot_app_id", cfg.bot_app_id)
    target_message_enabled = data.get("message_enabled", cfg.message_enabled)
    if target_message_enabled and not (bot_app_id and bot_secret_present):
        raise AppError("AILY_BOT_CONFIG_INCOMPLETE", "启用机器人消息前必须配置 Bot App ID 与 App Secret")
    callback_token_present = bool(
        data.get("card_callback_verification_token")
        or cfg.card_callback_verification_token_encrypted
    )
    callback_key_present = bool(
        data.get("card_callback_encrypt_key") or cfg.card_callback_encrypt_key_encrypted
    )
    if callback_token_present != callback_key_present:
        raise AppError(
            "AILY_CARD_CALLBACK_CONFIG_INCOMPLETE",
            "飞书卡片回调必须同时配置 Verification Token 与 Encrypt Key",
        )

    for key, value in data.items():
        if key == "mcp_jwt_secret":
            if value:
                cfg.mcp_jwt_secret_encrypted = encrypt_secret(value)
            continue
        if key == "bot_app_secret":
            if value:
                cfg.bot_app_secret_encrypted = encrypt_secret(value)
            continue
        if key == "card_callback_verification_token":
            if value:
                cfg.card_callback_verification_token_encrypted = encrypt_secret(value)
            continue
        if key == "card_callback_encrypt_key":
            if value:
                cfg.card_callback_encrypt_key_encrypted = encrypt_secret(value)
            continue
        if key == "allowed_tenant_ids":
            cfg.allowed_tenant_ids = tenants
            continue
        if key == "allowed_agent_ids":
            cfg.allowed_agent_ids = agents
            continue
        if key == "allowed_origins":
            cfg.allowed_origins = origins
            continue
        if key == "public_base_url":
            cfg.public_base_url = public_base_url
            continue
        setattr(cfg, key, value)
    audit(
        db,
        "aily_integration_config",
        cfg.id,
        "update",
        actor,
        {
            "fields": [
                k for k in data
                if k not in {
                    "mcp_jwt_secret",
                    "bot_app_secret",
                    "card_callback_verification_token",
                    "card_callback_encrypt_key",
                }
            ],
            "mcp_secret_changed": bool(data.get("mcp_jwt_secret")),
            "bot_secret_changed": bool(data.get("bot_app_secret")),
            "card_callback_token_changed": bool(
                data.get("card_callback_verification_token")
            ),
            "card_callback_key_changed": bool(data.get("card_callback_encrypt_key")),
        },
    )
    db.commit()
    return ok(_config_payload(cfg))


@router.get("/identities")
def list_identities(db: Session = Depends(get_db), _=Depends(require_roles("admin"))):
    rows = (
        db.query(ExternalIdentity)
        .filter(ExternalIdentity.is_deleted.is_(False))
        .order_by(ExternalIdentity.created_at.desc())
        .all()
    )
    return ok([_identity_payload(row) for row in rows])


@router.post("/identities")
def create_identity(
    body: ExternalIdentityIn,
    db: Session = Depends(get_db),
    actor=Depends(require_roles("admin")),
):
    user = db.get(AuthUser, body.auth_user_id)
    if not user or user.is_deleted:
        raise AppError("AILY_AUTH_USER_NOT_FOUND", "ITOM 账号不存在", 404)
    values = body.model_dump()
    for key in ("provider", "tenant_id", "app_id", "subject_type", "subject_id"):
        values[key] = values[key].strip()
    existing = (
        db.query(ExternalIdentity)
        .filter(
            ExternalIdentity.provider == values["provider"],
            ExternalIdentity.tenant_id == values["tenant_id"],
            ExternalIdentity.app_id == values["app_id"],
            ExternalIdentity.subject_type == values["subject_type"],
            ExternalIdentity.subject_id == values["subject_id"],
        )
        .first()
    )
    if existing:
        if not existing.is_deleted:
            raise AppError("AILY_EXTERNAL_IDENTITY_EXISTS", "该外部身份已建立映射", 409)
        for key, value in values.items():
            setattr(existing, key, value)
        existing.is_deleted = False
        existing.verified_at = datetime.now()
        existing.last_used_at = None
        row = existing
    else:
        row = ExternalIdentity(**values, verified_at=datetime.now())
        db.add(row)
    db.flush()
    audit(db, "external_identity", row.id, "create", actor, {
        "tenant_id": row.tenant_id,
        "app_id": row.app_id,
        "subject_type": row.subject_type,
        "auth_user_id": row.auth_user_id,
    })
    db.commit()
    return ok(_identity_payload(row))


@router.patch("/identities/{identity_id}")
def update_identity(
    identity_id: str,
    body: ExternalIdentityUpdate,
    db: Session = Depends(get_db),
    actor=Depends(require_roles("admin")),
):
    row = db.get(ExternalIdentity, identity_id)
    if not row or row.is_deleted:
        raise AppError("AILY_EXTERNAL_IDENTITY_NOT_FOUND", "外部身份映射不存在", 404)
    data = body.model_dump(exclude_unset=True)
    if data.get("auth_user_id"):
        user = db.get(AuthUser, data["auth_user_id"])
        if not user or user.is_deleted:
            raise AppError("AILY_AUTH_USER_NOT_FOUND", "ITOM 账号不存在", 404)
    for key, value in data.items():
        setattr(row, key, value)
    if row.status == "active" and not row.auth_user_id:
        raise AppError("AILY_AUTH_USER_REQUIRED", "启用身份映射前必须选择 ITOM 账号", 422)
    if row.status == "active":
        row.verified_at = datetime.now()
    audit(db, "external_identity", row.id, "update", actor, {"fields": list(data)})
    db.commit()
    return ok(_identity_payload(row))


@router.delete("/identities/{identity_id}")
def delete_identity(
    identity_id: str,
    db: Session = Depends(get_db),
    actor=Depends(require_roles("admin")),
):
    row = db.get(ExternalIdentity, identity_id)
    if not row or row.is_deleted:
        raise AppError("AILY_EXTERNAL_IDENTITY_NOT_FOUND", "外部身份映射不存在", 404)
    row.is_deleted = True
    audit(db, "external_identity", row.id, "delete", actor, {})
    db.commit()
    return ok({"deleted": True})


@router.post("/test-message")
def test_message(
    body: AilyTestMessageIn,
    db: Session = Depends(get_db),
    actor=Depends(require_roles("admin")),
):
    identity = db.get(ExternalIdentity, body.identity_id)
    if not identity or identity.is_deleted or identity.status != "active":
        raise AppError("AILY_EXTERNAL_IDENTITY_NOT_FOUND", "请选择有效的 Aily 外部身份映射", 404)
    cfg = get_aily_config(db)
    row = queue_aily_text(
        db,
        recipient_type=identity.subject_type,
        recipient_id=identity.subject_id,
        text=body.text,
        idempotency_key=f"aily-test:{new_glid()}",
    )
    try:
        deliver_aily_outbox_row(db, row)
    except Exception as exc:
        cfg.last_test_at = datetime.now()
        cfg.last_test_status = "failed"
        cfg.last_error_redacted = row.last_error_redacted
        audit(db, "aily_integration_config", cfg.id, "test_message_failed", actor, {
            "identity_id": identity.id,
            "error": row.last_error_redacted,
        })
        db.commit()
        raise
    cfg.last_test_at = datetime.now()
    cfg.last_test_status = "success"
    cfg.last_error_redacted = None
    audit(db, "aily_integration_config", cfg.id, "test_message", actor, {
        "identity_id": identity.id,
        "provider_message_id": row.provider_message_id,
    })
    db.commit()
    return ok({"sent": True, "provider_message_id": row.provider_message_id, "outbox_id": row.id})
