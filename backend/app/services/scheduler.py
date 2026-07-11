"""内置定时扫描（docs/05 §5）：每 15 分钟。M2 交付 SLA 临期升级。"""
import asyncio
import logging
from datetime import datetime

from app.core.rbac import CIO, IT_TM
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
        escalation_roles = {CIO, IT_TM}
        managers = [
            u.person_id
            for u in db.query(AuthUser).filter(AuthUser.is_active.is_(True)).all()
            if u.person_id and escalation_roles & set(u.roles or [])
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


def scan_contract_expiry():
    """合同到期前 90 天预警（每合同一次，续签改日期后重置）。"""
    from datetime import date, timedelta

    from app.models import Contract

    with SessionLocal() as db:
        threshold = date.today() + timedelta(days=90)
        expiring = (
            db.query(Contract)
            .filter(
                Contract.end_date <= threshold,
                Contract.end_date >= date.today(),
                Contract.expiry_warned.is_(False),
                Contract.is_deleted.is_(False),
            )
            .all()
        )
        escalation_roles = {CIO, IT_TM}
        managers = [
            u.person_id
            for u in db.query(AuthUser).filter(AuthUser.is_active.is_(True)).all()
            if u.person_id and escalation_roles & set(u.roles or [])
        ]
        for c in expiring:
            c.expiry_warned = True
            recipients = [r for r in {c.owner, *managers} if r]
            if recipients:
                days = (c.end_date - date.today()).days
                notifier.notify(
                    db, "contract.expiring", "contract", c.id,
                    recipients,
                    f"合同临期提醒：{c.name}（{days} 天后到期，{c.end_date}）",
                    link="/itsm/contracts",
                )
        db.commit()


SCANNERS = [scan_sla_warnings, scan_contract_expiry]


async def run_forever():
    while True:
        for scan in SCANNERS:
            try:
                scan()
            except Exception:
                logger.exception("scheduler scan failed: %s", scan.__name__)
        await asyncio.sleep(INTERVAL_SECONDS)
