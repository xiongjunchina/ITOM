"""项目组合治理 API：目标、评分、决策、依赖、资源承诺和基线。"""
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_not_example
from app.db import get_db
from app.deps import require_perm
from app.models import (
    PortfolioGovernanceAction,
    PortfolioObjective,
    PortfolioProject,
    PortfolioScoringRule,
    Project,
    ProjectDependency,
    ProjectResourceCommitment,
)
from app.schemas.common import ok
from app.services.audit import audit
from app.services.portfolio_governance import (
    create_dependency,
    create_resource_commitment,
    get_membership,
    get_portfolio,
    publish_baseline,
    record_governance_action,
    recompute_system_score,
    score_project,
    serialize_portfolio_dashboard,
    transition_membership,
    validate_objective_contributions,
)
from app.services.permissions import has_perm
from app.services.team_scope import require_it_member_if_configured

router = APIRouter(tags=["portfolio-governance"])


class ObjectiveIn(BaseModel):
    objective_code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=2, max_length=160)
    description: str | None = None
    metric_name: str | None = Field(default=None, max_length=128)
    target_value: float | None = None
    current_value: float | None = None
    weight: int = Field(default=0, ge=0, le=100)
    owner_id: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    status: str = Field(default="active", pattern="^(active|completed|archived)$")


class ScoringRuleIn(BaseModel):
    dimension_code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=2, max_length=128)
    description: str | None = None
    weight: int = Field(ge=0, le=100)
    evidence_required: bool = True
    active: bool = True
    sort: int = 0


class ScoreValueIn(BaseModel):
    rule_id: str
    score: float = Field(ge=0, le=100)
    evidence: str | None = None


class ScoreProjectIn(BaseModel):
    scores: list[ScoreValueIn] = Field(min_length=1)


class ObjectiveContributionIn(BaseModel):
    objective_id: str
    weight: int = Field(ge=1, le=100)
    note: str | None = Field(default=None, max_length=1000)


class ContributionsIn(BaseModel):
    contributions: list[ObjectiveContributionIn] = Field(default_factory=list)


class GovernanceTransitionIn(BaseModel):
    to: str = Field(pattern="^(candidate|scoring|pending_review|admitted|deferred|paused|completed|terminated|rejected)$")
    reason: str = Field(min_length=2, max_length=2000)
    priority_rank: int | None = Field(default=None, ge=1)


class DependencyIn(BaseModel):
    predecessor_project_id: str
    successor_project_id: str
    dependency_type: str = Field(default="finish_to_start", pattern="^(finish_to_start|shared_deliverable|shared_environment|external_prerequisite)$")
    deliverable: str = Field(min_length=2, max_length=300)
    due_date: date | None = None
    owner_id: str | None = None
    impact: str = Field(default="medium", pattern="^(low|medium|high)$")
    status: str = Field(default="open", pattern="^(open|at_risk|blocked|resolved|closed)$")
    description: str | None = None


class DependencyStatusIn(BaseModel):
    status: str = Field(pattern="^(open|at_risk|blocked|resolved|closed)$")
    reason: str = Field(min_length=2, max_length=1000)


class ResourceCommitmentIn(BaseModel):
    project_id: str
    person_id: str
    role_name: str | None = Field(default=None, max_length=96)
    start_date: date
    end_date: date
    allocation_percent: int = Field(ge=1, le=100)
    planned_person_days: float | None = Field(default=None, ge=0)
    note: str | None = None


class BaselineIn(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)


def _validate_objective_weight_total(
    db: Session,
    portfolio_id: str,
    *,
    prospective_weight: int,
    prospective_status: str,
    exclude_id: str | None = None,
) -> int:
    total = sum(
        row.weight
        for row in db.query(PortfolioObjective).filter(
            PortfolioObjective.portfolio_id == portfolio_id,
            PortfolioObjective.is_deleted.is_(False),
            PortfolioObjective.status == "active",
        )
        if row.id != exclude_id
    )
    if prospective_status == "active":
        total += prospective_weight
    if total > 100:
        raise AppError("OBJECTIVE_WEIGHT_OVERFLOW", "启用组合目标权重合计不能超过 100%")
    return total


def _require_project_pm_or_governance_editor(db: Session, actor, *projects: Project) -> None:
    """PM 只能维护自己负责项目的提交材料；治理编辑者可跨项目维护。"""
    if has_perm(db, actor, "portfolio_governance", "edit"):
        return
    if actor.person_id and any(project.pm == actor.person_id for project in projects):
        return
    raise AppError("FORBIDDEN", "仅项目经理或组合治理人员可维护该项目材料", 403)


@router.get("/api/portfolios/{portfolio_id}/dashboard")
def portfolio_dashboard(
    portfolio_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_perm("portfolio_governance", "view")),
):
    return ok(serialize_portfolio_dashboard(db, get_portfolio(db, portfolio_id)))


