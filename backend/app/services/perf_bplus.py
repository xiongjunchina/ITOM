"""矩阵角色绩效服务。

该服务与旧版岗位方案引擎并行存在：旧接口继续服务存量页面，矩阵角色接口使用周期快照、
分阶段评分组件和发布快照，保证负责人微调与员工结果可见性由后端强制执行。
"""
from collections import defaultdict
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    AuthUser,
    BusinessDomain,
    BusinessDomainMember,
    OrgMember,
    PerformanceExternalInput,
    PerformanceContributionConfig,
    PerformancePeriod,
    PerformanceReviewAction,
    PerformanceRoleAssignment,
    PerformanceRoleDimension,
    PerformanceRoleProfile,
    PerformanceScore,
    PerformanceScoreComponent,
    PointEntry,
    ProcessTask,
    Project,
    Requirement,
    UserGroup,
    UserGroupMember,
    WbsTask,
)
from app.services.perf import (
    _score_change_compliance,
    _score_domain_satisfaction,
    _score_knowledge_contrib,
    _score_project_delivery,
    _score_requirement_delivery,
    _score_ticket_service,
    period_range,
)
from app.services.points import period_clause
from app.services.rbac import effective_roles
from app.core.rbac import IT_PMO
from app.services.team_scope import it_member_ids

BPLUS_STATUSES = {"draft", "auto_scored", "external_input", "manager_review", "cio_review", "published", "locked"}
BUSINESS_ROLES = {"it_bm", "it_bp"}
PLATFORM_ROLES = {"is_mgr", "data_governance", "ai", "ai_technology", "security", "architecture"}
EXCLUDED_ROLES = {"admin", "cio", "auditor", "requester"}
TEAM_TARGETS = {
    "special_activity": 40.0,
    "learning_growth": 30.0,
    "training_knowledge": 30.0,
    "suggestion_improvement": 20.0,
    "knowledge_asset": 30.0,
    "cross_team_support": 20.0,
}
TEAM_WEIGHTS = {
    "special_activity": 20,
    "learning_growth": 20,
    "training_knowledge": 15,
    "suggestion_improvement": 15,
    "knowledge_asset": 15,
    "cross_team_support": 15,
}
EXTERNAL_INPUT_METRICS = {"external_business_satisfaction"}


def _default_contribution_config() -> dict:
    return {
        "weights": dict(TEAM_WEIGHTS),
        "targets": dict(TEAM_TARGETS),
        "internal_satisfaction_weight": 50.0,
        "external_satisfaction_weight": 50.0,
    }


def get_contribution_config(db: Session) -> dict:
    """读取当前全局规则；首次访问时幂等创建默认配置。"""
    row = db.query(PerformanceContributionConfig).filter(
        PerformanceContributionConfig.is_deleted.is_(False)
    ).order_by(PerformanceContributionConfig.updated_at.desc()).first()
    if not row:
        defaults = _default_contribution_config()
        row = PerformanceContributionConfig(**defaults)
        db.add(row)
        db.flush()
    defaults = _default_contribution_config()
    return {
        "id": row.id,
        "weights": {**defaults["weights"], **(row.weights or {})},
        "targets": {**defaults["targets"], **(row.targets or {})},
        "internal_satisfaction_weight": float(row.internal_satisfaction_weight if row.internal_satisfaction_weight is not None else 50),
        "external_satisfaction_weight": float(row.external_satisfaction_weight if row.external_satisfaction_weight is not None else 50),
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
    }


def _period_contribution_config(db: Session, period: PerformancePeriod) -> dict:
    snapshot = (period.rule_snapshot or {}).get("contribution") if period else None
    if snapshot:
        defaults = _default_contribution_config()
        return {
            **defaults,
            **snapshot,
            "weights": {**defaults["weights"], **(snapshot.get("weights") or {})},
            "targets": {**defaults["targets"], **(snapshot.get("targets") or {})},
        }
    return get_contribution_config(db)

