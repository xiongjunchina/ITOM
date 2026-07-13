"""活动积分（M6）：建言献策 + 专项活动 + 积分台账。"""
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_not_example
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import (
    ActivityCampaign,
    AuthUser,
    CampaignTask,
    Idea,
    IdeaLike,
    OrgMember,
    PointEntry,
)
from app.schemas.common import ok, paginate
from app.services.audit import audit
from app.services.codes import gen_code
from app.services.permissions import has_perm
from app.core.i18n import localize_status
from app.services.points import award, award_by_rule, current_period, period_clause

router = APIRouter(tags=["team"])


# ---------- Schemas ----------

class IdeaIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=1)


class IdeaStatusIn(BaseModel):
    status: str = Field(pattern="^(adopted|implemented|declined)$")
    reason: str | None = None


class CampaignTaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    points: float = Field(gt=0)
    max_times: int = Field(default=1, ge=0)


class CampaignIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    period_label: str = Field(min_length=2, max_length=32)
    start_date: date
    end_date: date
    performance_ratio: float = Field(default=1.0, gt=0)
    tasks: list[CampaignTaskIn] = Field(min_length=1)


class CampaignStatusIn(BaseModel):
    status: str = Field(pattern="^(draft|active|offline)$")


class AwardIn(BaseModel):
    person_id: str
    task_id: str
    times: int = Field(default=1, ge=1, le=10)
    note: str | None = None


# ---------- 建言献策 ----------

IDEA_STATUS_NAMES = {"submitted": "已提交", "adopted": "已采纳", "implemented": "已实现", "declined": "已婉拒"}


def _idea_row(i: Idea, liked_ids: set[str]) -> dict:
    return {
        "id": i.id, "idea_code": i.idea_code, "title": i.title, "content": i.content,
        "proposer_name": i.proposer_name, "status": i.status,
        "status_name": localize_status("idea", i.status, IDEA_STATUS_NAMES.get(i.status, i.status)),
        "like_count": i.like_count, "liked": i.id in liked_ids,
        "adopted_at": i.adopted_at, "decline_reason": i.decline_reason,
        "created_at": i.created_at, "is_example": i.is_example,
    }


@router.get("/api/ideas")
def list_ideas(status: str = "", page: int = 1, page_size: int = 50,
               db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("ideas", "view"))):
    query = db.query(Idea).filter(Idea.is_deleted.is_(False))
    if status:
        query = query.filter(Idea.status == status)
    items, total = paginate(query.order_by(Idea.is_example.desc(), Idea.created_at.desc()), page, page_size)
    liked_ids = {
        l.idea_id for l in db.query(IdeaLike).filter(IdeaLike.voter == user.id, IdeaLike.is_deleted.is_(False))
    }
    return ok([_idea_row(i, liked_ids) for i in items], total=total, page=page)


@router.post("/api/ideas")
def create_idea(body: IdeaIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("ideas", "create"))):
    person = db.get(OrgMember, user.person_id) if user.person_id else None
    idea = Idea(
        **body.model_dump(),
        idea_code=gen_code(db, Idea, "idea_code", "ID"),
        proposer=user.id, proposer_name=person.name if person else user.username,
    )
    db.add(idea)
    db.flush()
    award_by_rule(db, "idea_submit", user.person_id, idea.id, f"提出建言 {idea.title[:30]}")
    audit(db, "idea", idea.id, "create", user, {"code": idea.idea_code})
    db.commit()
    return ok(_idea_row(idea, set()))


@router.post("/api/ideas/{idea_id}/like")
def like_idea(idea_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("ideas", "view"))):
    idea = db.get(Idea, idea_id)
    if not idea or idea.is_deleted:
        raise AppError("NOT_FOUND", "建言不存在", 404)
    ensure_not_example(idea)
    if idea.proposer == user.id:
        raise AppError("SELF_LIKE", "不能给自己的建言点赞")
    dup = db.query(IdeaLike).filter(IdeaLike.idea_id == idea.id, IdeaLike.voter == user.id, IdeaLike.is_deleted.is_(False)).first()
    if dup:
        raise AppError("DUPLICATE", "已经点过赞了")
    db.add(IdeaLike(idea_id=idea.id, voter=user.id))
    idea.like_count = (idea.like_count or 0) + 1
    proposer_user = db.get(AuthUser, idea.proposer) if idea.proposer else None
    award_by_rule(db, "idea_like", proposer_user.person_id if proposer_user else None, idea.id, "建言被点赞")
    db.commit()
    return ok({"id": idea.id, "like_count": idea.like_count})


