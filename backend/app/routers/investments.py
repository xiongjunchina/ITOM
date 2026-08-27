"""B-OPS 统一 IT 投入台账 API。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_not_example
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import (
    AuthUser,
    InvestmentAllocation,
    InvestmentBudgetItem,
    InvestmentCostEntry,
    InvestmentWorklog,
    OrgMember,
    WbsTask,
)
from app.schemas.common import ok, paginate
from app.services.audit import audit
from app.services.investment import (
    ACTIVITY_TYPES,
    COST_CATEGORIES,
    ROLE_TYPES,
    allocation_total,
    money,
    subject_references,
    summary,
    validate_allocation_source,
    validate_dimensions,
    validate_subject,
    validate_wbs,
)
from app.services.permissions import TICKET_TYPE_MODULE, has_perm
from app.services.requirement_access import can_view_requirement
from app.services.rbac import effective_roles
from app.services.team_scope import require_it_member_if_configured


router = APIRouter(prefix="/api/investments", tags=["investments"])


class SubjectIn(BaseModel):
    subject_type: str
    subject_id: str | None = None
    lifecycle_stage: str | None = None
    investment_intent: str | None = None


class BudgetIn(SubjectIn):
    period_start: date
    period_end: date
    category: str
    cost_nature: Literal["capex", "opex"] = "opex"
    name: str = Field(min_length=1, max_length=128)
    amount_cny: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_end < self.period_start:
            raise ValueError("预算结束日期不能早于开始日期")
        if self.category not in COST_CATEGORIES:
            raise ValueError("费用分类无效")
        return self


class CostIn(SubjectIn):
    recognition_date: date
    amount_cny: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    cost_status: Literal["committed", "incurred", "paid"] = "incurred"
    category: str
    cost_nature: Literal["capex", "opex"] = "opex"
    labor_nature: Literal["none", "internal", "external", "unclassified"] = "none"
    recurrence: Literal["one_time", "recurring"] = "one_time"
    activity_type: str | None = None
    wbs_task_id: str | None = None
    supplier_snapshot: str | None = Field(default=None, max_length=128)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_cost(self):
        if self.category not in COST_CATEGORIES:
            raise ValueError("费用分类无效")
        if self.activity_type and self.activity_type not in ACTIVITY_TYPES:
            raise ValueError("运维活动类型无效")
        if self.cost_status in {"incurred", "paid"} and self.recognition_date > date.today():
            raise ValueError("已发生或已支付费用不能使用未来日期")
        if self.category == "labor" and self.labor_nature == "none":
            self.labor_nature = "unclassified"
        if self.category != "labor" and self.labor_nature != "none":
            raise ValueError("非人力费用不能设置人力性质")
        return self


class WorklogIn(SubjectIn):
    person_id: str
    work_date: date
    effort_days: Decimal = Field(gt=0, le=2, max_digits=8, decimal_places=2)
    role_type: str
    activity_type: str
    standard_rate_cny_per_day: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    wbs_task_id: str | None = None
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_worklog(self):
        if self.work_date > date.today():
            raise ValueError("实际工时不能登记未来日期")
        if self.role_type not in ROLE_TYPES:
            raise ValueError("投入角色类型无效")
        if self.activity_type not in ACTIVITY_TYPES:
            raise ValueError("投入活动类型无效")
        return self


class AllocationIn(BaseModel):
    source_kind: Literal["budget", "cost", "worklog"]
    source_id: str
    target_type: str
    target_id: str
    percentage: Decimal = Field(gt=0, le=100, max_digits=5, decimal_places=2)
    allocation_method: Literal["manual_percentage", "direct"] = "manual_percentage"
    note: str | None = Field(default=None, max_length=500)


SUBJECT_MODULES = {
    "project": "projects",
    "requirement": "requirements",
    "service_item": "catalog",
    "ci": "cmdb",
    "problem": "problems",
    "contract": "contracts",
    "business_domain": "admin_business_domains",
    "work_task": "task_delegated",
}


def _require_subject_view(db: Session, actor: AuthUser, subject_type: str, subject_id: str | None):
    row = validate_subject(db, subject_type, subject_id)
    if subject_type == "ticket":
        module = TICKET_TYPE_MODULE.get(row.ticket_type, "ticket_sr")
        if not has_perm(db, actor, module, "view"):
            raise AppError("FORBIDDEN", "无权查看该工单投入", 403)
        roles = effective_roles(db, actor)
        if roles and roles.issubset({"requester", "bdo"}) and row.submitter != actor.id:
            raise AppError("FORBIDDEN", "无权查看该工单投入", 403)
    elif subject_type == "requirement":
        if not has_perm(db, actor, "requirements", "view") or not can_view_requirement(db, actor, row):
            raise AppError("FORBIDDEN", "无权查看该需求投入", 403)
    elif subject_type == "shared_operations":
        if not has_perm(db, actor, "reports", "view"):
            raise AppError("FORBIDDEN", "无权查看共享运维投入", 403)
    else:
        module = SUBJECT_MODULES.get(subject_type)
        if module and not has_perm(db, actor, module, "view"):
            raise AppError("FORBIDDEN", "无权查看该投入归属对象", 403)
    return row


def _subject_params(subject_type: str, subject_id: str | None) -> dict:
    return {"subject_type": subject_type, "subject_id": subject_id}


def _person_names(db: Session, rows) -> dict[str, str]:
    ids = {row.person_id for row in rows}
    if not ids:
        return {}
    return {row.id: row.name for row in db.query(OrgMember).filter(OrgMember.id.in_(ids)).all()}


@router.get("/summary")
def get_summary(
    subject_type: str = "",
    subject_id: str = "",
    lifecycle_stage: str = "",
    period_start: date | None = None,
    period_end: date | None = None,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(get_current_user),
):
    if subject_type:
        _require_subject_view(db, actor, subject_type, subject_id or None)
    elif not has_perm(db, actor, "reports", "view"):
        raise AppError("FORBIDDEN", "无权查看投入汇总", 403)
    can_finance = has_perm(db, actor, "reports_finance", "view")
    can_people = has_perm(db, actor, "reports_people", "view")
    if not can_finance and not can_people:
        raise AppError("INVESTMENT_SUMMARY_FORBIDDEN", "缺少财务或人员投入查看权限", 403)
    data = summary(
        db, subject_type=subject_type or None, subject_id=subject_id or None,
        lifecycle_stage=lifecycle_stage or None, period_start=period_start, period_end=period_end,
    )
    if not can_finance:
        for key in (
            "budget_cny", "committed_cost_cny", "incurred_cost_cny", "paid_cost_cny",
            "effort_cost_cny", "management_total_cny", "unclassified_labor_cny",
            "financial_budget_execution_rate", "management_budget_execution_rate",
            "budget_execution_rate", "categories",
        ):
            data[key] = None if key != "categories" else []
    if not can_people:
        data["effort_days"] = None
        data["activity_effort"] = []
        data["quality"]["worklogs_with_rate"] = None
        data["quality"]["worklog_count"] = None
    return ok(data)


@router.get("/budgets")
def list_budgets(
    subject_type: str,
    subject_id: str = "",
    page: int = 1,
    page_size: int = 200,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("reports_finance", "view")),
):
    _require_subject_view(db, actor, subject_type, subject_id or None)
    query = db.query(InvestmentBudgetItem).filter(
        InvestmentBudgetItem.is_deleted.is_(False),
        InvestmentBudgetItem.subject_type == subject_type,
        InvestmentBudgetItem.subject_id == (subject_id or None),
    ).order_by(InvestmentBudgetItem.period_start.desc(), InvestmentBudgetItem.created_at.desc())
    rows, total = paginate(query, page, page_size)
    return ok([{
        "id": row.id, "lifecycle_stage": row.lifecycle_stage,
        "investment_intent": row.investment_intent, "subject_type": row.subject_type,
        "subject_id": row.subject_id, "period_start": row.period_start, "period_end": row.period_end,
        "category": row.category, "cost_nature": row.cost_nature, "name": row.name,
        "amount_cny": money(row.amount_cny), "note": row.note,
    } for row in rows], total=total)


@router.post("/budgets")
def create_budget(
    body: BudgetIn,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("investment_costs", "create")),
):
    subject = _require_subject_view(db, actor, body.subject_type, body.subject_id)
    if subject is not None:
        ensure_not_example(subject)
    lifecycle, intent = validate_dimensions(body.subject_type, body.lifecycle_stage, body.investment_intent)
    row = InvestmentBudgetItem(
        **body.model_dump(exclude={"lifecycle_stage", "investment_intent"}),
        lifecycle_stage=lifecycle, investment_intent=intent, created_by=actor.id,
    )
    db.add(row)
    db.flush()
    audit(db, "investment_budget_item", row.id, "create", actor, {
        "subject_type": row.subject_type, "category": row.category, "amount_cny": money(row.amount_cny),
    })
    db.commit()
    return ok({"id": row.id})


@router.get("/costs")
def list_costs(
    subject_type: str,
    subject_id: str = "",
    page: int = 1,
    page_size: int = 200,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("reports_finance", "view")),
):
    _require_subject_view(db, actor, subject_type, subject_id or None)
    query = db.query(InvestmentCostEntry).filter(
        InvestmentCostEntry.is_deleted.is_(False), InvestmentCostEntry.subject_type == subject_type,
        InvestmentCostEntry.subject_id == (subject_id or None),
    ).order_by(InvestmentCostEntry.recognition_date.desc(), InvestmentCostEntry.created_at.desc())
    rows, total = paginate(query, page, page_size)
    return ok([{
        "id": row.id, "lifecycle_stage": row.lifecycle_stage, "investment_intent": row.investment_intent,
        "subject_type": row.subject_type, "subject_id": row.subject_id,
        "recognition_date": row.recognition_date, "amount_cny": money(row.amount_cny),
        "cost_status": row.cost_status, "category": row.category, "cost_nature": row.cost_nature,
        "labor_nature": row.labor_nature, "recurrence": row.recurrence,
        "activity_type": row.activity_type, "wbs_task_id": row.wbs_task_id,
        "supplier_snapshot": row.supplier_snapshot, "note": row.note,
    } for row in rows], total=total)


@router.post("/costs")
def create_cost(
    body: CostIn,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("investment_costs", "create")),
):
    subject = _require_subject_view(db, actor, body.subject_type, body.subject_id)
    if subject is not None:
        ensure_not_example(subject)
    lifecycle, intent = validate_dimensions(body.subject_type, body.lifecycle_stage, body.investment_intent)
    refs = subject_references(body.subject_type, subject)
    validate_wbs(db, refs["project_id"], body.wbs_task_id)
    refs["wbs_task_id"] = body.wbs_task_id
    row = InvestmentCostEntry(
        **body.model_dump(exclude={"lifecycle_stage", "investment_intent", "wbs_task_id"}),
        **refs, lifecycle_stage=lifecycle, investment_intent=intent, created_by=actor.id,
    )
    db.add(row)
    db.flush()
    audit(db, "investment_cost_entry", row.id, "create", actor, {
        "subject_type": row.subject_type, "cost_status": row.cost_status,
        "category": row.category, "amount_cny": money(row.amount_cny),
    })
    db.commit()
    return ok({"id": row.id})


@router.get("/worklogs")
def list_worklogs(
    subject_type: str,
    subject_id: str = "",
    page: int = 1,
    page_size: int = 200,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("investment_worklogs", "view")),
):
    _require_subject_view(db, actor, subject_type, subject_id or None)
    query = db.query(InvestmentWorklog).filter(
        InvestmentWorklog.is_deleted.is_(False), InvestmentWorklog.subject_type == subject_type,
        InvestmentWorklog.subject_id == (subject_id or None),
    )
    if not has_perm(db, actor, "reports_people", "view"):
        query = query.filter(InvestmentWorklog.person_id == (actor.person_id or "-"))
    query = query.order_by(InvestmentWorklog.work_date.desc(), InvestmentWorklog.created_at.desc())
    rows, total = paginate(query, page, page_size)
    names = _person_names(db, rows)
    return ok([{
        "id": row.id, "lifecycle_stage": row.lifecycle_stage, "investment_intent": row.investment_intent,
        "subject_type": row.subject_type, "subject_id": row.subject_id, "person_id": row.person_id,
        "person_name": names.get(row.person_id), "work_date": row.work_date,
        "effort_days": money(row.effort_days), "role_type": row.role_type,
        "activity_type": row.activity_type,
        "standard_rate_cny_per_day": money(row.standard_rate_cny_per_day) if row.standard_rate_cny_per_day is not None else None,
        "wbs_task_id": row.wbs_task_id, "note": row.note,
    } for row in rows], total=total)


@router.post("/worklogs")
def create_worklog(
    body: WorklogIn,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("investment_worklogs", "create")),
):
    subject = _require_subject_view(db, actor, body.subject_type, body.subject_id)
    if subject is not None:
        ensure_not_example(subject)
    if body.person_id != actor.person_id and not has_perm(db, actor, "investment_worklogs", "edit"):
        raise AppError("INVESTMENT_WORKLOG_PERSON_FORBIDDEN", "只能登记本人的实际工时", 403)
    require_it_member_if_configured(db, body.person_id, "投入人员")
    person = db.get(OrgMember, body.person_id)
    if not person or person.is_deleted:
        raise AppError("MEMBER_NOT_FOUND", "投入人员不存在", 404)
    existing_days = sum((
        row.effort_days for row in db.query(InvestmentWorklog).filter(
            InvestmentWorklog.person_id == body.person_id,
            InvestmentWorklog.work_date == body.work_date,
            InvestmentWorklog.is_deleted.is_(False),
        )
    ), Decimal("0"))
    if existing_days + body.effort_days > Decimal("2"):
        raise AppError("INVESTMENT_WORKLOG_DAILY_LIMIT", "同一人员单日累计投入不能超过 2 人天", 409)
    lifecycle, intent = validate_dimensions(body.subject_type, body.lifecycle_stage, body.investment_intent)
    refs = subject_references(body.subject_type, subject)
    refs = {key: value for key, value in refs.items() if hasattr(InvestmentWorklog, key)}
    validate_wbs(db, refs["project_id"], body.wbs_task_id)
    refs["wbs_task_id"] = body.wbs_task_id
    rate = body.standard_rate_cny_per_day
    if rate is None:
        from app.services.org_settings import get_org_settings

        configured = (get_org_settings(db).report_role_rates or {}).get(body.role_type)
        rate = Decimal(str(configured)) if configured is not None else None
    row = InvestmentWorklog(
        **body.model_dump(exclude={"lifecycle_stage", "investment_intent", "standard_rate_cny_per_day", "wbs_task_id"}),
        **refs, lifecycle_stage=lifecycle, investment_intent=intent,
        standard_rate_cny_per_day=rate, created_by=actor.id,
    )
    db.add(row)
    db.flush()
    audit(db, "investment_worklog", row.id, "create", actor, {
        "subject_type": row.subject_type, "effort_days": money(row.effort_days),
        "role_type": row.role_type, "activity_type": row.activity_type,
        "standard_rate_used": rate is not None,
    })
    db.commit()
    return ok({"id": row.id})


@router.get("/allocations")
def list_allocations(
    source_kind: str,
    source_id: str,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("reports_finance", "view")),
):
    source = validate_allocation_source(db, source_kind, source_id)
    _require_subject_view(db, actor, source.subject_type, source.subject_id)
    rows = db.query(InvestmentAllocation).filter(
        InvestmentAllocation.is_deleted.is_(False), InvestmentAllocation.source_kind == source_kind,
        InvestmentAllocation.source_id == source_id,
    ).order_by(InvestmentAllocation.created_at).all()
    return ok([{
        "id": row.id, "source_kind": row.source_kind, "source_id": row.source_id,
        "target_type": row.target_type, "target_id": row.target_id,
        "percentage": money(row.percentage), "allocation_method": row.allocation_method,
        "note": row.note,
    } for row in rows], total=len(rows))


@router.post("/allocations")
def create_allocation(
    body: AllocationIn,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("investment_costs", "edit")),
):
    source = validate_allocation_source(db, body.source_kind, body.source_id)
    _require_subject_view(db, actor, source.subject_type, source.subject_id)
    target = _require_subject_view(db, actor, body.target_type, body.target_id)
    if target is not None:
        ensure_not_example(target)
    if source.subject_type == body.target_type and source.subject_id == body.target_id:
        raise AppError("INVESTMENT_ALLOCATION_REDUNDANT", "直接归属记录不能再次分摊到同一对象", 409)
    if allocation_total(db, body.source_kind, body.source_id) + body.percentage > Decimal("100"):
        raise AppError("INVESTMENT_ALLOCATION_EXCEEDS_100", "同一来源的分摊比例合计不能超过 100%", 409)
    row = InvestmentAllocation(**body.model_dump(), created_by=actor.id)
    db.add(row)
    db.flush()
    audit(db, "investment_allocation", row.id, "create", actor, {
        "source_kind": row.source_kind, "target_type": row.target_type,
        "percentage": money(row.percentage),
    })
    db.commit()
    return ok({"id": row.id})


def _delete_row(db: Session, actor: AuthUser, model, row_id: str, entity_type: str):
    row = db.get(model, row_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "投入记录不存在", 404)
    _require_subject_view(db, actor, row.subject_type, row.subject_id)
    row.is_deleted = True
    audit(db, entity_type, row.id, "delete", actor)
    db.commit()
    return ok({"id": row.id})


@router.delete("/budgets/{row_id}")
def delete_budget(row_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("investment_costs", "delete"))):
    return _delete_row(db, actor, InvestmentBudgetItem, row_id, "investment_budget_item")


@router.delete("/costs/{row_id}")
def delete_cost(row_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("investment_costs", "delete"))):
    return _delete_row(db, actor, InvestmentCostEntry, row_id, "investment_cost_entry")


@router.delete("/worklogs/{row_id}")
def delete_worklog(row_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("investment_worklogs", "delete"))):
    row = db.get(InvestmentWorklog, row_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "投入记录不存在", 404)
    if row.person_id != actor.person_id and not has_perm(db, actor, "investment_worklogs", "edit"):
        raise AppError("INVESTMENT_WORKLOG_PERSON_FORBIDDEN", "只能删除本人的实际工时", 403)
    return _delete_row(db, actor, InvestmentWorklog, row_id, "investment_worklog")


@router.delete("/allocations/{row_id}")
def delete_allocation(row_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("investment_costs", "edit"))):
    row = db.get(InvestmentAllocation, row_id)
    if not row or row.is_deleted:
        raise AppError("NOT_FOUND", "分摊记录不存在", 404)
    source = validate_allocation_source(db, row.source_kind, row.source_id)
    _require_subject_view(db, actor, source.subject_type, source.subject_id)
    row.is_deleted = True
    audit(db, "investment_allocation", row.id, "delete", actor)
    db.commit()
    return ok({"id": row.id})
