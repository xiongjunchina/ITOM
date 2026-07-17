from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import get_current_user
from app.models import AuthUser, InAppNotification
from app.schemas.common import ok

router = APIRouter(prefix="/api/notifications", tags=["support"])


def _my_recipient_ids(user: AuthUser) -> list[str]:
    """我的收件标识（M34 双语义）：人员 id（业务通知按人投递）+ 账号 id（未绑人员的管理员兜底）。"""
    return [x for x in (user.person_id, user.id) if x]


@router.get("")
def list_my_notifications(db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    items = (
        db.query(InAppNotification)
        .filter(InAppNotification.recipient.in_(_my_recipient_ids(user)), InAppNotification.is_deleted.is_(False))
        .order_by(InAppNotification.created_at.desc())
        .limit(50)
        .all()
    )
    return ok(
        [
            {
                "id": n.id,
                "title": n.title,
                "content": n.content,
                "link": n.link,
                "read_at": n.read_at,
                "created_at": n.created_at,
            }
            for n in items
        ],
        total=len(items),
    )


@router.post("/{notification_id}/read")
def mark_read(notification_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    n = db.get(InAppNotification, notification_id)
    if not n or n.recipient not in _my_recipient_ids(user):
        raise AppError("NOT_FOUND", "通知不存在", 404)
    n.read_at = n.read_at or datetime.now()
    db.commit()
    return ok({"id": n.id})