# 矩阵角色规则的可取数指标字典：页面与评分引擎共用同一套口径，避免外部原数据页只
# 显示已录入记录而不说明指标来源。source_type=system 表示系统自动取数，
# external 表示必须从系统外录入原始事实，manual 表示由 CIO/负责人依据证据评分。
METRIC_DEFINITIONS = {
    "ticket_service": {
        "name": "服务工单",
        "source_type": "system",
        "collection_mode": "auto",
        "description": "统计考核期内经办并解决的服务请求/事件工单，按 SLA 达成率和满意度计算。",
    },
    "change_compliance": {
        "name": "变更合规",
        "source_type": "system",
        "collection_mode": "auto",
        "description": "统计已完结变更中审批、关闭和回退情况，计算合规率。",
    },
    "project_delivery": {
        "name": "项目交付",
        "source_type": "system",
        "collection_mode": "auto",
        "description": "按考核期内到期 WBS 任务的按期完成率计算。",
    },
    "requirement_delivery": {
        "name": "需求交付",
        "source_type": "system",
        "collection_mode": "auto",
        "description": "按考核期内到期需求任务的按期完成率计算。",
    },
    "domain_satisfaction": {
        "name": "业务域满意度",
        "source_type": "system",
        "collection_mode": "auto",
        "description": "由 ITSM 工单满意度自动汇总业务域内成员的服务体验。",
    },
    "knowledge_contrib": {
        "name": "知识贡献",
        "source_type": "system",
        "collection_mode": "auto",
        "description": "根据知识库发布和被评价记录自动计分。",
    },
    "requirement_owner_delivery": {
        "name": "需求负责人交付",
        "source_type": "system",
        "collection_mode": "auto",
        "description": "按需求负责人负责的到期需求按期关闭情况计算。",
    },
    "project_manager_delivery": {
        "name": "项目治理结果",
        "source_type": "system",
        "collection_mode": "auto",
        "description": "按项目经理负责项目的计划与实际交付情况计算。",
    },
    "process_task_timeliness": {
        "name": "流程治理及时性",
        "source_type": "system",
        "collection_mode": "auto",
        "description": "按流程任务在截止时间前完成的比例计算。",
    },
    "domain_demand_outcome": {
        "name": "业务需求结果",
        "source_type": "system",
        "collection_mode": "auto",
        "description": "按业务域需求到期关闭与按期交付结果计算。",
    },
    "team_delivery_outcome": {
        "name": "团队交付结果",
        "source_type": "system",
        "collection_mode": "auto",
        "description": "汇总专业资源池内项目、需求等交付指标。",
    },
    "team_service_outcome": {
        "name": "团队服务结果",
        "source_type": "system",
        "collection_mode": "auto",
        "description": "汇总专业资源池内服务、变更和满意度指标。",
    },
    "internal_external_satisfaction": {
        "name": "内外部满意度",
        "source_type": "derived",
        "collection_mode": "derived",
        "description": "系统将内部 ITSM 满意度与对应业务域的外部业务满意度组合计算，不直接录入本指标。",
    },
    "external_business_satisfaction": {
        "name": "外部业务满意度",
        "source_type": "external",
        "collection_mode": "external_input",
        "description": "按百分比记录业务域负责人满意度。建议录入 0–100；系统按原始分÷满分×100 统一折算为 0–100%，兼容 4.5/5 等其他量表，并记录评价人、部门和来源说明。",
    },
    "business_value_confirmation": {
        "name": "业务价值确认",
        "source_type": "external",
        "collection_mode": "external_input",
        "description": "由业务负责人确认需求或项目产生的价值，需录入原始事实后折算。",
    },
    "manual": {
        "name": "人工评审指标",
        "source_type": "manual",
        "collection_mode": "manual_review",
        "description": "系统无法直接获取，由对应负责人或 CIO 根据证据在分级评审中评分。",
    },
}


def latest_period(db: Session, period: str) -> PerformancePeriod | None:
    return (
        db.query(PerformancePeriod)
        .filter(PerformancePeriod.period_code == period, PerformancePeriod.is_deleted.is_(False))
        .order_by(PerformancePeriod.version.desc())
        .first()
    )


def get_or_create_period(db: Session, period: str, actor_id: str | None = None) -> PerformancePeriod:
    current = latest_period(db, period)
    if current:
        return current
    row = PerformancePeriod(period_code=period, version=1, status="draft", created_by=actor_id, updated_by=actor_id)
    db.add(row)
    db.flush()
    return row


def _profiles(db: Session) -> dict[str, PerformanceRoleProfile]:
    return {
        p.role_code: p
        for p in db.query(PerformanceRoleProfile).filter(
            PerformanceRoleProfile.is_deleted.is_(False), PerformanceRoleProfile.active.is_(True)
        )
    }


def _person_roles(db: Session, member: OrgMember) -> set[str]:
    roles: set[str] = set()
    users = db.query(AuthUser).filter(AuthUser.person_id == member.id, AuthUser.is_deleted.is_(False)).all()
    for user in users:
        roles |= effective_roles(db, user)
    roles |= set((member.position.primary_roles if member.position else []) or [])
    return roles - EXCLUDED_ROLES


def _domain_scope(db: Session, person_id: str) -> tuple[list[str], list[str]]:
    domain_ids: set[str] = set()
    evaluator_ids: set[str] = set()
    for domain in db.query(BusinessDomain).filter(BusinessDomain.is_deleted.is_(False), BusinessDomain.active.is_(True)):
        members = db.query(BusinessDomainMember).filter(
            BusinessDomainMember.domain_id == domain.id,
            BusinessDomainMember.person_id == person_id,
            BusinessDomainMember.is_deleted.is_(False),
        ).first()
        if members or person_id in {domain.owner_id, domain.backup_owner_id}:
            domain_ids.add(domain.id)
            for evaluator in (domain.owner_id, domain.backup_owner_id):
                if evaluator and evaluator != person_id:
                    evaluator_ids.add(evaluator)
    return sorted(domain_ids), sorted(evaluator_ids)


