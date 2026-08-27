"""统一报表中心：受控指标目录、实时聚合与正式报告审计快照。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from statistics import mean
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    AuthUser,
    BugFixTask,
    InvestmentBudgetItem,
    InvestmentCostEntry,
    InvestmentWorklog,
    ProcessInstance,
    ProcessTask,
    ProcessDefinition,
    ProcessStep,
    Project,
    ProjectDevelopmentTask,
    ReportAudience,
    ReportGenerationJob,
    ReportInstance,
    ReportTemplate,
    ReportVersion,
    Requirement,
    RequirementTask,
    Role,
    Ticket,
    UserGroup,
    UserGroupMember,
    WorkTask,
)
from app.services.investment import summary as investment_summary
from app.services.permissions import TICKET_TYPE_MODULE, has_perm
from app.services.rbac import effective_roles
from app.services.requirement_access import business_portal_requirement_filter, is_business_portal_only


REPORT_PERIOD_TYPES = {"week", "month", "quarter", "half_year", "year", "custom"}
COST_CATEGORIES = {
    "software", "hardware", "cloud", "network", "security", "service",
    "outsourcing", "telecom", "facility", "labor", "other", "legacy",
}


@dataclass(frozen=True)
class MetricDefinition:
    code: str
    domain: str
    name_zh: str
    name_en: str
    unit: str
    kind: str = "scalar"
    sensitivity: str = "normal"
    source_module: str = ""
    formula_version: str = "1.0"


METRICS = [
    MetricDefinition("itsm.ticket_count", "itsm", "工单总数", "Ticket count", "count", source_module="tickets"),
    MetricDefinition("itsm.resolved_count", "itsm", "已解决工单", "Resolved tickets", "count", source_module="tickets"),
    MetricDefinition("itsm.sla_resolution_rate", "itsm", "SLA 解决达成率", "SLA resolution rate", "percent", source_module="sla"),
    MetricDefinition("itsm.avg_resolution_hours", "itsm", "平均解决时长", "Average resolution time", "hours", source_module="tickets"),
    MetricDefinition("itsm.first_time_fix_rate", "itsm", "一次解决率", "First-time-fix rate", "percent", source_module="tickets"),
    MetricDefinition("project.count", "project", "项目总数", "Project count", "count", source_module="projects"),
    MetricDefinition("project.active_count", "project", "在途项目", "Active projects", "count", source_module="projects"),
    MetricDefinition("project.budget_cny", "project", "项目预算", "Project budget", "CNY", sensitivity="finance", source_module="projects"),
    MetricDefinition("project.actual_cost_cny", "project", "实际投入成本", "Actual project cost", "CNY", sensitivity="finance", source_module="projects"),
    MetricDefinition("project.committed_cost_cny", "project", "已承诺成本", "Committed project cost", "CNY", sensitivity="finance", source_module="projects"),
    MetricDefinition("project.cost_by_category", "project", "成本类别分布", "Cost by category", "CNY", kind="series", sensitivity="finance", source_module="projects"),
    MetricDefinition("project.effort_days", "project", "实施人天", "Project effort", "days", sensitivity="people", source_module="projects"),
    MetricDefinition("project.effort_cost_cny", "project", "标准人天成本", "Standard effort cost", "CNY", sensitivity="finance", source_module="projects"),
    MetricDefinition("project.budget_execution_rate", "project", "预算执行率", "Budget execution rate", "percent", sensitivity="finance", source_module="projects"),
    MetricDefinition("operations.budget_cny", "operations", "运维预算", "Operations budget", "CNY", sensitivity="finance", source_module="reports"),
    MetricDefinition("operations.committed_cost_cny", "operations", "运维已承诺费用", "Committed operations cost", "CNY", sensitivity="finance", source_module="reports"),
    MetricDefinition("operations.incurred_cost_cny", "operations", "运维已发生费用", "Incurred operations cost", "CNY", sensitivity="finance", source_module="reports"),
    MetricDefinition("operations.paid_cost_cny", "operations", "运维已支付费用", "Paid operations cost", "CNY", sensitivity="finance", source_module="reports"),
    MetricDefinition("operations.effort_days", "operations", "运维实际人天", "Operations effort", "days", sensitivity="people", source_module="reports"),
    MetricDefinition("operations.effort_cost_cny", "operations", "运维标准人力成本", "Operations standard labor cost", "CNY", sensitivity="finance", source_module="reports"),
    MetricDefinition("operations.management_total_cny", "operations", "运维管理总投入", "Operations management total", "CNY", sensitivity="finance", source_module="reports"),
    MetricDefinition("operations.cost_by_category", "operations", "运维费用构成", "Operations cost by category", "CNY", kind="series", sensitivity="finance", source_module="reports"),
    MetricDefinition("operations.effort_by_activity", "operations", "运维人天活动构成", "Operations effort by activity", "days", kind="series", sensitivity="people", source_module="reports"),
    MetricDefinition("operations.budget_execution_rate", "operations", "运维财务预算执行率", "Operations financial budget execution", "percent", sensitivity="finance", source_module="reports"),
    MetricDefinition("operations.ticket_worklog_coverage", "operations", "工单工时登记覆盖率", "Ticket worklog coverage", "percent", sensitivity="people", source_module="reports"),
    MetricDefinition("operations.cost_per_resolved_ticket", "operations", "单已解决工单费用", "Cost per resolved ticket", "CNY", sensitivity="finance", source_module="reports"),
    MetricDefinition("people.effort_days", "people", "IT 总投入人天", "Total IT effort", "days", sensitivity="people", source_module="reports"),
    MetricDefinition("people.effort_by_lifecycle", "people", "人天生命周期构成", "Effort by lifecycle", "days", kind="series", sensitivity="people", source_module="reports"),
    MetricDefinition("people.effort_by_role", "people", "人天角色构成", "Effort by role", "days", kind="series", sensitivity="people", source_module="reports"),
    MetricDefinition("people.rate_coverage", "people", "标准费率覆盖率", "Standard rate coverage", "percent", sensitivity="people", source_module="reports"),
    MetricDefinition("requirement.count", "requirement", "需求总数", "Requirement count", "count", source_module="requirements"),
    MetricDefinition("requirement.closed_count", "requirement", "已关闭需求", "Closed requirements", "count", source_module="requirements"),
    MetricDefinition("requirement.avg_lead_days", "requirement", "平均处理时长", "Average lead time", "days", source_module="requirements"),
    MetricDefinition("requirement.p50_lead_days", "requirement", "处理时长 P50", "Lead time P50", "days", source_module="requirements"),
    MetricDefinition("requirement.p90_lead_days", "requirement", "处理时长 P90", "Lead time P90", "days", source_module="requirements"),
    MetricDefinition("requirement.stage_cycle_days", "requirement", "阶段平均耗时", "Average stage cycle", "days", kind="series", source_module="requirements"),
    MetricDefinition("requirement.on_time_rate", "requirement", "按期关闭率", "On-time closure rate", "percent", source_module="requirements"),
    MetricDefinition("task.open_count", "task", "未完成任务", "Open tasks", "count", source_module="tasks"),
    MetricDefinition("task.completed_count", "task", "已完成任务", "Completed tasks", "count", source_module="tasks"),
    MetricDefinition("task.actual_effort_days", "task", "任务实际人天", "Actual task effort", "days", sensitivity="people", source_module="tasks"),
    MetricDefinition("task.on_time_rate", "task", "任务按期完成率", "On-time task completion", "percent", source_module="tasks"),
    MetricDefinition("process.completed_count", "process", "已完成流程", "Completed processes", "count", source_module="process_monitor"),
    MetricDefinition("process.avg_cycle_hours", "process", "流程平均周期", "Average process cycle", "hours", source_module="process_monitor"),
    MetricDefinition("process.overdue_rate", "process", "流程超时率", "Process overdue rate", "percent", source_module="process_monitor"),
]
METRIC_MAP = {item.code: item for item in METRICS}


SYSTEM_TEMPLATES = [
    ("weekly_operations", "IT 运营周报", "Weekly IT Operations", ["itsm", "operations", "requirement", "task", "process"], "week"),
    ("monthly_management", "IT 管理月报", "Monthly IT Management", ["itsm", "project", "operations", "people", "requirement", "task", "process"], "month"),
    ("project_investment", "项目投入分析", "Project Investment", ["project"], "month"),
    ("requirement_timeliness", "需求处理时效", "Requirement Timeliness", ["requirement"], "month"),
    ("operations_investment", "运维投入分析", "Operations Investment", ["operations"], "month"),
    ("it_capacity", "IT 人力容量与投向", "IT Capacity and Allocation", ["people"], "month"),
]


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _percent(numerator: int | float | Decimal, denominator: int | float | Decimal) -> float | None:
    if not denominator:
        return None
    return round(float(numerator) * 100 / float(denominator), 2)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 2)


def _allowed_ticket_types(db: Session, actor: AuthUser) -> list[str]:
    return [kind for kind, module in TICKET_TYPE_MODULE.items() if has_perm(db, actor, module, "view")]


def _has_source_access(db: Session, actor: AuthUser, definition: MetricDefinition) -> bool:
    if definition.source_module == "tickets":
        return bool(_allowed_ticket_types(db, actor))
    if definition.source_module == "tasks":
        return any(has_perm(db, actor, module, "view") for module in ("req_tasks", "task_development", "task_bug", "task_delegated"))
    if definition.source_module == "sla":
        return has_perm(db, actor, "sla", "view") and bool(_allowed_ticket_types(db, actor))
    return has_perm(db, actor, definition.source_module, "view")


def _has_metric_access(db: Session, actor: AuthUser, definition: MetricDefinition) -> bool:
    if not has_perm(db, actor, "reports", "view") or not _has_source_access(db, actor, definition):
        return False
    sensitive_module = {
        "finance": "reports_finance",
        "people": "reports_people",
        "platform": "reports_platform",
    }.get(definition.sensitivity)
    return not sensitive_module or has_perm(db, actor, sensitive_module, "view")


def metric_catalog(db: Session, actor: AuthUser) -> list[dict]:
    return [asdict(item) for item in METRICS if _has_metric_access(db, actor, item)]


def resolve_period(period_type: str, anchor: date | None = None, start: date | None = None, end: date | None = None) -> tuple[date, date]:
    if period_type not in REPORT_PERIOD_TYPES:
        raise AppError("REPORT_PERIOD_INVALID", "报告周期类型无效", 400)
    anchor = anchor or date.today()
    if period_type == "custom":
        if not start or not end or end < start:
            raise AppError("REPORT_PERIOD_INVALID", "自定义周期必须提供有效的开始和结束日期", 400)
        return start, end
    if period_type == "week":
        begin = anchor - timedelta(days=anchor.weekday())
        return begin, begin + timedelta(days=6)
    if period_type == "month":
        begin = anchor.replace(day=1)
        following = (begin.replace(day=28) + timedelta(days=4)).replace(day=1)
        return begin, following - timedelta(days=1)
    if period_type == "quarter":
        month = ((anchor.month - 1) // 3) * 3 + 1
        begin = anchor.replace(month=month, day=1)
        following = begin.replace(year=begin.year + 1, month=1) if month == 10 else begin.replace(month=month + 3)
        return begin, following - timedelta(days=1)
    if period_type == "half_year":
        month = 1 if anchor.month <= 6 else 7
        begin = anchor.replace(month=month, day=1)
        following = begin.replace(year=begin.year + 1, month=1) if month == 7 else begin.replace(month=7)
        return begin, following - timedelta(days=1)
    return anchor.replace(month=1, day=1), anchor.replace(month=12, day=31)


def _ticket_rows(db: Session, actor: AuthUser, start: date, end: date, filters: dict | None = None) -> list[Ticket]:
    types = _allowed_ticket_types(db, actor)
    query = db.query(Ticket).filter(
        Ticket.is_deleted.is_(False), Ticket.ticket_type.in_(types),
        Ticket.submitted_at >= datetime.combine(start, time.min),
        Ticket.submitted_at < datetime.combine(end + timedelta(days=1), time.min),
    )
    roles = effective_roles(db, actor)
    if roles and roles.issubset({"requester", "bdo"}):
        query = query.filter(or_(Ticket.submitter == actor.id, Ticket.assignee == (actor.person_id or "-")))
    filters = filters or {}
    if filters.get("ticket_type"):
        if filters["ticket_type"] not in types:
            raise AppError("REPORT_FILTER_FORBIDDEN", "无权使用该工单类型筛选条件", 403)
        query = query.filter(Ticket.ticket_type == filters["ticket_type"])
    if filters.get("priority"):
        query = query.filter(Ticket.priority == filters["priority"])
    if filters.get("service_item_id"):
        query = query.filter(Ticket.service_item_id == filters["service_item_id"])
    if filters.get("ci_id"):
        query = query.filter(Ticket.ci_id == filters["ci_id"])
    return query.all()


def _requirement_rows(db: Session, actor: AuthUser, start: date, end: date, filters: dict | None = None) -> list[Requirement]:
    query = db.query(Requirement).filter(
        Requirement.is_deleted.is_(False),
        Requirement.registered_at >= datetime.combine(start, time.min),
        Requirement.registered_at < datetime.combine(end + timedelta(days=1), time.min),
    )
    if is_business_portal_only(db, actor):
        query = query.filter(business_portal_requirement_filter(db, actor))
    filters = filters or {}
    if filters.get("business_domain_id"):
        query = query.filter(Requirement.business_domain_id == filters["business_domain_id"])
    return query.all()


def _project_metrics(db: Session, start: date, end: date, filters: dict | None = None) -> dict[str, Any]:
    query = db.query(Project).filter(
        Project.is_deleted.is_(False), Project.planned_start <= end, Project.planned_end >= start
    )
    filters = filters or {}
    if filters.get("project_id"):
        query = query.filter(Project.id == filters["project_id"])
    if filters.get("portfolio_id"):
        query = query.filter(Project.portfolio_id == filters["portfolio_id"])
    projects = query.all()
    summaries = [
        investment_summary(
            db, subject_type="project", subject_id=row.id, lifecycle_stage="build",
            period_start=start, period_end=end,
        )
        for row in projects
    ]
    budget = sum((Decimal(item["budget_cny"]) for item in summaries), Decimal("0"))
    actual_cost = sum((Decimal(item["incurred_cost_cny"]) for item in summaries), Decimal("0"))
    committed_cost = sum((Decimal(item["committed_cost_cny"]) for item in summaries), Decimal("0"))
    effort_days = sum((Decimal(item["effort_days"]) for item in summaries), Decimal("0"))
    effort_cost = sum((Decimal(item["effort_cost_cny"]) for item in summaries), Decimal("0"))
    category_totals: dict[str, Decimal] = {category: Decimal("0") for category in sorted(COST_CATEGORIES)}
    for item in summaries:
        for category in item["categories"]:
            key = category["category"] if category["category"] in COST_CATEGORIES else "other"
            category_totals[key] += Decimal(category["actual_cny"])
    return {
        "project.count": len(projects),
        "project.active_count": sum(1 for row in projects if row.status not in {"completed", "closed", "已完成", "已关闭"}),
        "project.budget_cny": budget,
        "project.actual_cost_cny": actual_cost,
        "project.committed_cost_cny": committed_cost,
        "project.cost_by_category": [{"key": key, "value": _json_value(value)} for key, value in category_totals.items() if value],
        "project.effort_days": effort_days,
        "project.effort_cost_cny": effort_cost,
        # 项目财务预算执行率仅使用费用账本；标准人力估值另列，避免与未分类人力费用重复。
        "project.budget_execution_rate": _percent(actual_cost + committed_cost, budget),
    }


def _investment_subject_from_filters(filters: dict | None) -> tuple[str | None, str | None]:
    filters = filters or {}
    if filters.get("subject_type"):
        return filters["subject_type"], filters.get("subject_id")
    for key in ("service_item_id", "ci_id", "contract_id", "requirement_id", "project_id", "ticket_id", "problem_id"):
        if filters.get(key):
            return key.removesuffix("_id"), filters[key]
    return None, None


def _apply_investment_subject_filter(query, model, filters: dict | None):
    subject_type, subject_id = _investment_subject_from_filters(filters)
    if not subject_type or not subject_id:
        return query
    reference_column = getattr(model, f"{subject_type}_id", None)
    direct = (model.subject_type == subject_type) & (model.subject_id == subject_id)
    return query.filter(or_(direct, reference_column == subject_id)) if reference_column is not None else query.filter(direct)


def _operations_metrics(
    db: Session,
    start: date,
    end: date,
    tickets: list[Ticket],
    resolved: list[Ticket],
    filters: dict | None = None,
) -> dict[str, Any]:
    subject_type, subject_id = _investment_subject_from_filters(filters)
    values = investment_summary(
        db, subject_type=subject_type, subject_id=subject_id,
        lifecycle_stage="run", period_start=start, period_end=end,
    )
    ticket_ids = {row.id for row in tickets}
    logged_ticket_ids = set()
    if ticket_ids:
        logged_ticket_ids = {
            row.ticket_id for row in db.query(InvestmentWorklog).filter(
                InvestmentWorklog.is_deleted.is_(False),
                InvestmentWorklog.lifecycle_stage == "run",
                InvestmentWorklog.ticket_id.in_(ticket_ids),
                InvestmentWorklog.work_date >= start,
                InvestmentWorklog.work_date <= end,
            ).all()
        }
    incurred = Decimal(values["incurred_cost_cny"])
    return {
        "operations.budget_cny": Decimal(values["budget_cny"]),
        "operations.committed_cost_cny": Decimal(values["committed_cost_cny"]),
        "operations.incurred_cost_cny": incurred,
        "operations.paid_cost_cny": Decimal(values["paid_cost_cny"]),
        "operations.effort_days": Decimal(values["effort_days"]),
        "operations.effort_cost_cny": Decimal(values["effort_cost_cny"]),
        "operations.management_total_cny": (
            Decimal(values["management_total_cny"])
            if values["management_total_cny"] is not None else None
        ),
        "operations.cost_by_category": [
            {"key": item["category"], "value": item["actual_cny"]}
            for item in values["categories"] if Decimal(item["actual_cny"])
        ],
        "operations.effort_by_activity": [
            {"key": item["activity_type"], "value": item["effort_days"]}
            for item in values["activity_effort"] if Decimal(item["effort_days"])
        ],
        "operations.budget_execution_rate": values["financial_budget_execution_rate"],
        "operations.ticket_worklog_coverage": _percent(len(logged_ticket_ids), len(ticket_ids)),
        "operations.cost_per_resolved_ticket": (
            (incurred / len(resolved)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if resolved else None
        ),
    }


def _people_metrics(db: Session, start: date, end: date, filters: dict | None = None) -> dict[str, Any]:
    query = db.query(InvestmentWorklog).filter(
        InvestmentWorklog.is_deleted.is_(False), InvestmentWorklog.work_date >= start,
        InvestmentWorklog.work_date <= end,
    )
    filters = filters or {}
    subject_type, subject_id = _investment_subject_from_filters(filters)
    if subject_type and subject_id:
        reference_column = getattr(InvestmentWorklog, f"{subject_type}_id", None)
        if reference_column is not None:
            query = query.filter(or_(
                (InvestmentWorklog.subject_type == subject_type) & (InvestmentWorklog.subject_id == subject_id),
                reference_column == subject_id,
            ))
        else:
            query = query.filter(
                InvestmentWorklog.subject_type == subject_type,
                InvestmentWorklog.subject_id == subject_id,
            )
    rows = query.all()
    lifecycle: dict[str, Decimal] = {}
    roles: dict[str, Decimal] = {}
    for row in rows:
        lifecycle[row.lifecycle_stage] = lifecycle.get(row.lifecycle_stage, Decimal("0")) + row.effort_days
        roles[row.role_type] = roles.get(row.role_type, Decimal("0")) + row.effort_days
    return {
        "people.effort_days": sum((row.effort_days for row in rows), Decimal("0")),
        "people.effort_by_lifecycle": [
            {"key": key, "value": _json_value(value)} for key, value in sorted(lifecycle.items())
        ],
        "people.effort_by_role": [
            {"key": key, "value": _json_value(value)} for key, value in sorted(roles.items())
        ],
        "people.rate_coverage": _percent(
            sum(1 for row in rows if row.standard_rate_cny_per_day is not None), len(rows)
        ),
    }


def _allowed_task_models(db: Session, actor: AuthUser) -> list[tuple[Any, str]]:
    models: list[tuple[Any, str]] = []
    if has_perm(db, actor, "req_tasks", "view") or has_perm(db, actor, "task_development", "view"):
        models.append((RequirementTask, "name"))
    if has_perm(db, actor, "task_bug", "view"):
        models.append((BugFixTask, "name"))
    if has_perm(db, actor, "task_delegated", "view"):
        models.append((WorkTask, "title"))
    if has_perm(db, actor, "task_development", "view"):
        models.append((ProjectDevelopmentTask, "title"))
    return models


def _task_metrics(db: Session, actor: AuthUser, start: date, end: date) -> dict[str, Any]:
    begin_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end + timedelta(days=1), time.min)
    rows: list[Any] = []
    for model, _ in _allowed_task_models(db, actor):
        rows.extend(db.query(model).filter(model.is_deleted.is_(False), model.created_at >= begin_dt, model.created_at < end_dt).all())
    completed = [row for row in rows if getattr(row, "done_at", None) or getattr(row, "closed_at", None) or row.status in {"已完成", "completed", "完成", "关闭", "已关闭"}]
    on_time = 0
    eligible = 0
    for row in completed:
        completed_at = getattr(row, "done_at", None) or getattr(row, "closed_at", None)
        due = getattr(row, "plan_date", None)
        if completed_at and due:
            eligible += 1
            if completed_at.date() <= due:
                on_time += 1
    return {
        "task.open_count": len(rows) - len(completed),
        "task.completed_count": len(completed),
        "task.actual_effort_days": round(sum(float(getattr(row, "actual_effort", 0) or 0) for row in rows), 2),
        "task.on_time_rate": _percent(on_time, eligible),
    }


def _raw_metrics(db: Session, actor: AuthUser, start: date, end: date, filters: dict | None = None) -> dict[str, Any]:
    tickets = _ticket_rows(db, actor, start, end, filters) if _allowed_ticket_types(db, actor) else []
    resolved = [row for row in tickets if row.resolved_at]
    sla_known = [row for row in resolved if row.sla_resolution_met is not None]
    ftr_known = [row for row in resolved if row.first_time_fix is not None]
    requirements = _requirement_rows(db, actor, start, end, filters) if has_perm(db, actor, "requirements", "view") else []
    closed_requirements = [row for row in requirements if row.closed_at and row.registered_at]
    lead_days = [(row.closed_at - row.registered_at).total_seconds() / 86400 for row in closed_requirements]
    stage_fields = [
        ("registered_to_evaluating", "registered_at", "evaluating_at"),
        ("evaluating_to_analyzing", "evaluating_at", "analyzing_at"),
        ("analyzing_to_implementing", "analyzing_at", "implementing_at"),
        ("implementing_to_closed", "implementing_at", "closed_at"),
    ]
    stage_series = []
    for key, left, right in stage_fields:
        values = [
            (getattr(row, right) - getattr(row, left)).total_seconds() / 86400
            for row in requirements if getattr(row, left) and getattr(row, right)
        ]
        stage_series.append({"key": key, "value": round(mean(values), 2) if values else None, "sample_size": len(values)})
    req_due = [row for row in closed_requirements if row.target_date or row.expected_date]
    req_on_time = sum(1 for row in req_due if row.closed_at.date() <= (row.target_date or row.expected_date))
    process_rows = db.query(ProcessInstance).filter(
        ProcessInstance.is_deleted.is_(False), ProcessInstance.started_at >= datetime.combine(start, time.min),
        ProcessInstance.started_at < datetime.combine(end + timedelta(days=1), time.min),
    ).all()
    complete_processes = [row for row in process_rows if row.completed_at]
    process_hours = [(row.completed_at - row.started_at).total_seconds() / 3600 for row in complete_processes if row.started_at]
    process_tasks = db.query(ProcessTask).filter(
        ProcessTask.instance_id.in_([row.id for row in process_rows] or ["-"]),
        ProcessTask.is_deleted.is_(False), ProcessTask.due_at.is_not(None),
    ).all()
    report_cutoff = min(datetime.now(), datetime.combine(end + timedelta(days=1), time.min))
    overdue_process_tasks = [
        row for row in process_tasks
        if (row.completed_at is not None and row.completed_at > row.due_at)
        or (row.completed_at is None and row.due_at < report_cutoff)
    ]
    raw: dict[str, Any] = {
        "itsm.ticket_count": len(tickets),
        "itsm.resolved_count": len(resolved),
        "itsm.sla_resolution_rate": _percent(sum(1 for row in sla_known if row.sla_resolution_met), len(sla_known)),
        "itsm.avg_resolution_hours": round(mean([row.actual_resolution_hours for row in resolved if row.actual_resolution_hours is not None]), 2) if any(row.actual_resolution_hours is not None for row in resolved) else None,
        "itsm.first_time_fix_rate": _percent(sum(1 for row in ftr_known if row.first_time_fix), len(ftr_known)),
        "requirement.count": len(requirements),
        "requirement.closed_count": len(closed_requirements),
        "requirement.avg_lead_days": round(mean(lead_days), 2) if lead_days else None,
        "requirement.p50_lead_days": _percentile(lead_days, .5),
        "requirement.p90_lead_days": _percentile(lead_days, .9),
        "requirement.stage_cycle_days": stage_series,
        "requirement.on_time_rate": _percent(req_on_time, len(req_due)),
        "process.completed_count": len(complete_processes),
        "process.avg_cycle_hours": round(mean(process_hours), 2) if process_hours else None,
        "process.overdue_rate": _percent(len(overdue_process_tasks), len(process_tasks)),
    }
    raw.update(_project_metrics(db, start, end, filters))
    raw.update(_task_metrics(db, actor, start, end))
    raw.update(_operations_metrics(db, start, end, tickets, resolved, filters))
    raw.update(_people_metrics(db, start, end, filters))
    return raw


def query_metrics(db: Session, actor: AuthUser, metric_codes: list[str], start: date, end: date, filters: dict | None = None) -> dict:
    if end < start or (end - start).days > 731:
        raise AppError("REPORT_PERIOD_INVALID", "报告周期无效或超过两年上限", 400)
    filters = filters or {}
    allowed_filters = {
        "project_id", "portfolio_id", "business_domain_id", "ticket_type", "priority",
        "service_item_id", "ci_id", "contract_id", "requirement_id", "ticket_id",
        "problem_id", "subject_type", "subject_id",
    }
    unknown_filters = sorted(set(filters) - allowed_filters)
    if unknown_filters:
        raise AppError("REPORT_FILTER_UNKNOWN", f"未知筛选条件：{', '.join(unknown_filters)}", 400)
    unknown = sorted(set(metric_codes) - set(METRIC_MAP))
    if unknown:
        raise AppError("REPORT_METRIC_UNKNOWN", f"未知指标：{', '.join(unknown)}", 400)
    denied = [code for code in metric_codes if not _has_metric_access(db, actor, METRIC_MAP[code])]
    if denied:
        raise AppError("REPORT_METRIC_FORBIDDEN", f"无权查看指标：{', '.join(denied)}", 403)
    raw = _raw_metrics(db, actor, start, end, filters)
    results = []
    for code in metric_codes:
        definition = METRIC_MAP[code]
        value = raw.get(code)
        quality = "no_data" if value is None else "ok"
        if definition.kind == "series" and value and all(item.get("value") is None for item in value):
            quality = "no_data"
        results.append({
            **asdict(definition), "value": _json_value(value), "quality": quality,
            "period_start": start.isoformat(), "period_end": end.isoformat(),
        })
    return {"period_start": start.isoformat(), "period_end": end.isoformat(), "filters": filters, "metrics": results}


def drilldown_metric(db: Session, actor: AuthUser, code: str, start: date, end: date, limit: int = 200, filters: dict | None = None) -> list[dict]:
    """穿透明细重新执行指标、敏感模块及来源域数据范围授权。"""
    definition = METRIC_MAP.get(code)
    if not definition:
        raise AppError("REPORT_METRIC_UNKNOWN", "未知指标", 404)
    if not _has_metric_access(db, actor, definition):
        raise AppError("REPORT_METRIC_FORBIDDEN", "无权查看该指标明细", 403)
    limit = min(max(limit, 1), 500)
    filters = filters or {}
    if definition.domain == "itsm":
        return [{
            "id": row.id, "code": row.ticket_code, "title": row.title, "type": row.ticket_type,
            "status": row.status, "submitted_at": _json_value(row.submitted_at),
            "resolved_at": _json_value(row.resolved_at), "actual_resolution_hours": row.actual_resolution_hours,
            "sla_resolution_met": row.sla_resolution_met,
        } for row in _ticket_rows(db, actor, start, end, filters)[:limit]]
    if definition.domain == "requirement":
        rows = _requirement_rows(db, actor, start, end, filters)
        return [{
            "id": row.id, "code": row.requirement_code, "title": row.title, "status": row.status,
            "registered_at": _json_value(row.registered_at), "closed_at": _json_value(row.closed_at),
            "lead_days": round((row.closed_at - row.registered_at).total_seconds() / 86400, 2) if row.closed_at and row.registered_at else None,
        } for row in rows[:limit]]
    if definition.domain == "project" and code == "project.effort_days":
        if not has_perm(db, actor, "reports_people", "view"):
            raise AppError("REPORT_METRIC_FORBIDDEN", "无权查看人员投入明细", 403)
        query = db.query(InvestmentWorklog).filter(
            InvestmentWorklog.is_deleted.is_(False), InvestmentWorklog.work_date >= start,
            InvestmentWorklog.work_date <= end, InvestmentWorklog.lifecycle_stage == "build",
        )
        if filters.get("project_id"):
            query = query.filter(InvestmentWorklog.project_id == filters["project_id"])
        rows = query.order_by(InvestmentWorklog.work_date.desc()).limit(limit).all()
        return [{
            "id": row.id, "project_id": row.project_id, "person_id": row.person_id,
            "work_date": _json_value(row.work_date), "effort_days": _json_value(row.effort_days),
            "role_type": row.role_type,
        } for row in rows]
    if definition.domain == "project" and code == "project.budget_cny":
        query = db.query(InvestmentBudgetItem).filter(
            InvestmentBudgetItem.is_deleted.is_(False),
            InvestmentBudgetItem.lifecycle_stage == "build",
            InvestmentBudgetItem.subject_type == "project",
            InvestmentBudgetItem.period_end >= start,
            InvestmentBudgetItem.period_start <= end,
        )
        if filters.get("project_id"):
            query = query.filter(InvestmentBudgetItem.subject_id == filters["project_id"])
        rows = query.order_by(InvestmentBudgetItem.created_at.desc()).limit(limit).all()
        return [{"id": row.id, "project_id": row.subject_id, "category": row.category,
                 "name": row.name, "amount_cny": _json_value(row.amount_cny)} for row in rows]
    if definition.domain == "project" and code == "project.effort_cost_cny":
        query = db.query(InvestmentWorklog).filter(
            InvestmentWorklog.is_deleted.is_(False), InvestmentWorklog.work_date >= start,
            InvestmentWorklog.work_date <= end, InvestmentWorklog.lifecycle_stage == "build",
        )
        if filters.get("project_id"):
            query = query.filter(InvestmentWorklog.project_id == filters["project_id"])
        rows = query.all()
        totals: dict[str, dict[str, Decimal]] = {}
        for row in rows:
            bucket = totals.setdefault(row.role_type, {"effort_days": Decimal("0"), "cost_cny": Decimal("0")})
            bucket["effort_days"] += row.effort_days
            if row.standard_rate_cny_per_day is not None:
                bucket["cost_cny"] += row.effort_days * row.standard_rate_cny_per_day
        return [{"id": role, "role_type": role, "effort_days": _json_value(values["effort_days"]),
                 "cost_cny": _json_value(values["cost_cny"])} for role, values in totals.items()]
    if definition.domain == "project" and definition.sensitivity == "finance":
        query = db.query(InvestmentCostEntry).filter(
            InvestmentCostEntry.is_deleted.is_(False),
            InvestmentCostEntry.lifecycle_stage == "build",
            InvestmentCostEntry.recognition_date >= start,
            InvestmentCostEntry.recognition_date <= end,
        )
        if filters.get("project_id"):
            query = query.filter(InvestmentCostEntry.project_id == filters["project_id"])
        rows = query.order_by(InvestmentCostEntry.recognition_date.desc()).limit(limit).all()
        return [{
            "id": row.id, "project_id": row.project_id,
            "entry_date": _json_value(row.recognition_date),
            "amount_cny": _json_value(row.amount_cny),
            "category": row.category, "cost_type": row.cost_status,
            "supplier": row.supplier_snapshot,
        } for row in rows]
    if definition.domain == "operations" and code == "operations.budget_cny":
        query = db.query(InvestmentBudgetItem).filter(
            InvestmentBudgetItem.is_deleted.is_(False),
            InvestmentBudgetItem.lifecycle_stage == "run",
            InvestmentBudgetItem.period_end >= start,
            InvestmentBudgetItem.period_start <= end,
        )
        rows = _apply_investment_subject_filter(query, InvestmentBudgetItem, filters).order_by(
            InvestmentBudgetItem.period_start.desc()
        ).limit(limit).all()
        return [{
            "id": row.id, "subject_type": row.subject_type, "subject_id": row.subject_id,
            "category": row.category, "name": row.name,
            "amount_cny": _json_value(row.amount_cny),
        } for row in rows]
    if definition.domain in {"operations", "people"} and (
        definition.sensitivity == "people" or definition.domain == "people"
    ):
        query = db.query(InvestmentWorklog).filter(
            InvestmentWorklog.is_deleted.is_(False), InvestmentWorklog.work_date >= start,
            InvestmentWorklog.work_date <= end,
        )
        if definition.domain == "operations":
            query = query.filter(InvestmentWorklog.lifecycle_stage == "run")
        rows = _apply_investment_subject_filter(query, InvestmentWorklog, filters).order_by(
            InvestmentWorklog.work_date.desc()
        ).limit(limit).all()
        return [{
            "id": row.id, "subject_type": row.subject_type, "subject_id": row.subject_id,
            "person_id": row.person_id, "work_date": _json_value(row.work_date),
            "effort_days": _json_value(row.effort_days), "role_type": row.role_type,
            "activity_type": row.activity_type,
        } for row in rows]
    if definition.domain == "operations" and definition.sensitivity == "finance":
        query = db.query(InvestmentCostEntry).filter(
            InvestmentCostEntry.is_deleted.is_(False),
            InvestmentCostEntry.lifecycle_stage == "run",
            InvestmentCostEntry.recognition_date >= start,
            InvestmentCostEntry.recognition_date <= end,
        )
        rows = _apply_investment_subject_filter(query, InvestmentCostEntry, filters).order_by(
            InvestmentCostEntry.recognition_date.desc()
        ).limit(limit).all()
        return [{
            "id": row.id, "subject_type": row.subject_type, "subject_id": row.subject_id,
            "entry_date": _json_value(row.recognition_date),
            "amount_cny": _json_value(row.amount_cny), "category": row.category,
            "cost_status": row.cost_status, "activity_type": row.activity_type,
            "supplier": row.supplier_snapshot,
        } for row in rows]
    if definition.domain == "project":
        query = db.query(Project).filter(
            Project.is_deleted.is_(False), Project.planned_start <= end, Project.planned_end >= start,
        )
        if filters.get("project_id"):
            query = query.filter(Project.id == filters["project_id"])
        if filters.get("portfolio_id"):
            query = query.filter(Project.portfolio_id == filters["portfolio_id"])
        rows = query.order_by(Project.project_code).limit(limit).all()
        return [{"id": row.id, "code": row.project_code, "name": row.name, "status": row.status,
                 "planned_start": _json_value(row.planned_start), "planned_end": _json_value(row.planned_end)} for row in rows]
    if definition.domain == "task":
        begin_dt = datetime.combine(start, time.min)
        end_dt = datetime.combine(end + timedelta(days=1), time.min)
        output = []
        for model, label_field in _allowed_task_models(db, actor):
            query = db.query(model).filter(model.is_deleted.is_(False), model.created_at >= begin_dt, model.created_at < end_dt)
            if filters.get("project_id") and model is ProjectDevelopmentTask:
                query = query.filter(ProjectDevelopmentTask.project_id == filters["project_id"])
            elif filters.get("project_id"):
                continue
            for row in query.limit(max(limit - len(output), 0)).all():
                output.append({"id": row.id, "code": row.task_code, "title": getattr(row, label_field),
                               "status": row.status, "plan_date": _json_value(getattr(row, "plan_date", None)),
                               "actual_effort": getattr(row, "actual_effort", None)})
            if len(output) >= limit:
                break
        return output
    if definition.domain == "process":
        rows = db.query(ProcessInstance).filter(
            ProcessInstance.is_deleted.is_(False), ProcessInstance.started_at >= datetime.combine(start, time.min),
            ProcessInstance.started_at < datetime.combine(end + timedelta(days=1), time.min),
        ).order_by(ProcessInstance.started_at.desc()).limit(limit).all()
        return [{
            "id": row.id, "entity_type": row.entity_type, "entity_id": row.entity_id,
            "status": row.status, "started_at": _json_value(row.started_at),
            "completed_at": _json_value(row.completed_at),
        } for row in rows]
    raise AppError("REPORT_DRILLDOWN_UNAVAILABLE", "该指标暂不提供明细穿透", 409)


def seed_report_center(db: Session):
    for code, name, description, domains, period_type in SYSTEM_TEMPLATES:
        metric_codes = [metric.code for metric in METRICS if metric.domain in domains]
        existing = db.query(ReportTemplate).filter(ReportTemplate.code == code).first()
        if existing:
            if existing.is_system:
                existing.name = name
                existing.description = description
                existing.domains = domains
                existing.metric_codes = metric_codes
                existing.default_period_type = period_type
                existing.active = True
            continue
        db.add(ReportTemplate(
            code=code, name=name, description=description, domains=domains,
            metric_codes=metric_codes, default_filters={}, default_period_type=period_type,
            is_system=True, active=True,
        ))
    definition = db.query(ProcessDefinition).filter(
        ProcessDefinition.code == "report_flow", ProcessDefinition.is_deleted.is_(False)
    ).first()
    if not definition:
        definition = ProcessDefinition(
            code="report_flow", name="正式报告审核", entity_type="report",
            trigger_condition={}, version=1, active=True,
            description="正式报告发布前由 CIO 审核；发布后当前版本不可修改。",
        )
        db.add(definition)
        db.flush()
        db.add(ProcessStep(
            definition_id=definition.id, seq=1, step_code="report_approval",
            name="管理审核", node_type="approval", default_role="cio", cc_roles=[],
            autonomy_level="L3", sla_hours=24,
        ))
    db.commit()


def _digest(payload: Any) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_value, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def generate_report_version(db: Session, actor: AuthUser, report: ReportInstance, idempotency_key: str) -> ReportVersion:
    if not idempotency_key or len(idempotency_key) > 128:
        raise AppError("IDEMPOTENCY_KEY_REQUIRED", "生成报告必须提供有效的幂等键", 400)
    template = db.get(ReportTemplate, report.template_id)
    if not template or template.is_deleted or not template.active:
        raise AppError("REPORT_TEMPLATE_NOT_FOUND", "报告模板不存在或已停用", 404)
    request_payload = {
        "report_id": report.id, "period_start": report.period_start, "period_end": report.period_end,
        "filters": report.filters or {}, "metric_codes": template.metric_codes or [],
    }
    request_digest = _digest(request_payload)
    existing = db.query(ReportGenerationJob).filter(
        ReportGenerationJob.actor_id == actor.id,
        ReportGenerationJob.idempotency_key == idempotency_key,
        ReportGenerationJob.is_deleted.is_(False),
    ).first()
    if existing:
        if existing.request_digest != request_digest:
            raise AppError("IDEMPOTENCY_CONFLICT", "同一幂等键对应了不同的报告生成请求", 409)
        if existing.status == "completed" and existing.version_id:
            return db.get(ReportVersion, existing.version_id)
        raise AppError("REPORT_GENERATION_RUNNING", "报告正在生成，请勿重复提交", 409)
    job = ReportGenerationJob(
        report_instance_id=report.id, actor_id=actor.id, idempotency_key=idempotency_key,
        request_digest=request_digest, status="running",
    )
    db.add(job)
    db.flush()
    snapshot = query_metrics(db, actor, template.metric_codes or [], report.period_start, report.period_end, report.filters or {})
    next_version = report.current_version + 1
    formula_versions = {code: METRIC_MAP[code].formula_version for code in template.metric_codes or []}
    version_payload = {"snapshot": snapshot, "formula_versions": formula_versions, "version": next_version}
    version = ReportVersion(
        report_instance_id=report.id, version=next_version, status="draft",
        metric_snapshot=snapshot, narrative={}, formula_versions=formula_versions,
        data_quality={item["code"]: item["quality"] for item in snapshot["metrics"]},
        checksum=_digest(version_payload), generated_by=actor.id, generated_at=datetime.now(),
    )
    db.add(version)
    db.flush()
    report.current_version = next_version
    report.status = "draft"
    report.process_instance_id = None
    report.locked_at = None
    job.status = "completed"
    job.version_id = version.id
    job.completed_at = datetime.now()
    db.commit()
    db.refresh(version)
    return version


def can_view_report(db: Session, actor: AuthUser, report: ReportInstance) -> bool:
    template = db.get(ReportTemplate, report.template_id)
    if not template:
        return False
    for code in template.metric_codes or []:
        definition = METRIC_MAP.get(code)
        sensitive_module = {
            "finance": "reports_finance", "people": "reports_people", "platform": "reports_platform",
        }.get(definition.sensitivity if definition else "")
        if sensitive_module and not has_perm(db, actor, sensitive_module, "view"):
            return False
    if has_perm(db, actor, "reports_publish", "view") or report.created_by == actor.id:
        return True
    if not report.published_version:
        return False
    audiences = db.query(ReportAudience).filter(
        ReportAudience.report_instance_id == report.id, ReportAudience.is_deleted.is_(False)
    ).all()
    roles = effective_roles(db, actor)
    group_ids: set[str] = set()
    if actor.person_id:
        group_ids = {row.group_id for row in db.query(UserGroupMember).filter(
            UserGroupMember.person_id == actor.person_id, UserGroupMember.is_deleted.is_(False)
        )}
    return any(
        (row.subject_type == "user" and row.subject_id == actor.id)
        or (row.subject_type == "role" and row.subject_id in roles)
        or (row.subject_type == "group" and row.subject_id in group_ids)
        for row in audiences
    )


def replace_report_audience(db: Session, report: ReportInstance, audience: list[dict]):
    db.query(ReportAudience).filter(ReportAudience.report_instance_id == report.id).delete(synchronize_session=False)
    seen = set()
    for item in audience:
        key = (item.get("subject_type"), item.get("subject_id"))
        if key in seen or key[0] not in {"user", "role", "group"} or not key[1]:
            continue
        valid = (
            key[0] == "user" and db.query(AuthUser.id).filter(AuthUser.id == key[1], AuthUser.is_active.is_(True), AuthUser.is_deleted.is_(False)).first()
        ) or (
            key[0] == "role" and db.query(Role.id).filter(Role.code == key[1], Role.is_deleted.is_(False)).first()
        ) or (
            key[0] == "group" and db.query(UserGroup.id).filter(UserGroup.id == key[1], UserGroup.is_deleted.is_(False)).first()
        )
        if not valid:
            raise AppError("REPORT_AUDIENCE_INVALID", "发布受众包含不存在或已停用的用户、角色或用户组", 400)
        seen.add(key)
        db.add(ReportAudience(report_instance_id=report.id, subject_type=key[0], subject_id=key[1]))


def publish_report(db: Session, actor: AuthUser, report: ReportInstance, audience: list[dict]) -> ReportVersion:
    if not has_perm(db, actor, "reports_publish", "create"):
        raise AppError("FORBIDDEN", "没有报表发布权限", 403)
    if report.status != "approved" or not report.current_version:
        raise AppError("REPORT_NOT_APPROVED", "报告必须审批通过后才能发布", 409)
    version = db.query(ReportVersion).filter(
        ReportVersion.report_instance_id == report.id,
        ReportVersion.version == report.current_version,
        ReportVersion.is_deleted.is_(False),
    ).first()
    if not version:
        raise AppError("REPORT_VERSION_NOT_FOUND", "当前报告版本不存在", 404)
    now = datetime.now()
    version.status = "locked"
    version.locked_at = now
    report.status = "published"
    report.published_version = version.version
    report.published_at = now
    report.locked_at = now
    replace_report_audience(db, report, audience)
    db.commit()
    return version


def report_version_payload(version: ReportVersion) -> dict:
    return {
        "id": version.id, "version": version.version, "status": version.status,
        "metric_snapshot": version.metric_snapshot, "narrative": version.narrative,
        "formula_versions": version.formula_versions, "data_quality": version.data_quality,
        "checksum": version.checksum, "generated_by": version.generated_by,
        "generated_at": _json_value(version.generated_at), "locked_at": _json_value(version.locked_at),
    }
