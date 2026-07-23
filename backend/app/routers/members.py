from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_example_delete_allowed
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
    scope: str = "",
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
):
    query = db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))
    if scope == "it":
        from app.services.team_scope import it_member_ids
        query = query.filter(OrgMember.id.in_(it_member_ids(db) or {"-"}))
    if q:
        query = query.filter(OrgMember.name.ilike(f"%{q}%"))
    # 全员同步后近千人，人员下拉需一次取全：上限放宽到 2000（M36.1）
    items, total = paginate(query.order_by(OrgMember.created_at.desc()), page, page_size, max_size=2000)
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
    from app.services.team_scope import it_member_ids

    onboard = (
        db.query(OrgMember)
        .filter(OrgMember.position_id == p.id, OrgMember.id.in_(it_member_ids(db) or {"-"}),
                OrgMember.status == "在岗", OrgMember.is_deleted.is_(False),
                # 编制只统计正式员工；历史未填 employment_type 的人员按正式员工兼容处理。
                (OrgMember.employment_type.is_(None) | (OrgMember.employment_type == "正式")))
        .count()
    )
    return {
        "id": p.id,
        "position_code": p.position_code,
        "name": p.name,
        "position_family": p.position_family,
        "duties": p.duties,
        "headcount": p.headcount,
        "service_domains": p.service_domains or [],
        "primary_roles": p.primary_roles or [],
        "level_framework": p.level_framework,
        "location_scope": p.location_scope,
        "skills": p.skills,
        "contractor_allowed": p.contractor_allowed,
        "status": p.status,
        "sort": p.sort,
        "onboard": onboard,
        "formal_onboard": onboard,
        "gap": p.headcount - onboard,
    }


@router.get("/api/positions")
def list_positions(
    page: int = 1,
    page_size: int = 20,
    q: str = "",
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_perm("positions", "view")),
):
    query = db.query(Position).filter(Position.is_deleted.is_(False))
    if q:
        query = query.filter((Position.name.ilike(f"%{q}%")) | (Position.position_code.ilike(f"%{q}%")))
    items, total = paginate(query.order_by(Position.sort, Position.created_at), page, page_size, max_size=2000)
    return ok([_position_row(p, db) for p in items], total=total, page=page)


def _position_sheet():
    from app.services.excel_io import Col, Sheet

    return Sheet("岗位定义", [
        Col("position_code", "岗位编码", hint="建议唯一；留空时按岗位名称匹配已有岗位，否则新建", max_length=32),
        Col("name", "岗位名称", required=True, max_length=64),
        Col("position_family", "岗位族/序列", hint="如治理、产品、研发、数据、运维、安全", max_length=32),
        Col("service_domains", "服务业务域", hint="多个值用分号分隔"),
        Col("primary_roles", "主责角色", hint="填写角色 code，多个值用分号分隔"),
        Col("level_framework", "职级/能力框架", max_length=64),
        Col("location_scope", "办公地点范围", max_length=128),
        Col("skills", "关键技能", hint="多个值用分号分隔"),
        Col("headcount", "正式编制数", required=True, kind="int"),
        Col("contractor_allowed", "允许外包", enum=["是", "否"]),
        Col("status", "状态", enum=["启用", "停用"], max_length=16),
        Col("sort", "排序", kind="int"),
        Col("duties", "职责"),
    ])


def _xlsx_response(content: bytes, filename: str) -> Response:
    from urllib.parse import quote

    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=template.xlsx; filename*=UTF-8''{quote(filename)}"},
    )


def _split_values(value: str | None) -> list[str]:
    if not value:
        return []
    text = str(value).replace("、", ";").replace(",", ";").replace("，", ";").replace("；", ";")
    return [v.strip() for v in text.split(";") if v.strip()]


@router.get("/api/positions/template")
def position_template(_: AuthUser = Depends(require_perm("positions", "create"))):
    from app.services.excel_io import build_template

    return _xlsx_response(build_template([_position_sheet()]), "岗位定义导入模板.xlsx")


@router.get("/api/positions/export")
def export_positions(db: Session = Depends(get_db), _: AuthUser = Depends(require_perm("positions", "view"))):
    from app.services.excel_io import build_export

    rows = []
    for p in db.query(Position).filter(Position.is_deleted.is_(False)).order_by(Position.sort, Position.created_at).all():
        row = _position_row(p, db)
        rows.append({
            "position_code": row["position_code"], "name": row["name"], "position_family": row["position_family"],
            "service_domains": row["service_domains"], "primary_roles": row["primary_roles"],
            "level_framework": row["level_framework"], "location_scope": row["location_scope"],
            "skills": row["skills"], "headcount": row["headcount"],
            "contractor_allowed": "是" if row["contractor_allowed"] else "否", "status": row["status"],
            "sort": row["sort"], "duties": row["duties"],
        })
    return _xlsx_response(build_export(_position_sheet(), rows), "岗位定义.xlsx")


