"""总览 Dashboard：单接口一次聚合（PRD §4）。

M2：服务板块聚合 + SLA 告警；M3：问题关闭率 + 合同到期告警；其余随 M4-M6 填充。
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Contract, Milestone, Problem, Project, Requirement, Ticket
from app.schemas.common import ok

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

OPEN_STATUSES_EXCLUDED = ["resolved", "closed", "rejected"]


def _service_section(db: Session) -> tuple[dict, list]:
    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    tickets = db.query(Ticket).filter(Ticket.is_deleted.is_(False)).all()

    open_tickets = [t for t in tickets if t.status not in OPEN_STATUSES_EXCLUDED]
    resolved_month = [t for t in tickets if t.resolved_at and t.resolved_at >= month_start and t.sla_resolution_met is not None]
    sla_rate = round(sum(1 for t in resolved_month if t.sla_resolution_met) / len(resolved_month) * 100, 1) if resolved_month else None

    changes_done = [t for t in tickets if t.ticket_type == "change" and t.status in ("closed", "rolled_back")]
    changes_ok = [t for t in changes_done if t.status == "closed" and t.closure_code != "cancelled"]
    change_rate = round(len(changes_ok) / len(changes_done) * 100, 1) if changes_done else None

    open_by_priority = {p: sum(1 for t in open_tickets if t.priority == p) for p in ("P1", "P2", "P3", "P4")}

    problems = db.query(Problem).filter(Problem.is_deleted.is_(False)).all()
    problem_close_rate = (
        round(sum(1 for p in problems if p.status == "closed") / len(problems) * 100, 1) if problems else None
    )

    alerts = [
        {
            "type": "sla_warning",
            "title": f"SLA 临期：{t.ticket_code} {t.title}",
            "link": f"/itsm/tickets/{t.id}",
        }
        for t in open_tickets
        if t.sla_warned
    ]
    expiring = (
        db.query(Contract)
        .filter(
            Contract.end_date <= date.today() + timedelta(days=90),
            Contract.end_date >= date.today(),
            Contract.is_deleted.is_(False),
        )
        .order_by(Contract.end_date)
        .all()
    )
    alerts += [
        {
            "type": "contract_expiring",
            "title": f"合同临期：{c.name}（{(c.end_date - date.today()).days} 天后到期）",
            "link": "/itsm/contracts",
        }
        for c in expiring
    ]
    return (
        {
            "open_tickets": len(open_tickets),
            "open_by_priority": open_by_priority,
            "sla_rate": sla_rate,
            "change_success_rate": change_rate,
            "problem_close_rate": problem_close_rate,
            "open_problems": sum(1 for p in problems if p.status not in ("closed",)),
        },
        alerts,
    )


def _project_section(db: Session) -> tuple[dict, list]:
    from app.services.projects import compute_metrics

    projects = db.query(Project).filter(Project.is_deleted.is_(False), Project.status.in_(["planning", "active", "paused"])).all()
    health = {"green": 0, "yellow": 0, "red": 0}
    overdue = 0
    budget_total = 0.0
    cost_total = 0.0
    alerts = []
    for p in projects:
        m = compute_metrics(db, p)
        health[m["health"]] = health.get(m["health"], 0) + 1
        overdue += m["milestone_overdue"]
        cost_total += m["actual_cost_10k"]
        if p.budget_10k:
            budget_total += p.budget_10k
        if m["health"] == "red":
            alerts.append({"type": "project_red", "title": f"红色健康度项目：{p.name}", "link": f"/projects/{p.id}"})
        if m["milestone_overdue"]:
            alerts.append({"type": "milestone_overdue", "title": f"里程碑逾期：{p.name}（{m['milestone_overdue']} 个）", "link": f"/projects/{p.id}"})
    return (
        {
            "active": sum(1 for p in projects if p.status == "active"),
            "health": health,
            "overdue_milestones": overdue,
            "budget_usage": round(cost_total / budget_total * 100, 1) if budget_total else None,
        },
        alerts,
    )


def _requirement_section(db: Session) -> dict:
    rows = db.query(Requirement).filter(Requirement.is_deleted.is_(False)).all()
    by_stage = {"registered": 0, "analyzing": 0, "implementing": 0, "closed": 0}
    for r in rows:
        if r.status in by_stage:
            by_stage[r.status] += 1
    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    closed_month = [r for r in rows if r.closed_at and r.closed_at >= month_start and r.registered_at]
    avg_lead = (
        round(sum((r.closed_at - r.registered_at).total_seconds() / 86400 for r in closed_month) / len(closed_month), 1)
        if closed_month else None
    )
    return {"by_stage": by_stage, "avg_lead_days": avg_lead}


@router.get("")
def dashboard(db: Session = Depends(get_db), _=Depends(get_current_user)):
    service, alerts = _service_section(db)
    project_section, project_alerts = _project_section(db)
    alerts = alerts + project_alerts
    return ok(
        {
            "service": service,
            "project": project_section,
            "requirement": _requirement_section(db),
            "team": {"top_workload": [], "top_points": [], "trainings": 0, "hirings": 0},
            "alerts": alerts,
        }
    )
