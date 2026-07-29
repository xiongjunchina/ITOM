"""验证 x-aily-jwt 并映射到唯一活动 ITOM 账号。"""
from datetime import datetime
import hashlib
import hmac
import logging

import jwt
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.mcp.context import AilyPrincipal
from app.models import AuthUser, ExternalIdentity
from app.services.aily import get_aily_config
from app.services.secrets_store import decrypt_secret

logger = logging.getLogger("aom.aily_identity")


def _claim(payload: dict, *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _allowed(value: str, allowlist: list[str]) -> bool:
    return any(hmac.compare_digest(value, str(candidate)) for candidate in allowlist)


def _subject(payload: dict) -> tuple[str, str]:
    explicit_type = _claim(payload, "subject_type", "subjectType", "sub_type")
    explicit_id = _claim(payload, "subject_id", "subjectId")
    if explicit_type and explicit_id:
        return explicit_type, explicit_id
    for subject_type, names in (
        ("open_id", ("open_id", "feishu_open_id")),
        ("user_id", ("user_id",)),
        ("union_id", ("union_id",)),
    ):
        value = _claim(payload, *names)
        if value:
            return subject_type, value
    subject = _claim(payload, "sub")
    if subject and explicit_type:
        return explicit_type, subject
    return "", ""


def validate_aily_request_source(db: Session, *, origin: str | None):
    """校验 MCP 总开关与请求来源；协议发现阶段不要求用户 JWT。"""
    cfg = get_aily_config(db)
    if not cfg.enabled:
        raise AppError("AILY_MCP_DISABLED", "Aily MCP 尚未启用", 503)
    if not origin:
        raise AppError("AILY_ORIGIN_MISSING", "MCP 请求缺少 Origin", 403)
    if not _allowed(origin, list(cfg.allowed_origins or [])):
        raise AppError("AILY_ORIGIN_FORBIDDEN", "MCP 请求 Origin 不在允许范围内", 403)
    return cfg


def _record_pending_identity(
    db: Session,
    *,
    tenant_id: str,
    app_id: str,
    subject_type: str,
    subject_id: str,
) -> ExternalIdentity:
    """登记已通过 Aily 验签但尚未获 ITOM 授权的身份，不自动建立账号映射。"""
    row = (
        db.query(ExternalIdentity)
        .filter(
            ExternalIdentity.provider == "feishu",
            ExternalIdentity.tenant_id == tenant_id,
            ExternalIdentity.app_id == app_id,
            ExternalIdentity.subject_type == subject_type,
            ExternalIdentity.subject_id == subject_id,
        )
        .first()
    )
    if not row:
        row = ExternalIdentity(
            provider="feishu",
            tenant_id=tenant_id,
            app_id=app_id,
            subject_type=subject_type,
            subject_id=subject_id,
            auth_user_id=None,
            status="pending",
            verified_at=datetime.now(),
        )
        db.add(row)
    elif row.is_deleted:
        row.is_deleted = False
        row.auth_user_id = None
        row.status = "pending"
        row.verified_at = datetime.now()
    elif row.status == "pending":
        row.verified_at = datetime.now()
    db.commit()
    return row


def resolve_aily_principal(
    db: Session,
    *,
    token: str,
    origin: str | None,
    session_ref: str | None,
) -> AilyPrincipal:
    """校验签名、白名单和外部身份映射；不接受 ITOM Bearer Token 替代。"""
    cfg = validate_aily_request_source(db, origin=origin)
    secret = decrypt_secret(cfg.mcp_jwt_secret_encrypted)
    if not secret:
        raise AppError("AILY_MCP_NOT_CONFIGURED", "Aily MCP JWT Secret 未配置", 503)
    if not token or len(token) > 8192:
        raise AppError("AILY_JWT_MISSING", "缺少有效的 x-aily-jwt", 401)
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["exp"], "verify_aud": False},
            leeway=30,
        )
    except jwt.ExpiredSignatureError as exc:
        raise AppError("AILY_JWT_EXPIRED", "Aily 身份凭证已过期", 401) from exc
    except jwt.PyJWTError as exc:
        raise AppError("AILY_JWT_INVALID", "Aily 身份凭证无效", 401) from exc

    tenant_id = _claim(payload, "tenant_id", "tenant_key", "tenantId")
    agent_id = _claim(payload, "agent_id", "agentId", "aily_app_id")
    app_id = _claim(payload, "app_id", "appId") or agent_id
    if not agent_id:
        agent_id = app_id
    subject_type, subject_id = _subject(payload)
    if subject_type not in {"open_id", "user_id", "union_id"}:
        logger.warning(
            "Aily JWT missing supported subject claim; claim_keys=%s",
            sorted(str(key) for key in payload),
        )
        raise AppError("AILY_JWT_CLAIMS_INVALID", "Aily JWT 缺少有效的用户标识类型", 401)
    if not all((tenant_id, app_id, agent_id, subject_id)):
        raise AppError("AILY_JWT_CLAIMS_INVALID", "Aily JWT 缺少租户、应用、Agent 或用户标识", 401)
    if not _allowed(agent_id, list(cfg.allowed_agent_ids or [])):
        raise AppError("AILY_AGENT_FORBIDDEN", "Aily Agent 不在允许范围内", 403)
    if not _allowed(tenant_id, list(cfg.allowed_tenant_ids or [])):
        _record_pending_identity(
            db,
            tenant_id=tenant_id,
            app_id=app_id,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        raise AppError("AILY_TENANT_FORBIDDEN", "Aily 租户尚未获 ITOM 管理员批准", 403)

    identity = (
        db.query(ExternalIdentity)
        .filter(
            ExternalIdentity.provider == "feishu",
            ExternalIdentity.tenant_id == tenant_id,
            ExternalIdentity.app_id == app_id,
            ExternalIdentity.subject_type == subject_type,
            ExternalIdentity.subject_id == subject_id,
            ExternalIdentity.status == "active",
            ExternalIdentity.is_deleted.is_(False),
        )
        .first()
    )
    if not identity:
        _record_pending_identity(
            db,
            tenant_id=tenant_id,
            app_id=app_id,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        raise AppError("AILY_IDENTITY_UNMAPPED", "该 Aily 用户尚未映射到 ITOM 账号", 403)
    user = db.get(AuthUser, identity.auth_user_id)
    if not user or not user.is_active or user.is_deleted:
        raise AppError("AILY_ITOM_ACCOUNT_DISABLED", "映射的 ITOM 账号不存在或已停用", 403)
    identity.last_used_at = datetime.now()
    db.commit()
    return AilyPrincipal(
        auth_user_id=user.id,
        tenant_id=tenant_id,
        app_id=app_id,
        agent_id=agent_id,
        subject_type=subject_type,
        subject_id=subject_id,
        session_ref_hash=(
            hashlib.sha256(session_ref.encode()).hexdigest() if session_ref else None
        ),
    )