@router.post("/api/portfolios/{portfolio_id}/objectives")
def create_objective(
    portfolio_id: str,
    body: ObjectiveIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("portfolio_governance", "edit")),
):
    portfolio = get_portfolio(db, portfolio_id)
    ensure_not_example(portfolio)
    require_it_member_if_configured(db, body.owner_id, "组合目标负责人")
    if body.period_start and body.period_end and body.period_end < body.period_start:
        raise AppError("INVALID_DATES", "目标结束日期不能早于开始日期")
    duplicate = db.query(PortfolioObjective).filter(
        PortfolioObjective.portfolio_id == portfolio_id,
        PortfolioObjective.objective_code == body.objective_code,
        PortfolioObjective.is_deleted.is_(False),
    ).first()
    if duplicate:
        raise AppError("DUPLICATE", "组合目标编码已存在")
    active_weight = _validate_objective_weight_total(
        db,
        portfolio_id,
        prospective_weight=body.weight,
        prospective_status=body.status,
    )
    row = PortfolioObjective(portfolio_id=portfolio_id, **body.model_dump())
    db.add(row); db.flush()
    audit(db, "portfolio_objective", row.id, "create", actor, {
        "code": row.objective_code, "name": row.name, "active_weight": active_weight,
    })
    db.commit()
    return ok({"id": row.id})


@router.patch("/api/portfolio-objectives/{objective_id}")
def update_objective(
    objective_id: str,
    body: ObjectiveIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("portfolio_governance", "edit")),
):
    row = db.get(PortfolioObjective, objective_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "组合目标不存在", 404)
    ensure_not_example(row)
    ensure_not_example(get_portfolio(db, row.portfolio_id))
    require_it_member_if_configured(db, body.owner_id, "组合目标负责人")
    if body.period_start and body.period_end and body.period_end < body.period_start:
        raise AppError("INVALID_DATES", "目标结束日期不能早于开始日期")
    duplicate = db.query(PortfolioObjective).filter(
        PortfolioObjective.portfolio_id == row.portfolio_id,
        PortfolioObjective.objective_code == body.objective_code,
        PortfolioObjective.id != row.id,
        PortfolioObjective.is_deleted.is_(False),
    ).first()
    if duplicate:
        raise AppError("DUPLICATE", "组合目标编码已存在")
    active_weight = _validate_objective_weight_total(
        db,
        row.portfolio_id,
        prospective_weight=body.weight,
        prospective_status=body.status,
        exclude_id=row.id,
    )
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    audit(db, "portfolio_objective", row.id, "update", actor, {
        "code": row.objective_code, "active_weight": active_weight,
    })
    db.commit()
    return ok({"id": row.id})


@router.put("/api/portfolios/{portfolio_id}/scoring-rules/{rule_id}")
def update_scoring_rule(
    portfolio_id: str,
    rule_id: str,
    body: ScoringRuleIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("portfolio_scoring", "edit")),
):
    if not has_perm(db, actor, "portfolio_governance", "edit"):
        raise AppError("FORBIDDEN", "仅组合治理人员可维护评分规则", 403)
    portfolio = get_portfolio(db, portfolio_id)
    ensure_not_example(portfolio)
    row = db.get(PortfolioScoringRule, rule_id)
    if not row or row.is_deleted or row.portfolio_id != portfolio_id:
        raise AppError("NOT_FOUND", "评分规则不存在", 404)
    duplicate = db.query(PortfolioScoringRule).filter(
        PortfolioScoringRule.portfolio_id == portfolio_id,
        PortfolioScoringRule.dimension_code == body.dimension_code,
        PortfolioScoringRule.id != row.id,
        PortfolioScoringRule.is_deleted.is_(False),
    ).first()
    if duplicate:
        raise AppError("DUPLICATE", "评分维度编码已存在")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    active_weight = sum(
        item.weight for item in db.query(PortfolioScoringRule).filter(
            PortfolioScoringRule.portfolio_id == portfolio_id,
            PortfolioScoringRule.is_deleted.is_(False),
            PortfolioScoringRule.active.is_(True),
        ) if item.id != row.id
    ) + (row.weight if row.active else 0)
    if active_weight > 100:
        raise AppError("SCORING_WEIGHT_OVERFLOW", "启用评分维度权重合计不能超过 100%")
    db.flush()
    for membership in db.query(PortfolioProject).filter(
        PortfolioProject.portfolio_id == portfolio_id,
        PortfolioProject.is_deleted.is_(False),
    ):
        recompute_system_score(db, membership)
    audit(db, "portfolio_scoring_rule", row.id, "update", actor, {"active_weight": active_weight})
    db.commit()
    return ok({"id": row.id, "active_weight": active_weight})


@router.put("/api/portfolios/{portfolio_id}/projects/{project_id}/scores")
def put_project_scores(
    portfolio_id: str,
    project_id: str,
    body: ScoreProjectIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("portfolio_scoring", "edit")),
):
    membership = get_membership(db, portfolio_id, project_id)
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    ensure_not_example(project)
    system_score = score_project(db, membership, [item.model_dump() for item in body.scores], actor)
    db.commit()
    return ok({"membership_id": membership.id, "system_score": system_score, "status": membership.governance_status})


