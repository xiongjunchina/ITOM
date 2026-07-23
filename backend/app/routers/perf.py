"""人效评分（M6.1 + 矩阵角色）：旧版方案兼容 + 矩阵角色周期评审。

权限：performance.view 查看；performance.edit 管理方案（默认仅 admin/cio）。
"""
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import require_perm
from app.models import (
    AuthUser,
    BusinessDomain,
    OrgMember,
    PerformanceExternalInput,
    PerformanceContributionConfig,
    PerformancePeriod,
    PerformanceReviewAction,
    PerformanceRoleAssignment,
    PerformanceRoleDimension,
    PerformanceRoleProfile,
    PerformanceScore,
    PerfScheme,
    Position,
)
from app.schemas.common import ok
from app.services.audit import audit
from app.services.perf import DIMENSION_CODES, DIMENSIONS, compute_performance
from app.services.points import current_period
from app.services.perf_bplus import (
    BPLUS_STATUSES,
    apply_review,
    build_internal_result,
    ensure_assignments,
    get_or_create_period,
    latest_period,
    publish_period,
    recompute_bplus,
    is_pmo_person,
    unlock_period,
    EXTERNAL_INPUT_METRICS,
    get_contribution_config,
)

router = APIRouter(tags=["perf"])


class DimensionItem(BaseModel):
    code: str
    weight: float = Field(gt=0, le=1000)


