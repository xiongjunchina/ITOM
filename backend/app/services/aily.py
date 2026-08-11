"""Aily MCP 配置与机器人可靠消息服务。"""
from datetime import datetime, timedelta
import json
import logging

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AilyIntegrationConfig, AuthUser, ExternalIdentity, NotificationOutbox
from app.services.feishu import FeishuClient
from app.services.audit import audit
from app.services.secrets_store import decrypt_secret

logger = logging.getLogger("aom.aily")

MAX_MESSAGE_ATTEMPTS = 8
AILY_IDENTITY_NOT_MAPPED = "AILY_IDENTITY_NOT_MAPPED"
AILY_IDENTITY_RETRY_SECONDS = 60


def get_aily_config(db: Session) -> AilyIntegrationConfig:
    """读取单行配置；首次访问时创建安全关闭的默认记录。"""
    row = (
        db.query(AilyIntegrationConfig)
        .filter(AilyIntegrationConfig.is_deleted.is_(False))
        .first()
    )
    if not row:
        row = AilyIntegrationConfig(
            enabled=False,
            message_enabled=False,
            allowed_tenant_ids=[],
            allowed_agent_ids=[],
            allowed_origins=["https://aily.feishu.cn"],
        )
        db.add(row)
        db.flush()
    return row


def build_aily_bot_client(cfg: AilyIntegrationConfig) -> FeishuClient:
    """使用独立 Aily 机器人应用凭据构造通用飞书客户端。"""
    secret = decrypt_secret(cfg.bot_app_secret_encrypted)
    if not (cfg.message_enabled and cfg.bot_app_id and secret):
        raise AppError("AILY_MESSAGE_NOT_CONFIGURED", "请先启用并配置 Aily 机器人消息", 501)
    return FeishuClient(cfg.api_base, cfg.bot_app_id, secret)


def find_aily_identity(
    db: Session,
    *,
    auth_user_id: str,
    cfg: AilyIntegrationConfig,
) -> ExternalIdentity | None:
    """解析当前可用于 Aily 机器人出站的、已授权飞书身份。

    经飞书 OAuth 验真后为当前机器人应用自动建立的身份，以 ``app_id``
    作为出站信任边界；Aily JWT 的租户白名单只约束 MCP 入站调用。历史
    人工/Aily 映射仍按原租户白名单筛选，避免放宽既有入站授权。
    """
    base_query = db.query(ExternalIdentity).filter(
        ExternalIdentity.provider == "feishu",
        ExternalIdentity.auth_user_id == auth_user_id,
        ExternalIdentity.subject_type.in_(["open_id", "user_id", "union_id"]),
        ExternalIdentity.status == "active",
        ExternalIdentity.is_deleted.is_(False),
    )
    ordering = (
        ExternalIdentity.last_used_at.desc(),
        ExternalIdentity.verified_at.desc(),
        ExternalIdentity.created_at.desc(),
    )

    bot_app_id = str(cfg.bot_app_id or "").strip()
    if bot_app_id:
        trusted_bot_identity = (
            base_query.filter(ExternalIdentity.app_id == bot_app_id)
            .order_by(*ordering)
            .first()
        )
        if trusted_bot_identity:
            return trusted_bot_identity

    allowed_tenants = list(cfg.allowed_tenant_ids or [])
    if allowed_tenants:
        base_query = base_query.filter(ExternalIdentity.tenant_id.in_(allowed_tenants))
    return base_query.order_by(*ordering).first()


