"""团队管理（M6）：培训发展 / 团队文化 / 招聘需求 / 团队总览 / 人效评分框架。"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_example_delete_allowed
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import (
    ActivityCampaign,
    AuthUser,
    DevelopmentActivity,
    HiringNeed,
    Idea,
    KnowledgeArticle,
    OrgMember,
    PointEntry,
    Position,
    Requirement,
    RequirementTask,
    TeamCharter,
    Ticket,
    WbsTask,
)
from app.schemas.common import ok
from app.services.audit import audit
from app.services.points import award_by_rule, current_period, period_clause
from app.services.team_scope import is_it_member, it_member_ids

router = APIRouter(tags=["team"])

ACTIVITY_TYPES = ("内部交叉培训", "外部技术交流", "新技术研究")


class TrainingIn(BaseModel):
    activity_type: str
    topic: str = Field(min_length=2, max_length=200)
    activity_date: date
    host_id: str | None = None
    participant_ids: list[str] = []
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

@router.get("/api/trainings")
def list_trainings(db: Session = Depends(get_db), _=Depends(require_perm("activities", "view"))):
    team_ids = it_member_ids(db)
    rows = (
        db.query(DevelopmentActivity)
        .filter(DevelopmentActivity.is_deleted.is_(False))
        .order_by(DevelopmentActivity.activity_date.desc())
        .limit(200)
        .all()
    )
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.id.in_(team_ids or {"-"}))}
    return ok([
        {"id": r.id, "activity_type": r.activity_type, "topic": r.topic,
         "activity_date": r.activity_date, "host_id": r.host_id, "host_name": names.get(r.host_id),
         "participant_names": [names.get(p) for p in (r.participant_ids or []) if names.get(p)],
         "output_link": r.output_link, "remarks": r.remarks}
        for r in rows
    ], total=len(rows))


@router.post("/api/trainings")
def create_training(body: TrainingIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("activities", "create"))):
    if body.activity_type not in ACTIVITY_TYPES:
        raise AppError("INVALID_TYPE", f"活动类型须为 {'/'.join(ACTIVITY_TYPES)}")
    people = set(body.participant_ids or []) | ({body.host_id} if body.host_id else set())
    outside = people - it_member_ids(db)
    if outside:
        raise AppError("NOT_IT_TEAM_MEMBER", "培训发展仅可选择 IT 团队成员")
    row = DevelopmentActivity(**body.model_dump())
    db.add(row)
    db.flush()
    # 登记即触发培训积分：主讲/组织人 + 参与人
    if row.host_id:
        award_by_rule(db, "training_host", row.host_id, row.id, f"主讲培训 {row.topic[:30]}")
    for pid in row.participant_ids or []:
        if pid != row.host_id:
            award_by_rule(db, "training_attend", pid, row.id, f"参与培训 {row.topic[:30]}")
    audit(db, "development_activity", row.id, "create", user, {"topic": body.topic})
    db.commit()
    return ok({"id": row.id})


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
    board = (
        db.query(PointEntry.person_id, func.sum(PointEntry.points))
        .filter(
            period_clause(PointEntry.period, period),
            PointEntry.person_id.in_(team_ids or {"-"}),
            PointEntry.contribution_bucket == "team_contribution",
            PointEntry.is_deleted.is_(False),
        )
        .group_by(PointEntry.person_id)
        .order_by(func.sum(PointEntry.points).desc())
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
        "workload": _workload(db)[:20],
        "points_board": [{"person_name": names.get(pid), "points": round(float(pts), 1)} for pid, pts in board],
        "trainings_month": trainings_month,
        "active_campaigns": active_campaigns,
        "onboard_count": len(team_ids),
        "open_hirings": db.query(HiringNeed).filter(
            HiringNeed.is_deleted.is_(False), HiringNeed.status.in_(["待招聘", "面试中"])
        ).count(),
    })
