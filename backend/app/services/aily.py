"""Aily MCP 配置与机器人可靠消息服务。"""
from datetime import datetime, timedelta
import json
import logging

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AilyIntegrationConfig, NotificationOutbox
from app.services.feishu import FeishuClient
from app.services.secrets_store import decrypt_secret

logger = logging.getLogger("aom.aily")

MAX_MESSAGE_ATTEMPTS = 8


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

    row.status = "sending"
    row.attempt_count = (row.attempt_count or 0) + 1
    db.flush()
    try:
        cfg = get_aily_config(db)
        client = build_aily_bot_client(cfg)
        payload = row.payload or {}
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
