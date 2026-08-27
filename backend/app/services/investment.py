"""B-OPS 统一投入领域服务。

所有汇总、项目兼容接口和报表指标都应复用本模块，避免在路由或报表层
复制金额、人天及预算执行率公式。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, TypeVar

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    BusinessDomain,
    Ci,
    Contract,
    InvestmentAllocation,
    InvestmentBudgetItem,
    InvestmentCostEntry,
    InvestmentWorklog,
    Problem,
    Project,
    Requirement,
    ServiceItem,
    Ticket,
    WorkTask,
    WbsTask,
)


LIFECYCLE_STAGES = {"demand", "build", "run"}
INVESTMENT_INTENTS = {"run", "grow", "transform"}
SUBJECT_TYPES = {
    "project", "requirement", "service_item", "ci", "ticket", "problem",
    "contract", "business_domain", "work_task", "shared_operations",
}
COST_CATEGORIES = {
    "software", "hardware", "cloud", "network", "security", "service",
    "outsourcing", "telecom", "facility", "labor", "other", "legacy",
}
COST_STATUSES = {"committed", "incurred", "paid"}
COST_NATURES = {"capex", "opex"}
LABOR_NATURES = {"none", "internal", "external", "unclassified"}
RECURRENCES = {"one_time", "recurring"}
ROLE_TYPES = {"design", "development", "testing", "implementation", "pm", "operations", "other"}
ACTIVITY_TYPES = {
    "analysis", "design", "development", "testing", "implementation", "pm",
    "incident_response", "service_request", "problem_management", "change_delivery",
    "preventive_maintenance", "monitoring", "security_operations", "asset_maintenance",
    "service_improvement", "operations_management", "other",
}

SUBJECT_MODELS = {
    "project": Project,
    "requirement": Requirement,
    "service_item": ServiceItem,
    "ci": Ci,
    "ticket": Ticket,
    "problem": Problem,
    "contract": Contract,
    "business_domain": BusinessDomain,
    "work_task": WorkTask,
}


def money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def default_lifecycle(subject_type: str) -> str:
    if subject_type == "requirement":
        return "demand"
    if subject_type == "project":
        return "build"
    return "run"


def default_intent(lifecycle_stage: str) -> str:
    return {"demand": "grow", "build": "transform", "run": "run"}[lifecycle_stage]


def validate_subject(db: Session, subject_type: str, subject_id: str | None) -> Any | None:
    if subject_type not in SUBJECT_TYPES:
        raise AppError("INVESTMENT_SUBJECT_INVALID", "投入归属对象类型无效", 400)
    if subject_type == "shared_operations":
        if subject_id:
            raise AppError("INVESTMENT_SUBJECT_INVALID", "共享运维成本池不应指定对象 ID", 400)
        return None
    if not subject_id:
        raise AppError("INVESTMENT_SUBJECT_REQUIRED", "投入归属对象不能为空", 400)
    row = db.get(SUBJECT_MODELS[subject_type], subject_id)
    if not row or row.is_deleted:
        raise AppError("INVESTMENT_SUBJECT_NOT_FOUND", "投入归属对象不存在", 404)
    return row


def validate_dimensions(
    subject_type: str,
    lifecycle_stage: str | None,
    investment_intent: str | None,
) -> tuple[str, str]:
    lifecycle = lifecycle_stage or default_lifecycle(subject_type)
    intent = investment_intent or default_intent(lifecycle)
    if lifecycle not in LIFECYCLE_STAGES:
        raise AppError("INVESTMENT_LIFECYCLE_INVALID", "生命周期必须是需求、建设或运维", 400)
    if intent not in INVESTMENT_INTENTS:
        raise AppError("INVESTMENT_INTENT_INVALID", "投入目的必须是运行、增长或转型", 400)
    return lifecycle, intent


def subject_references(subject_type: str, subject: Any | None) -> dict[str, str | None]:
    refs = {
        "project_id": None, "requirement_id": None, "service_item_id": None,
        "ci_id": None, "ticket_id": None, "problem_id": None, "contract_id": None,
        "vendor_id": None, "wbs_task_id": None,
    }
    if subject is None:
        return refs
    direct_key = f"{subject_type}_id"
    if direct_key in refs:
        refs[direct_key] = subject.id
    if subject_type == "ticket":
        refs.update(service_item_id=subject.service_item_id, ci_id=subject.ci_id)
    elif subject_type == "problem":
        refs["service_item_id"] = subject.service_item_id
    elif subject_type == "contract":
        refs.update(contract_id=subject.id, vendor_id=subject.vendor_id)
    return refs


def validate_wbs(db: Session, project_id: str | None, wbs_task_id: str | None) -> None:
    if not wbs_task_id:
        return
    row = db.get(WbsTask, wbs_task_id)
    if not row or row.is_deleted or not project_id or row.project_id != project_id:
        raise AppError("INVALID_WBS", "关联 WBS 任务不存在或不属于当前项目", 400)


T = TypeVar("T", InvestmentBudgetItem, InvestmentCostEntry, InvestmentWorklog)


def _weighted_rows(
    db: Session,
    model: type[T],
    source_kind: str,
    *,
    subject_type: str | None = None,
    subject_id: str | None = None,
    lifecycle_stage: str | None = None,
) -> list[tuple[T, Decimal]]:
    query = db.query(model).filter(model.is_deleted.is_(False))
    if lifecycle_stage:
        query = query.filter(model.lifecycle_stage == lifecycle_stage)
    if not subject_type:
        return [(row, Decimal("1")) for row in query.all()]

    direct = query.filter(model.subject_type == subject_type, model.subject_id == subject_id).all()
    # 工单登记的投入同时带服务项/CI 等来源引用，汇总上层运维对象时应自然归集，
    # 但仍以账本原始行作为唯一事实，不能复制记录。
    reference_column = getattr(model, f"{subject_type}_id", None)
    if reference_column is not None:
        referenced = query.filter(reference_column == subject_id).all()
        known = {row.id for row in direct}
        direct.extend(row for row in referenced if row.id not in known)
    direct_ids = {row.id for row in direct}
    allocations = db.query(InvestmentAllocation).filter(
        InvestmentAllocation.is_deleted.is_(False),
        InvestmentAllocation.source_kind == source_kind,
        InvestmentAllocation.target_type == subject_type,
        InvestmentAllocation.target_id == subject_id,
    ).all()
    weights: dict[str, Decimal] = defaultdict(Decimal)
    for allocation in allocations:
        if allocation.source_id not in direct_ids:
            weights[allocation.source_id] += allocation.percentage / Decimal("100")
    allocated = []
    if weights:
        allocated = query.filter(model.id.in_(list(weights))).all()
    return [(row, Decimal("1")) for row in direct] + [
        (row, min(weights[row.id], Decimal("1"))) for row in allocated
    ]


def _date_filtered(
    rows: Iterable[tuple[T, Decimal]],
    field: str,
    start: date | None,
    end: date | None,
) -> list[tuple[T, Decimal]]:
    result = []
    for row, weight in rows:
        value = getattr(row, field)
        if start and value < start:
            continue
        if end and value > end:
            continue
        result.append((row, weight))
    return result


def summary(
    db: Session,
    *,
    subject_type: str | None = None,
    subject_id: str | None = None,
    lifecycle_stage: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict[str, Any]:
    if subject_type:
        validate_subject(db, subject_type, subject_id)
    if lifecycle_stage and lifecycle_stage not in LIFECYCLE_STAGES:
        raise AppError("INVESTMENT_LIFECYCLE_INVALID", "生命周期必须是需求、建设或运维", 400)

    budgets = _weighted_rows(
        db, InvestmentBudgetItem, "budget", subject_type=subject_type,
        subject_id=subject_id, lifecycle_stage=lifecycle_stage,
    )
    # ``project.budget_10k`` 只是在旧项目没有预算分项时的兼容兜底。
    # 一旦同一项目存在显式预算分项，必须排除兜底行，避免项目及全局汇总重复计量。
    explicit_project_ids = {
        row.subject_id for row, _ in budgets
        if row.subject_type == "project"
        and row.source_type != "legacy_project_budget_total"
    }
    budgets = [
        (row, weight) for row, weight in budgets
        if not (
            row.source_type == "legacy_project_budget_total"
            and row.subject_id in explicit_project_ids
        )
    ]
    if period_start or period_end:
        budgets = [
            (row, weight) for row, weight in budgets
            if (not period_start or row.period_end >= period_start)
            and (not period_end or row.period_start <= period_end)
        ]
    costs = _date_filtered(
        _weighted_rows(
            db, InvestmentCostEntry, "cost", subject_type=subject_type,
            subject_id=subject_id, lifecycle_stage=lifecycle_stage,
        ),
        "recognition_date", period_start, period_end,
    )
    worklogs = _date_filtered(
        _weighted_rows(
            db, InvestmentWorklog, "worklog", subject_type=subject_type,
            subject_id=subject_id, lifecycle_stage=lifecycle_stage,
        ),
        "work_date", period_start, period_end,
    )

    budget_total = sum((row.amount_cny * weight for row, weight in budgets), Decimal("0"))
    committed = sum(
        (row.amount_cny * weight for row, weight in costs if row.cost_status == "committed"),
        Decimal("0"),
    )
    incurred = sum(
        (row.amount_cny * weight for row, weight in costs if row.cost_status in {"incurred", "paid"}),
        Decimal("0"),
    )
    paid = sum(
        (row.amount_cny * weight for row, weight in costs if row.cost_status == "paid"),
        Decimal("0"),
    )
    effort_days = sum((row.effort_days * weight for row, weight in worklogs), Decimal("0"))
    effort_cost = sum(
        (
            row.effort_days * row.standard_rate_cny_per_day * weight
            for row, weight in worklogs if row.standard_rate_cny_per_day is not None
        ),
        Decimal("0"),
    )
    unclassified_labor = sum(
        (
            row.amount_cny * weight for row, weight in costs
            if row.category == "labor" and row.labor_nature == "unclassified"
            and row.cost_status in {"incurred", "paid"}
        ),
        Decimal("0"),
    )
    category_budget: dict[str, Decimal] = defaultdict(Decimal)
    category_totals: dict[str, Decimal] = defaultdict(Decimal)
    activity_days: dict[str, Decimal] = defaultdict(Decimal)
    for row, weight in budgets:
        category_budget[row.category] += row.amount_cny * weight
    for row, weight in costs:
        if row.cost_status in {"incurred", "paid"}:
            category_totals[row.category] += row.amount_cny * weight
    for row, weight in worklogs:
        activity_days[row.activity_type] += row.effort_days * weight

    management_total = None if unclassified_labor else incurred + effort_cost
    financial_execution = (
        round(float((incurred + committed) * Decimal("100") / budget_total), 2)
        if budget_total else None
    )
    management_execution = (
        round(float((management_total + committed) * Decimal("100") / budget_total), 2)
        if budget_total and management_total is not None else None
    )
    return {
        "budget_cny": money(budget_total),
        "committed_cost_cny": money(committed),
        "incurred_cost_cny": money(incurred),
        "paid_cost_cny": money(paid),
        "effort_days": money(effort_days),
        "effort_cost_cny": money(effort_cost),
        "management_total_cny": money(management_total) if management_total is not None else None,
        "unclassified_labor_cny": money(unclassified_labor),
        "financial_budget_execution_rate": financial_execution,
        "management_budget_execution_rate": management_execution,
        # 兼容既有项目客户端；新页面应明确使用财务或管理口径字段。
        "budget_execution_rate": financial_execution,
        "categories": [
            {
                "category": key,
                "budget_cny": money(category_budget[key]),
                "actual_cny": money(category_totals[key]),
            }
            for key in sorted(set(category_budget) | set(category_totals))
        ],
        "activity_effort": [
            {"activity_type": key, "effort_days": money(value)}
            for key, value in sorted(activity_days.items())
        ],
        "quality": {
            "management_total_available": management_total is not None,
            "unclassified_labor": unclassified_labor != 0,
            "worklogs_with_rate": sum(1 for row, _ in worklogs if row.standard_rate_cny_per_day is not None),
            "worklog_count": len(worklogs),
        },
    }


def allocation_total(db: Session, source_kind: str, source_id: str, *, exclude_id: str | None = None) -> Decimal:
    rows = db.query(InvestmentAllocation).filter(
        InvestmentAllocation.is_deleted.is_(False),
        InvestmentAllocation.source_kind == source_kind,
        InvestmentAllocation.source_id == source_id,
    ).all()
    return sum((row.percentage for row in rows if row.id != exclude_id), Decimal("0"))


def validate_allocation_source(db: Session, source_kind: str, source_id: str) -> Any:
    models = {
        "budget": InvestmentBudgetItem,
        "cost": InvestmentCostEntry,
        "worklog": InvestmentWorklog,
    }
    model = models.get(source_kind)
    if not model:
        raise AppError("INVESTMENT_ALLOCATION_SOURCE_INVALID", "分摊来源类型无效", 400)
    row = db.get(model, source_id)
    if not row or row.is_deleted:
        raise AppError("INVESTMENT_ALLOCATION_SOURCE_NOT_FOUND", "分摊来源不存在", 404)
    return row