def _professional_scope(db: Session, person_id: str, role_code: str) -> tuple[list[str], list[str]]:
    resource_role = role_code[:-7] if role_code.endswith("_leader") else role_code
    groups = (
        db.query(UserGroup)
        .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
        .filter(
            UserGroupMember.person_id == person_id,
            UserGroupMember.is_deleted.is_(False),
            UserGroup.is_deleted.is_(False),
        )
        .all()
    )
    # 普通成员从所在资源池取范围；负责人也可以通过资源池 owner 形成评审范围。
    relevant = [g for g in db.query(UserGroup).filter(UserGroup.is_deleted.is_(False)).all() if resource_role in (g.roles or []) or role_code in (g.roles or [])]
    relevant += [g for g in groups if g not in relevant]
    group_ids = sorted({g.id for g in relevant})
    evaluator_ids = sorted({g.owner_id for g in relevant if g.owner_id and g.owner_id != person_id})
    # IT PM 虚拟团队由 PMO 治理：只有具备 it_pmo 角色的资源池负责人可以对
    # it_pm 角色做专业线初评，避免任意把用户组 owner 当成项目经理评审人。
    if role_code == "it_pm":
        evaluator_ids = sorted({
            owner_id for owner_id in evaluator_ids
            if is_pmo_person(db, owner_id)
        })
    return group_ids, evaluator_ids


def is_pmo_person(db: Session, person_id: str) -> bool:
    """Return whether a person is an active IT PMO role holder."""
    owner = db.get(OrgMember, person_id)
    return bool(owner and not owner.is_deleted and IT_PMO in _person_roles(db, owner))


def _uniform_evaluator_weights(evaluator_ids: list[str] | None) -> dict[str, float]:
    ids = list(dict.fromkeys(evaluator_ids or []))
    if not ids:
        return {}
    value = round(100 / len(ids), 4)
    weights = {item: value for item in ids}
    # 避免浮点累计误差，让最后一位补齐到 100。
    weights[ids[-1]] = round(100 - sum(weights[item] for item in ids[:-1]), 4)
    return weights


def ensure_assignments(db: Session, period: PerformancePeriod, actor_id: str | None = None) -> list[PerformanceRoleAssignment]:
    profiles = _profiles(db)
    members = (
        db.query(OrgMember)
        .filter(OrgMember.id.in_(it_member_ids(db) or {"-"}), OrgMember.is_deleted.is_(False), OrgMember.status == "在岗")
        .all()
    )
    existing = {
        (a.person_id, a.role_code): a
        for a in db.query(PerformanceRoleAssignment).filter(
            PerformanceRoleAssignment.period_id == period.id, PerformanceRoleAssignment.is_deleted.is_(False)
        )
    }
    specs: list[tuple[OrgMember, str, PerformanceRoleProfile, list[str], list[str], list[str], list[str]]] = []
    for member in members:
        for role_code in sorted(_person_roles(db, member)):
            profile = profiles.get(role_code)
            if not profile:
                # 自定义岗位角色按 profile code 使用；没有档案就不自动进入评分。
                continue
            if profile.line_type == "business":
                scope_ids, evaluator_ids = _domain_scope(db, member.id)
                specs.append((member, role_code, profile, scope_ids, [], evaluator_ids, scope_ids))
            elif profile.line_type == "platform" or profile.review_mode == "cio_direct":
                specs.append((member, role_code, profile, [], [], [], []))
            else:
                group_ids, evaluator_ids = _professional_scope(db, member.id, role_code)
                specs.append((member, role_code, profile, [], group_ids, evaluator_ids, group_ids))

    business_count: dict[str, int] = defaultdict(int)
    professional_count: dict[str, int] = defaultdict(int)
    for member, _, profile, *_ in specs:
        if profile.line_type == "business":
            business_count[member.id] += 1
        else:
            professional_count[member.id] += 1

    assignments: list[PerformanceRoleAssignment] = []
    snapshot: list[dict] = []
    for member, role_code, profile, domain_ids, group_ids, evaluator_ids, scope_ids in specs:
        key = (member.id, role_code)
        both_sides = business_count[member.id] > 0 and professional_count[member.id] > 0
        side_total = 40.0 if both_sides else 80.0
        count = business_count[member.id] if profile.line_type == "business" else professional_count[member.id]
        role_weight = round(side_total / max(count, 1), 2)
        row = existing.get(key)
        scope = {
            "business_domain_ids": domain_ids,
            "professional_group_ids": group_ids,
            "target_person_id": member.id,
            "evaluator_ids": evaluator_ids,
        }
        if not row:
            row = PerformanceRoleAssignment(
                period_id=period.id,
                person_id=member.id,
                role_code=role_code,
                line_type=profile.line_type,
                business_domain_id=domain_ids[0] if domain_ids else None,
                professional_group_id=group_ids[0] if group_ids else None,
                role_weight=role_weight,
                evaluator_ids=evaluator_ids,
                evaluator_weights=_uniform_evaluator_weights(evaluator_ids),
                review_scope=scope,
                review_mode=profile.review_mode,
                snapshot_detail={"role_name": profile.name},
            )
            db.add(row)
            db.flush()
        else:
            # 周期内已由 CIO/管理员手工调整过的角色权重属于周期配置，重新取数只刷新角色范围和评分主体，不能覆盖该配置。
            if row.role_weight is None:
                row.role_weight = role_weight
            row.review_scope = scope
            row.evaluator_ids = evaluator_ids
            existing_weights = row.evaluator_weights or {}
            if set(existing_weights) != set(evaluator_ids or []):
                row.evaluator_weights = _uniform_evaluator_weights(evaluator_ids)
            row.review_mode = profile.review_mode
        assignments.append(row)
        snapshot.append({"person_id": member.id, "role_code": role_code, "role_weight": role_weight, **scope})
    period.role_snapshot = {"assignments": snapshot}
    period.updated_by = actor_id
    db.flush()
    return assignments


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total * 100, 1) if total else None