@router.patch("/api/ideas/{idea_id}/status")
def set_idea_status(idea_id: str, body: IdeaStatusIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("ideas", "edit"))):
    idea = db.get(Idea, idea_id)
    if not idea or idea.is_deleted:
        raise AppError("NOT_FOUND", "建言不存在", 404)
    ensure_not_example(idea)
    prev = idea.status
    idea.status = body.status
    if body.status == "adopted" and prev != "adopted":
        idea.adopted_at = datetime.now()
        proposer_user = db.get(AuthUser, idea.proposer) if idea.proposer else None
        award_by_rule(db, "idea_adopt", proposer_user.person_id if proposer_user else None, idea.id,
                      f"建言被采纳 {idea.title[:30]}")
    if body.status == "declined":
        idea.decline_reason = body.reason
    audit(db, "idea", idea.id, "status", user, {"from": prev, "to": body.status})
    db.commit()
    return ok({"id": idea.id, "status": idea.status})


# ---------- 专项活动 ----------

CAMPAIGN_STATUS_NAMES = {"draft": "草稿", "active": "上架中", "offline": "已下架"}


def _campaign_row(c: ActivityCampaign, db: Session, detail: bool = False, person_id: str | None = None) -> dict:
    total_awarded = (
        db.query(func.coalesce(func.sum(PointEntry.points), 0))
        .filter(PointEntry.campaign_id == c.id, PointEntry.is_deleted.is_(False))
        .scalar()
    )
    row = {
        "id": c.id, "name": c.name, "description": c.description,
        "period_label": c.period_label, "start_date": c.start_date, "end_date": c.end_date,
        "performance_ratio": c.performance_ratio,
        "status": c.status, "status_name": localize_status("campaign", c.status, CAMPAIGN_STATUS_NAMES.get(c.status, c.status)),
        "is_example": c.is_example,
        "total_awarded": float(total_awarded or 0),
        "tasks": [
            {"id": t.id, "name": t.name, "description": t.description,
             "points": t.points, "max_times": t.max_times}
            for t in c.tasks if not t.is_deleted
        ],
    }
    if person_id:
        mine = (
            db.query(func.coalesce(func.sum(PointEntry.points), 0))
            .filter(PointEntry.campaign_id == c.id, PointEntry.person_id == person_id, PointEntry.is_deleted.is_(False))
            .scalar()
        )
        row["my_points"] = float(mine or 0)
        row["my_performance"] = round(row["my_points"] * c.performance_ratio, 2)
    if detail:
        entries = (
            db.query(PointEntry)
            .filter(PointEntry.campaign_id == c.id, PointEntry.is_deleted.is_(False))
            .order_by(PointEntry.created_at.desc())
            .limit(100)
            .all()
        )
        names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
        task_names = {t.id: t.name for t in c.tasks}
        row["awards"] = [
            {"id": e.id, "person_name": names.get(e.person_id), "task_name": task_names.get(e.task_id),
             "points": e.points, "note": e.note, "created_at": e.created_at}
            for e in entries
        ]
        board: dict[str, float] = {}
        for e in db.query(PointEntry).filter(PointEntry.campaign_id == c.id, PointEntry.is_deleted.is_(False)):
            board[e.person_id] = board.get(e.person_id, 0) + e.points
        row["leaderboard"] = sorted(
            [{"person_name": names.get(pid), "points": pts, "performance": round(pts * c.performance_ratio, 2)}
             for pid, pts in board.items()],
            key=lambda x: -x["points"],
        )[:20]
    return row