class SchemeIn(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    description: str | None = None
    position_ids: list[str] = []
    dimensions: list[DimensionItem] = Field(min_length=1)
    is_default: bool = False
    active: bool = True


def _scheme_row(s: PerfScheme, positions: dict[str, str]) -> dict:
    return {
        "id": s.id, "name": s.name, "description": s.description,
        "position_ids": s.position_ids or [],
        "position_names": [positions.get(p) for p in (s.position_ids or []) if positions.get(p)],
        "dimensions": s.dimensions or [],
        "weight_total": round(sum(float(d.get("weight") or 0) for d in (s.dimensions or [])), 1),
        "is_default": s.is_default, "active": s.active,
    }


def _validate(db: Session, body: SchemeIn, exclude_id: str | None = None):
    bad = [d.code for d in body.dimensions if d.code not in DIMENSION_CODES]
    if bad:
        raise AppError("INVALID_DIMENSION", f"未知的评分维度：{'、'.join(bad)}")
    if len({d.code for d in body.dimensions}) != len(body.dimensions):
        raise AppError("DUPLICATE_DIMENSION", "同一维度只能配置一次")
    # 岗位冲突：同一岗位不能同时命中两个启用方案
    if body.active and body.position_ids:
        others = db.query(PerfScheme).filter(PerfScheme.is_deleted.is_(False), PerfScheme.active.is_(True))
        if exclude_id:
            others = others.filter(PerfScheme.id != exclude_id)
        positions = {p.id: p.name for p in db.query(Position).filter(Position.is_deleted.is_(False))}
        for s in others:
            overlap = set(body.position_ids) & set(s.position_ids or [])
            if overlap:
                names = "、".join(positions.get(p, p) for p in overlap)
                raise AppError("POSITION_CONFLICT", f"岗位（{names}）已被方案「{s.name}」使用，请先从原方案移除")


def _clear_other_default(db: Session, exclude_id: str | None = None):
    q = db.query(PerfScheme).filter(PerfScheme.is_deleted.is_(False), PerfScheme.is_default.is_(True))
    if exclude_id:
        q = q.filter(PerfScheme.id != exclude_id)
    for s in q:
        s.is_default = False


@router.get("/api/perf/dimensions")
def list_dimensions(_=Depends(require_perm("performance", "view"))):
    return ok([{"code": c, "name": n, "public": p, "description": d} for c, n, p, d in DIMENSIONS])


@router.get("/api/perf/schemes")
def list_schemes(db: Session = Depends(get_db), _=Depends(require_perm("performance", "view"))):
    rows = (
        db.query(PerfScheme)
        .filter(PerfScheme.is_deleted.is_(False))
        .order_by(PerfScheme.is_default.desc(), PerfScheme.created_at)
        .all()
    )
    positions = {p.id: p.name for p in db.query(Position).filter(Position.is_deleted.is_(False))}
    return ok([_scheme_row(s, positions) for s in rows], total=len(rows))


@router.post("/api/perf/schemes")
def create_scheme(body: SchemeIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance", "edit"))):
    _validate(db, body)
    if body.is_default:
        _clear_other_default(db)
    s = PerfScheme(**{**body.model_dump(), "dimensions": [d.model_dump() for d in body.dimensions]})
    db.add(s)
    db.flush()
    audit(db, "perf_scheme", s.id, "create", user, {"name": s.name})
    db.commit()
    positions = {p.id: p.name for p in db.query(Position).filter(Position.is_deleted.is_(False))}
    return ok(_scheme_row(s, positions))


@router.patch("/api/perf/schemes/{scheme_id}")
def update_scheme(scheme_id: str, body: SchemeIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance", "edit"))):
    s = db.get(PerfScheme, scheme_id)
    if not s or s.is_deleted:
        raise AppError("NOT_FOUND", "计分方案不存在", 404)
    _validate(db, body, exclude_id=s.id)
    if body.is_default:
        _clear_other_default(db, exclude_id=s.id)
    data = body.model_dump()
    data["dimensions"] = [d.model_dump() for d in body.dimensions]
    for k, v in data.items():
        setattr(s, k, v)
    audit(db, "perf_scheme", s.id, "update", user, {"name": s.name})
    db.commit()
    positions = {p.id: p.name for p in db.query(Position).filter(Position.is_deleted.is_(False))}
    return ok(_scheme_row(s, positions))


@router.delete("/api/perf/schemes/{scheme_id}")
def delete_scheme(scheme_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance", "edit"))):
    s = db.get(PerfScheme, scheme_id)
    if not s or s.is_deleted:
        raise AppError("NOT_FOUND", "计分方案不存在", 404)
    s.is_deleted = True
    audit(db, "perf_scheme", s.id, "delete", user, {"name": s.name})
    db.commit()
    return ok({"deleted": True})


class OverrideIn(BaseModel):
    period: str
    person_id: str
    dimension_code: str
    score: float | None = Field(default=None, ge=0, le=100, description="null=清除核定，回到系统参考值")


class AdjustmentIn(BaseModel):
    period: str
    person_id: str
    kind: str = Field(pattern="^(bonus|penalty)$")
    points: float = Field(gt=0, le=1000)
    reason: str = Field(min_length=2, max_length=200)


@router.put("/api/perf/overrides")
def put_override(body: OverrideIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance", "edit"))):
    """核定维度分：score=null 清除核定恢复系统参考值。"""
    from app.models import OrgMember, PerfOverride

    if body.dimension_code not in DIMENSION_CODES:
        raise AppError("INVALID_DIMENSION", "未知的评分维度")
    if not db.get(OrgMember, body.person_id):
        raise AppError("NOT_FOUND", "人员不存在", 404)
    from app.services.team_scope import require_it_member_if_configured
    require_it_member_if_configured(db, body.person_id, "考核人员")
    row = (
        db.query(PerfOverride)
        .filter(PerfOverride.period == body.period, PerfOverride.person_id == body.person_id,
                PerfOverride.dimension_code == body.dimension_code, PerfOverride.is_deleted.is_(False))
        .first()
    )
    if body.score is None:
        if row:
            row.is_deleted = True
            audit(db, "perf_override", row.id, "clear", user, {"period": body.period, "dim": body.dimension_code})
            db.commit()
        return ok({"cleared": True})
    if row:
        row.score = body.score
        row.created_by = user.id
    else:
        row = PerfOverride(period=body.period, person_id=body.person_id,
                           dimension_code=body.dimension_code, score=body.score, created_by=user.id)
        db.add(row)
        db.flush()
    audit(db, "perf_override", row.id, "set", user,
          {"period": body.period, "dim": body.dimension_code, "score": body.score})
    db.commit()
    return ok({"id": row.id, "score": row.score})


@router.post("/api/perf/adjustments")
def create_adjustment(body: AdjustmentIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance", "edit"))):
    from app.models import OrgMember, PerfAdjustment

    if not db.get(OrgMember, body.person_id):
        raise AppError("NOT_FOUND", "人员不存在", 404)
    from app.services.team_scope import require_it_member_if_configured
    require_it_member_if_configured(db, body.person_id, "考核人员")
    row = PerfAdjustment(**body.model_dump(), created_by=user.id)
    db.add(row)
    db.flush()
    audit(db, "perf_adjustment", row.id, "create", user,
          {"period": body.period, "kind": body.kind, "points": body.points, "reason": body.reason})
    db.commit()
    return ok({"id": row.id})


@router.delete("/api/perf/adjustments/{adj_id}")
def delete_adjustment(adj_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance", "edit"))):
    from app.models import PerfAdjustment

    row = db.get(PerfAdjustment, adj_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "加减分事项不存在", 404)
    row.is_deleted = True
    audit(db, "perf_adjustment", row.id, "delete", user, {"reason": row.reason})
    db.commit()
    return ok({"deleted": True})


@router.get("/api/team/performance")
def team_performance(period: str = "", db: Session = Depends(get_db), _=Depends(require_perm("performance", "view"))):
    import re

    period = period or current_period()
    if not re.fullmatch(r"\d{4}-(Q[123]|All)", period):
        raise AppError("INVALID_PERIOD", "考核期格式应为 YYYY-Q1/Q2/Q3 或 YYYY-All（全年考核）")
    return ok(compute_performance(db, period))


# ==================== 矩阵角色绩效 ====================


class BplusScoreIn(BaseModel):
    score: float | None = Field(default=None, ge=0, le=100)
    reason: str | None = Field(default=None, max_length=2000)
    evidence_refs: list[str] = []


class ExternalInputIn(BaseModel):
    period: str
    metric_code: str = Field(min_length=2, max_length=64)
    target_type: str = Field(pattern="^business_domain$")
    target_id: str
    evaluator_name: str = Field(min_length=1, max_length=128)
    evaluator_department: str | None = Field(default=None, max_length=128)
    raw_score: float = Field(ge=0)
    raw_scale: float = Field(gt=0, le=1000)
    comment: str | None = Field(default=None, max_length=4000)
    evidence_refs: list[str] = []
    status: str = Field(default="draft", pattern="^(draft|submitted|verified|locked)$")


class RoleProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    line_type: str | None = Field(default=None, pattern="^(business|professional|platform)$")
    review_mode: str | None = Field(default=None, pattern="^(manager_review|cio_direct)$")
    description: str | None = None
    active: bool | None = None


class RoleProfileCreate(BaseModel):
    role_code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1, max_length=128)
    line_type: str = Field(pattern="^(business|professional|platform)$")
    review_mode: str = Field(default="manager_review", pattern="^(manager_review|cio_direct)$")
    description: str | None = None
    active: bool = True


class RoleDimensionUpdate(BaseModel):
    dimension_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    weight: float = Field(gt=0, le=100)
    metric: str = Field(min_length=1, max_length=64)
    evidence_required: bool = False
    sort: int = 0
    active: bool = True


class RoleDimensionsUpdate(BaseModel):
    dimensions: list[RoleDimensionUpdate] = Field(min_length=1)


TEAM_CONTRIBUTION_DIMENSIONS = (
    "special_activity", "learning_growth", "training_knowledge",
    "suggestion_improvement", "knowledge_asset", "cross_team_support",
)


class ContributionRulesIn(BaseModel):
    weights: dict[str, float]
    targets: dict[str, float]
    internal_satisfaction_weight: float = Field(ge=0, le=100)
    external_satisfaction_weight: float = Field(ge=0, le=100)


def _validate_contribution_rules(body: ContributionRulesIn):
    if set(body.weights) != set(TEAM_CONTRIBUTION_DIMENSIONS) or set(body.targets) != set(TEAM_CONTRIBUTION_DIMENSIONS):
        raise AppError("INVALID_CONTRIBUTION_RULES", "团队贡献权重和目标必须覆盖全部六个维度", 422)
    if any(value < 0 for value in body.weights.values()) or abs(sum(body.weights.values()) - 100) > 0.01:
        raise AppError("INVALID_CONTRIBUTION_WEIGHT", "团队贡献权重必须为非负数且合计 100%", 422)
    if any(value <= 0 for value in body.targets.values()):
        raise AppError("INVALID_CONTRIBUTION_TARGET", "团队贡献目标积分必须大于 0", 422)
    if abs(body.internal_satisfaction_weight + body.external_satisfaction_weight - 100) > 0.01:
        raise AppError("INVALID_SATISFACTION_WEIGHT", "内外部满意度组合比例必须合计 100%", 422)


class AssignmentItem(BaseModel):
    assignment_id: str
    role_weight: float = Field(gt=0, le=80)
    evaluator_ids: list[str] | None = None
    evaluator_weights: dict[str, float] | None = None


class AssignmentBatchUpdate(BaseModel):
    period: str
    person_id: str
    assignments: list[AssignmentItem] = Field(min_length=1)


def _valid_bplus_period(period: str) -> str:
    import re

    if not re.fullmatch(r"\d{4}-(Q[123]|All)", period):
        raise AppError("INVALID_PERIOD", "考核期格式应为 YYYY-Q1/Q2/Q3 或 YYYY-All（全年考核）")
    return period


def _validate_external_target(db: Session, target_type: str, target_id: str):
    domain = db.get(BusinessDomain, target_id)
    if not domain or domain.is_deleted or not domain.active:
        raise AppError("NOT_FOUND", "外部评价目标业务域不存在或已停用", 404)


def _validate_external_metric(metric_code: str):
    if metric_code not in EXTERNAL_INPUT_METRICS:
        raise AppError("INVALID_EXTERNAL_METRIC", "当前仅允许录入外部业务满意度指标", 422)


@router.post("/api/admin/performance/role-profiles")
def create_bplus_role_profile(body: RoleProfileCreate, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance_admin", "edit"))):
    if db.query(PerformanceRoleProfile).filter(PerformanceRoleProfile.role_code == body.role_code).first():
        raise AppError("DUPLICATE_ROLE_PROFILE", "绩效角色档案编码已存在", 409)
    profile = PerformanceRoleProfile(**body.model_dump())
    db.add(profile)
    db.flush()
    audit(db, "performance_role_profile", profile.id, "create", user, body.model_dump())
    db.commit()
    return ok({"id": profile.id, "role_code": profile.role_code, "name": profile.name, "line_type": profile.line_type, "review_mode": profile.review_mode})


@router.get("/api/admin/performance/role-profiles")
def list_bplus_role_profiles(db: Session = Depends(get_db), _=Depends(require_perm("performance_admin", "view"))):
    profiles = db.query(PerformanceRoleProfile).filter(PerformanceRoleProfile.is_deleted.is_(False)).order_by(PerformanceRoleProfile.role_code).all()
    output = []
    for profile in profiles:
        dimensions = db.query(PerformanceRoleDimension).filter(
            PerformanceRoleDimension.profile_id == profile.id, PerformanceRoleDimension.is_deleted.is_(False)
        ).order_by(PerformanceRoleDimension.sort).all()
        output.append({
            "id": profile.id, "role_code": profile.role_code, "name": profile.name, "line_type": profile.line_type,
            "review_mode": profile.review_mode, "description": profile.description, "active": profile.active,
            "dimensions": [{
                "id": d.id, "dimension_code": d.dimension_code, "name": d.name, "weight": d.weight,
                "metric": (d.source_config or {}).get("metric", "manual"), "evidence_required": d.evidence_required,
                "sort": d.sort, "active": d.active,
            } for d in dimensions],
        })
    return ok(output, total=len(output))


@router.get("/api/admin/performance/metric-definitions")
def list_bplus_metric_definitions(db: Session = Depends(get_db), _=Depends(require_perm("performance_external", "view"))):
    """列出矩阵角色规则实际引用的指标及取数方式。

    外部原数据页不能只展示已经录入的事实，还必须明确哪些指标来自系统、哪些
    指标需要人工录入或由 CIO 评分。指标定义从当前角色档案维度实时汇总，避免
    页面与实际生效规则再次分叉。
    """
    from app.services.perf_bplus import METRIC_DEFINITIONS

    profiles = db.query(PerformanceRoleProfile).filter(
        PerformanceRoleProfile.is_deleted.is_(False), PerformanceRoleProfile.active.is_(True)
    ).order_by(PerformanceRoleProfile.role_code).all()
    profile_map = {profile.id: profile for profile in profiles}
    dimensions = db.query(PerformanceRoleDimension).filter(
        PerformanceRoleDimension.profile_id.in_(list(profile_map) or ["-"]),
        PerformanceRoleDimension.is_deleted.is_(False), PerformanceRoleDimension.active.is_(True),
    ).order_by(PerformanceRoleDimension.sort).all()
    used_by: dict[str, list[dict]] = {}
    for dimension in dimensions:
        profile = profile_map.get(dimension.profile_id)
        if not profile:
            continue
        metric = (dimension.source_config or {}).get("metric", dimension.dimension_code)
        used_by.setdefault(metric, []).append({
            "role_code": profile.role_code,
            "role_name": profile.name,
            "dimension_code": dimension.dimension_code,
            "dimension_name": dimension.name,
            "weight": dimension.weight,
        })

    rows = []
    # 仅返回当前矩阵角色规则引用的指标；显式补充复合满意度实际需要录入的外部指标。
    metric_codes = set(used_by) | {"external_business_satisfaction"}
    for metric_code in sorted(metric_codes):
        references = used_by.get(metric_code, [])
        # 复合满意度指标内部包含外部业务满意度；把这条依赖也展示出来，
        # 让录入人员知道为何该原数据会影响多个角色维度。
        if metric_code in {"external_business_satisfaction", "business_value_confirmation"} and not references:
            references = used_by.get("internal_external_satisfaction", [])
        definition = METRIC_DEFINITIONS.get(metric_code, {})
        rows.append({
            "metric_code": metric_code,
            "name": definition.get("name") or metric_code,
            "source_type": definition.get("source_type", "manual"),
            "collection_mode": definition.get("collection_mode", "manual_review"),
            "description": definition.get("description", "需由评审人按证据人工核定"),
            "input_allowed": metric_code in EXTERNAL_INPUT_METRICS,
            "references": references,
        })
    rows.sort(key=lambda row: (row["source_type"] != "external", row["metric_code"]))
    return ok(rows, total=len(rows))


@router.get("/api/admin/performance/contribution-rules")
def list_contribution_rules(db: Session = Depends(get_db), _=Depends(require_perm("performance_admin", "view"))):
    """返回 CIO/系统管理员可维护的团队贡献和满意度组合规则。"""
    return ok(get_contribution_config(db))


@router.put("/api/admin/performance/contribution-rules")
def update_contribution_rules(body: ContributionRulesIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance_admin", "edit"))):
    _validate_contribution_rules(body)
    row = db.query(PerformanceContributionConfig).filter(
        PerformanceContributionConfig.is_deleted.is_(False)
    ).order_by(PerformanceContributionConfig.updated_at.desc()).first()
    if not row:
        row = PerformanceContributionConfig()
        db.add(row)
    row.weights = body.weights
    row.targets = body.targets
    row.internal_satisfaction_weight = body.internal_satisfaction_weight
    row.external_satisfaction_weight = body.external_satisfaction_weight
    row.updated_by = user.id
    db.flush()
    audit(db, "performance_contribution_config", row.id, "update", user, body.model_dump())
    db.commit()
    return ok(get_contribution_config(db))


@router.patch("/api/admin/performance/role-profiles/{profile_id}")
def update_bplus_role_profile(profile_id: str, body: RoleProfileUpdate, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance_admin", "edit"))):
    profile = db.get(PerformanceRoleProfile, profile_id)
    if not profile or profile.is_deleted:
        raise AppError("NOT_FOUND", "绩效角色档案不存在", 404)
    if profile.role_code == "it_pmo" and body.review_mode == "manager_review":
        raise AppError("INVALID_REVIEW_MODE", "IT PMO 角色必须由 CIO 直评", 422)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    audit(db, "performance_role_profile", profile.id, "update", user, body.model_dump(exclude_unset=True))
    db.commit()
    return ok({"id": profile.id, "role_code": profile.role_code, "name": profile.name, "review_mode": profile.review_mode})


@router.put("/api/admin/performance/role-profiles/{profile_id}/dimensions")
def replace_bplus_role_dimensions(profile_id: str, body: RoleDimensionsUpdate, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance_admin", "edit"))):
    profile = db.get(PerformanceRoleProfile, profile_id)
    if not profile or profile.is_deleted:
        raise AppError("NOT_FOUND", "绩效角色档案不存在", 404)
    if len({item.dimension_code for item in body.dimensions}) != len(body.dimensions):
        raise AppError("DUPLICATE_DIMENSION", "同一角色维度只能配置一次", 422)
    if round(sum(item.weight for item in body.dimensions), 4) != 100:
        raise AppError("INVALID_DIMENSION_WEIGHT", "角色启用维度权重合计必须为 100", 422)
    for old in db.query(PerformanceRoleDimension).filter(PerformanceRoleDimension.profile_id == profile.id).all():
        old.is_deleted = True
    for item in body.dimensions:
        db.add(PerformanceRoleDimension(
            profile_id=profile.id, dimension_code=item.dimension_code, name=item.name, weight=item.weight,
            source_config={"metric": item.metric}, evidence_required=item.evidence_required,
            sort=item.sort, active=item.active,
        ))
    audit(db, "performance_role_profile", profile.id, "replace_dimensions", user, {"count": len(body.dimensions)})
    db.commit()
    return ok({"profile_id": profile.id, "weight_total": 100})


@router.get("/api/admin/performance/assignments")
def list_bplus_assignments(period: str = "", db: Session = Depends(get_db), _=Depends(require_perm("performance_admin", "view"))):
    period = _valid_bplus_period(period or current_period())
    period_row = latest_period(db, period)
    if not period_row:
        recompute_bplus(db, period)
        db.commit()
        period_row = latest_period(db, period)
    members = {
        m.id: m.name for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False)).all()
    }
    profiles = _profiles_for_admin(db)
    assignments = db.query(PerformanceRoleAssignment).filter(
        PerformanceRoleAssignment.period_id == period_row.id,
        PerformanceRoleAssignment.is_deleted.is_(False),
    ).order_by(PerformanceRoleAssignment.person_id, PerformanceRoleAssignment.role_code).all()
    return ok({
        "period": period, "version": period_row.version, "status": period_row.status,
        "assignments": [{
            "assignment_id": item.id, "person_id": item.person_id, "person_name": members.get(item.person_id, ""),
            "role_code": item.role_code, "role_name": profiles.get(item.role_code, {}).get("name", item.role_code),
            "line_type": item.line_type, "role_weight": item.role_weight,
            "evaluator_ids": item.evaluator_ids or [], "evaluator_weights": item.evaluator_weights or {}, "review_scope": item.review_scope or {},
            "review_mode": item.review_mode,
        } for item in assignments],
    }, total=len(assignments))


def _profiles_for_admin(db: Session) -> dict[str, dict]:
    return {
        item.role_code: {"name": item.name}
        for item in db.query(PerformanceRoleProfile).filter(PerformanceRoleProfile.is_deleted.is_(False)).all()
    }


@router.put("/api/admin/performance/assignments")
def update_bplus_assignments(body: AssignmentBatchUpdate, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance_admin", "edit"))):
    period_code = _valid_bplus_period(body.period)
    period = latest_period(db, period_code)
    if not period:
        raise AppError("NOT_FOUND", "绩效周期不存在，请先执行重新取数", 404)
    if period.status in {"published", "locked"}:
        raise AppError("PERFORMANCE_LOCKED", "已发布/锁定周期不能修改角色配置，请先生成新版本", 409)
    if len({item.assignment_id for item in body.assignments}) != len(body.assignments):
        raise AppError("DUPLICATE_ASSIGNMENT", "同一角色快照不能重复提交", 422)
    current = db.query(PerformanceRoleAssignment).filter(
        PerformanceRoleAssignment.period_id == period.id,
        PerformanceRoleAssignment.person_id == body.person_id,
        PerformanceRoleAssignment.is_deleted.is_(False),
    ).all()
    current_map = {item.id: item for item in current}
    if set(current_map) != {item.assignment_id for item in body.assignments}:
        raise AppError("ASSIGNMENT_SET_MISMATCH", "必须一次提交该人员全部角色配置", 422)
    if round(sum(item.role_weight for item in body.assignments), 4) != 80:
        raise AppError("INVALID_ROLE_WEIGHT", "业务角色与专业角色权重合计必须为 80", 422)
    for item in body.assignments:
        assignment = current_map[item.assignment_id]
        before = {"role_weight": assignment.role_weight, "evaluator_ids": assignment.evaluator_ids or [], "evaluator_weights": assignment.evaluator_weights or {}}
        if item.evaluator_ids is not None:
            if assignment.role_code == "it_pm" and any(not is_pmo_person(db, evaluator_id) for evaluator_id in item.evaluator_ids):
                raise AppError("INVALID_EVALUATOR", "IT 项目经理角色只能由 IT PMO 负责人初评", 422)
            if assignment.review_mode == "cio_direct" and item.evaluator_ids:
                raise AppError("INVALID_EVALUATOR", "CIO 直评角色不能配置普通负责人", 422)
            for evaluator_id in item.evaluator_ids:
                if evaluator_id == body.person_id:
                    raise AppError("SELF_REVIEW_FORBIDDEN", "评分主体不能是被评价人本人", 422)
                evaluator = db.get(OrgMember, evaluator_id)
                if not evaluator or evaluator.is_deleted:
                    raise AppError("NOT_FOUND", "评分主体人员不存在", 404)
            assignment.evaluator_ids = item.evaluator_ids
            if item.evaluator_weights is not None:
                if set(item.evaluator_weights) != set(item.evaluator_ids):
                    raise AppError("INVALID_EVALUATOR_WEIGHT", "评审人权重必须覆盖全部评审人", 422)
                if any(weight <= 0 for weight in item.evaluator_weights.values()) or abs(sum(item.evaluator_weights.values()) - 100) > 0.01:
                    raise AppError("INVALID_EVALUATOR_WEIGHT", "评审人权重必须为正数且合计 100%", 422)
                assignment.evaluator_weights = item.evaluator_weights
            else:
                from app.services.perf_bplus import _uniform_evaluator_weights
                assignment.evaluator_weights = _uniform_evaluator_weights(item.evaluator_ids)
            scope = dict(assignment.review_scope or {})
            scope["evaluator_ids"] = item.evaluator_ids
            assignment.review_scope = scope
        assignment.role_weight = item.role_weight
        db.add(PerformanceReviewAction(
            period_id=period.id, assignment_id=assignment.id, actor_id=user.id, stage="draft", action="assignment_updated",
            before_value=before, after_value={"role_weight": assignment.role_weight, "evaluator_ids": assignment.evaluator_ids or [], "evaluator_weights": assignment.evaluator_weights or {}},
            reason="CIO 调整周期角色权重/评分主体",
        ))
    period.role_snapshot = {**(period.role_snapshot or {}), "assignments": [
        {"assignment_id": item.id, "person_id": item.person_id, "role_code": item.role_code, "role_weight": item.role_weight,
         "evaluator_ids": item.evaluator_ids or [], "evaluator_weights": item.evaluator_weights or {}, "review_scope": item.review_scope or {}}
        for item in current
    ]}
    period.updated_by = user.id
    db.commit()
    return ok({"period": period.period_code, "person_id": body.person_id, "role_weight_total": 80})


def _bplus_row(period: PerformancePeriod, row: PerformanceRoleAssignment, profile: PerformanceRoleProfile, dims: list, components: dict):
    values = []
    for dimension in dims:
        component = components.get(dimension.dimension_code)
        values.append({
            "code": dimension.dimension_code, "name": dimension.name, "weight": dimension.weight,
            "system_score": component.system_score if component else None,
            "business_manager_score": component.business_manager_score if component else None,
            "professional_manager_score": component.professional_manager_score if component else None,
            "cio_score": component.cio_score if component else None,
            "manager_scores": component.manager_scores if component else {},
            "manager_reasons": component.manager_reasons if component else {},
            "manager_evidence_refs": component.manager_evidence_refs if component else {},
            "effective_score": component.effective_score if component else None,
            "reason": component.reason if component else None,
            "evidence_refs": component.evidence_refs if component else [],
        })
    return {
        "assignment_id": row.id, "person_id": row.person_id, "role_code": row.role_code,
        "role_name": profile.name, "line_type": row.line_type, "role_weight": row.role_weight,
        "review_mode": row.review_mode, "review_scope": row.review_scope or {},
        "evaluator_ids": row.evaluator_ids or [], "evaluator_weights": row.evaluator_weights or {}, "dimensions": values,
    }


@router.get("/api/admin/performance/reviews")
def list_bplus_reviews(period: str = "", db: Session = Depends(get_db), _=Depends(require_perm("performance_review", "view"))):
    period = _valid_bplus_period(period or current_period())
    period_row = latest_period(db, period)
    if not period_row:
        recompute_bplus(db, period)
        db.commit()
        period_row = latest_period(db, period)
    result = build_internal_result(db, period_row)
    return ok({**result, "review_details": True})


@router.get("/api/admin/performance/reviews/person/{person_id}")
def get_bplus_review_person(person_id: str, period: str = "", db: Session = Depends(get_db), _=Depends(require_perm("performance_review", "view"))):
    """返回单个员工的完整评审详情，供员工级评审页面使用。"""
    period = _valid_bplus_period(period or current_period())
    period_row = latest_period(db, period)
    if not period_row:
        recompute_bplus(db, period)
        db.commit()
        period_row = latest_period(db, period)
    result = build_internal_result(db, period_row)
    row = next((item for item in result["rows"] if item["person_id"] == person_id), None)
    if not row:
        raise AppError("NOT_FOUND", "该员工在当前考核周期没有评审记录", 404)
    return ok({
        "period": result["period"], "version": result["version"], "status": result["status"],
        "row": row, "review_details": True,
    })


@router.post("/api/admin/performance/{period}/recompute")
def recompute_bplus_endpoint(period: str, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance_admin", "edit"))):
    period = _valid_bplus_period(period)
    result = recompute_bplus(db, period, user.id)
    db.commit()
    return ok(result)


@router.put("/api/admin/performance/reviews/{assignment_id}/components/{dimension_code}")
def update_bplus_component(
    assignment_id: str,
    dimension_code: str,
    body: BplusScoreIn,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_perm("performance_review", "edit")),
):
    assignment = db.get(PerformanceRoleAssignment, assignment_id)
    if not assignment or assignment.is_deleted:
        raise AppError("NOT_FOUND", "绩效角色快照不存在", 404)
    period = db.get(PerformancePeriod, assignment.period_id)
    if not period or period.status in {"published", "locked"}:
        raise AppError("PERFORMANCE_LOCKED", "已发布/锁定周期不能直接修改，请先生成新版本")
    result = apply_review(db, period, assignment_id, dimension_code, body.score, body.reason, body.evidence_refs, user)
    db.commit()
    return ok(result)


@router.post("/api/admin/performance/{period}/submit-manager-review")
def submit_manager_review(period: str, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance_review", "edit"))):
    period = _valid_bplus_period(period)
    row = latest_period(db, period)
    if not row:
        raise AppError("NOT_FOUND", "绩效周期不存在", 404)
    if row.status in {"published", "locked"}:
        raise AppError("PERFORMANCE_LOCKED", "已发布/锁定周期不能提交", 409)
    row.status = "manager_review"
    row.updated_by = user.id
    db.commit()
    return ok({"period": period, "status": row.status})


@router.post("/api/admin/performance/{period}/submit-cio-review")
def submit_cio_review(period: str, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance_admin", "edit"))):
    period = _valid_bplus_period(period)
    row = latest_period(db, period)
    if not row:
        raise AppError("NOT_FOUND", "绩效周期不存在", 404)
    row.status = "cio_review"
    row.updated_by = user.id
    db.commit()
    return ok({"period": period, "status": row.status})


@router.post("/api/admin/performance/{period}/publish")
def publish_bplus_endpoint(period: str, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance_admin", "edit"))):
    period = _valid_bplus_period(period)
    row = latest_period(db, period)
    if not row:
        raise AppError("NOT_FOUND", "绩效周期不存在", 404)
    return ok(publish_period(db, row, user))


@router.post("/api/admin/performance/{period}/unlock")
def unlock_bplus_endpoint(period: str, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance_admin", "edit"))):
    period = _valid_bplus_period(period)
    row = latest_period(db, period)
    if not row:
        raise AppError("NOT_FOUND", "绩效周期不存在", 404)
    new_period = unlock_period(db, row, user)
    return ok({"period": new_period.period_code, "version": new_period.version, "status": new_period.status})


@router.get("/api/admin/performance/external-inputs")
def list_external_inputs(period: str = "", db: Session = Depends(get_db), _=Depends(require_perm("performance_external", "view"))):
    period = _valid_bplus_period(period or current_period())
    row = latest_period(db, period)
    if not row:
        return ok([], total=0)
    inputs = db.query(PerformanceExternalInput).filter(
        PerformanceExternalInput.period_id == row.id, PerformanceExternalInput.is_deleted.is_(False)
    ).order_by(PerformanceExternalInput.created_at.desc()).all()
    member_names = {member.id: member.name for member in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False)).all()}
    domain_names = {domain.id: domain.name for domain in db.query(BusinessDomain).filter(BusinessDomain.is_deleted.is_(False)).all()}
    return ok([{
        "id": item.id, "period": period, "metric_code": item.metric_code, "target_type": item.target_type,
        "target_id": item.target_id,
        "target_name": (domain_names if item.target_type in {"business_domain", "domain"} else member_names).get(item.target_id),
        "evaluator_name": item.evaluator_name,
        "evaluator_department": item.evaluator_department, "raw_score": item.raw_score,
        "raw_scale": item.raw_scale, "normalized_score": item.normalized_score,
        "comment": item.comment, "evidence_refs": item.evidence_refs or [], "status": item.status,
        "version": item.version, "created_at": item.created_at,
    } for item in inputs], total=len(inputs))


@router.post("/api/admin/performance/external-inputs")
def create_external_input(body: ExternalInputIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance_external", "create"))):
    period = _valid_bplus_period(body.period)
    _validate_external_metric(body.metric_code)
    if body.raw_score > body.raw_scale:
        raise AppError("INVALID_EXTERNAL_SCORE", "原始评分不能超过原始量表", 422)
    _validate_external_target(db, body.target_type, body.target_id)
    period_row = get_or_create_period(db, period, user.id)
    if period_row.status in {"published", "locked"}:
        raise AppError("PERFORMANCE_LOCKED", "已发布/锁定周期不能直接录入，请先生成新版本")
    row = PerformanceExternalInput(
        period_id=period_row.id, metric_code=body.metric_code, target_type=body.target_type, target_id=body.target_id,
        evaluator_name=body.evaluator_name, evaluator_department=body.evaluator_department,
        raw_score=body.raw_score, raw_scale=body.raw_scale,
        normalized_score=round(body.raw_score / body.raw_scale * 100, 1), comment=body.comment,
        evidence_refs=body.evidence_refs, inputter_id=user.id, status=body.status,
        locked_at=datetime.now() if body.status == "locked" else None,
    )
    db.add(row)
    period_row.status = "external_input"
    period_row.updated_by = user.id
    db.commit()
    return ok({"id": row.id, "normalized_score": row.normalized_score, "status": row.status})


@router.patch("/api/admin/performance/external-inputs/{input_id}")
def update_external_input(input_id: str, body: ExternalInputIn, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance_external", "edit"))):
    row = db.get(PerformanceExternalInput, input_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "外部原数据不存在", 404)
    if row.status == "locked":
        raise AppError("EXTERNAL_INPUT_LOCKED", "外部原数据已锁定，只能生成修订版本", 409)
    _validate_external_metric(body.metric_code)
    if body.raw_score > body.raw_scale:
        raise AppError("INVALID_EXTERNAL_SCORE", "原始评分不能超过原始量表", 422)
    _validate_external_target(db, body.target_type, body.target_id)
    for key in ("metric_code", "target_type", "target_id", "evaluator_name", "evaluator_department", "raw_score", "raw_scale", "comment", "evidence_refs", "status"):
        setattr(row, key, getattr(body, key))
    row.normalized_score = round(body.raw_score / body.raw_scale * 100, 1)
    row.inputter_id = user.id
    row.locked_at = datetime.now() if body.status == "locked" else None
    db.commit()
    return ok({"id": row.id, "normalized_score": row.normalized_score, "status": row.status})


@router.delete("/api/admin/performance/external-inputs/{input_id}")
def delete_external_input(input_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance_external", "delete"))):
    row = db.get(PerformanceExternalInput, input_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "外部原数据不存在", 404)
    if row.status == "locked":
        raise AppError("EXTERNAL_INPUT_LOCKED", "外部原数据已锁定，只能生成修订版本", 409)
    row.is_deleted = True
    db.commit()
    return ok({"id": row.id, "deleted": True})


@router.get("/api/my/performance")
def my_bplus_performance(period: str = "", db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("performance_result", "view"))):
    period = _valid_bplus_period(period or current_period())
    row = latest_period(db, period)
    if not row or row.status not in {"published", "locked"} or not user.person_id:
        return ok({"period": period, "status": row.status if row else "unpublished", "published": False, "result": None})
    score = db.query(PerformanceScore).filter(
        PerformanceScore.period_id == row.id,
        PerformanceScore.person_id == user.person_id,
        PerformanceScore.is_deleted.is_(False),
    ).first()
    if not score:
        return ok({"period": period, "status": row.status, "published": False, "result": None})
    return ok({
        "period": period, "version": row.version, "status": row.status, "published": True,
        "result": {
            "business_role_score": score.business_role_score, "professional_role_score": score.professional_role_score,
            "team_contribution_score": score.team_contribution_score, "regular_score": score.regular_score,
            "bonus": score.bonus, "penalty": score.penalty, "published_score": score.published_score,
            "roles": [{"role_code": r.get("role_code"), "role_name": r.get("role_name"), "role_score": r.get("role_score"), "role_weight": r.get("role_weight")} for r in (score.detail or {}).get("roles", [])],
        },
    })