def _score_requirement_owner_delivery(db: Session, member_ids: list[str], start, end) -> dict[str, float]:
    today = end.date()
    rows = db.query(Requirement).filter(
        Requirement.owner.in_(member_ids), Requirement.is_deleted.is_(False), Requirement.is_example.is_(False),
        Requirement.target_date.isnot(None), Requirement.target_date >= start.date(), Requirement.target_date <= end.date(),
    ).all()
    per: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "n": 0})
    for row in rows:
        if not row.closed_at and row.target_date >= today:
            continue
        per[row.owner]["n"] += 1
        if row.closed_at and row.closed_at.date() <= row.target_date:
            per[row.owner]["ok"] += 1
    return {pid: _rate(v["ok"], v["n"]) for pid, v in per.items() if v["n"]}


def _score_project_manager_delivery(db: Session, member_ids: list[str], start, end) -> dict[str, float]:
    rows = db.query(Project).filter(
        Project.pm.in_(member_ids), Project.is_deleted.is_(False), Project.is_example.is_(False),
        Project.planned_end >= start.date(), Project.planned_end <= end.date(),
    ).all()
    per: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "n": 0})
    for row in rows:
        if row.status not in {"completed", "closed", "已完成", "已关闭"} and row.planned_end >= end.date():
            continue
        per[row.pm]["n"] += 1
        if row.actual_end and row.actual_end <= row.planned_end:
            per[row.pm]["ok"] += 1
    return {pid: _rate(v["ok"], v["n"]) for pid, v in per.items() if v["n"]}


def _score_process_task_timeliness(db: Session, member_ids: list[str], start, end) -> dict[str, float]:
    rows = db.query(ProcessTask).filter(
        ProcessTask.assignee.in_(member_ids), ProcessTask.is_deleted.is_(False),
        ProcessTask.due_at.isnot(None), ProcessTask.due_at >= start, ProcessTask.due_at <= end,
    ).all()
    per: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "n": 0})
    for row in rows:
        if not row.completed_at and row.due_at >= datetime.now():
            continue
        per[row.assignee]["n"] += 1
        if row.completed_at and row.completed_at <= row.due_at:
            per[row.assignee]["ok"] += 1
    return {pid: _rate(v["ok"], v["n"]) for pid, v in per.items() if v["n"]}


def _score_domain_demand_outcome(db: Session, member_ids: list[str], start, end) -> dict[str, float]:
    domain_people: dict[str, set[str]] = defaultdict(set)
    for dm in db.query(BusinessDomainMember).filter(BusinessDomainMember.is_deleted.is_(False)):
        domain_people[dm.domain_id].add(dm.person_id)
    for domain in db.query(BusinessDomain).filter(BusinessDomain.is_deleted.is_(False)):
        for pid in (domain.owner_id, domain.backup_owner_id):
            if pid:
                domain_people[domain.id].add(pid)
    demands = db.query(Requirement).filter(
        Requirement.business_domain_id.isnot(None), Requirement.is_deleted.is_(False), Requirement.is_example.is_(False),
        Requirement.target_date.isnot(None), Requirement.target_date >= start.date(), Requirement.target_date <= end.date(),
    ).all()
    domain_rate: dict[str, float] = {}
    for domain_id, people in domain_people.items():
        subset = [r for r in demands if r.business_domain_id == domain_id]
        if not subset:
            continue
        due = [r for r in subset if r.closed_at or r.target_date < end.date()]
        if due:
            domain_rate[domain_id] = _rate(sum(1 for r in due if r.closed_at and r.closed_at.date() <= r.target_date), len(due)) or 0
    out: dict[str, float] = {}
    for domain_id, people in domain_people.items():
        if domain_id in domain_rate:
            for pid in people & set(member_ids):
                out[pid] = domain_rate[domain_id]
    return out


def _external_scores(db: Session, period: PerformancePeriod, member_ids: list[str]) -> dict[str, float]:
    rows = db.query(PerformanceExternalInput).filter(
        PerformanceExternalInput.period_id == period.id,
        PerformanceExternalInput.metric_code == "external_business_satisfaction",
        PerformanceExternalInput.status.in_(["verified", "locked"]),
        PerformanceExternalInput.is_deleted.is_(False),
    ).all()
    member_ids_set = set(member_ids)
    members = {
        member.id: member
        for member in db.query(OrgMember).filter(OrgMember.id.in_(member_ids_set), OrgMember.is_deleted.is_(False)).all()
    }
    # 业务域评价只对该域负责人（BM/备份负责人）和该域 IT BP 生效，
    # 不扩散到业务部门成员、开发、运维等其他人员。
    domain_targets: dict[str, set[str]] = defaultdict(set)
    domains = db.query(BusinessDomain).filter(BusinessDomain.is_deleted.is_(False), BusinessDomain.active.is_(True)).all()
    for domain in domains:
        for owner_id in (domain.owner_id, domain.backup_owner_id):
            if owner_id and owner_id in member_ids_set:
                domain_targets[domain.id].add(owner_id)
    for dm in db.query(BusinessDomainMember).filter(BusinessDomainMember.is_deleted.is_(False)):
        if dm.person_id not in member_ids_set:
            continue
        member = members.get(dm.person_id)
        if member and "it_bp" in _person_roles(db, member):
            domain_targets[dm.domain_id].add(dm.person_id)
    out: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        score = row.normalized_score
        if score is None and row.raw_scale:
            score = row.raw_score / row.raw_scale * 100
        if score is None:
            continue
        if row.target_type in {"business_domain", "domain"}:
            for pid in domain_targets.get(row.target_id, set()):
                out[pid].append(score)
    return {pid: round(sum(values) / len(values), 1) for pid, values in out.items() if values}


