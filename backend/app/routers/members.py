from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import get_current_user, require_perm
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


def _member_row(m: OrgMember) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "name_en": m.name_en,
        "employee_no": m.employee_no,
        "gender": m.gender,
        "birth_date": m.birth_date,
        "employment_type": m.employment_type,
        "supervisor_id": m.supervisor_id,
        "work_location": m.work_location,
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
    return ok([_member_row(m) for m in items], total=total, page=page)


@router.post("/api/members")
def create_member(body: MemberCreate, db: Session = Depends(get_db), actor=Depends(require_perm("admin_members", "create"))):
    member = OrgMember(**body.model_dump())
    db.add(member)
    db.flush()
    audit(db, "org_member", member.id, "create", actor, {"name": body.name})
    db.commit()
    return ok(_member_row(member))


@router.patch("/api/members/{member_id}")
def update_member(
    member_id: str, body: MemberUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("admin_members", "edit"))
):
    member = db.get(OrgMember, member_id)
    if not member or member.is_deleted:
        raise AppError("NOT_FOUND", "人员不存在", 404)
    data = body.model_dump(exclude_unset=True)
    if member.external_source:  # 同步记录：HR 基础信息以外部源为准，仅本地扩展可改
        from app.services.org_sync import MEMBER_LOCAL_FIELDS

        locked = set(data) - MEMBER_LOCAL_FIELDS
        if locked:
            raise AppError(
                "SYNCED_READONLY",
                f"该人员由 {member.external_source} 同步，基础信息以外部源为准；本地仅可编辑：岗位/技能/备注",
            )
    for k, v in data.items():
        setattr(member, k, v)
    audit(db, "org_member", member.id, "update", actor, {"fields": list(data.keys())})
    db.commit()
    return ok(_member_row(member))


@router.delete("/api/members/{member_id}")
def delete_member(member_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("admin_members", "delete"))):
    """删除人员（软删）。同步人员不可删；名下有未完成工作先转移；绑定账号一并停用。"""
    member = db.get(OrgMember, member_id)
    if not member or member.is_deleted:
        raise AppError("NOT_FOUND", "人员不存在", 404)
    if member.external_source:
        raise AppError("SYNCED_READONLY", f"该人员由 {member.external_source} 同步，请在源系统办理离职后同步，不能本地删除")

    from app.models import RequirementTask, Ticket, WbsTask

    open_tickets = db.query(Ticket).filter(
        Ticket.assignee == member.id, Ticket.is_deleted.is_(False),
        Ticket.status.notin_(["resolved", "closed", "rejected"]),
    ).count()
    open_wbs = db.query(WbsTask).filter(
        WbsTask.assignee == member.id, WbsTask.is_deleted.is_(False), WbsTask.progress < 100,
    ).count()
    open_req = db.query(RequirementTask).filter(
        RequirementTask.assignee == member.id, RequirementTask.is_deleted.is_(False),
        RequirementTask.status != "已完成",
    ).count()
    total_open = open_tickets + open_wbs + open_req
    if total_open:
        raise AppError(
            "MEMBER_HAS_OPEN_WORK",
            f"该人员名下还有 {total_open} 项未完成工作（工单 {open_tickets}/项目任务 {open_wbs}/需求任务 {open_req}），请先转移再删除",
        )

    disabled_accounts = []
    for u in db.query(AuthUser).filter(AuthUser.person_id == member.id, AuthUser.is_deleted.is_(False)):
        u.is_deleted = True
        disabled_accounts.append(u.username)
    member.is_deleted = True
    audit(db, "org_member", member.id, "delete", actor, {"name": member.name, "accounts_disabled": disabled_accounts})
    db.commit()
    msg = f"已删除人员「{member.name}」" + (f"，并停用其账号：{'、'.join(disabled_accounts)}" if disabled_accounts else "")
    return ok({"deleted": True, "accounts_disabled": disabled_accounts, "message": msg})


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
def list_positions(db: Session = Depends(get_db), _: AuthUser = Depends(require_perm("positions", "view"))):
    items = db.query(Position).filter(Position.is_deleted.is_(False)).order_by(Position.created_at).all()
    return ok([_position_row(p, db) for p in items], total=len(items))


@router.post("/api/positions")
def create_position(body: PositionCreate, db: Session = Depends(get_db), actor=Depends(require_perm("positions", "create"))):
    pos = Position(**body.model_dump())
    db.add(pos)
    db.flush()
    audit(db, "position", pos.id, "create", actor, {"name": body.name})
    db.commit()
    return ok(_position_row(pos, db))


@router.patch("/api/positions/{position_id}")
def update_position(
    position_id: str, body: PositionUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("positions", "edit"))
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
