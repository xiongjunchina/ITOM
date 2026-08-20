"""团队管理（M6）：培训发展 / 团队文化 / 招聘需求 / 团队总览 / 人效评分框架。"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_example_delete_allowed
from app.core.rbac import ADMIN, CIO
from app.db import get_db
from app.deps import require_perm
from app.models import (
    ActivityCampaign,
    AuthUser,
    Department,
    DevelopmentActivity,
    HiringNeed,
    Idea,
    KnowledgeArticle,
    OrgMember,
    PerformancePeriod,
    PointEntry,
    Position,
    ProjectDevelopmentTask,
    Requirement,
    RequirementTask,
    TeamCharter,
    Ticket,
    WbsTask,
)
from app.schemas.common import BatchDeleteIn, ok
from app.services.audit import audit
from app.services.batch_delete import execute_batch_delete
from app.services.points import award_by_rule, current_period, live_team_points_expression, period_clause
from app.services.rbac import effective_roles
from app.services.team_scope import is_it_member, it_member_ids

router = APIRouter(tags=["team"])

ACTIVITY_TYPES = ("内部交叉培训", "外部技术交流", "新技术研究")


class TrainingIn(BaseModel):
    activity_type: str
    topic: str = Field(min_length=2, max_length=200)
    activity_date: date
    host_id: str | None = None
    participant_ids: list[str] = Field(default_factory=list)
    # None 表示旧客户端/不含部门语义的 PATCH，保留原有部门快照；[] 表示明确取消部门范围。
    participant_department_ids: list[str] | None = None
    output_link: str | None = None
    remarks: str | None = None


class CharterIn(BaseModel):
    vision: str | None = None
    goals: str | None = None
    principles: str | None = None


class HiringIn(BaseModel):
    position_id: str
    level: str = Field(default="中级", pattern="^(高级|中级|初级)$")
    headcount: int = Field(default=1, ge=1)
    qualification: str = Field(min_length=5, max_length=2000, description="任职资格要求（必填）")
    status: str = Field(default="待招聘", pattern="^(待招聘|面试中|已到岗|已取消)$")
    progress_note: str | None = None


# ---------- 培训发展 ----------

TRAINING_POINT_TYPES = ("training_host", "training_attend")


def _normalise_training(body: TrainingIn) -> TrainingIn:
    """去重参与人，保持前端勾选顺序，避免同一活动重复发分。"""
    departments = body.participant_department_ids
    return body.model_copy(update={
        "participant_ids": list(dict.fromkeys(body.participant_ids or [])),
        "participant_department_ids": list(dict.fromkeys(departments)) if departments is not None else None,
    })


def _resolve_training_departments(db: Session, body: TrainingIn) -> tuple[TrainingIn, list[dict] | None]:
    """展开整部门选择，并冻结部门显示名及活动登记当日的 IT 人员范围。"""
    selected_ids = body.participant_department_ids
    if selected_ids is None:
        return body, None
    if not selected_ids:
        return body, []

    departments = {
        department.id: department
        for department in db.query(Department).filter(
            Department.id.in_(selected_ids),
            Department.active.is_(True),
            Department.is_deleted.is_(False),
        )
    }
    if missing_ids := set(selected_ids) - set(departments):
        raise AppError("INVALID_TRAINING_DEPARTMENT", "参与部门不存在或已停用", 422)

    team_ids = it_member_ids(db)
    members = (
        db.query(OrgMember)
        .filter(
            OrgMember.id.in_(team_ids or {"-"}),
            OrgMember.department_id.in_(selected_ids),
            OrgMember.is_deleted.is_(False),
            OrgMember.status == "在岗",
        )
        .order_by(OrgMember.name, OrgMember.id)
        .all()
    )
    by_department: dict[str, list[str]] = {department_id: [] for department_id in selected_ids}
    for member in members:
        if member.department_id:
            by_department[member.department_id].append(member.id)

    snapshots: list[dict] = []
    expanded_ids: list[str] = []
    for department_id in selected_ids:
        member_ids = by_department[department_id]
        if not member_ids:
            raise AppError("EMPTY_TRAINING_DEPARTMENT", "参与部门没有可选择的 IT 团队成员", 422)
        snapshots.append({
            "id": department_id,
            "name": departments[department_id].name,
            "member_ids": member_ids,
        })
        expanded_ids.extend(member_ids)
    return body.model_copy(update={"participant_ids": list(dict.fromkeys((body.participant_ids or []) + expanded_ids))}), snapshots


def _validate_training_people(db: Session, body: TrainingIn) -> tuple[TrainingIn, list[dict] | None]:
    if body.activity_type not in ACTIVITY_TYPES:
        raise AppError("INVALID_TYPE", f"活动类型须为 {'/'.join(ACTIVITY_TYPES)}")
    normalized = _normalise_training(body)
    normalized, department_snapshots = _resolve_training_departments(db, normalized)
    people = set(normalized.participant_ids or []) | ({normalized.host_id} if normalized.host_id else set())
    outside = people - it_member_ids(db)
    if outside:
        raise AppError("NOT_IT_TEAM_MEMBER", "培训发展仅可选择 IT 团队成员")
    return normalized, department_snapshots


def _training_point_entries(db: Session, activity_id: str) -> list[PointEntry]:
    return (
        db.query(PointEntry)
        .filter(
            PointEntry.source_ref == activity_id,
            PointEntry.source_type.in_(TRAINING_POINT_TYPES),
            PointEntry.is_deleted.is_(False),
        )
        .all()
    )


def _ensure_training_points_mutable(db: Session, activity_id: str) -> list[PointEntry]:
    """仅允许修正当前且未发布/锁定考核期的培训积分。"""
    entries = _training_point_entries(db, activity_id)
    if not entries:
        return entries
    period = current_period()
    if any(entry.period != period for entry in entries):
        raise AppError("TRAINING_POINTS_LOCKED", "历史考核期的培训积分不可重算或撤销", 409)
    performance_period = (
        db.query(PerformancePeriod)
        .filter(
            PerformancePeriod.period_code == period,
            PerformancePeriod.status.in_(("published", "locked")),
            PerformancePeriod.is_deleted.is_(False),
        )
        .first()
    )
    if performance_period:
        raise AppError("TRAINING_POINTS_LOCKED", "当前考核期已发布/锁定，不能修改会影响培训积分的内容", 409)
    return entries


def _award_training_points(db: Session, row: DevelopmentActivity):
    """按当前生效规则写入主讲/参与培训积分。"""
    if row.host_id:
        award_by_rule(db, "training_host", row.host_id, row.id, f"主讲培训 {row.topic[:30]}")
    for person_id in row.participant_ids or []:
        if person_id != row.host_id:
            award_by_rule(db, "training_attend", person_id, row.id, f"参与培训 {row.topic[:30]}")


def _can_manage_training(row: DevelopmentActivity, user: AuthUser, roles: set[str]) -> bool:
    return ADMIN in roles or CIO in roles or row.created_by == user.id


def _training_department_snapshots(row: DevelopmentActivity) -> list[dict]:
    """兼容历史空值和异常旧快照；清单只使用完整、可读的部门快照。"""
    snapshots: list[dict] = []
    for value in row.participant_department_selections or []:
        if not isinstance(value, dict):
            continue
        department_id = value.get("id")
        name = value.get("name")
        member_ids = value.get("member_ids")
        if isinstance(department_id, str) and isinstance(name, str) and isinstance(member_ids, list):
            snapshots.append({
                "id": department_id,
                "name": name,
                "member_ids": [member_id for member_id in member_ids if isinstance(member_id, str)],
            })
    return snapshots


def _training_row(row: DevelopmentActivity, names: dict[str, str], can_manage: bool) -> dict:
    department_snapshots = _training_department_snapshots(row)
    department_member_ids = {
        person_id
        for snapshot in department_snapshots
        for person_id in snapshot["member_ids"]
    }
    participant_ids = row.participant_ids or []
    return {
        "id": row.id,
        "activity_type": row.activity_type,
        "topic": row.topic,
        "activity_date": row.activity_date,
        "host_id": row.host_id,
        "host_name": names.get(row.host_id),
        "participant_ids": participant_ids,
        # participant_names 保留给旧客户端；新版清单优先读部门和范围外个人摘要。
        "participant_names": [names.get(person_id) for person_id in participant_ids if names.get(person_id)],
        "participant_departments": [{"id": snapshot["id"], "name": snapshot["name"]} for snapshot in department_snapshots],
        "participant_individual_names": [
            names.get(person_id)
            for person_id in participant_ids
            if person_id not in department_member_ids and names.get(person_id)
        ],
        "output_link": row.output_link,
        "remarks": row.remarks,
        "can_manage": can_manage,
    }

@router.get("/api/trainings")
def list_trainings(db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("activities", "view"))):
    team_ids = it_member_ids(db)
    rows = (
        db.query(DevelopmentActivity)
        .filter(DevelopmentActivity.is_deleted.is_(False))
        .order_by(DevelopmentActivity.activity_date.desc())
        .limit(200)
        .all()
    )
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.id.in_(team_ids or {"-"}))}
    roles = effective_roles(db, user)
    return ok([_training_row(row, names, _can_manage_training(row, user, roles)) for row in rows], total=len(rows))


@router.post("/api/trainings")
def create_training(body: TrainingIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("activities", "create"))):
    body, department_snapshots = _validate_training_people(db, body)
    row = DevelopmentActivity(
        **body.model_dump(exclude={"participant_department_ids"}),
        participant_department_selections=department_snapshots or [],
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    _award_training_points(db, row)
    audit(db, "development_activity", row.id, "create", user, {
        "topic": body.topic,
        "participant_department_ids": [snapshot["id"] for snapshot in department_snapshots or []],
    })
    db.commit()
    return ok({"id": row.id})


@router.patch("/api/trainings/{activity_id}")
def update_training(
    activity_id: str,
    body: TrainingIn,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_perm("activities", "view")),
):
    row = db.get(DevelopmentActivity, activity_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "培训活动不存在", 404)
    roles = effective_roles(db, user)
    if not _can_manage_training(row, user, roles):
        raise AppError("FORBIDDEN", "仅管理员、CIO 或登记人可编辑该培训活动", 403)
    body, department_snapshots = _validate_training_people(db, body)
    scores_changed = row.host_id != body.host_id or (row.participant_ids or []) != (body.participant_ids or [])
    existing_entries = _ensure_training_points_mutable(db, row.id) if scores_changed else []
    for field, value in body.model_dump(exclude={"participant_department_ids"}).items():
        setattr(row, field, value)
    if department_snapshots is not None:
        row.participant_department_selections = department_snapshots
    if scores_changed:
        for entry in existing_entries:
            entry.is_deleted = True
        _award_training_points(db, row)
    audit(
        db,
        "development_activity",
        row.id,
        "update",
        user,
        {
            "fields": list(body.model_dump(exclude={"participant_department_ids"}).keys()),
            "participant_departments_changed": department_snapshots is not None,
            "points_recalculated": scores_changed,
        },
    )
    db.commit()
    return ok({"id": row.id, "points_recalculated": scores_changed})


def _delete_training(db: Session, row: DevelopmentActivity, user: AuthUser) -> dict:
    """沿用培训活动的登记人/CIO/管理员权限与积分撤回规则，不提交事务。"""
    roles = effective_roles(db, user)
    if not _can_manage_training(row, user, roles):
        raise AppError("FORBIDDEN", "仅管理员、CIO 或登记人可删除该培训活动", 403)
    entries = _ensure_training_points_mutable(db, row.id)
    for entry in entries:
        entry.is_deleted = True
    row.is_deleted = True
    audit(db, "development_activity", row.id, "delete", user, {"points_retracted": len(entries)})
    return {"id": row.id, "points_retracted": len(entries)}


@router.delete("/api/trainings/batch-delete")
def batch_delete_trainings(
    body: BatchDeleteIn,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_perm("activities", "view")),
):
    def delete_one(activity_id: str) -> None:
        row = db.get(DevelopmentActivity, activity_id)
        if not row or row.is_deleted:
            raise AppError("NOT_FOUND", "培训活动不存在", 404)
        _delete_training(db, row, user)

    return ok(execute_batch_delete(db, body.ids, delete_one))


@router.delete("/api/trainings/{activity_id}")
def delete_training(
    activity_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_perm("activities", "view")),
):
    row = db.get(DevelopmentActivity, activity_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "培训活动不存在", 404)
    result = _delete_training(db, row, user)
    db.commit()
    return ok(result)


# ---------- 团队文化（单例） ----------

@router.get("/api/team-charter")
def get_charter(db: Session = Depends(get_db), _=Depends(require_perm("charter", "view"))):
    row = db.query(TeamCharter).filter(TeamCharter.is_deleted.is_(False)).first()
    if not row:
        return ok({"vision": None, "goals": None, "principles": None, "updated_at": None})
    return ok({"vision": row.vision, "goals": row.goals, "principles": row.principles, "updated_at": row.updated_at})


@router.put("/api/team-charter")
def put_charter(body: CharterIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("charter", "edit"))):
    row = db.query(TeamCharter).filter(TeamCharter.is_deleted.is_(False)).first()
    if not row:
        row = TeamCharter()
        db.add(row)
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    row.updated_by = user.id
    audit(db, "team_charter", row.id or "singleton", "update", user, {})
    db.commit()
    return ok({"updated": True})


# ---------- 招聘需求（岗位编制页） ----------

@router.get("/api/hiring-needs")
def list_hiring(db: Session = Depends(get_db), _=Depends(require_perm("positions", "view"))):
    rows = db.query(HiringNeed).filter(HiringNeed.is_deleted.is_(False)).order_by(HiringNeed.created_at.desc()).all()
    positions = {p.id: p for p in db.query(Position).filter(Position.is_deleted.is_(False))}
    return ok([
        {"id": r.id, "position_id": r.position_id, "position_name": positions.get(r.position_id).name if positions.get(r.position_id) else None,
         "position_code": positions.get(r.position_id).position_code if positions.get(r.position_id) else None,
         "level": r.level, "qualification": r.qualification,
         "headcount": r.headcount, "status": r.status, "progress_note": r.progress_note}
        for r in rows
    ], total=len(rows))


def _hiring_sheet():
    from app.services.excel_io import Col, Sheet

    return Sheet("招聘需求", [
        Col("hiring_id", "需求ID", hint="导出数据中存在；填写时留空表示新建，填写已有 ID 表示更新", max_length=26),
        Col("position_code", "岗位编码", hint="优先按岗位编码匹配；也可只填岗位名称", max_length=32),
        Col("position_name", "岗位名称", hint="岗位编码为空时按名称精确匹配", max_length=64),
        Col("level", "级别", required=True, enum=["高级", "中级", "初级"], max_length=8),
        Col("headcount", "招聘人数", required=True, kind="int"),
        Col("qualification", "任职资格", required=True, hint="至少 5 个字符"),
        Col("status", "状态", enum=["待招聘", "面试中", "已到岗", "已取消"], max_length=16),
        Col("progress_note", "进度备注", max_length=200),
    ])


def _hiring_xlsx_response(content: bytes, filename: str) -> Response:
    from urllib.parse import quote

    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=template.xlsx; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/api/hiring-needs/template")
def hiring_template(_: AuthUser = Depends(require_perm("positions", "create"))):
    from app.services.excel_io import build_template

    return _hiring_xlsx_response(build_template([_hiring_sheet()]), "招聘需求导入模板.xlsx")


@router.get("/api/hiring-needs/export")
def export_hiring(db: Session = Depends(get_db), _: AuthUser = Depends(require_perm("positions", "view"))):
    from app.services.excel_io import build_export

    positions = {p.id: p for p in db.query(Position).filter(Position.is_deleted.is_(False))}
    rows = []
    for r in db.query(HiringNeed).filter(HiringNeed.is_deleted.is_(False)).order_by(HiringNeed.created_at.desc()).all():
        p = positions.get(r.position_id)
        rows.append({
            "hiring_id": r.id, "position_code": p.position_code if p else None, "position_name": p.name if p else None,
            "level": r.level, "headcount": r.headcount, "qualification": r.qualification,
            "status": r.status, "progress_note": r.progress_note,
        })
    return _hiring_xlsx_response(build_export(_hiring_sheet(), rows), "招聘需求.xlsx")


@router.post("/api/hiring-needs/import")
async def import_hiring(file: UploadFile, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("positions", "create"))):
    from app.services.excel_io import parse_sheet

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise AppError("FILE_TOO_LARGE", "导入文件不能超过 5MB")
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise AppError("INVALID_FORMAT", "请上传 .xlsx 文件（使用系统导出的模板）")
    rows, errors = parse_sheet(content, _hiring_sheet())
    positions = db.query(Position).filter(Position.is_deleted.is_(False)).all()
    by_code = {p.position_code: p for p in positions if p.position_code}
    by_name = {p.name: p for p in positions}
    created = updated = 0
    for row in rows:
        rownum = row.pop("_row")
        position = by_code.get((row.get("position_code") or "").strip()) or by_name.get((row.get("position_name") or "").strip())
        if not position:
            errors.append({"row": rownum, "error": "岗位编码或岗位名称不存在，请先在岗位定义中维护"})
            continue
        qualification = (row.get("qualification") or "").strip()
        if len(qualification) < 5:
            errors.append({"row": rownum, "error": "任职资格至少填写 5 个字符"})
            continue
        row["status"] = row.get("status") or "待招聘"
        existing = None
        hiring_id = (row.get("hiring_id") or "").strip()
        if hiring_id:
            existing = db.get(HiringNeed, hiring_id)
            if existing and existing.is_deleted:
                existing = None
        if existing is None:
            existing = HiringNeed(position_id=position.id)
            db.add(existing)
            created += 1
        else:
            updated += 1
        existing.position_id = position.id
        existing.level = row["level"]
        existing.headcount = row["headcount"]
        existing.qualification = qualification
        existing.status = row["status"]
        existing.progress_note = row.get("progress_note")
    try:
        db.flush()
        audit(db, "hiring_need", "bulk", "import", actor, {"created": created, "updated": updated, "failed": len(errors)})
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError("IMPORT_FAILED", "招聘需求导入失败，请检查岗位、字段长度和数据库约束后重试") from exc
    return ok({"created": created, "updated": updated, "failed": errors})


@router.post("/api/hiring-needs")
def create_hiring(body: HiringIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("positions", "create"))):
    if not db.get(Position, body.position_id):
        raise AppError("NOT_FOUND", "岗位不存在", 404)
    row = HiringNeed(**body.model_dump())
    db.add(row)
    db.flush()
    audit(db, "hiring_need", row.id, "create", user, {"headcount": body.headcount})
    db.commit()
    return ok({"id": row.id})


@router.patch("/api/hiring-needs/{hiring_id}")
def update_hiring(hiring_id: str, body: HiringIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("positions", "edit"))):
    row = db.get(HiringNeed, hiring_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "招聘需求不存在", 404)
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    audit(db, "hiring_need", row.id, "update", user, {"status": body.status})
    db.commit()
    return ok({"id": row.id})


@router.delete("/api/hiring-needs/{hiring_id}")
def delete_hiring(hiring_id: str, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("positions", "delete"))):
    row = db.get(HiringNeed, hiring_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "招聘需求不存在", 404)
    ensure_example_delete_allowed(row, db, actor)
    row.is_deleted = True
    audit(db, "hiring_need", row.id, "delete", actor, {"position_id": row.position_id, "headcount": row.headcount})
    db.commit()
    return ok({"id": row.id})


# ---------- 团队总览 ----------

def _workload(db: Session) -> list[dict]:
    members = db.query(OrgMember).filter(OrgMember.id.in_(it_member_ids(db) or {"-"}), OrgMember.is_deleted.is_(False), OrgMember.status == "在岗").all()
    open_tickets: dict[str, int] = {}
    for (assignee,) in db.query(Ticket.assignee).filter(
        Ticket.assignee.isnot(None), Ticket.is_deleted.is_(False), Ticket.is_example.is_(False),
        Ticket.status.notin_(["resolved", "closed", "rejected"]),
    ):
        open_tickets[assignee] = open_tickets.get(assignee, 0) + 1
    open_wbs: dict[str, int] = {}
    for (assignee,) in db.query(WbsTask.assignee).filter(
        WbsTask.is_deleted.is_(False), WbsTask.is_example.is_(False), WbsTask.progress < 100,
    ):
        open_wbs[assignee] = open_wbs.get(assignee, 0) + 1
    # “项目任务”同时包含项目计划中的未完成 WBS 工作包，以及在 WBS
    # 未细分到开发活动时单独登记的未完成项目开发任务。
    for (assignee,) in db.query(ProjectDevelopmentTask.assignee).filter(
        ProjectDevelopmentTask.assignee.isnot(None),
        ProjectDevelopmentTask.is_deleted.is_(False),
        ProjectDevelopmentTask.is_example.is_(False),
        ProjectDevelopmentTask.status != "已完成",
    ):
        open_wbs[assignee] = open_wbs.get(assignee, 0) + 1
    open_req: dict[str, int] = {}
    for (assignee,) in db.query(RequirementTask.assignee).filter(
        RequirementTask.is_deleted.is_(False), RequirementTask.is_example.is_(False), RequirementTask.status != "已完成",
    ):
        open_req[assignee] = open_req.get(assignee, 0) + 1
    rows = []
    for m in members:
        t, w, r = open_tickets.get(m.id, 0), open_wbs.get(m.id, 0), open_req.get(m.id, 0)
        rows.append({"person_id": m.id, "person_name": m.name, "tickets": t, "wbs_tasks": w,
                     "req_tasks": r, "total": t + w + r})
    return sorted(rows, key=lambda x: -x["total"])


@router.get("/api/team/overview")
def team_overview(db: Session = Depends(get_db), _=Depends(require_perm("team_overview", "view"))):
    period = current_period()
    team_ids = it_member_ids(db)
    live_rule, effective_points, join_condition = live_team_points_expression()
    board = (
        db.query(PointEntry.person_id, func.sum(effective_points))
        .outerjoin(live_rule, join_condition)
        .filter(
            period_clause(PointEntry.period, period),
            PointEntry.person_id.in_(team_ids or {"-"}),
            PointEntry.contribution_bucket == "team_contribution",
            PointEntry.is_deleted.is_(False),
        )
        .group_by(PointEntry.person_id)
        .order_by(func.sum(effective_points).desc())
        .limit(10)
        .all()
    )
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.id.in_(team_ids or {"-"}))}
    month_start = date.today().replace(day=1)
    trainings_month = (
        db.query(DevelopmentActivity)
        .filter(DevelopmentActivity.activity_date >= month_start, DevelopmentActivity.is_deleted.is_(False))
        .count()
    )
    active_campaigns = (
        db.query(ActivityCampaign)
        .filter(ActivityCampaign.status == "active", ActivityCampaign.is_deleted.is_(False))
        .count()
    )
    return ok({
        "period": period,
        # 团队总览需要展示全部在岗 IT 成员；页面在客户端按 20 条分页，
        # 不能在接口层截断，否则工具栏和在岗人数会产生不一致。
        "workload": _workload(db),
        "points_board": [{"person_name": names.get(pid), "points": round(float(pts), 1)} for pid, pts in board],
        "trainings_month": trainings_month,
        "active_campaigns": active_campaigns,
        "onboard_count": len(team_ids),
        "open_hirings": db.query(HiringNeed).filter(
            HiringNeed.is_deleted.is_(False), HiringNeed.status.in_(["待招聘", "面试中"])
        ).count(),
    })
