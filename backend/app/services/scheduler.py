"""内置定时扫描（docs/05 §5）：每 15 分钟。M2 交付 SLA 临期升级。"""
import asyncio
import logging
from datetime import datetime

from app.core.rbac import MANAGER
from app.db import SessionLocal
from app.events import notifier
from app.models import AuthUser, Ticket
from app.services import sla

logger = logging.getLogger("aom.scheduler")

INTERVAL_SECONDS = 15 * 60
WARN_RATIO = 0.8  # PRD §5.1：超 SLA 目标 80% 未解决触发升级


def scan_sla_warnings():
    with SessionLocal() as db:
        now = datetime.now()
        open_tickets = (
            db.query(Ticket)
            .filter(
                Ticket.status.notin_(["resolved", "closed", "rejected"]),
                Ticket.priority.in_(["P1", "P2"]),
                Ticket.sla_warned.is_(False),
                Ticket.sla_resolution_hours.isnot(None),
                Ticket.is_deleted.is_(False),
            )
            .all()
        )
        managers = [
            u.person_id
            for u in db.query(AuthUser).filter(AuthUser.is_active.is_(True)).all()
            if u.person_id and MANAGER in (u.roles or [])
        ]
        for t in open_tickets:
            elapsed_hours = sla.effective_minutes(t, now) / 60
            if elapsed_hours >= t.sla_resolution_hours * WARN_RATIO:
                t.sla_warned = True
                recipients = [r for r in {t.assignee, *managers} if r]
                if recipients:
                    notifier.notify(
                        db, "ticket.sla_warning", "ticket", t.id,
                        recipients,
                        f"SLA 临期升级：{t.ticket_code} {t.title}（已用 {elapsed_hours:.1f}h / 目标 {t.sla_resolution_hours}h）",
                        link=f"/itsm/tickets/{t.id}",
                    )
        db.commit()


SCANNERS = [scan_sla_warnings]


async def run_forever():
    while True:
        for scan in SCANNERS:
            try:
                scan()
            except Exception:
                logger.exception("scheduler scan failed: %s", scan.__name__)
        await asyncio.sleep(INTERVAL_SECONDS)