def sync_aily_notification_identity(
    db: Session,
    *,
    user: AuthUser,
    feishu_info: dict | None,
) -> str:
    """用已验真的飞书 OAuth 用户信息自动建立机器人通知映射。

    该函数只由已通过 ITOM 飞书 OAuth/绑定校验的路径调用。优先使用同租户
    跨应用稳定的 ``user_id``，权限不足未返回时回退 ``union_id``；不能用
    登录应用的 ``open_id`` 冒充机器人应用的 ``open_id``。

    OAuth 返回的 ``tenant_key`` 与 Aily MCP JWT 的 ``tenant_id`` 属于不同
    契约，不使用 MCP 入站租户白名单阻断出站通知身份自动映射。
    """
    info = feishu_info or {}
    tenant_id = str(info.get("tenant_key") or "").strip()
    user_id = str(info.get("user_id") or "").strip()
    union_id = str(info.get("union_id") or "").strip()
    subject_type = "user_id" if user_id else "union_id"
    subject_id = user_id or union_id
    cfg = get_aily_config(db)
    if not (cfg.enabled and cfg.bot_app_id and tenant_id and subject_id):
        return "skipped"

    disabled_for_account = (
        db.query(ExternalIdentity)
        .filter(
            ExternalIdentity.provider == "feishu",
            ExternalIdentity.tenant_id == tenant_id,
            ExternalIdentity.app_id == cfg.bot_app_id,
            ExternalIdentity.auth_user_id == user.id,
            ExternalIdentity.status == "disabled",
            ExternalIdentity.is_deleted.is_(False),
        )
        .first()
    )
    if disabled_for_account:
        # 标识从 union_id 升级到 user_id 时，也不能绕过管理员对该账号在
        # 当前机器人应用下的显式停用决定。
        return "disabled"

    row = (
        db.query(ExternalIdentity)
        .filter(
            ExternalIdentity.provider == "feishu",
            ExternalIdentity.tenant_id == tenant_id,
            ExternalIdentity.app_id == cfg.bot_app_id,
            ExternalIdentity.subject_type == subject_type,
            ExternalIdentity.subject_id == subject_id,
        )
        .first()
    )
    if row and not row.is_deleted and row.status == "disabled":
        # 管理员显式停用的映射不能被普通登录自动重新启用。
        return "disabled"
    if row and row.auth_user_id and row.auth_user_id != user.id:
        # 同一已验证身份指向两个 ITOM 账号时保持拒绝，不能静默抢占。
        return "conflict"
    if not row:
        row = ExternalIdentity(
            provider="feishu",
            tenant_id=tenant_id,
            app_id=cfg.bot_app_id,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        db.add(row)
    row.auth_user_id = user.id
    row.status = "active"
    row.is_deleted = False
    row.verified_at = datetime.now()
    row.last_used_at = datetime.now()
    db.flush()
    audit(
        db,
        "external_identity",
        row.id,
        "auto_map_aily_notification_identity",
        user,
        {
            "provider": "feishu",
            "tenant_id": tenant_id,
            "app_id": cfg.bot_app_id,
            "subject_type": subject_type,
            "auth_user_id": user.id,
        },
    )
    return "mapped"


def queue_aily_text(
    db: Session,
    *,
    recipient_type: str,
    recipient_id: str,
    text: str,
    idempotency_key: str,
    event_type: str = "aily.test_message",
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> NotificationOutbox:
    """幂等写入 Aily 机器人文本消息发件箱。"""
    recipient_type = recipient_type.strip()
    recipient_id = recipient_id.strip()
    text = text.strip()
    if recipient_type not in {"open_id", "user_id", "union_id"}:
        raise AppError("AILY_RECIPIENT_TYPE_INVALID", "飞书接收人标识类型无效", 422)
    if not recipient_id or not text or not idempotency_key.strip():
        raise AppError("AILY_MESSAGE_INVALID", "Aily 消息缺少接收人、内容或幂等键", 422)
    existing = (
        db.query(NotificationOutbox)
        .filter(NotificationOutbox.idempotency_key == idempotency_key)
        .first()
    )
    if existing:
        return existing
    row = NotificationOutbox(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload={"text": text},
        channel="feishu_aily",
        status="pending",
        recipient_type=recipient_type,
        recipient_id=recipient_id,
        idempotency_key=idempotency_key,
        attempt_count=0,
        next_attempt_at=datetime.now(),
    )
    db.add(row)
    db.flush()
    return row


def queue_aily_text_for_user(
    db: Session,
    *,
    auth_user_id: str,
    text: str,
    idempotency_key: str,
    event_type: str = "aily.test_message",
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> NotificationOutbox:
    """按 ITOM 账号排队文本；身份暂缺时保留待映射记录而非静默丢弃。"""
    text = text.strip()
    if not auth_user_id.strip() or not text or not idempotency_key.strip():
        raise AppError("AILY_MESSAGE_INVALID", "Aily 消息缺少账号、内容或幂等键", 422)
    existing = (
        db.query(NotificationOutbox)
        .filter(NotificationOutbox.idempotency_key == idempotency_key)
        .first()
    )
    if existing:
        if existing.channel == "feishu_aily" and existing.status != "sent":
            existing.payload = {
                **(existing.payload or {}),
                "auth_user_id": auth_user_id,
            }
        return existing
    cfg = get_aily_config(db)
    identity = find_aily_identity(db, auth_user_id=auth_user_id, cfg=cfg)
    if identity:
        row = queue_aily_text(
            db,
            recipient_type=identity.subject_type,
            recipient_id=identity.subject_id,
            text=text,
            idempotency_key=idempotency_key,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        row.payload = {**(row.payload or {}), "auth_user_id": auth_user_id}
        return row

    row = NotificationOutbox(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload={"text": text, "auth_user_id": auth_user_id},
        channel="feishu_aily",
        status="pending",
        idempotency_key=idempotency_key,
        attempt_count=0,
        next_attempt_at=datetime.now(),
        last_error_redacted=AILY_IDENTITY_NOT_MAPPED,
    )
    db.add(row)
    db.flush()
    return row


def queue_aily_card(
    db: Session,
    *,
    recipient_type: str,
    recipient_id: str,
    card: dict,
    fallback_text: str,
    idempotency_key: str,
    event_type: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> NotificationOutbox:
    """幂等写入 Aily 交互卡片发件箱。"""
    recipient_type = recipient_type.strip()
    recipient_id = recipient_id.strip()
    fallback_text = fallback_text.strip()
    if recipient_type not in {"open_id", "user_id", "union_id"}:
        raise AppError("AILY_RECIPIENT_TYPE_INVALID", "飞书接收人标识类型无效", 422)
    if not recipient_id or not fallback_text or not idempotency_key.strip():
        raise AppError("AILY_MESSAGE_INVALID", "Aily 卡片缺少接收人、回退文本或幂等键", 422)
    if not isinstance(card, dict) or not card.get("header") or not card.get("elements"):
        raise AppError("AILY_CARD_INVALID", "Aily 交互卡片结构无效", 422)
    if len(json.dumps(card, ensure_ascii=False)) > 30000:
        raise AppError("AILY_CARD_TOO_LARGE", "Aily 交互卡片内容过大", 422)
    existing = (
        db.query(NotificationOutbox)
        .filter(NotificationOutbox.idempotency_key == idempotency_key)
        .first()
    )
    if existing:
        return existing
    row = NotificationOutbox(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload={
            "message_type": "interactive",
            "card": card,
            "fallback_text": fallback_text,
        },
        channel="feishu_aily",
        status="pending",
        recipient_type=recipient_type,
        recipient_id=recipient_id,
        idempotency_key=idempotency_key,
        attempt_count=0,
        next_attempt_at=datetime.now(),
    )
    db.add(row)
    db.flush()
    return row


def queue_aily_card_for_user(
    db: Session,
    *,
    auth_user_id: str,
    card: dict,
    fallback_text: str,
    idempotency_key: str,
    event_type: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> NotificationOutbox:
    """按 ITOM 账号排队卡片；身份暂缺时等待后续安全映射。"""
    fallback_text = fallback_text.strip()
    if not auth_user_id.strip() or not fallback_text or not idempotency_key.strip():
        raise AppError("AILY_CARD_INVALID", "Aily 卡片缺少账号、回退文本或幂等键", 422)
    existing = (
        db.query(NotificationOutbox)
        .filter(NotificationOutbox.idempotency_key == idempotency_key)
        .first()
    )
    if existing:
        if existing.channel == "feishu_aily" and existing.status != "sent":
            existing.payload = {
                **(existing.payload or {}),
                "auth_user_id": auth_user_id,
            }
        return existing
    cfg = get_aily_config(db)
    identity = find_aily_identity(db, auth_user_id=auth_user_id, cfg=cfg)
    if identity:
        row = queue_aily_card(
            db,
            recipient_type=identity.subject_type,
            recipient_id=identity.subject_id,
            card=card,
            fallback_text=fallback_text,
            idempotency_key=idempotency_key,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        row.payload = {**(row.payload or {}), "auth_user_id": auth_user_id}
        return row

    if not isinstance(card, dict) or not card.get("header") or not card.get("elements"):
        raise AppError("AILY_CARD_INVALID", "Aily 卡片结构无效", 422)
    if len(json.dumps(card, ensure_ascii=False)) > 30000:
        raise AppError("AILY_CARD_TOO_LARGE", "Aily 卡片内容过大", 422)
    row = NotificationOutbox(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload={
            "message_type": "interactive",
            "card": card,
            "fallback_text": fallback_text,
            "auth_user_id": auth_user_id,
        },
        channel="feishu_aily",
        status="pending",
        idempotency_key=idempotency_key,
        attempt_count=0,
        next_attempt_at=datetime.now(),
        last_error_redacted=AILY_IDENTITY_NOT_MAPPED,
    )
    db.add(row)
    db.flush()
    return row


def _redacted_error(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return f"{exc.code}: {exc.message}"[:500]
    return f"{type(exc).__name__}: Aily message delivery failed"[:500]


def deliver_aily_outbox_row(db: Session, row: NotificationOutbox) -> NotificationOutbox:
    """发送一条出站消息并记录提供方消息 ID；失败进入指数退避。"""
    if row.channel != "feishu_aily":
        raise AppError("AILY_OUTBOX_CHANNEL_INVALID", "发件箱记录不是 Aily 消息", 422)
    if row.status == "sent":
        return row
    if (row.attempt_count or 0) >= MAX_MESSAGE_ATTEMPTS:
        raise AppError("AILY_MESSAGE_RETRY_EXHAUSTED", "Aily 消息重试次数已耗尽", 409)

    cfg = get_aily_config(db)
    payload = row.payload or {}
    auth_user_id = str(payload.get("auth_user_id") or "").strip()
    if auth_user_id:
        identity = find_aily_identity(db, auth_user_id=auth_user_id, cfg=cfg)
        if not identity:
            row.status = "pending"
            row.last_error_redacted = AILY_IDENTITY_NOT_MAPPED
            row.next_attempt_at = datetime.now() + timedelta(seconds=AILY_IDENTITY_RETRY_SECONDS)
            return row
        row.recipient_type = identity.subject_type
        row.recipient_id = identity.subject_id

    row.status = "sending"
    row.attempt_count = (row.attempt_count or 0) + 1
    db.flush()
    try:
        client = build_aily_bot_client(cfg)
        if payload.get("message_type") == "interactive":
            message_id = client.send_interactive_card(
                row.recipient_id or "",
                row.recipient_type or "open_id",
                payload.get("card") or {},
            )
        else:
            message_id = client.send_app_text(
                row.recipient_id or "",
                row.recipient_type or "open_id",
                str(payload.get("text") or ""),
            )
    except Exception as exc:
        row.status = "failed"
        row.last_error_redacted = _redacted_error(exc)
        delay = min(300, 2 ** min(row.attempt_count, 8))
        row.next_attempt_at = datetime.now() + timedelta(seconds=delay)
        raise

    row.status = "sent"
    row.provider_message_id = message_id
    row.last_error_redacted = None
    row.next_attempt_at = None
    row.sent_at = datetime.now()
    return row


def scan_aily_outbox(limit: int = 50) -> int:
    """后台消费待发送/可重试消息，单条失败不阻断其他消息。"""
    from app.db import SessionLocal

    processed = 0
    with SessionLocal() as db:
        cfg = get_aily_config(db)
        if not (
            cfg.enabled
            and cfg.message_enabled
            and cfg.bot_app_id
            and cfg.bot_app_secret_encrypted
        ):
            # 配置未就绪时保留 pending，不消耗重试次数；启用后由下一轮继续投递。
            db.commit()
            return 0
        query = (
            db.query(NotificationOutbox)
            .filter(
                NotificationOutbox.channel == "feishu_aily",
                NotificationOutbox.status.in_(["pending", "failed"]),
                NotificationOutbox.attempt_count < MAX_MESSAGE_ATTEMPTS,
                (NotificationOutbox.next_attempt_at.is_(None))
                | (NotificationOutbox.next_attempt_at <= datetime.now()),
                NotificationOutbox.is_deleted.is_(False),
            )
            .order_by(NotificationOutbox.created_at)
        )
        if db.get_bind().dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        rows = query.limit(limit).all()
        for row in rows:
            try:
                deliver_aily_outbox_row(db, row)
                db.commit()
                processed += 1
            except Exception:
                db.commit()
                logger.exception("Aily message delivery failed: outbox=%s", row.id)
    return processed
