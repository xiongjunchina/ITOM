"""SLA 引擎（docs/05 §6.5）：目标匹配 + 达成判定，挂起时间扣除。"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import ServiceItem, SlaPolicy, Ticket


def resolve_targets(db: Session, priority: str, item: ServiceItem | None) -> tuple[float | None, float | None]:
    """返回 (响应分钟, 解决小时)。服务项覆盖优先，否则按优先级策略。"""
    resp_min = None
    reso_hours = None
    if item:
        if item.sla_response_hours is not None:
            resp_min = item.sla_response_hours * 60
        if item.sla_resolution_hours is not None:
            reso_hours = item.sla_resolution_hours
    if resp_min is None or reso_hours is None:
        policy = (
            db.query(SlaPolicy)
            .filter(SlaPolicy.priority == priority, SlaPolicy.active.is_(True))
            .first()
        )
        if policy:
            resp_min = resp_min if resp_min is not None else policy.response_minutes
            reso_hours = reso_hours if reso_hours is not None else policy.resolution_hours
    return resp_min, reso_hours


def effective_minutes(ticket: Ticket, until: datetime) -> float:
    """开单至 until 的有效分钟数（扣除挂起累计；若当前正挂起，扣除进行中的挂起段）。"""
    if not ticket.submitted_at:
        return 0
    total = (until - ticket.submitted_at).total_seconds() / 60
    paused = ticket.paused_minutes or 0
    if ticket.paused_started_at:
        paused += (until - ticket.paused_started_at).total_seconds() / 60
    return max(total - paused, 0)


def mark_first_response(ticket: Ticket, now: datetime):
    if ticket.first_response_at:
        return
    ticket.first_response_at = now
    elapsed = effective_minutes(ticket, now)
    ticket.actual_response_min = round(elapsed, 1)
    if ticket.sla_response_min is not None:
        ticket.sla_response_met = elapsed <= ticket.sla_response_min


def mark_resolved(ticket: Ticket, now: datetime):
    ticket.resolved_at = now
    elapsed_hours = effective_minutes(ticket, now) / 60
    ticket.actual_resolution_hours = round(elapsed_hours, 2)
    if ticket.sla_resolution_hours is not None:
        ticket.sla_resolution_met = elapsed_hours <= ticket.sla_resolution_hours
    ticket.first_time_fix = (ticket.reopen_count or 0) == 0
