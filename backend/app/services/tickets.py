"""工单域业务逻辑（PRD §5.1）。"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.rbac import MANAGER
from app.events import notifier
from app.events.bus import publish
from app.models import AuthUser, OrgMember, ServiceItem, Ticket
from app.services import process_engine, sla
from app.services.audit import audit
from app.services.codes import gen_code
from app.services.workflow import transition as wf_transition

CHANGE = "change"
TICKET_TYPES = ("incident", "service_request", "change")


def entity_type_of(ticket: Ticket) -> str:
    return "ticket_change" if ticket.ticket_type == CHANGE else "ticket"


def _manager_person_ids(db: Session) -> list[str]:
    users = db.query(AuthUser).filter(AuthUser.is_active.is_(True)).all()
    return [u.person_id for u in users if u.person_id and MANAGER in (u.roles or [])]


def create_ticket(db: Session, data: dict, actor: AuthUser) -> Ticket:
    if data["ticket_type"] not in TICKET_TYPES:
        raise AppError("INVALID_TYPE", "工单类型无效")
    item = db.get(ServiceItem, data["service_item_id"])
    if not item or item.is_deleted or item.status != "上架":
        raise AppError("INVALID_ITEM", "服务项不存在或已下架")
    if data["ticket_type"] == CHANGE and not data.get("change_type"):
        raise AppError("STAGE_FIELD_REQUIRED", "变更工单必须选择变更类型")

    now = datetime.now()
    resp_min, reso_hours = sla.resolve_targets(db, data["priority"], item)
    person = db.get(OrgMember, actor.person_id) if actor.person_id else None

    ticket = Ticket(
        **data,
        ticket_code=gen_code(db, Ticket, "ticket_code", "TK"),
        status="new",
        submitter=actor.id,
        submitter_name=person.name if person else actor.username,
        submitter_dept=person.dept if person else None,
        service_line=item.catalog.name,
        submitted_at=now,
        sla_response_min=resp_min,
        sla_resolution_hours=reso_hours,
    )
    db.add(ticket)
    db.flush()

    process_engine.start_instance(
        db,
        entity_type_of(ticket),
        ticket.id,
        {"ticket_type": ticket.ticket_type},
        preferred_assignee=ticket.assignee,
    )
    audit(db, "ticket", ticket.id, "create", actor, {"code": ticket.ticket_code, "type": ticket.ticket_type})
    publish(db, "ticket.created", "ticket", ticket.id, {"code": ticket.ticket_code})

    if ticket.assignee:
        notifier.notify(
            db, "ticket.assigned", "ticket", ticket.id,
            [ticket.assignee],
            f"新工单指派：{ticket.ticket_code} {ticket.title}",
            link=f"/itsm/tickets/{ticket.id}",
        )
    db.commit()
    return ticket


def do_transition(db: Session, ticket: Ticket, to: str, fields: dict, actor: AuthUser) -> Ticket:
    now = datetime.now()
    etype = entity_type_of(ticket)
    from_code, _ = wf_transition(db, ticket, etype, to, fields, actor)

    # 打点与派生
    if from_code == "new" and to != "new":
        sla.mark_first_response(ticket, now)
    if to == "paused":
        ticket.paused_started_at = now
    if from_code == "paused" and to != "paused":
        if ticket.paused_started_at:
            ticket.paused_minutes = (ticket.paused_minutes or 0) + (now - ticket.paused_started_at).total_seconds() / 60
            ticket.paused_started_at = None
    if to == "resolved":
        sla.mark_resolved(ticket, now)
        publish(db, "ticket.resolved", "ticket", ticket.id, {})
        if ticket.submitter:
            submitter_user = db.get(AuthUser, ticket.submitter)
            if submitter_user and submitter_user.person_id:
                notifier.notify(
                    db, "ticket.resolved", "ticket", ticket.id,
                    [submitter_user.person_id],
                    f"您的工单已解决：{ticket.ticket_code} {ticket.title}，请确认并评价",
                    link=f"/itsm/tickets/{ticket.id}",
                )
    if from_code == "resolved" and to == "processing":  # 重开
        ticket.reopen_count = (ticket.reopen_count or 0) + 1
        ticket.resolved_at = None
        ticket.sla_resolution_met = None
        ticket.first_time_fix = False
    if to == "closed":
        ticket.closed_at = now
        publish(db, "ticket.closed", "ticket", ticket.id, {"sla_met": bool(ticket.sla_resolution_met)})
    # 变更审批
    if to == "pending_approval":
        publish(db, "change.approval_requested", "ticket", ticket.id, {})
        managers = _manager_person_ids(db)
        if managers:
            notifier.notify(
                db, "change.approval_requested", "ticket", ticket.id,
                managers,
                f"变更待审批：{ticket.ticket_code} {ticket.title}（风险 {ticket.risk_level or '-'}）",
                link=f"/itsm/tickets/{ticket.id}",
            )
    if to in ("approved", "rejected"):
        ticket.approved_by = actor.id
        ticket.approved_at = now
        ticket.approval_comment = fields.get("approval_comment") or ticket.approval_comment
        publish(db, f"change.{to}", "ticket", ticket.id, {})

    db.commit()
    return ticket


def rate_satisfaction(db: Session, ticket: Ticket, score: int, actor: AuthUser) -> Ticket:
    if ticket.status != "closed":
        raise AppError("NOT_CLOSED", "工单关闭后才能评价")
    if ticket.submitter != actor.id:
        raise AppError("FORBIDDEN", "只有提交人可以评价", 403)
    if not 1 <= score <= 5:
        raise AppError("INVALID_SCORE", "评分须为 1-5")
    ticket.satisfaction = score
    audit(db, "ticket", ticket.id, "satisfaction", actor, {"score": score})
    if score >= 4:
        publish(db, "ticket.satisfaction_rated", "ticket", ticket.id, {"score": score})
    db.commit()
    return ticket
