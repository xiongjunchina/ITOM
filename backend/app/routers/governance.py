"""轻量治理记录接口（P0）。

ITOM 只记录线下 DMC/授权决策结果，不承载在线投票或替代 DMC 的决策流程。
"""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.deps import get_current_user
from app.db import get_db
from app.models import AuthUser, DmcDecisionRecord, OrgMember, Project, Requirement
from app.schemas.common import ok
from app.services.audit import audit
from app.services.permissions import has_perm
from app.services.rbac import effective_roles
from app.services.requirement_scoring import decision_level_for_amount

router = APIRouter(prefix="/api/governance", tags=["governance"])


class DmcDecisionCreate(BaseModel):
    entity_type: str = Field(pattern="^(requirement|project)$")
    entity_id: str
    decision_level: str | None = Field(default=None, pattern="^(digital_leader|eason|dmc)$")
    decision: str = Field(pattern="^(approved|conditional|hold|rejected)$")
    amount_cny: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    budget_source: str | None = Field(default=None, max_length=64)
    conditions: str | None = Field(default=None, max_length=2000)
    decision_date: date | None = None
    meeting_reference: str | None = Field(default=None, max_length=200)
    owner_id: str | None = None
    deadline: date | None = None
    check_at: date | None = None
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    note: str | None = Field(default=None, max_length=2000)


def _can_manage(db: Session, user: AuthUser, entity_type: str) -> bool:
    if "admin" in effective_roles(db, user):
        return True
    return has_perm(db, user, f"{entity_type}s", "edit")


def _can_view(db: Session, user: AuthUser, entity_type: str) -> bool:
    if "admin" in effective_roles(db, user):
        return True
    return has_perm(db, user, f"{entity_type}s", "view")


def _ensure_entity(db: Session, entity_type: str, entity_id: str):
    model = Requirement if entity_type == "requirement" else Project
    entity = db.get(model, entity_id)
    if not entity or entity.is_deleted:
        raise AppError("NOT_FOUND", f"{entity_type} 不存在", 404)
    return entity


def _row(row: DmcDecisionRecord) -> dict:
    return {
        "id": row.id,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "decision_level": row.decision_level,
        "decision": row.decision,
        "amount_cny": row.amount_cny,
        "budget_source": row.budget_source,
        "conditions": row.conditions,
        "decision_date": row.decision_date,
        "meeting_reference": row.meeting_reference,
        "owner_id": row.owner_id,
        "deadline": row.deadline,
        "check_at": row.check_at,
        "recorded_by": row.recorded_by,
        "recorded_at": row.recorded_at,
        "evidence_refs": row.evidence_refs or [],
        "note": row.note,
    }


@router.post("/dmc-decisions")
def create_dmc_decision(
    body: DmcDecisionCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    if not _can_manage(db, user, body.entity_type):
        raise AppError("FORBIDDEN", "无权记录该对象的治理决策", 403)
    _ensure_entity(db, body.entity_type, body.entity_id)
    if body.owner_id and not db.get(OrgMember, body.owner_id):
        raise AppError("NOT_FOUND", "决议跟进责任人不存在", 404)
    level = body.decision_level or decision_level_for_amount(body.amount_cny) or "digital_leader"
    row = DmcDecisionRecord(
        **body.model_dump(exclude={"decision_level"}),
        decision_level=level,
        recorded_by=user.id,
    )
    db.add(row)
    db.flush()
    audit(db, "dmc_decision_record", row.id, "create", user, {
        "entity_type": body.entity_type, "entity_id": body.entity_id,
        "decision_level": level, "decision": body.decision,
    })
    db.commit()
    return ok(_row(row))


@router.get("/dmc-decisions")
def list_dmc_decisions(
    entity_type: str = Query(..., pattern="^(requirement|project)$"),
    entity_id: str = Query(...),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    if not _can_view(db, user, entity_type):
        raise AppError("FORBIDDEN", "无权查看该对象的治理决策", 403)
    _ensure_entity(db, entity_type, entity_id)
    rows = db.query(DmcDecisionRecord).filter(
        DmcDecisionRecord.entity_type == entity_type,
        DmcDecisionRecord.entity_id == entity_id,
        DmcDecisionRecord.is_deleted.is_(False),
    ).order_by(DmcDecisionRecord.decision_date.desc(), DmcDecisionRecord.created_at.desc()).all()
    return ok([_row(row) for row in rows], total=len(rows))
