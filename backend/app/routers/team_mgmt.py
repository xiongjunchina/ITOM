"""团队管理（M6）：培训发展 / 团队文化 / 招聘需求 / 团队总览 / 人效评分框架。"""
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import AppError
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
from app.services.points import award_by_rule, current_period

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
    rows = (
        db.query(DevelopmentActivity)
        .filter(DevelopmentActivity.is_deleted.is_(False))
        .order_by(DevelopmentActivity.activity_date.desc())
        .limit(200)
        .all()
    )
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
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
    positions = {p.id: p.name for p in db.query(Position).filter(Position.is_deleted.is_(False))}
    return ok([
        {"id": r.id, "position_id": r.position_id, "position_name": positions.get(r.position_id),
         "level": r.level, "qualification": r.qualification,
         "headcount": r.headcount, "status": r.status, "progress_note": r.progress_note}
        for r in rows
    ], total=len(rows))


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


# ---------- 团队总览 ----------

def _workload(db: Session) -> list[dict]:
    members = db.query(OrgMember).filter(OrgMember.is_deleted.is_(False), OrgMember.status == "在岗").all()
    open_tickets: dict[str, int] = {}
    for (assignee,) in db.query(Ticket.assignee).filter(
        Ticket.assignee.isnot(None), Ticket.is_deleted.is_(False), Ticket.is_example.is_(False),
        Ticket.status.notin_(["resolved", "closed", "rejected"]),
    ):
        open_tickets[assignee] = open_tickets.get(assignee, 0) + 1
    open_wbs: dict[str, int] = {}
    for (assignee,) in db.query(WbsTask.assignee).filter(
        WbsTask.is_deleted.is_(False), WbsTask.is_example.is_(False), WbsTask.status != "已完成",
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
    board = (
        db.query(PointEntry.person_id, func.sum(PointEntry.points))
        .filter(PointEntry.period == period, PointEntry.is_deleted.is_(False))
        .group_by(PointEntry.person_id)
        .order_by(func.sum(PointEntry.points).desc())
        .limit(10)
        .all()
    )
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
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
        "onboard_count": db.query(OrgMember).filter(OrgMember.is_deleted.is_(False), OrgMember.status == "在岗").count(),
        "open_hirings": db.query(HiringNeed).filter(
            HiringNeed.is_deleted.is_(False), HiringNeed.status.in_(["待招聘", "面试中"])
        ).count(),
    })
