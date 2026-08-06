"""通知订阅者：领域事件 → 站内通知 + 飞书可靠消息发件箱。

ITOM 的领域服务只调用本模块；飞书消息仍通过 ``notification_outbox``
异步投递，避免外部网络调用阻塞或破坏原业务事务。
"""

from hashlib import sha256

from sqlalchemy.orm import Session

from app.models import (
    AilyIntegrationConfig,
    AuthUser,
    InAppNotification,
    NotificationOutbox,
)


def _category(event_type: str) -> str:
    prefix = event_type.split(".", 1)[0]
    if prefix in {"ticket", "incident", "change", "problem", "sla"}:
        return "work"
    if prefix in {"process", "task", "requirement", "project", "wbs", "milestone"}:
        return "workflow"
    return "system"


def _enabled(db: Session, recipient: str, event_type: str) -> bool:
    user = db.query(AuthUser).filter(
        (AuthUser.person_id == recipient) | (AuthUser.id == recipient),
        AuthUser.is_deleted.is_(False),
    ).first()
    prefs = ((user.preferences or {}).get("notification_preferences") or {}) if user else {}
    return prefs.get(_category(event_type), True)


def _recipient_user(db: Session, recipient: str) -> AuthUser | None:
    """按人员或账号标识解析活动 ITOM 账号。"""
    user = db.query(AuthUser).filter(
        (AuthUser.person_id == recipient) | (AuthUser.id == recipient),
        AuthUser.is_deleted.is_(False),
        AuthUser.is_active.is_(True),
    ).first()
    return user


def _aily_text(cfg: AilyIntegrationConfig, title: str, content: str, link: str) -> str:
    """生成不含秘密的飞书文本消息，并仅拼接 ITOM 自己的相对详情链接。"""
    parts = [value.strip() for value in (title, content) if value and value.strip()]
    if link and link.startswith("/") and cfg.public_base_url:
        parts.append(f"查看详情：{cfg.public_base_url.rstrip('/')}{link}")
    return "\n".join(parts)[:4000]


def _aily_idempotency_key(
    event_type: str,
    entity_type: str,
    entity_id: str,
    auth_user_id: str,
) -> str:
    """用事件、实体和 ITOM 账号摘要保证映射补齐后仍不重复发送。"""
    raw = "|".join((event_type, entity_type or "", entity_id or "", auth_user_id))
    return f"aily:notification:{sha256(raw.encode('utf-8')).hexdigest()}"


def _queue_aily_notification(
    db: Session,
    event_type: str,
    entity_type: str,
    entity_id: str,
    recipient: str,
    title: str,
    content: str,
    link: str,
) -> None:
    """将通用 ITOM 通知写入 Aily 飞书发件箱，不在当前事务内访问飞书。"""
    # 服务请求解决通知已有带确认按钮的专用 Aily 订阅者；这里只保留站内通知，
    # 避免同一收件人同时收到一条普通文本和一张确认卡片。
    if event_type == "ticket.resolved":
        return
    cfg = db.query(AilyIntegrationConfig).filter(
        AilyIntegrationConfig.is_deleted.is_(False),
    ).first()
    # Integration disabled means the administrator has not opted into outbound
    # Feishu delivery. Do not create an unbounded pending queue in that state;
    # an enabled integration with an unmapped identity is handled by the
    # user-scoped queue and remains observable/retryable.
    if not cfg or not cfg.enabled:
        return
    user = _recipient_user(db, recipient)
    if not user:
        return
    # Reopen feedback is an IT handling detail. Keep it in ITOM's in-app
    # notification, but send only a safe state-change summary to Feishu so a
    # user's diagnostic text does not cross the proactive-message boundary.
    outbound_title = title
    outbound_content = content
    if event_type == "ticket.reopened":
        outbound_title = title.replace("用户反馈仍未解决：", "服务请求已重新打开：")
        outbound_content = ""
    text = _aily_text(cfg, outbound_title, outbound_content, link)
    if not text:
        return
    from app.services.aily import queue_aily_text_for_user

    queue_aily_text_for_user(
        db,
        auth_user_id=user.id,
        text=text,
        idempotency_key=_aily_idempotency_key(event_type, entity_type, entity_id, user.id),
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
    )


def notify(
    db: Session,
    event_type: str,
    entity_type: str,
    entity_id: str,
    recipients: list[str],
    title: str,
    content: str = "",
    link: str = "",
):
    """同事务写入站内通知和飞书可靠发件箱。"""
    db.add(
        NotificationOutbox(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload={"title": title, "recipients": recipients, "link": link},
            channel="in_app",
            status="sent",
        )
    )
    for person_id in recipients:
        if _enabled(db, person_id, event_type):
            db.add(InAppNotification(recipient=person_id, title=title, content=content, link=link))
            _queue_aily_notification(
                db,
                event_type,
                entity_type,
                entity_id,
                person_id,
                title,
                content,
                link,
            )