@router.post("/api/positions/import")
async def import_positions(file: UploadFile, db: Session = Depends(get_db), actor=Depends(require_perm("positions", "create"))):
    from app.services.excel_io import parse_sheet

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise AppError("FILE_TOO_LARGE", "导入文件不能超过 5MB")
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise AppError("INVALID_FORMAT", "请上传 .xlsx 文件（使用系统导出的模板）")
    rows, errors = parse_sheet(content, _position_sheet())
    created = updated = 0
    for row in rows:
        rownum = row.pop("_row")
        code = (row.get("position_code") or "").strip() or None
        name = row["name"].strip()
        code_pos = None
        if code:
            code_pos = db.query(Position).filter(Position.position_code == code, Position.is_deleted.is_(False)).first()
        name_pos = db.query(Position).filter(Position.name == name, Position.is_deleted.is_(False)).first()
        # 编码和名称分别命中不同岗位时，不能静默覆盖其中一个岗位。
        if code_pos and name_pos and code_pos.id != name_pos.id:
            errors.append({"row": rownum, "error": f"岗位编码「{code}」与岗位名称「{name}」分别对应不同岗位，请只保留正确的一条记录"})
            continue
        pos = code_pos or name_pos
        if pos is None and code:
            deleted = db.query(Position).filter(Position.position_code == code, Position.is_deleted.is_(True)).first()
            if deleted:
                errors.append({"row": rownum, "error": f"岗位编码「{code}」对应的岗位已删除，请使用新编码"})
                continue
        if pos is None:
            pos = Position(position_code=code, name=name)
            db.add(pos)
            created += 1
        else:
            updated += 1
        row["position_code"] = code
        row["service_domains"] = _split_values(row.get("service_domains"))
        row["primary_roles"] = _split_values(row.get("primary_roles"))
        row["contractor_allowed"] = row.get("contractor_allowed") == "是"
        row["status"] = row.get("status") or "启用"
        row["sort"] = row.get("sort") or 0
        for key in ("position_code", "name", "position_family", "duties", "headcount", "service_domains", "primary_roles",
                    "level_framework", "location_scope", "skills", "contractor_allowed", "status", "sort"):
            if key in row:
                setattr(pos, key, row[key])
    try:
        db.flush()
        audit(db, "position", "bulk", "import", actor, {"created": created, "updated": updated, "failed": len(errors)})
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError("IMPORT_FAILED", "岗位定义导入失败，请检查字段长度、岗位编码和数据库约束后重试") from exc
    return ok({"created": created, "updated": updated, "failed": errors})


@router.post("/api/positions")
def create_position(body: PositionCreate, db: Session = Depends(get_db), actor=Depends(require_perm("positions", "create"))):
    if body.position_code and db.query(Position).filter(Position.position_code == body.position_code, Position.is_deleted.is_(False)).first():
        raise AppError("DUPLICATE", f"岗位编码「{body.position_code}」已存在", 409)
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
    if data.get("position_code") and db.query(Position).filter(
        Position.position_code == data["position_code"], Position.id != pos.id, Position.is_deleted.is_(False)
    ).first():
        raise AppError("DUPLICATE", f"岗位编码「{data['position_code']}」已存在", 409)
    for k, v in data.items():
        setattr(pos, k, v)
    audit(db, "position", pos.id, "update", actor, {"fields": list(data.keys())})
    db.commit()
    return ok(_position_row(pos, db))


@router.delete("/api/positions/{position_id}")
def delete_position(position_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("positions", "delete"))):
    """删除岗位定义（软删）；仍被人员或招聘需求引用时拒绝，避免断开历史关联。"""
    pos = db.get(Position, position_id)
    if not pos or pos.is_deleted:
        raise AppError("NOT_FOUND", "岗位不存在", 404)
    ensure_example_delete_allowed(pos, db, actor)
    member_count = db.query(OrgMember).filter(OrgMember.position_id == pos.id, OrgMember.is_deleted.is_(False)).count()
    if member_count:
        raise AppError("POSITION_IN_USE", f"该岗位仍关联 {member_count} 名人员，请先调整人员岗位后再删除")
    from app.models import HiringNeed

    hiring_count = db.query(HiringNeed).filter(HiringNeed.position_id == pos.id, HiringNeed.is_deleted.is_(False)).count()
    if hiring_count:
        raise AppError("POSITION_HAS_HIRING", f"该岗位仍有 {hiring_count} 条招聘需求，请先删除或关闭招聘需求")
    pos.is_deleted = True
    audit(db, "position", pos.id, "delete", actor, {"name": pos.name, "position_code": pos.position_code})
    db.commit()
    return ok({"id": pos.id})
