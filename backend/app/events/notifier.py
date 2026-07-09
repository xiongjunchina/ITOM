"""通知订阅者：事件 → 发件箱 + 站内通知。飞书通道未来在此挂接。"""
from sqlalchemy.orm import Session

from app.models import InAppNotification, NotificationOutbox


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
        db.add(InAppNotification(recipient=person_id, title=title, content=content, link=link))