def _team_people(db: Session, group_ids: list[str]) -> set[str]:
    if not group_ids:
        return set()
    rows = db.query(UserGroupMember).filter(
        UserGroupMember.group_id.in_(group_ids), UserGroupMember.is_deleted.is_(False)
    ).all()
    return {row.person_id for row in rows}


def _team_contribution_scores(db: Session, period: str, member_ids: list[str], period_row: PerformancePeriod | None = None) -> dict[str, dict[str, float]]:
    rows = db.query(PointEntry).filter(
        period_clause(PointEntry.period, period),
        or_(PointEntry.contribution_bucket == "team_contribution", PointEntry.contribution_bucket.is_(None)),
        PointEntry.person_id.in_(member_ids), PointEntry.is_deleted.is_(False),
    ).all()
    aliases = {
        "campaign_award": "special_activity", "training_host": "training_knowledge", "training_attend": "training_knowledge",
        "knowledge_published": "knowledge_asset", "knowledge_voted": "knowledge_asset",
        "idea_submit": "suggestion_improvement", "idea_like": "suggestion_improvement", "idea_adopt": "suggestion_improvement",
    }
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        dimension = row.contribution_dimension or aliases.get(row.source_type)
        if dimension:
            totals[row.person_id][dimension] += row.points
    config = _period_contribution_config(db, period_row) if period_row else get_contribution_config(db)
    scores: dict[str, dict[str, float]] = {}
    for pid in member_ids:
        result: dict[str, float] = {}
        for dimension, target in config["targets"].items():
            result[dimension] = round(min(100.0, max(0.0, totals[pid].get(dimension, 0) / target * 100)), 1)
        scores[pid] = result
    return scores


def _system_scores(db: Session, period: str, member_ids: list[str], period_row: PerformancePeriod) -> dict[str, dict[str, float]]:
    start, end = period_range(period)
    scores: dict[str, dict[str, float]] = {
        "ticket_service": _score_ticket_service(db, member_ids, start, end),
        "change_compliance": _score_change_compliance(db, member_ids, start, end),
        "project_delivery": _score_project_delivery(db, member_ids, start, end),
        "requirement_delivery": _score_requirement_delivery(db, member_ids, start, end),
        "domain_satisfaction": _score_domain_satisfaction(db, member_ids, start, end),
        "knowledge_contrib": _score_knowledge_contrib(db, member_ids, start, end),
        "requirement_owner_delivery": _score_requirement_owner_delivery(db, member_ids, start, end),
        "project_manager_delivery": _score_project_manager_delivery(db, member_ids, start, end),
        "process_task_timeliness": _score_process_task_timeliness(db, member_ids, start, end),
        "domain_demand_outcome": _score_domain_demand_outcome(db, member_ids, start, end),
        "external_business_satisfaction": _external_scores(db, period_row, member_ids),
    }
    scores["team_contribution"] = _team_contribution_scores(db, period, member_ids)
    return scores


def _score_for_assignment(assignment: PerformanceRoleAssignment, metric: str, scores: dict, db: Session, period: PerformancePeriod | None = None) -> float | None:
    if metric == "manual":
        return None
    if metric == "team_service_outcome":
        people = _team_people(db, (assignment.review_scope or {}).get("professional_group_ids", []))
        values = []
        for code in ("ticket_service", "change_compliance", "domain_satisfaction"):
            values.extend(scores.get(code, {}).get(pid) for pid in people if scores.get(code, {}).get(pid) is not None)
        return round(sum(values) / len(values), 1) if values else None
    if metric == "team_delivery_outcome":
        people = _team_people(db, (assignment.review_scope or {}).get("professional_group_ids", []))
        values = []
        for code in ("project_delivery", "requirement_delivery", "project_manager_delivery", "requirement_owner_delivery"):
            values.extend(scores.get(code, {}).get(pid) for pid in people if scores.get(code, {}).get(pid) is not None)
        return round(sum(values) / len(values), 1) if values else None
    if metric == "internal_external_satisfaction":
        internal = scores.get("domain_satisfaction", {}).get(assignment.person_id)
        external = scores.get("external_business_satisfaction", {}).get(assignment.person_id)
        config = _period_contribution_config(db, period) if period else get_contribution_config(db)
        weighted = []
        if internal is not None:
            weighted.append((internal, config["internal_satisfaction_weight"]))
        if external is not None:
            weighted.append((external, config["external_satisfaction_weight"]))
        weight_sum = sum(weight for _, weight in weighted)
        return round(sum(value * weight for value, weight in weighted) / weight_sum, 1) if weight_sum else None
    value = scores.get(metric, {}).get(assignment.person_id)
    if isinstance(value, dict):
        values = [v for v in value.values() if v is not None]
        return round(sum(values) / len(values), 1) if values else None
    return value