@router.get("/api/campaigns")
def list_campaigns(db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("ideas", "view"))):
    query = db.query(ActivityCampaign).filter(ActivityCampaign.is_deleted.is_(False))
    if not has_perm(db, user, "ideas", "edit"):
        query = query.filter(ActivityCampaign.status == "active")
    rows = query.order_by(ActivityCampaign.is_example.desc(), ActivityCampaign.created_at.desc()).all()
    return ok([_campaign_row(c, db, person_id=user.person_id) for c in rows], total=len(rows))


@router.get("/api/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("ideas", "view"))):
    c = db.get(ActivityCampaign, campaign_id)
    if not c or c.is_deleted:
        raise AppError("NOT_FOUND", "活动不存在", 404)
    if c.status != "active" and not has_perm(db, user, "ideas", "edit") and not c.is_example:
        raise AppError("FORBIDDEN", "活动未上架", 403)
    row = _campaign_row(c, db, detail=True, person_id=user.person_id)
    row["can_manage"] = (not c.is_example) and has_perm(db, user, "ideas", "edit")
    return ok(row)


@router.post("/api/campaigns")
def create_campaign(body: CampaignIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("ideas", "edit"))):
    if body.end_date < body.start_date:
        raise AppError("INVALID_DATES", "结束日期不能早于开始日期")
    data = body.model_dump()
    tasks = data.pop("tasks")
    c = ActivityCampaign(**data, created_by=user.id)
    db.add(c)
    db.flush()
    for idx, t in enumerate(tasks):
        db.add(CampaignTask(campaign_id=c.id, sort=idx, **t))
    audit(db, "activity_campaign", c.id, "create", user, {"name": c.name, "tasks": len(tasks)})
    db.commit()
    db.refresh(c)
    return ok(_campaign_row(c, db))


@router.patch("/api/campaigns/{campaign_id}")
def update_campaign(campaign_id: str, body: CampaignIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("ideas", "edit"))):
    c = db.get(ActivityCampaign, campaign_id)
    if not c or c.is_deleted:
        raise AppError("NOT_FOUND", "活动不存在", 404)
    ensure_not_example(c)
    if body.end_date < body.start_date:
        raise AppError("INVALID_DATES", "结束日期不能早于开始日期")
    has_awards = db.query(PointEntry).filter(PointEntry.campaign_id == c.id, PointEntry.is_deleted.is_(False)).first()
    data = body.model_dump()
    tasks = data.pop("tasks")
    for k, v in data.items():
        setattr(c, k, v)
    if has_awards:
        # 已有发放记录：任务只增不删改（保护台账引用），新任务追加
        existing_names = {t.name for t in c.tasks if not t.is_deleted}
        new_tasks = [t for t in tasks if t["name"] not in existing_names]
        base_sort = len(c.tasks)
        for idx, t in enumerate(new_tasks):
            db.add(CampaignTask(campaign_id=c.id, sort=base_sort + idx, **t))
    else:
        db.query(CampaignTask).filter(CampaignTask.campaign_id == c.id).delete()
        for idx, t in enumerate(tasks):
            db.add(CampaignTask(campaign_id=c.id, sort=idx, **t))
    audit(db, "activity_campaign", c.id, "update", user, {"name": c.name, "awards_locked": bool(has_awards)})
    db.commit()
    db.refresh(c)
    return ok(_campaign_row(c, db))


@router.post("/api/campaigns/{campaign_id}/status")
def set_campaign_status(campaign_id: str, body: CampaignStatusIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("ideas", "edit"))):
    c = db.get(ActivityCampaign, campaign_id)
    if not c or c.is_deleted:
        raise AppError("NOT_FOUND", "活动不存在", 404)
    ensure_not_example(c)
    prev = c.status
    c.status = body.status
    audit(db, "activity_campaign", c.id, "status", user, {"from": prev, "to": body.status})
    db.commit()
    return ok({"id": c.id, "status": c.status})


