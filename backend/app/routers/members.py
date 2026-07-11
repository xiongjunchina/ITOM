from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.rbac import MANAGER
from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import AuthUser, OrgMember, Position
from app.schemas.common import ok, paginate
from app.schemas.support import (
    MemberCreate,
    MemberUpdate,
    PositionCreate,
    PositionUpdate,
)
from app.services.audit import audit

router = APIRouter(tags=["team"])


def _member_row(m: OrgMember, groups_by_person: dict[str, list] | None = None) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "name_en": m.name_en,
        "department_id": m.department_id,
        "department_name": m.department.name if m.department else None,
        "position_id": m.position_id,
        "position_name": m.position.name if m.position else None,
        "status": m.status,
        "hire_date": m.hire_date,
        "email": m.email,
        "mobile": m.mobile,
        "external_source": m.external_source,
        "skills": m.skills or [],
        "remarks": m.remarks,
        "groups": (groups_by_person or {}).get(m.id, []),
    }


@router.get("/api/members")
def list_members(
    page: int = 1,
    page_size: int = 20,
    q: str = "",
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
):
    query = db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))
    if q:
        query = query.filter(OrgMember.name.ilike(f"%{q}%"))
    items, total = paginate(query.order_by(OrgMember.created_at.desc()), page, page_size)
    from app.models import UserGroup, UserGroupMember

    groups_by_person: dict[str, list] = {}
    rows = (
        db.query(UserGroupMember.person_id, UserGroup.name)
        .join(UserGroup, UserGroup.id == UserGroupMember.group_id)
        .filter(UserGroupMember.is_deleted.is_(False), UserGroup.is_deleted.is_(False))
        .all()
    )
    for person_id, group_name in rows:
        groups_by_person.setdefault(person_id, []).append(group_name)
    return ok([_member_row(m, groups_by_person) for m in items], total=total, page=page)


@router.post("/api/members")
def create_member(body: MemberCreate, db: Session = Depends(get_db), actor=Depends(require_roles(MANAGER))):
    member = OrgMember(**body.model_dump())
    db.add(member)
    db.flush()
    audit(db, "org_member", member.id, "create", actor, {"name": body.name})
    db.commit()
    return ok(_member_row(member))


@router.patch("/api/members/{member_id}")
def update_member(
    member_id: str, body: MemberUpdate, db: Session = Depends(get_db), actor=Depends(require_roles(MANAGER))
):
    member = db.get(OrgMember, member_id)
    if not member or member.is_deleted:
        raise AppError("NOT_FOUND", "人员不存在", 404)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(member, k, v)
    audit(db, "org_member", member.id, "update", actor, {"fields": list(data.keys())})
    db.commit()
    return ok(_member_row(member))


# ---- 岗位（人员主数据依赖，M1 一并交付） ----


def _position_row(p: Position, db: Session) -> dict:
    onboard = (
        db.query(OrgMember)
        .filter(OrgMember.position_id == p.id, OrgMember.status == "在岗", OrgMember.is_deleted.is_(False))
        .count()
    )
    return {
        "id": p.id,
        "name": p.name,
        "duties": p.duties,
        "headcount": p.headcount,
        "onboard": onboard,
        "gap": p.headcount - onboard,
    }


@router.get("/api/positions")
def list_positions(db: Session = Depends(get_db), _: AuthUser = Depends(get_current_user)):
    items = db.query(Position).filter(Position.is_deleted.is_(False)).order_by(Position.created_at).all()
    return ok([_position_row(p, db) for p in items], total=len(items))


@router.post("/api/positions")
def create_position(body: PositionCreate, db: Session = Depends(get_db), actor=Depends(require_roles(MANAGER))):
    pos = Position(**body.model_dump())
    db.add(pos)
    db.flush()
    audit(db, "position", pos.id, "create", actor, {"name": body.name})
    db.commit()
    return ok(_position_row(pos, db))


@router.patch("/api/positions/{position_id}")
def update_position(
    position_id: str, body: PositionUpdate, db: Session = Depends(get_db), actor=Depends(require_roles(MANAGER))
):
    pos = db.get(Position, position_id)
    if not pos or pos.is_deleted:
        raise AppError("NOT_FOUND", "岗位不存在", 404)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(pos, k, v)
    audit(db, "position", pos.id, "update", actor, {"fields": list(data.keys())})
    db.commit()
    return ok(_position_row(pos, db))