@router.put("/api/portfolios/{portfolio_id}/projects/{project_id}/objectives")
def put_project_objectives(
    portfolio_id: str,
    project_id: str,
    body: ContributionsIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("portfolio_governance", "create")),
):
    membership = get_membership(db, portfolio_id, project_id)
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    ensure_not_example(project)
    _require_project_pm_or_governance_editor(db, actor, project)
    before = membership.objective_contributions or []
    membership.objective_contributions = validate_objective_contributions(
        db,
        portfolio_id,
        [item.model_dump() for item in body.contributions],
    )
    audit(db, "portfolio_project", membership.id, "objectives", actor, {
        "before": before, "after": membership.objective_contributions,
    })
    record_governance_action(
        db,
        portfolio_id,
        membership,
        "objectives_updated",
        "更新项目组合目标贡献",
        actor,
        before={"contributions": before},
        after={"contributions": membership.objective_contributions},
    )
    db.commit()
    return ok({"membership_id": membership.id, "objective_contributions": membership.objective_contributions})


@router.post("/api/portfolios/{portfolio_id}/projects/{project_id}/transition")
def transition_portfolio_project(
    portfolio_id: str,
    project_id: str,
    body: GovernanceTransitionIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("portfolio_decision", "edit")),
):
    membership = get_membership(db, portfolio_id, project_id)
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    ensure_not_example(project)
    transition_membership(db, membership, body.to, body.reason, actor, priority_rank=body.priority_rank)
    db.commit()
    return ok({"membership_id": membership.id, "status": membership.governance_status, "priority_rank": membership.priority_rank})


@router.post("/api/project-dependencies")
def post_dependency(
    body: DependencyIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("portfolio_governance", "create")),
):
    predecessor = db.get(Project, body.predecessor_project_id)
    successor = db.get(Project, body.successor_project_id)
    if not predecessor or predecessor.is_deleted or not successor or successor.is_deleted:
        raise AppError("NOT_FOUND", "依赖项目不存在", 404)
    ensure_not_example(predecessor)
    ensure_not_example(successor)
    _require_project_pm_or_governance_editor(db, actor, predecessor, successor)
    if body.owner_id:
        require_it_member_if_configured(db, body.owner_id, "依赖负责人")
    row = create_dependency(db, body.model_dump(), actor)
    db.commit()
    return ok({"id": row.id})


@router.patch("/api/project-dependencies/{dependency_id}")
def patch_dependency(
    dependency_id: str,
    body: DependencyStatusIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("portfolio_governance", "edit")),
):
    row = db.get(ProjectDependency, dependency_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "跨项目依赖不存在", 404)
    before = row.status
    row.status = body.status
    audit(db, "project_dependency", row.id, "status", actor, {"from": before, "to": row.status, "reason": body.reason})
    db.commit()
    return ok({"id": row.id, "status": row.status})


@router.post("/api/project-resource-commitments")
def post_resource_commitment(
    body: ResourceCommitmentIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("portfolio_resource", "edit")),
):
    require_it_member_if_configured(db, body.person_id, "资源人员")
    project = db.get(Project, body.project_id)
    if not project or project.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    ensure_not_example(project)
    row = create_resource_commitment(db, body.model_dump(), actor)
    db.commit()
    return ok({"id": row.id})


@router.delete("/api/project-resource-commitments/{commitment_id}")
def delete_resource_commitment(
    commitment_id: str,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("portfolio_resource", "delete")),
):
    row = db.get(ProjectResourceCommitment, commitment_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "资源承诺不存在", 404)
    ensure_not_example(row)
    row.is_deleted = True
    audit(db, "project_resource_commitment", row.id, "delete", actor, {"project_id": row.project_id})
    db.commit()
    return ok({"id": row.id})


@router.post("/api/portfolios/{portfolio_id}/baselines")
def post_baseline(
    portfolio_id: str,
    body: BaselineIn,
    db: Session = Depends(get_db),
    actor=Depends(require_perm("portfolio_decision", "edit")),
):
    portfolio = get_portfolio(db, portfolio_id)
    ensure_not_example(portfolio)
    row = publish_baseline(db, portfolio, body.reason, actor)
    db.commit()
    return ok({"id": row.id, "version": row.version, "published_at": row.published_at})


@router.get("/api/portfolios/{portfolio_id}/governance-actions")
def list_governance_actions(
    portfolio_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_perm("portfolio_audit", "view")),
):
    get_portfolio(db, portfolio_id)
    rows = db.query(PortfolioGovernanceAction).filter(
        PortfolioGovernanceAction.portfolio_id == portfolio_id,
        PortfolioGovernanceAction.is_deleted.is_(False),
    ).order_by(PortfolioGovernanceAction.effective_at.desc(), PortfolioGovernanceAction.id.desc()).all()
    return ok([
        {"id": row.id, "portfolio_project_id": row.portfolio_project_id, "action": row.action,
         "reason": row.reason, "before_value": row.before_value, "after_value": row.after_value,
         "actor_id": row.actor_id, "effective_at": row.effective_at}
        for row in rows
    ], total=len(rows))
