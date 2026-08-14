"""内置定时扫描：SLA 升级、Aily 发件箱和 AI 提供商安全复探。"""
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
AILY_OUTBOX_INTERVAL_SECONDS = 5
AI_PROVIDER_PROBE_REFRESH_INTERVAL_SECONDS = 10 * 60
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


def scan_overdue_milestones():
    from datetime import date

    from app.models import Milestone, Project

    with SessionLocal() as db:
        today = date.today()
        rows = (
            db.query(Milestone, Project)
            .join(Project, Project.id == Milestone.project_id)
            .filter(
                Milestone.achieved_at.is_(None),
                Milestone.target_date < today,
                Milestone.overdue_warned.is_(False),
                Milestone.is_deleted.is_(False),
                Project.status.in_(["planning", "active", "paused"]),
                Project.is_deleted.is_(False),
            )
            .all()
        )
        for m, p in rows:
            m.overdue_warned = True
            recipients = [r for r in {p.pm} if r]
            if recipients:
                notifier.notify(
                    db, "milestone.overdue", "project", p.id,
                    recipients,
                    f"里程碑逾期：{p.name} / {m.name}（目标 {m.target_date}）",
                    link=f"/projects/{p.id}",
                )
        db.commit()


def scan_feishu_org_sync():
    """按管理员配置的周期自动同步飞书组织；先登记尝试时间，防止失败时高频重试。"""
    from datetime import timedelta
    from app.services.feishu import is_enabled
    from app.services.org_settings import get_org_settings
    from app.services.org_sync import run_sync

    with SessionLocal() as db:
        settings = get_org_settings(db)
        if not settings.feishu_auto_sync_enabled or not is_enabled(db):
            db.commit()
            return
        now = datetime.now()
        last = settings.feishu_auto_sync_last_attempt_at
        if last and now - last < timedelta(minutes=settings.feishu_auto_sync_interval_minutes):
            db.commit()
            return
        settings.feishu_auto_sync_last_attempt_at = now
        db.commit()
        run_sync(db, "feishu")


def scan_aily_confirmation_reminders():
    from app.services.aily_ticket_notifications import scan_pending_confirmation_reminders

    scan_pending_confirmation_reminders()


SCANNERS = [
    scan_sla_warnings,
    scan_contract_expiry,
    scan_overdue_milestones,
    scan_feishu_org_sync,
    scan_aily_confirmation_reminders,
]


async def run_forever():
    while True:
        for scan in SCANNERS:
            try:
                scan()
            except Exception:
                logger.exception("scheduler scan failed: %s", scan.__name__)
        await asyncio.sleep(INTERVAL_SECONDS)


async def run_aily_outbox_forever():
    """高频消费 Aily 机器人可靠消息发件箱。"""
    from app.services.aily import scan_aily_outbox

    while True:
        try:
            scan_aily_outbox()
        except Exception:
            logger.exception("Aily outbox scan failed")
        await asyncio.sleep(AILY_OUTBOX_INTERVAL_SECONDS)


async def scan_ai_provider_probe_refresh():
    """Refresh unchanged enabled model-provider probes before their 15m expiry."""
    from app.core.errors import AppError
    from app.services import assistant_config

    with SessionLocal() as db:
        provider_ids = assistant_config.list_provider_ids_due_for_automatic_probe(db)

    for provider_id in provider_ids:
        with SessionLocal() as db:
            try:
                result = await assistant_config.probe_provider(
                    db,
                    provider_id,
                    None,
                    trigger="automatic",
                    require_enabled=True,
                )
                if result is not None:
                    logger.info("automatic AI provider probe succeeded: provider_id=%s", provider_id)
            except AppError as exc:
                logger.warning(
                    "automatic AI provider probe failed: provider_id=%s code=%s",
                    provider_id,
                    exc.code,
                )
            except Exception:
                logger.exception("automatic AI provider probe failed: provider_id=%s", provider_id)


async def run_ai_provider_probe_refresh_forever():
    """Keep active, unchanged model providers safely verified without UI work."""
    while True:
        try:
            await scan_ai_provider_probe_refresh()
        except Exception:
            logger.exception("AI provider probe refresh scanner failed")
        await asyncio.sleep(AI_PROVIDER_PROBE_REFRESH_INTERVAL_SECONDS)
