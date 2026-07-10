"""问题管理（PRD §5.2）：手工创建 / 工单升级转入 / (M5)需求遗留转入。"""
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import get_current_user
from app.events.bus import publish
from app.models import AuthUser, OrgMember, Problem, ProblemTicket, ServiceItem, Ticket
from app.schemas.common import ok, paginate
from app.services import process_engine
from app.services.audit import audit
from app.services.codes import gen_code
from app.services.workflow import allowed_targets, status_names
from app.services.workflow import transition as wf_transition

router = APIRouter(tags=["itsm"])


class ProblemCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=1)
    priority: str = "P3"
    service_item_id: str | None = None
    owner: str | None = None


class ProblemUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    service_item_id: str | None = None
    owner: str | None = None
    workaround: str | None = None
    root_cause: str | None = None


class TransitionIn(BaseModel):
    to: str
    fields: dict = {}


class LinkTicketIn(BaseModel):
    ticket_id: str


def _row(p: Problem, db: Session, names: dict) -> dict:
    owner = db.get(OrgMember, p.owner) if p.owner else None
    item = db.get(ServiceItem, p.service_item_id) if p.service_item_id else None
    ticket_count = (
        db.query(ProblemTicket).filter(ProblemTicket.problem_id == p.id, ProblemTicket.is_deleted.is_(False)).count()
    )
    return {
        "id": p.id, "problem_code": p.problem_code, "title": p.title,
        "priority": p.priority, "status": p.status, "status_name": names.get(p.status, p.status),
        "service_item_id": p.service_item_id, "service_item_name": item.name if item else None,
        "owner": p.owner, "owner_name": owner.name if owner else None,
        "linked_ticket_count": ticket_count,
        "created_at": p.created_at,
    }


def _create_problem(db: Session, data: dict, actor: AuthUser, source_ticket: Ticket | None = None) -> Problem:
    problem = Problem(
        **data,
        problem_code=gen_code(db, Problem, "problem_code", "PB"),
        source_ticket_id=source_ticket.id if source_ticket else None,
    )
    db.add(problem)
    db.flush()
    if source_ticket:
        db.add(ProblemTicket(problem_id=problem.id, ticket_id=source_ticket.id))
        source_ticket.problem_id = problem.id
    process_engine.start_instance(db, "problem", problem.id, {}, preferred_assignee=problem.owner)
    audit(db, "problem", problem.id, "create", actor, {"code": problem.problem_code, "from_ticket": source_ticket.ticket_code if source_ticket else None})
    publish(db, "problem.created", "problem", problem.id, {})
    return problem


@router.get("/api/problems")
def list_problems(
    page: int = 1, page_size: int = 20, q: str = "", status: str = "", priority: str = "",
    db: Session = Depends(get_db), _: AuthUser = Depends(get_current_user),
):
    query = db.query(Problem).filter(Problem.is_deleted.is_(False))
    if q:
        query = query.filter(or_(Problem.title.ilike(f"%{q}%"), Problem.problem_code.ilike(f"%{q}%")))
    if status:
        query = query.filter(Problem.status == status)
    if priority:
        query = query.filter(Problem.priority == priority)
    items, total = paginate(query.order_by(Problem.created_at.desc()), page, page_size)
    names = status_names(db, "problem")
    return ok([_row(p, db, names) for p in items], total=total, page=page)


@router.post("/api/problems")
def create_problem(body: ProblemCreate, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    problem = _create_problem(db, body.model_dump(), user)
    db.commit()
    return ok(_row(problem, db, status_names(db, "problem")))


@router.get("/api/problems/{problem_id}")
def get_problem(problem_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    p = db.get(Problem, problem_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "问题不存在", 404)
    names = status_names(db, "problem")
    detail = _row(p, db, names)
    links = db.query(ProblemTicket).filter(ProblemTicket.problem_id == p.id, ProblemTicket.is_deleted.is_(False)).all()
    tickets = db.query(Ticket).filter(Ticket.id.in_([l.ticket_id for l in links] or ["-"])).all()
    detail.update(
        {
            "description": p.description,
            "root_cause": p.root_cause,
            "workaround": p.workaround,
            "source_ticket_id": p.source_ticket_id,
            "source_requirement_id": p.source_requirement_id,
            "linked_tickets": [
                {"id": t.id, "ticket_code": t.ticket_code, "title": t.title, "status": t.status}
                for t in tickets
            ],
            "allowed_transitions": [
                {"to": code, "to_name": names.get(code, code)}
                for code in allowed_targets(db, "problem", p.status, user)
            ],
            "process": process_engine.instance_view(db, "problem", p.id),
        }
    )
    return ok(detail)


@router.patch("/api/problems/{problem_id}")
def update_problem(problem_id: str, body: ProblemUpdate, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    p = db.get(Problem, problem_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "问题不存在", 404)
    data = body.model_dump(exclude_unset=True)
    root_cause_filled = data.get("root_cause") and not p.root_cause
    for k, v in data.items():
        setattr(p, k, v)
    if root_cause_filled:
        publish(db, "problem.root_cause_found", "problem", p.id, {})
    audit(db, "problem", p.id, "update", user, {"fields": list(data.keys())})
    db.commit()
    return ok({"id": p.id})


@router.post("/api/problems/{problem_id}/transition")
def transition_problem(problem_id: str, body: TransitionIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    p = db.get(Problem, problem_id)
    if not p or p.is_deleted:
        raise AppError("NOT_FOUND", "问题不存在", 404)
    had_root_cause = bool(p.root_cause)
    wf_transition(db, p, "problem", body.to, body.fields, user)
    if not had_root_cause and p.root_cause:
        publish(db, "problem.root_cause_found", "problem", p.id, {})
    if body.to == "closed":
        publish(db, "problem.closed", "problem", p.id, {})
    db.commit()
    return ok({"id": p.id, "status": p.status})


@router.post("/api/problems/{problem_id}/link-ticket")
def link_ticket(problem_id: str, body: LinkTicketIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    p = db.get(Problem, problem_id)
    t = db.get(Ticket, body.ticket_id)
    if not p or p.is_deleted or not t or t.is_deleted:
        raise AppError("NOT_FOUND", "问题或工单不存在", 404)
    exists = (
        db.query(ProblemTicket)
        .filter(ProblemTicket.problem_id == p.id, ProblemTicket.ticket_id == t.id, ProblemTicket.is_deleted.is_(False))
        .first()
    )
    if exists:
        raise AppError("DUPLICATE", "该工单已关联")
    db.add(ProblemTicket(problem_id=p.id, ticket_id=t.id))
    t.problem_id = p.id
    audit(db, "problem", p.id, "link_ticket", user, {"ticket": t.ticket_code})
    db.commit()
    return ok({"id": p.id})