@router.post("/api/campaigns/{campaign_id}/awards")
def award_points(campaign_id: str, body: AwardIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("ideas", "edit"))):
    c = db.get(ActivityCampaign, campaign_id)
    if not c or c.is_deleted:
        raise AppError("NOT_FOUND", "活动不存在", 404)
    ensure_not_example(c)
    if c.status != "active":
        raise AppError("NOT_ACTIVE", "活动未上架，不能发放积分")
    task = db.get(CampaignTask, body.task_id)
    if not task or task.is_deleted or task.campaign_id != c.id:
        raise AppError("NOT_FOUND", "激励任务不存在", 404)
    person = db.get(OrgMember, body.person_id)
    if not person or person.is_deleted:
        raise AppError("NOT_FOUND", "人员不存在", 404)
    if task.max_times:
        used = (
            db.query(PointEntry)
            .filter(PointEntry.campaign_id == c.id, PointEntry.task_id == task.id,
                    PointEntry.person_id == person.id, PointEntry.is_deleted.is_(False))
            .count()
        )
        if used + body.times > task.max_times:
            raise AppError("MAX_TIMES", f"超出该任务每人上限（{task.max_times} 次，已发 {used} 次）")
    for _ in range(body.times):
        award(db, person.id, task.points, "campaign_award", source_ref=task.id,
              campaign_id=c.id, task_id=task.id, period=c.period_label,
              note=body.note or f"{c.name}·{task.name}", created_by=user.id)
    audit(db, "activity_campaign", c.id, "award", user,
          {"person": person.name, "task": task.name, "times": body.times, "points": task.points * body.times})
    db.commit()
    return ok({"awarded": task.points * body.times})


# ---------- 积分规则（自动事件分值，可调可停用） ----------

class RuleIn(BaseModel):
    points: float = Field(ge=0)
    active: bool = True


@router.get("/api/point-rules")
def list_point_rules(db: Session = Depends(get_db), _=Depends(require_perm("ideas", "view"))):
    from app.models import PointRule

    rows = db.query(PointRule).filter(PointRule.is_deleted.is_(False)).order_by(PointRule.created_at).all()
    return ok([{"code": r.code, "name": r.name, "points": r.points, "active": r.active} for r in rows], total=len(rows))


@router.patch("/api/point-rules/{code}")
def update_point_rule(code: str, body: RuleIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("ideas", "edit"))):
    from app.models import PointRule

    rule = db.query(PointRule).filter(PointRule.code == code, PointRule.is_deleted.is_(False)).first()
    if not rule:
        raise AppError("NOT_FOUND", "积分规则不存在", 404)
    rule.points, rule.active = body.points, body.active
    audit(db, "point_rule", rule.id, "update", user, {"code": code, "points": body.points, "active": body.active})
    db.commit()
    return ok({"code": rule.code, "points": rule.points, "active": rule.active})


# ---------- 积分台账 ----------

@router.get("/api/points/mine")
def my_points(db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("ideas", "view"))):
    if not user.person_id:
        return ok({"period": current_period(), "total": 0, "entries": []})
    entries = (
        db.query(PointEntry)
        .filter(PointEntry.person_id == user.person_id, PointEntry.is_deleted.is_(False))
        .order_by(PointEntry.created_at.desc())
        .limit(100)
        .all()
    )
    period = current_period()
    if period.endswith("-All"):
        year_prefix = period.split("-")[0] + "-"
        period_total = sum(e.points for e in entries if (e.period or "").startswith(year_prefix))
    else:
        period_total = sum(e.points for e in entries if e.period == period)
    return ok({
        "period": period,
        "period_total": round(period_total, 1),
        "total": round(sum(e.points for e in entries), 1),
        "entries": [
            {"id": e.id, "points": e.points, "source_type": e.source_type, "period": e.period,
             "note": e.note, "created_at": e.created_at}
            for e in entries
        ],
    })


@router.get("/api/points/leaderboard")
def points_leaderboard(period: str = "", db: Session = Depends(get_db), _=Depends(require_perm("ideas", "view"))):
    period = period or current_period()
    rows = (
        db.query(PointEntry.person_id, func.sum(PointEntry.points))
        .filter(period_clause(PointEntry.period, period), PointEntry.is_deleted.is_(False))
        .group_by(PointEntry.person_id)
        .order_by(func.sum(PointEntry.points).desc())
        .limit(20)
        .all()
    )
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False))}
    return ok({
        "period": period,
        "board": [{"person_name": names.get(pid), "points": round(float(pts), 1)} for pid, pts in rows],
    })