def _effective(component: PerformanceScoreComponent, line_type: str) -> float | None:
    if component.cio_score is not None:
        return component.cio_score
    if line_type == "business" and component.business_manager_score is not None:
        return component.business_manager_score
    if line_type == "professional" and component.professional_manager_score is not None:
        return component.professional_manager_score
    return component.system_score


def recompute_bplus(db: Session, period: str, actor_id: str | None = None) -> dict:
    period_row = get_or_create_period(db, period, actor_id)
    if period_row.status in {"published", "locked"}:
        raise AppError("PERFORMANCE_LOCKED", "已发布/锁定周期必须通过解锁生成新版本")
    config = get_contribution_config(db)
    period_row.rule_snapshot = {**(period_row.rule_snapshot or {}), "contribution": {
        "weights": config["weights"], "targets": config["targets"],
        "internal_satisfaction_weight": config["internal_satisfaction_weight"],
        "external_satisfaction_weight": config["external_satisfaction_weight"],
    }}
    assignments = ensure_assignments(db, period_row, actor_id)
    member_ids = sorted({a.person_id for a in assignments})
    scores = _system_scores(db, period, member_ids, period_row)
    profiles = _profiles(db)
    for assignment in assignments:
        profile = profiles.get(assignment.role_code)
        if not profile:
            continue
        dimensions = db.query(PerformanceRoleDimension).filter(
            PerformanceRoleDimension.profile_id == profile.id,
            PerformanceRoleDimension.is_deleted.is_(False), PerformanceRoleDimension.active.is_(True),
        ).order_by(PerformanceRoleDimension.sort).all()
        for dimension in dimensions:
            metric = (dimension.source_config or {}).get("metric", dimension.dimension_code)
            system_score = _score_for_assignment(assignment, metric, scores, db, period_row)
            component = db.query(PerformanceScoreComponent).filter(
                PerformanceScoreComponent.period_id == period_row.id,
                PerformanceScoreComponent.assignment_id == assignment.id,
                PerformanceScoreComponent.dimension_code == dimension.dimension_code,
                PerformanceScoreComponent.is_deleted.is_(False),
            ).first()
            if not component:
                component = PerformanceScoreComponent(
                    period_id=period_row.id, assignment_id=assignment.id, dimension_code=dimension.dimension_code,
                    system_score=system_score, effective_score=system_score, updated_by=actor_id,
                )
                db.add(component)
            else:
                component.system_score = system_score
                component.effective_score = _effective(component, assignment.line_type)
                component.updated_by = actor_id
    period_row.status = "auto_scored"
    period_row.updated_by = actor_id
    db.flush()
    return build_internal_result(db, period_row)


