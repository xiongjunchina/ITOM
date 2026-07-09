"""总览 Dashboard：单接口一次聚合（PRD §4）。

M2：服务板块真实聚合 + SLA 告警；其余板块随 M3-M6 填充。
"""
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Ticket
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

    alerts = [
        {
            "type": "sla_warning",
            "title": f"SLA 临期：{t.ticket_code} {t.title}",
            "link": f"/itsm/tickets/{t.id}",
        }
        for t in open_tickets
        if t.sla_warned
    ]
    return (
        {
            "open_tickets": len(open_tickets),
            "open_by_priority": open_by_priority,
            "sla_rate": sla_rate,
            "change_success_rate": change_rate,
            "problem_close_rate": None,  # M3
        },
        alerts,
    )


@router.get("")
def dashboard(db: Session = Depends(get_db), _=Depends(get_current_user)):
    service, alerts = _service_section(db)
    return ok(
        {
            "service": service,
            "project": {
                "active": 0,
                "health": {"green": 0, "yellow": 0, "red": 0},
                "overdue_milestones": 0,
                "budget_usage": None,
            },
            "requirement": {
                "by_stage": {"registered": 0, "analyzing": 0, "implementing": 0, "closed": 0},
                "avg_lead_days": None,
            },
            "team": {"top_workload": [], "top_points": [], "trainings": 0, "hirings": 0},
            "alerts": alerts,
        }
    )
