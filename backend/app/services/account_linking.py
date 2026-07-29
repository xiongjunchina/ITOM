"""账号与公司人员主数据的关联校验。"""

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import OrgMember


def get_linkable_person(db: Session, person_id: str | None) -> OrgMember | None:
    """返回可关联的公司人员；账号开通面向全员，不套用数字化 IT 团队范围。"""
    if not person_id:
        return None
    person = (
        db.query(OrgMember)
        .filter(OrgMember.id == person_id, OrgMember.is_deleted.is_(False))
        .first()
    )
    if not person:
        raise AppError("NOT_FOUND", "关联人员不存在", 404)
    return person
