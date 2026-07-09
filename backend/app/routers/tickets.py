"""工单路由（PRD §5.1）。"""
from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.rbac import REQUESTER
from app.db import get_db
from app.deps import get_current_user
from app.models import AuthUser, OrgMember, Ticket
from app.schemas.common import ok, paginate
from app.schemas.itsm import SatisfactionIn, TicketCreate, TicketUpdate, TransitionIn
from app.services import process_engine
from app.services import tickets as svc
from app.services.audit import audit
from app.services.workflow import allowed_targets, status_names

router = APIRouter(prefix="/api/tickets", tags=["itsm"])


def _is_requester_only(user: AuthUser) -> bool:
    roles = set(user.roles or [])
    return roles == {REQUESTER}


def _row(t: Ticket, db: Session, names: dict) -> dict:
    assignee = db.get(OrgMember, t.assignee) if t.assignee else None
    return {
        "id": t.id, "ticket_code": t.ticket_code, "title": t.title,
        "ticket_type": t.ticket_type, "priority": t.priority,
        "status": t.status, "status_name": names.get(t.status, t.status),
        "service_item_id": t.service_item_id,
        "service_item_name": t.service_item.name if t.service_item else None,
        "service_line": t.service_line,
        "submitter_name": t.submitter_name, "submitter_dept": t.submitter_dept,
        "assignee": t.assignee, "assignee_name": assignee.name if assignee else None,
        "submitted_at": t.submitted_at,
        "sla_resolution_hours": t.sla_resolution_hours,
        "sla_response_met": t.sla_response_met, "sla_resolution_met": t.sla_resolution_met,
        "sla_warned": t.sla_warned, "satisfaction": t.satisfaction,
    }


@router.get("")
def list_tickets(
    page: int = 1,
    page_size: int = 20,
    q: str = "",
    status: str = "",
    ticket_type: str = "",
    priority: str = "",
    assignee: str = "",
    scope: str = "",
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    query = db.query(Ticket).filter(Ticket.is_deleted.is_(False))
    if _is_requester_only(user) or scope == "mine":
        query = query.filter(or_(Ticket.submitter == user.id, Ticket.assignee == (user.person_id or "-")))
    if q:
        query = query.filter(or_(Ticket.title.ilike(f"%{q}%"), Ticket.ticket_code.ilike(f"%{q}%")))
    if status:
        query = query.filter(Ticket.status == status)
    if ticket_type:
        query = query.filter(Ticket.ticket_type == ticket_type)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if assignee:
        query = query.filter(Ticket.assignee == assignee)
    items, total = paginate(query.order_by(Ticket.submitted_at.desc()), page, page_size)
    names = {**status_names(db, "ticket"), **status_names(db, "ticket_change")}
    return ok([_row(t, db, names) for t in items], total=total, page=page)


@router.post("")
def create_ticket(body: TicketCreate, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    ticket = svc.create_ticket(db, body.model_dump(exclude_none=True), user)
    names = {**status_names(db, "ticket"), **status_names(db, "ticket_change")}
    return ok(_row(ticket, db, names))


def _get_ticket(db: Session, ticket_id: str, user: AuthUser) -> Ticket:
    t = db.get(Ticket, ticket_id)
    if not t or t.is_deleted:
        raise AppError("NOT_FOUND", "工单不存在", 404)
    if _is_requester_only(user) and t.submitter != user.id:
        raise AppError("FORBIDDEN", "无权查看他人工单", 403)
    return t


@router.get("/{ticket_id}")
def get_ticket(ticket_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    t = _get_ticket(db, ticket_id, user)
    etype = svc.entity_type_of(t)
    names = status_names(db, etype)
    detail = _row(t, db, names)
    detail.update(
        {
            "submitter": t.submitter,
            "description": t.description, "remarks": t.remarks, "ci_id": t.ci_id,
            "solution": t.solution, "root_cause": t.root_cause, "closure_code": t.closure_code,
            "change_type": t.change_type, "risk_level": t.risk_level,
            "change_reason": t.change_reason, "rollback_plan": t.rollback_plan,
            "planned_start_at": t.planned_start_at, "planned_end_at": t.planned_end_at,
            "implementation_plan": t.implementation_plan,
            "approved_at": t.approved_at, "approval_comment": t.approval_comment,
            "first_response_at": t.first_response_at, "resolved_at": t.resolved_at, "closed_at": t.closed_at,
            "paused_minutes": t.paused_minutes, "reopen_count": t.reopen_count,
            "first_time_fix": t.first_time_fix,
            "sla_response_min": t.sla_response_min,
            "actual_response_min": t.actual_response_min, "actual_resolution_hours": t.actual_resolution_hours,
            "allowed_transitions": [
                {"to": code, "to_name": names.get(code, code)}
                for code in allowed_targets(db, etype, t.status, user)
            ],
            "process": process_engine.instance_view(db, etype, t.id),
        }
    )
    return ok(detail)


@router.patch("/{ticket_id}")
def update_ticket(ticket_id: str, body: TicketUpdate, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    t = _get_ticket(db, ticket_id, user)
    if t.status in ("closed", "rejected"):
        raise AppError("TICKET_FINAL", "终态工单不可编辑")
    data = body.model_dump(exclude_unset=True)
    reassigned = "assignee" in data and data["assignee"] != t.assignee
    for k, v in data.items():
        setattr(t, k, v)
    audit(db, "ticket", t.id, "update", user, {"fields": list(data.keys())})
    if reassigned and t.assignee:
        from app.events import notifier

        notifier.notify(
            db, "ticket.assigned", "ticket", t.id, [t.assignee],
            f"工单改派给您：{t.ticket_code} {t.title}", link=f"/itsm/tickets/{t.id}",
        )
    db.commit()
    return ok({"id": t.id})


@router.post("/{ticket_id}/transition")
def transition_ticket(ticket_id: str, body: TransitionIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    t = _get_ticket(db, ticket_id, user)
    svc.do_transition(db, t, body.to, body.fields, user)
    return ok({"id": t.id, "status": t.status})


@router.post("/{ticket_id}/satisfaction")
def rate(ticket_id: str, body: SatisfactionIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    t = _get_ticket(db, ticket_id, user)
    svc.rate_satisfaction(db, t, body.score, user)
    return ok({"id": t.id, "satisfaction": t.satisfaction})
