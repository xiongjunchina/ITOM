"""组织治理配置及部门树范围解析。"""
from sqlalchemy.orm import Session

from app.models import Department, OrgSettings


def get_org_settings(db: Session) -> OrgSettings:
    settings = db.query(OrgSettings).filter(OrgSettings.is_deleted.is_(False)).first()
    if not settings:
        settings = OrgSettings()
        db.add(settings)
        db.flush()
    return settings


def expand_department_ids(db: Session, roots: list[str], include_children: bool) -> set[str]:
    selected = set(roots or [])
    if not include_children or not selected:
        return selected
    rows = db.query(Department.id, Department.parent_id).filter(
        Department.is_deleted.is_(False), Department.active.is_(True)
    ).all()
    changed = True
    while changed:
        changed = False
        for dept_id, parent_id in rows:
            if parent_id in selected and dept_id not in selected:
                selected.add(dept_id)
                changed = True
    return selected
