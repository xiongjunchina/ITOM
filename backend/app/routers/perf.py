"""人效评分（M6.1）：计分规则（方案 CRUD）+ 依规则自动计算的团队总览。

权限：performance.view 查看；performance.edit 管理方案（默认仅 admin/cio）。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import require_perm
from app.models import AuthUser, PerfScheme, Position
from app.schemas.common import ok
from app.services.audit import audit
from app.services.perf import DIMENSION_CODES, DIMENSIONS, compute_performance
from app.services.points import current_period

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
    period = period or current_period()
    if "-H" not in period:
        raise AppError("INVALID_PERIOD", "考核期格式应为 YYYY-H1 / YYYY-H2")
    return ok(compute_performance(db, period))
