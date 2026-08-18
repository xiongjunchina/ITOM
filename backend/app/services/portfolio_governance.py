"""项目组合治理领域服务。

ITOM 项目仍是执行事实来源；本模块只管理组合选择、排序、跨项目依赖、资源承诺
和不可变治理基线，不复制 WBS、风险、成本或流程状态。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    AuthUser,
    OrgMember,
    Portfolio,
    PortfolioBaseline,
    PortfolioGovernanceAction,
    PortfolioObjective,
    PortfolioProject,
    PortfolioProjectScore,
    PortfolioScoringRule,
    Project,
    ProjectDependency,
    ProjectResourceCommitment,
)
from app.services.audit import audit
from app.services.projects import compute_metrics

DEFAULT_SCORING_RULES = (
    ("strategic_alignment", "战略契合", 30),
    ("business_value", "业务价值", 25),
    ("urgency_compliance", "合规与紧迫", 15),
    ("resource_feasibility", "资源可行性", 15),
    ("delivery_confidence", "交付信心", 15),
)

GOVERNANCE_TRANSITIONS: dict[str, set[str]] = {
    "candidate": {"scoring", "rejected"},
    "scoring": {"pending_review", "deferred", "rejected"},
    "pending_review": {"admitted", "deferred", "rejected"},
    "admitted": {"paused", "completed", "terminated"},
    "paused": {"admitted", "terminated"},
    "deferred": {"scoring", "rejected"},
    "completed": set(),
    "terminated": set(),
    "rejected": {"candidate"},
}


def _active(model):
    return model.is_deleted.is_(False)


def get_portfolio(db: Session, portfolio_id: str) -> Portfolio:
    row = db.get(Portfolio, portfolio_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "项目组合不存在", 404)
    return row


def get_membership(db: Session, portfolio_id: str, project_id: str) -> PortfolioProject:
    row = (
        db.query(PortfolioProject)
        .filter(
            PortfolioProject.portfolio_id == portfolio_id,
            PortfolioProject.project_id == project_id,
            _active(PortfolioProject),
        )
        .first()
    )
    if not row:
        raise AppError("NOT_FOUND", "项目不在该组合中", 404)
    return row


def create_default_rules(db: Session, portfolio_id: str):
    existing = {
        row.dimension_code
        for row in db.query(PortfolioScoringRule)
        .filter(PortfolioScoringRule.portfolio_id == portfolio_id, _active(PortfolioScoringRule))
    }
    for sort, (code, name, weight) in enumerate(DEFAULT_SCORING_RULES):
        if code not in existing:
            db.add(PortfolioScoringRule(
                portfolio_id=portfolio_id,
                dimension_code=code,
                name=name,
                weight=weight,
                evidence_required=True,
                active=True,
                sort=sort,
            ))


def ensure_primary_membership(
    db: Session,
    project: Project,
    actor: AuthUser | None = None,
    *,
    proposal_reason: str | None = None,
) -> PortfolioProject | None:
    """同步兼容字段与活动治理成员；首期一个项目只有一个活动组合。"""
    current = (
        db.query(PortfolioProject)
        .filter(PortfolioProject.project_id == project.id, _active(PortfolioProject))
        .first()
    )
    if not project.portfolio_id:
        if current:
            current.is_deleted = True
            if actor:
                record_governance_action(db, current.portfolio_id, current, "unlinked", "项目解除主要组合", actor)
        return None
    portfolio = get_portfolio(db, project.portfolio_id)
    create_default_rules(db, portfolio.id)
    if current and current.portfolio_id == portfolio.id:
        if proposal_reason:
            current.proposal_reason = proposal_reason
        return current
    if current:
        current.is_deleted = True
        if actor:
            record_governance_action(db, current.portfolio_id, current, "moved_out", "项目迁移至其他组合", actor)
        # 活动成员由 partial unique index 约束；先让旧行退出活动集合，再插入新行。
        db.flush()
    row = PortfolioProject(
        portfolio_id=portfolio.id,
        project_id=project.id,
        governance_status="candidate",
        proposal_reason=proposal_reason or "由项目主要组合字段同步",
        objective_contributions=[],
    )
    db.add(row)
    db.flush()
    if actor:
        record_governance_action(db, portfolio.id, row, "proposed", row.proposal_reason or "项目加入候选", actor)
    return row


def record_governance_action(
    db: Session,
    portfolio_id: str,
    membership: PortfolioProject | None,
    action: str,
    reason: str,
    actor: AuthUser,
    before: dict | None = None,
    after: dict | None = None,
) -> PortfolioGovernanceAction:
    row = PortfolioGovernanceAction(
        portfolio_id=portfolio_id,
        portfolio_project_id=membership.id if membership else None,
        action=action,
        reason=reason,
        before_value=before,
        after_value=after,
        actor_id=actor.id,
    )
    db.add(row)
    return row


def _score_rows(db: Session, membership_id: str) -> tuple[list[PortfolioScoringRule], dict[str, PortfolioProjectScore]]:
    membership = db.get(PortfolioProject, membership_id)
    if not membership:
        return [], {}
    rules = (
        db.query(PortfolioScoringRule)
        .filter(
            PortfolioScoringRule.portfolio_id == membership.portfolio_id,
            PortfolioScoringRule.active.is_(True),
            _active(PortfolioScoringRule),
        )
        .order_by(PortfolioScoringRule.sort, PortfolioScoringRule.created_at)
        .all()
    )
    scores = {
        row.rule_id: row
        for row in db.query(PortfolioProjectScore)
        .filter(PortfolioProjectScore.portfolio_project_id == membership_id, _active(PortfolioProjectScore))
    }
    return rules, scores


def recompute_system_score(db: Session, membership: PortfolioProject) -> float | None:
    rules, scores = _score_rows(db, membership.id)
    if not rules or sum(rule.weight for rule in rules) != 100 or any(rule.id not in scores for rule in rules):
        membership.system_score = None
        return None
    membership.system_score = round(sum(scores[rule.id].score * rule.weight for rule in rules) / 100, 2)
    return membership.system_score


def validate_objective_contributions(
    db: Session, portfolio_id: str, contributions: list[dict] | None,
) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    valid_ids = {
        row.id for row in db.query(PortfolioObjective).filter(
            PortfolioObjective.portfolio_id == portfolio_id,
            PortfolioObjective.status == "active",
            _active(PortfolioObjective),
        )
    }
    for item in contributions or []:
        objective_id = str(item.get("objective_id") or "")
        weight = int(item.get("weight") or 0)
        if objective_id not in valid_ids or objective_id in seen:
            raise AppError("INVALID_OBJECTIVE", "组合目标不存在、已停用或重复")
        if weight < 1 or weight > 100:
            raise AppError("INVALID_OBJECTIVE_WEIGHT", "项目目标贡献权重必须为 1–100")
        seen.add(objective_id)
        normalized.append({
            "objective_id": objective_id,
            "weight": weight,
            "note": str(item.get("note") or "").strip() or None,
        })
    if sum(item["weight"] for item in normalized) > 100:
        raise AppError("OBJECTIVE_WEIGHT_OVERFLOW", "项目目标贡献权重合计不能超过 100%")
    return normalized


def score_project(
    db: Session,
    membership: PortfolioProject,
    values: list[dict],
    actor: AuthUser,
) -> float | None:
    rules, existing = _score_rows(db, membership.id)
    rules_by_id = {rule.id: rule for rule in rules}
    seen: set[str] = set()
    before = {rid: row.score for rid, row in existing.items()}
    for value in values:
        rule_id = str(value.get("rule_id") or "")
        if rule_id not in rules_by_id or rule_id in seen:
            raise AppError("INVALID_SCORING_RULE", "评分维度不存在、已停用或重复")
        seen.add(rule_id)
        score = float(value.get("score"))
        if score < 0 or score > 100:
            raise AppError("INVALID_SCORE", "评分必须在 0–100 之间")
        evidence = str(value.get("evidence") or "").strip() or None
        if rules_by_id[rule_id].evidence_required and not evidence:
            raise AppError("EVIDENCE_REQUIRED", f"评分维度“{rules_by_id[rule_id].name}”必须提供证据")
        row = existing.get(rule_id)
        if row:
            row.score = score
            row.evidence = evidence
            row.scored_by = actor.id
            row.scored_at = datetime.now()
        else:
            row = PortfolioProjectScore(
                portfolio_project_id=membership.id,
                rule_id=rule_id,
                score=score,
                evidence=evidence,
                scored_by=actor.id,
            )
            db.add(row)
            existing[rule_id] = row
    # SessionLocal 明确关闭 autoflush；重算会重新查询评分行，必须先让本事务的新行可见。
    db.flush()
    result = recompute_system_score(db, membership)
    if membership.governance_status == "candidate":
        membership.governance_status = "scoring"
    record_governance_action(
        db, membership.portfolio_id, membership, "scored", "更新组合评分", actor,
        before=before,
        after={rid: row.score for rid, row in existing.items()},
    )
    audit(db, "portfolio_project", membership.id, "score", actor, {"system_score": result})
    return result


def transition_membership(
    db: Session,
    membership: PortfolioProject,
    target: str,
    reason: str,
    actor: AuthUser,
    *,
    priority_rank: int | None = None,
):
    reason = reason.strip()
    if len(reason) < 2:
        raise AppError("REASON_REQUIRED", "治理决策必须填写至少 2 个字符的理由")
    current = membership.governance_status
    if target not in GOVERNANCE_TRANSITIONS.get(current, set()):
        raise AppError("INVALID_GOVERNANCE_TRANSITION", f"组合治理状态不能从 {current} 转为 {target}")
    if target in {"pending_review", "admitted"} and membership.system_score is None:
        raise AppError("SCORING_INCOMPLETE", "所有启用评分维度完成且权重合计 100% 后才能提交评审或纳入")
    effective_priority = priority_rank if priority_rank is not None else membership.priority_rank
    if target == "admitted" and effective_priority is None:
        raise AppError("PRIORITY_REQUIRED", "纳入组合时必须确定治理优先级")
    if effective_priority is not None:
        duplicate_priority = db.query(PortfolioProject).filter(
            PortfolioProject.portfolio_id == membership.portfolio_id,
            PortfolioProject.id != membership.id,
            PortfolioProject.priority_rank == effective_priority,
            _active(PortfolioProject),
        ).first()
        if duplicate_priority:
            raise AppError("DUPLICATE_PRIORITY", "组合内治理优先级不能重复")
    before = {"status": current, "priority_rank": membership.priority_rank}
    membership.governance_status = target
    membership.decision_reason = reason
    membership.decided_by = actor.id
    membership.decided_at = datetime.now()
    if priority_rank is not None:
        if priority_rank < 1:
            raise AppError("INVALID_PRIORITY", "治理优先级必须大于 0")
        membership.priority_rank = priority_rank
    record_governance_action(
        db, membership.portfolio_id, membership, target, reason, actor,
        before=before,
        after={"status": target, "priority_rank": membership.priority_rank},
    )
    audit(db, "portfolio_project", membership.id, "governance_transition", actor, {
        "from": current, "to": target, "reason": reason, "priority_rank": membership.priority_rank,
    })


def _dependency_reaches(db: Session, start_id: str, target_id: str) -> bool:
    edges = defaultdict(set)
    for row in db.query(ProjectDependency).filter(_active(ProjectDependency), ProjectDependency.status != "closed"):
        edges[row.predecessor_project_id].add(row.successor_project_id)
    stack = [start_id]
    visited: set[str] = set()
    while stack:
        current = stack.pop()
        if current == target_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        stack.extend(edges[current])
    return False


def create_dependency(db: Session, data: dict, actor: AuthUser) -> ProjectDependency:
    predecessor_id = data["predecessor_project_id"]
    successor_id = data["successor_project_id"]
    if predecessor_id == successor_id:
        raise AppError("DEPENDENCY_SELF", "项目不能依赖自身")
    for project_id in (predecessor_id, successor_id):
        project = db.get(Project, project_id)
        if not project or project.is_deleted:
            raise AppError("NOT_FOUND", "依赖项目不存在", 404)
    duplicate = db.query(ProjectDependency).filter(
        ProjectDependency.predecessor_project_id == predecessor_id,
        ProjectDependency.successor_project_id == successor_id,
        ProjectDependency.dependency_type == data["dependency_type"],
        _active(ProjectDependency),
    ).first()
    if duplicate:
        raise AppError("DUPLICATE_DEPENDENCY", "相同跨项目依赖已存在")
    if _dependency_reaches(db, successor_id, predecessor_id):
        raise AppError("DEPENDENCY_CYCLE", "新增依赖会形成跨项目循环")
    row = ProjectDependency(**data)
    db.add(row)
    db.flush()
    audit(db, "project_dependency", row.id, "create", actor, {
        "predecessor_project_id": predecessor_id, "successor_project_id": successor_id,
    })
    return row


def create_resource_commitment(db: Session, data: dict, actor: AuthUser) -> ProjectResourceCommitment:
    project = db.get(Project, data["project_id"])
    person = db.get(OrgMember, data["person_id"])
    if not project or project.is_deleted:
        raise AppError("NOT_FOUND", "项目不存在", 404)
    if not person or person.is_deleted or person.status != "在岗":
        raise AppError("NOT_FOUND", "资源人员不存在或不在岗", 404)
    if data["end_date"] < data["start_date"]:
        raise AppError("INVALID_DATES", "资源承诺结束日期不能早于开始日期")
    row = ProjectResourceCommitment(**data)
    db.add(row)
    db.flush()
    audit(db, "project_resource_commitment", row.id, "create", actor, {
        "project_id": row.project_id, "person_id": row.person_id, "allocation_percent": row.allocation_percent,
    })
    return row


def resource_conflicts(db: Session, project_ids: set[str] | None = None) -> list[dict]:
    query = db.query(ProjectResourceCommitment).filter(_active(ProjectResourceCommitment))
    if project_ids is not None:
        portfolio_people = {
            row.person_id for row in query.filter(ProjectResourceCommitment.project_id.in_(project_ids)).all()
        }
        if not portfolio_people:
            return []
        query = db.query(ProjectResourceCommitment).filter(
            _active(ProjectResourceCommitment),
            ProjectResourceCommitment.person_id.in_(portfolio_people),
        )
    rows = query.all()
    by_person: dict[str, list[ProjectResourceCommitment]] = defaultdict(list)
    for row in rows:
        by_person[row.person_id].append(row)
    names = {row.id: row.name for row in db.query(OrgMember).filter(_active(OrgMember))}
    project_names = {row.id: row.name for row in db.query(Project).filter(_active(Project))}
    conflicts: list[dict] = []
    for person_id, commitments in by_person.items():
        boundaries = sorted({point for row in commitments for point in (row.start_date, row.end_date)})
        for point in boundaries:
            active = [row for row in commitments if row.start_date <= point <= row.end_date]
            allocation = sum(row.allocation_percent for row in active)
            if allocation <= 100 or (project_ids is not None and not any(row.project_id in project_ids for row in active)):
                continue
            signature = tuple(sorted(row.id for row in active))
            if conflicts and conflicts[-1].get("_signature") == signature:
                conflicts[-1]["end_date"] = point
                continue
            conflicts.append({
                "_signature": signature,
                "person_id": person_id,
                "person_name": names.get(person_id),
                "start_date": point,
                "end_date": point,
                "allocation_percent": allocation,
                "commitments": [
                    {"id": row.id, "project_id": row.project_id, "project_name": project_names.get(row.project_id),
                     "allocation_percent": row.allocation_percent}
                    for row in active
                ],
            })
    for conflict in conflicts:
        conflict.pop("_signature", None)
    return conflicts


def serialize_portfolio_dashboard(db: Session, portfolio: Portfolio) -> dict:
    memberships = db.query(PortfolioProject).filter(
        PortfolioProject.portfolio_id == portfolio.id, _active(PortfolioProject),
    ).all()
    project_ids = {row.project_id for row in memberships}
    projects = db.query(Project).filter(Project.id.in_(project_ids), _active(Project)).all() if project_ids else []
    metrics_by_id = {project.id: compute_metrics(db, project) for project in projects}
    names = {row.id: row.name for row in db.query(OrgMember).filter(_active(OrgMember))}
    project_by_id = {row.id: row for row in projects}
    objectives = db.query(PortfolioObjective).filter(
        PortfolioObjective.portfolio_id == portfolio.id, _active(PortfolioObjective),
    ).order_by(PortfolioObjective.created_at).all()
    dependencies = db.query(ProjectDependency).filter(
        _active(ProjectDependency),
        ProjectDependency.predecessor_project_id.in_(project_ids) | ProjectDependency.successor_project_id.in_(project_ids),
    ).all() if project_ids else []
    dependency_project_ids = {
        project_id for row in dependencies
        for project_id in (row.predecessor_project_id, row.successor_project_id)
    }
    dependency_projects = {
        row.id: row for row in db.query(Project).filter(Project.id.in_(dependency_project_ids), _active(Project)).all()
    } if dependency_project_ids else {}
    commitments = db.query(ProjectResourceCommitment).filter(
        ProjectResourceCommitment.project_id.in_(project_ids), _active(ProjectResourceCommitment),
    ).order_by(ProjectResourceCommitment.start_date, ProjectResourceCommitment.created_at).all() if project_ids else []
    scores_by_membership: dict[str, dict[str, float]] = defaultdict(dict)
    score_details_by_membership: dict[str, dict[str, dict]] = defaultdict(dict)
    for score, rule in db.query(PortfolioProjectScore, PortfolioScoringRule).join(
        PortfolioScoringRule, PortfolioScoringRule.id == PortfolioProjectScore.rule_id,
    ).filter(PortfolioProjectScore.portfolio_project_id.in_([row.id for row in memberships]), _active(PortfolioProjectScore)):
        scores_by_membership[score.portfolio_project_id][rule.dimension_code] = score.score
        score_details_by_membership[score.portfolio_project_id][rule.dimension_code] = {
            "score": score.score,
            "evidence": score.evidence,
            "scored_by": score.scored_by,
            "scored_at": score.scored_at,
        }
    project_rows = []
    for membership in memberships:
        project = project_by_id.get(membership.project_id)
        if not project:
            continue
        project_rows.append({
            "membership_id": membership.id,
            "project_id": project.id,
            "project_code": project.project_code,
            "name": project.name,
            "pm": project.pm,
            "pm_name": names.get(project.pm),
            "status": project.status,
            "governance_status": membership.governance_status,
            "system_score": membership.system_score,
            "priority_rank": membership.priority_rank,
            "proposal_reason": membership.proposal_reason,
            "decision_reason": membership.decision_reason,
            "objective_contributions": membership.objective_contributions or [],
            "scores": scores_by_membership.get(membership.id, {}),
            "score_details": score_details_by_membership.get(membership.id, {}),
            **metrics_by_id[project.id],
            "budget_10k": project.budget_10k,
        })
    project_rows.sort(key=lambda row: (row["priority_rank"] is None, row["priority_rank"] or 999999, -(row["system_score"] or -1)))
    health = defaultdict(int)
    for row in project_rows:
        health[row["health"]] += 1
    return {
        "portfolio": {
            "id": portfolio.id,
            "portfolio_code": portfolio.portfolio_code,
            "name": portfolio.name,
            "owner_id": portfolio.owner_id,
            "owner_name": names.get(portfolio.owner_id),
            "year": portfolio.year,
            "description": portfolio.description,
            "status": portfolio.status,
            "planning_start": portfolio.planning_start,
            "planning_end": portfolio.planning_end,
            "budget_limit_10k": portfolio.budget_limit_10k,
            "sort": portfolio.sort,
            "project_count": len(project_rows),
            "is_example": portfolio.is_example,
        },
        "summary": {
            "project_count": len(project_rows),
            "admitted_count": sum(row["governance_status"] == "admitted" for row in project_rows),
            "pending_decisions": sum(row["governance_status"] in {"candidate", "scoring", "pending_review"} for row in project_rows),
            "health": dict(health),
            "budget_10k": round(sum(row["budget_10k"] or 0 for row in project_rows), 2),
            "actual_cost_10k": round(sum(row["actual_cost_10k"] or 0 for row in project_rows), 2),
            "open_dependencies": sum(row.status != "closed" for row in dependencies),
            "resource_conflict_count": len(resource_conflicts(db, project_ids)),
        },
        "objectives": [
            {"id": row.id, "objective_code": row.objective_code, "name": row.name,
             "description": row.description, "metric_name": row.metric_name,
             "target_value": row.target_value, "current_value": row.current_value,
             "weight": row.weight, "owner_id": row.owner_id, "owner_name": names.get(row.owner_id),
             "period_start": row.period_start, "period_end": row.period_end, "status": row.status}
            for row in objectives
        ],
        "projects": project_rows,
        "dependencies": [
            {"id": row.id, "predecessor_project_id": row.predecessor_project_id,
             "predecessor_project_name": dependency_projects.get(row.predecessor_project_id).name if dependency_projects.get(row.predecessor_project_id) else None,
             "successor_project_id": row.successor_project_id,
             "successor_project_name": dependency_projects.get(row.successor_project_id).name if dependency_projects.get(row.successor_project_id) else None,
             "dependency_type": row.dependency_type, "deliverable": row.deliverable,
             "due_date": row.due_date, "owner_id": row.owner_id, "owner_name": names.get(row.owner_id),
             "impact": row.impact, "status": row.status, "description": row.description}
            for row in dependencies
        ],
        "resource_commitments": [
            {"id": row.id, "project_id": row.project_id,
             "project_name": project_by_id.get(row.project_id).name if project_by_id.get(row.project_id) else None,
             "person_id": row.person_id, "person_name": names.get(row.person_id),
             "role_name": row.role_name, "start_date": row.start_date, "end_date": row.end_date,
             "allocation_percent": row.allocation_percent, "planned_person_days": row.planned_person_days,
             "note": row.note}
            for row in commitments
        ],
        "resource_conflicts": resource_conflicts(db, project_ids),
        "scoring_rules": [
            {"id": row.id, "dimension_code": row.dimension_code, "name": row.name,
             "description": row.description, "weight": row.weight,
             "evidence_required": row.evidence_required, "active": row.active, "sort": row.sort}
            for row in db.query(PortfolioScoringRule).filter(
                PortfolioScoringRule.portfolio_id == portfolio.id, _active(PortfolioScoringRule),
            ).order_by(PortfolioScoringRule.sort).all()
        ],
        "latest_baseline": latest_baseline(db, portfolio.id),
    }


def latest_baseline(db: Session, portfolio_id: str) -> dict | None:
    row = db.query(PortfolioBaseline).filter(
        PortfolioBaseline.portfolio_id == portfolio_id, _active(PortfolioBaseline),
    ).order_by(PortfolioBaseline.version.desc()).first()
    if not row:
        return None
    return {"id": row.id, "version": row.version, "snapshot": row.snapshot,
            "published_by": row.published_by, "published_at": row.published_at}


def publish_baseline(db: Session, portfolio: Portfolio, reason: str, actor: AuthUser) -> PortfolioBaseline:
    reason = reason.strip()
    if len(reason) < 2:
        raise AppError("REASON_REQUIRED", "发布组合基线必须填写至少 2 个字符的理由")
    dashboard = serialize_portfolio_dashboard(db, portfolio)
    pending = [row for row in dashboard["projects"] if row["governance_status"] in {"candidate", "scoring", "pending_review"}]
    if pending:
        raise AppError("PENDING_GOVERNANCE", "仍有候选、评分中或待评审项目，不能发布组合基线")
    incomplete = [
        row for row in dashboard["projects"]
        if row["governance_status"] in {"admitted", "paused", "completed", "terminated"}
        and (row["system_score"] is None or row["priority_rank"] is None)
    ]
    if incomplete:
        raise AppError("SCORING_INCOMPLETE", "已纳入项目必须完成评分和治理排序后才能发布组合基线")
    version = (db.query(func.max(PortfolioBaseline.version)).filter(
        PortfolioBaseline.portfolio_id == portfolio.id,
    ).scalar() or 0) + 1
    snapshot = jsonable_encoder({
        "portfolio": dashboard["portfolio"],
        "objectives": dashboard["objectives"],
        "projects": dashboard["projects"],
        "dependencies": dashboard["dependencies"],
        "resource_commitments": dashboard["resource_commitments"],
        "resource_conflicts": dashboard["resource_conflicts"],
        "scoring_rules": dashboard["scoring_rules"],
        "published_reason": reason,
    })
    row = PortfolioBaseline(
        portfolio_id=portfolio.id,
        version=version,
        snapshot=snapshot,
        published_by=actor.id,
    )
    db.add(row)
    db.flush()
    portfolio.status = "active"
    record_governance_action(db, portfolio.id, None, "baseline_published", reason, actor, after={"version": version})
    audit(db, "portfolio", portfolio.id, "publish_baseline", actor, {"version": version, "reason": reason})
    return row
