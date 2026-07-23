"""学习成长目标：员工按考核期填写目标、进度与佐证，并自动计入团队贡献。"""

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_not_example
from app.db import get_db
from app.deps import require_perm
from app.models import AuthUser, LearningGrowthGoal, OrgMember
from app.schemas.common import ok
from app.services.audit import audit
from app.services.learning_growth import sync_learning_growth_points
from app.services.rbac import actor_keys
from app.services.team_scope import require_it_member

router = APIRouter(tags=["team"])


class LearningGrowthGoalIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}-(Q[123]|All)$")
    goal: str = Field(min_length=2, max_length=200)
    target_description: str | None = Field(default=None, max_length=4000)
    progress: float = Field(default=0, ge=0, le=100)
    evidence: str | None = Field(default=None, max_length=4000)
    note: str | None = Field(default=None, max_length=4000)


class LearningGrowthGoalPatch(BaseModel):
    goal: str | None = Field(default=None, min_length=2, max_length=200)
    target_description: str | None = Field(default=None, max_length=4000)
    progress: float | None = Field(default=None, ge=0, le=100)
    evidence: str | None = Field(default=None, max_length=4000)
    note: str | None = Field(default=None, max_length=4000)


def _period(period: str) -> str:
    if not re.fullmatch(r"\d{4}-(Q[123]|All)", period):
        raise AppError("INVALID_PERIOD", "考核期格式应为 YYYY-Q1/Q2/Q3 或 YYYY-All")
    return period


def _is_manager(db: Session, user: AuthUser) -> bool:
    return bool(actor_keys(db, user) & {"admin", "cio", "it_tm"})


def _row(db: Session, goal: LearningGrowthGoal) -> dict:
    member = db.get(OrgMember, goal.person_id)
    return {
        "id": goal.id,
        "period": goal.period,
        "person_id": goal.person_id,
        "person_name": member.name if member else "",
        "goal": goal.goal,
        "target_description": goal.target_description,
        "progress": round(goal.progress or 0, 1),
        "points": round(goal.points or 0, 2),
        "evidence": goal.evidence,
        "note": goal.note,
        "created_at": goal.created_at,
        "updated_at": goal.updated_at,
    }


@router.get("/api/team/learning-growth")
def list_learning_growth(
    period: str,
    scope: str = "mine",
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_perm("learning_growth", "view")),
):
    period = _period(period)
    if scope not in {"mine", "team"}:
        raise AppError("INVALID_SCOPE", "scope 只能是 mine 或 team")
    if scope == "team" and not _is_manager(db, user):
        raise AppError("FORBIDDEN", "只有系统管理员、CIO 或 IT 团队负责人可以查看团队目标", 403)
    if scope == "mine":
        if not user.person_id:
            return ok([], total=0)
        require_it_member(db, user.person_id, "学习成长目标人员")
        query = db.query(LearningGrowthGoal).filter(LearningGrowthGoal.person_id == user.person_id)
    else:
        from app.services.team_scope import it_member_ids

        query = db.query(LearningGrowthGoal).filter(LearningGrowthGoal.person_id.in_(it_member_ids(db) or {"-"}))
    goals = (
        query.filter(LearningGrowthGoal.period == period, LearningGrowthGoal.is_deleted.is_(False))
        .order_by(LearningGrowthGoal.created_at.desc())
        .all()
    )
    return ok([_row(db, goal) for goal in goals], total=len(goals))


@router.post("/api/team/learning-growth")
def create_learning_growth(
    body: LearningGrowthGoalIn,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_perm("learning_growth", "create")),
):
    if not user.person_id:
        raise AppError("NO_PERSON", "当前账号未绑定人员主数据，无法填写学习成长目标")
    require_it_member(db, user.person_id, "学习成长目标人员")
    body.period = _period(body.period)
    goal = LearningGrowthGoal(person_id=user.person_id, **body.model_dump())
    db.add(goal)
    db.flush()
    sync_learning_growth_points(db, user.person_id, goal.period, user.id)
    audit(db, "learning_growth_goal", goal.id, "create", user, {"period": goal.period, "progress": goal.progress})
    db.commit()
    db.refresh(goal)
    return ok(_row(db, goal))


@router.patch("/api/team/learning-growth/{goal_id}")
def update_learning_growth(
    goal_id: str,
    body: LearningGrowthGoalPatch,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_perm("learning_growth", "edit")),
):
    goal = db.get(LearningGrowthGoal, goal_id)
    if not goal or goal.is_deleted:
        raise AppError("NOT_FOUND", "学习成长目标不存在", 404)
    ensure_not_example(goal)
    is_owner = goal.person_id == user.person_id
    if not is_owner and not _is_manager(db, user):
        raise AppError("FORBIDDEN", "只能修改自己的学习成长目标", 403)
    require_it_member(db, goal.person_id, "学习成长目标人员")
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(goal, key, value)
    sync_learning_growth_points(db, goal.person_id, goal.period, user.id)
    audit(db, "learning_growth_goal", goal.id, "update", user, changes)
    db.commit()
    db.refresh(goal)
    return ok(_row(db, goal))


@router.delete("/api/team/learning-growth/{goal_id}")
def delete_learning_growth(
    goal_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_perm("learning_growth", "delete")),
):
    goal = db.get(LearningGrowthGoal, goal_id)
    if not goal or goal.is_deleted:
        raise AppError("NOT_FOUND", "学习成长目标不存在", 404)
    ensure_not_example(goal)
    if goal.person_id != user.person_id and not _is_manager(db, user):
        raise AppError("FORBIDDEN", "只能删除自己的学习成长目标", 403)
    goal.is_deleted = True
    sync_learning_growth_points(db, goal.person_id, goal.period, user.id)
    audit(db, "learning_growth_goal", goal.id, "delete", user, {"period": goal.period})
    db.commit()
    return ok({"id": goal.id, "deleted": True})