def build_internal_result(db: Session, period: PerformancePeriod) -> dict:
    assignments = db.query(PerformanceRoleAssignment).filter(
        PerformanceRoleAssignment.period_id == period.id, PerformanceRoleAssignment.is_deleted.is_(False)
    ).all()
    profiles = _profiles(db)
    scoped_member_ids = it_member_ids(db) or {"-"}
    member_map = {
        m.id: m for m in db.query(OrgMember).filter(
            OrgMember.id.in_(scoped_member_ids), OrgMember.is_deleted.is_(False), OrgMember.status == "在岗"
        ).all()
    }
    rows: dict[str, dict] = {}
    for assignment in assignments:
        profile = profiles.get(assignment.role_code)
        if not profile:
            continue
        dims = db.query(PerformanceRoleDimension).filter(
            PerformanceRoleDimension.profile_id == profile.id,
            PerformanceRoleDimension.is_deleted.is_(False), PerformanceRoleDimension.active.is_(True),
        ).order_by(PerformanceRoleDimension.sort).all()
        components = db.query(PerformanceScoreComponent).filter(
            PerformanceScoreComponent.assignment_id == assignment.id,
            PerformanceScoreComponent.is_deleted.is_(False),
        ).all()
        component_map = {c.dimension_code: c for c in components}
        weighted = 0.0
        weight_sum = 0.0
        detail = []
        for dimension in dims:
            component = component_map.get(dimension.dimension_code)
            effective = _effective(component, assignment.line_type) if component else None
            detail.append({
                "code": dimension.dimension_code, "name": dimension.name, "weight": dimension.weight,
                "system_score": component.system_score if component else None,
                "business_manager_score": component.business_manager_score if component else None,
                "professional_manager_score": component.professional_manager_score if component else None,
                "cio_score": component.cio_score if component else None,
                "manager_scores": component.manager_scores if component else {},
                "manager_reasons": component.manager_reasons if component else {},
                "manager_evidence_refs": component.manager_evidence_refs if component else {},
                "effective_score": effective,
                "reason": component.reason if component else None,
                "evidence_refs": component.evidence_refs if component else [],
            })
            if effective is not None and dimension.weight > 0:
                weighted += effective * dimension.weight
                weight_sum += dimension.weight
        role_score = round(weighted / weight_sum, 1) if weight_sum else None
        row = rows.setdefault(assignment.person_id, {
            "person_id": assignment.person_id,
            "person_name": member_map.get(assignment.person_id).name if member_map.get(assignment.person_id) else "",
            "roles": [], "business_contribution": 0.0, "professional_contribution": 0.0,
        })
        role = {
            "assignment_id": assignment.id, "role_code": assignment.role_code, "role_name": profile.name,
            "line_type": assignment.line_type, "role_weight": assignment.role_weight,
            "review_mode": assignment.review_mode, "evaluator_ids": assignment.evaluator_ids or [],
            "evaluator_weights": assignment.evaluator_weights or {},
            "review_scope": assignment.review_scope or {}, "role_score": role_score, "dimensions": detail,
        }
        row["roles"].append(role)
        contribution = (role_score or 0) * assignment.role_weight / 100 if role_score is not None else 0
        if assignment.line_type == "business":
            row["business_contribution"] += contribution
        else:
            row["professional_contribution"] += contribution

    for person_id, member in member_map.items():
        rows.setdefault(person_id, {
            "person_id": person_id,
            "person_name": member.name,
            "roles": [],
            "role_status": "未配置角色",
            "business_contribution": 0.0,
            "professional_contribution": 0.0,
        })

    member_ids = list(rows)
    config = _period_contribution_config(db, period)
    contribution_scores = _team_contribution_scores(db, period.period_code, member_ids, period)
    adjustments = defaultdict(lambda: {"bonus": 0.0, "penalty": 0.0, "items": []})
    from app.models import PerfAdjustment

    for item in db.query(PerfAdjustment).filter(
        PerfAdjustment.period == period.period_code, PerfAdjustment.is_deleted.is_(False), PerfAdjustment.person_id.in_(member_ids)
    ).all():
        adjustments[item.person_id][item.kind] += item.points
        adjustments[item.person_id]["items"].append({
            "id": item.id, "kind": item.kind, "points": item.points, "reason": item.reason, "created_at": item.created_at,
        })
    output = []
    for pid, row in rows.items():
        team_dims = contribution_scores.get(pid, {})
        team_score = round(sum(team_dims.get(code, 0) * weight for code, weight in config["weights"].items()) / 100, 1)
        row["business_contribution"] = round(row["business_contribution"], 1)
        row["professional_contribution"] = round(row["professional_contribution"], 1)
        row["team_contribution_dimensions"] = team_dims
        row["team_contribution_score"] = team_score
        row["regular_score"] = round(row["business_contribution"] + row["professional_contribution"] + team_score * 0.2, 1)
        row["bonus"] = round(adjustments[pid]["bonus"], 1)
        row["penalty"] = round(adjustments[pid]["penalty"], 1)
        row["published_score"] = round(row["regular_score"] + row["bonus"] - row["penalty"], 1)
        row["adjustments"] = adjustments[pid]["items"]
        output.append(row)
    output.sort(key=lambda row: (row["published_score"] is None, -(row["published_score"] or 0)))
    return {"period": period.period_code, "version": period.version, "status": period.status, "rows": output}


def apply_review(
    db: Session, period: PerformancePeriod, assignment_id: str, dimension_code: str,
    score: float | None, reason: str | None, evidence_refs: list | None, actor: AuthUser,
) -> dict:
    assignment = db.get(PerformanceRoleAssignment, assignment_id)
    if not assignment or assignment.period_id != period.id or assignment.is_deleted:
        raise AppError("NOT_FOUND", "绩效角色快照不存在", 404)
    if assignment.person_id == actor.person_id:
        raise AppError("SELF_REVIEW_FORBIDDEN", "负责人不能评价自己", 403)
    roles = effective_roles(db, actor)
    is_cio = "admin" in roles or "cio" in roles
    if not is_cio:
        if period.status == "cio_review":
            raise AppError("CIO_REVIEW_ACTIVE", "当前已进入 CIO 终审，负责人不能继续修改", 403)
        if assignment.review_mode == "cio_direct":
            raise AppError("CIO_REVIEW_ONLY", "该平台角色只能由 CIO 直接评分", 403)
        scope = assignment.review_scope or {}
        if actor.person_id not in set(scope.get("evaluator_ids", [])):
            raise AppError("REVIEW_SCOPE_FORBIDDEN", "不在该人员角色的评审范围内", 403)
        if assignment.line_type not in {"business", "professional"}:
            raise AppError("REVIEW_SCOPE_FORBIDDEN", "无权评价该角色条线", 403)
    component = db.query(PerformanceScoreComponent).filter(
        PerformanceScoreComponent.period_id == period.id,
        PerformanceScoreComponent.assignment_id == assignment.id,
        PerformanceScoreComponent.dimension_code == dimension_code,
        PerformanceScoreComponent.is_deleted.is_(False),
    ).first()
    if not component:
        raise AppError("NOT_FOUND", "评分维度不存在", 404)
    if not reason or not reason.strip():
        raise AppError("REVIEW_REASON_REQUIRED", "调整或清除评分必须填写原因", 422)
    before = {
        "effective_score": component.effective_score,
        "reason": component.reason,
        "manager_scores": component.manager_scores or {},
    }
    if score is not None and (score < 0 or score > 100):
        raise AppError("INVALID_SCORE", "评分必须在 0-100 之间", 422)
    if is_cio:
        component.cio_score = score
        stage = "cio_review"
    else:
        manager_scores = dict(component.manager_scores or {})
        if score is None:
            manager_scores.pop(actor.person_id, None)
        else:
            manager_scores[actor.person_id] = score
        component.manager_scores = manager_scores
        manager_reasons = dict(component.manager_reasons or {})
        manager_evidence = dict(component.manager_evidence_refs or {})
        if score is None:
            manager_reasons.pop(actor.person_id, None)
            manager_evidence.pop(actor.person_id, None)
        else:
            manager_reasons[actor.person_id] = reason
            manager_evidence[actor.person_id] = evidence_refs or []
        component.manager_reasons = manager_reasons
        component.manager_evidence_refs = manager_evidence
        weights = assignment.evaluator_weights or _uniform_evaluator_weights(assignment.evaluator_ids or [])
        selected = [(value, float(weights.get(evaluator_id, 0))) for evaluator_id, value in manager_scores.items()]
        weight_sum = sum(weight for _, weight in selected)
        aggregate = round(sum(value * weight for value, weight in selected) / weight_sum, 1) if weight_sum else None
        if assignment.line_type == "business":
            component.business_manager_score = aggregate
        else:
            component.professional_manager_score = aggregate
        stage = "manager_review"
    component.reason = reason
    component.evidence_refs = evidence_refs or []
    component.updated_by = actor.id
    component.effective_score = _effective(component, assignment.line_type)
    db.add(PerformanceReviewAction(
        period_id=period.id, assignment_id=assignment.id, actor_id=actor.id, stage=stage, action="score_updated",
        before_value=before, after_value={"score": score, "effective_score": component.effective_score},
        reason=reason, evidence_refs=evidence_refs or [],
    ))
    period.status = "cio_review" if is_cio else "manager_review"
    period.updated_by = actor.id
    db.flush()
    return {"assignment_id": assignment.id, "dimension_code": dimension_code, "effective_score": component.effective_score}


