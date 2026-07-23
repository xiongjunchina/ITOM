"""总览 Dashboard：单接口一次聚合（PRD §4）。

M2：服务板块聚合 + SLA 告警；M3：问题关闭率 + 合同到期告警；其余随 M4-M6 填充。
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_perm
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

    priority_levels = ("P1", "P2", "P3", "P4")

    def _priority_counts(items):
        """Return the open workload split by ITSM priority for a single module."""
        return {p: sum(1 for item in items if item.priority == p) for p in priority_levels}

    open_service_requests = [t for t in open_tickets if t.ticket_type == "service_request"]
    open_changes = [t for t in open_tickets if t.ticket_type == "change"]
    open_incidents = [t for t in open_tickets if t.ticket_type == "incident"]
    open_by_priority = _priority_counts(open_tickets)

    by_type = {
        "service_request_open": sum(1 for t in open_tickets if t.ticket_type == "service_request"),
        "incident_open": sum(1 for t in open_tickets if t.ticket_type == "incident"),
        "change_pending_approval": sum(1 for t in tickets if t.ticket_type == "change" and t.status == "pending_approval"),
        "change_implementing": sum(1 for t in tickets if t.ticket_type == "change" and t.status in ("approved", "implementing")),
    }

    problems = db.query(Problem).filter(Problem.is_deleted.is_(False)).all()
    problem_close_rate = (
        round(sum(1 for p in problems if p.status == "closed") / len(problems) * 100, 1) if problems else None
    )

    def _month_resolved(ttype):
        return sum(1 for t in tickets if t.ticket_type == ttype and t.resolved_at and t.resolved_at >= month_start)

    def _sla_rate(ttype):
        done = [t for t in tickets if t.ticket_type == ttype and t.resolved_at and t.resolved_at >= month_start
                and t.sla_resolution_met is not None]
        return round(sum(1 for t in done if t.sla_resolution_met) / len(done) * 100, 1) if done else None

    itsm_blocks = {
        "service_request": {
            "open": by_type["service_request_open"],
            "open_by_priority": _priority_counts(open_service_requests),
            "month_resolved": _month_resolved("service_request"),
            "sla_rate": _sla_rate("service_request"),
        },
        "change": {
            "open": len(open_changes),
            "open_by_priority": _priority_counts(open_changes),
            "pending_approval": by_type["change_pending_approval"],
            "implementing": by_type["change_implementing"],
            "success_rate": change_rate,
        },
        "incident": {
            "open": by_type["incident_open"],
            "open_by_priority": _priority_counts(open_incidents),
            "sla_warned": sum(1 for t in open_tickets if t.ticket_type == "incident" and t.sla_warned),
            "month_resolved": _month_resolved("incident"),
            "sla_rate": _sla_rate("incident"),
        },
        "problem": {
            "open": sum(1 for p in problems if p.status not in ("closed",)),
            "open_by_priority": _priority_counts([p for p in problems if p.status not in ("closed",)]),
            "known_errors": sum(1 for p in problems if p.status == "known_error"),
            "close_rate": problem_close_rate,
        },
    }

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
            "by_type": by_type,
            "itsm_blocks": itsm_blocks,
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


def _team_section(db: Session) -> dict:
    from app.models import DevelopmentActivity, HiringNeed, PointEntry, OrgMember
    from app.services.points import current_period, period_clause
    from sqlalchemy import func as _f
    from app.services.team_scope import it_member_ids

    period = current_period()
    team_ids = it_member_ids(db)
    board = (
        db.query(PointEntry.person_id, _f.sum(PointEntry.points))
        .filter(period_clause(PointEntry.period, period), PointEntry.person_id.in_(team_ids or {"-"}), PointEntry.is_deleted.is_(False))
        .group_by(PointEntry.person_id)
        .order_by(_f.sum(PointEntry.points).desc())
        .limit(5)
        .all()
    )
    names = {m.id: m.name for m in db.query(OrgMember).filter(OrgMember.id.in_(team_ids or {"-"}))}
    month_start = date.today().replace(day=1)
    trainings = (
        db.query(DevelopmentActivity)
        .filter(DevelopmentActivity.activity_date >= month_start, DevelopmentActivity.is_deleted.is_(False))
        .count()
    )
    from app.routers.team_mgmt import _workload

    workload = _workload(db)[:5]
    return {
        "top_workload": [{"name": w["person_name"], "value": w["total"]} for w in workload],
        "top_points": [{"name": names.get(pid), "value": round(float(pts), 1)} for pid, pts in board],
        "trainings": trainings,
        "hirings": db.query(HiringNeed).filter(
            HiringNeed.is_deleted.is_(False), HiringNeed.status.in_(["待招聘", "面试中"])
        ).count(),
    }


def _requirement_section(db: Session) -> dict:
    rows = db.query(Requirement).filter(Requirement.is_deleted.is_(False)).all()
    by_stage = {"registered": 0, "evaluating": 0, "analyzing": 0, "implementing": 0, "closed": 0}
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
def dashboard(db: Session = Depends(get_db), user=Depends(require_perm("dashboard", "view"))):  # M19：接口层强制，不只菜单隐藏
    """总览聚合（M22：按用户权限矩阵裁剪板块——无权限的模块不聚合、不下发）。"""
    from app.services.permissions import has_perm

    def can(module: str) -> bool:
        return has_perm(db, user, module, "view")

    any_ticket = can("ticket_sr") or can("ticket_incident") or can("ticket_change")
    payload: dict = {"alerts": []}

    if any_ticket or can("problems") or can("contracts"):
        service, service_alerts = _service_section(db)
        blocks = service["itsm_blocks"]
        for key, module in (("service_request", "ticket_sr"), ("change", "ticket_change"),
                            ("incident", "ticket_incident"), ("problem", "problems")):
            if not can(module):
                blocks.pop(key, None)
        if not any_ticket:  # 仅问题/合同权限：工单级聚合不下发
            for k in ("open_tickets", "open_by_priority", "by_type", "sla_rate", "change_success_rate"):
                service.pop(k, None)
        payload["service"] = service
        payload["alerts"] += [
            a for a in service_alerts
            if (a["type"] == "sla_warning" and any_ticket) or (a["type"] == "contract_expiring" and can("contracts"))
        ]
    if can("projects"):
        project_section, project_alerts = _project_section(db)
        payload["project"] = project_section
        payload["alerts"] += project_alerts
    if can("requirements"):
        payload["requirement"] = _requirement_section(db)
    if can("team_overview"):
        payload["team"] = _team_section(db)
    return ok(payload)
