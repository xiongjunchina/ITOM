"""通知订阅者：事件 → 发件箱 + 站内通知。飞书通道未来在此挂接。"""
from sqlalchemy.orm import Session

from app.models import AuthUser, InAppNotification, NotificationOutbox


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
    """写发件箱（外部通道挂接点）+ 给每个接收人写站内通知。"""
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