def publish_period(db: Session, period: PerformancePeriod, actor: AuthUser) -> dict:
    roles = effective_roles(db, actor)
    if not ({"admin", "cio"} & roles):
        raise AppError("FORBIDDEN", "只有 CIO 可以发布绩效结果", 403)
    if period.status in {"draft", "external_input"}:
        recompute_bplus(db, period.period_code, actor.id)
    result = build_internal_result(db, period)
    now = datetime.now()
    for row in result["rows"]:
        snapshot = db.query(PerformanceScore).filter(
            PerformanceScore.period_id == period.id, PerformanceScore.person_id == row["person_id"],
            PerformanceScore.is_deleted.is_(False),
        ).first()
        values = dict(
            period_id=period.id, person_id=row["person_id"], version=period.version,
            business_role_score=row["business_contribution"], professional_role_score=row["professional_contribution"],
            team_contribution_score=row["team_contribution_score"], regular_score=row["regular_score"],
            bonus=row["bonus"], penalty=row["penalty"], published_score=row["published_score"],
            detail={"roles": row["roles"], "team_contribution_dimensions": row["team_contribution_dimensions"]},
            published_at=now,
        )
        if snapshot:
            for key, value in values.items():
                if key not in {"period_id", "person_id"}:
                    setattr(snapshot, key, value)
        else:
            db.add(PerformanceScore(**values))
    period.status = "published"
    period.published_at = now
    period.updated_by = actor.id
    db.add(PerformanceReviewAction(
        period_id=period.id, actor_id=actor.id, stage="cio_review", action="published",
        after_value={"version": period.version}, reason="CIO 发布绩效结果",
    ))
    db.commit()
    return build_internal_result(db, period)


def unlock_period(db: Session, period: PerformancePeriod, actor: AuthUser) -> PerformancePeriod:
    if not ({"admin", "cio"} & effective_roles(db, actor)):
        raise AppError("FORBIDDEN", "只有 CIO 可以解锁绩效周期", 403)
    if period.status not in {"published", "locked"}:
        return period
    new_period = PerformancePeriod(
        period_code=period.period_code, version=period.version + 1, status="draft",
        rule_snapshot=period.rule_snapshot or {}, role_snapshot=period.role_snapshot or {}, created_by=actor.id, updated_by=actor.id,
    )
    db.add(new_period)
    db.flush()
    for old in db.query(PerformanceRoleAssignment).filter(
        PerformanceRoleAssignment.period_id == period.id, PerformanceRoleAssignment.is_deleted.is_(False)
    ).all():
        db.add(PerformanceRoleAssignment(
            period_id=new_period.id, person_id=old.person_id, role_code=old.role_code, line_type=old.line_type,
            business_domain_id=old.business_domain_id, professional_group_id=old.professional_group_id,
            role_weight=old.role_weight, evaluator_ids=old.evaluator_ids or [], review_scope=old.review_scope or {},
            evaluator_weights=old.evaluator_weights or {},
            review_mode=old.review_mode, snapshot_detail=old.snapshot_detail or {},
        ))
    period.status = "locked"
    period.locked_at = datetime.now()
    db.add(PerformanceReviewAction(
        period_id=period.id, actor_id=actor.id, stage="cio_review", action="unlocked",
        after_value={"new_version": new_period.version}, reason="发布版本修订，生成新版本",
    ))
    db.commit()
    return new_period
