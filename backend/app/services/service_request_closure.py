"""P2 服务请求用户确认、重开与评价闭环。"""

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.events import notifier
from app.models import AuthUser, ProcessInstance, Ticket, TicketSatisfaction
from app.services import mcp_intents, process_engine, tickets
from app.services.audit import audit


def _own_service_request(db: Session, user: AuthUser, ticket_code: str) -> Ticket:
    ticket = (
        db.query(Ticket)
        .filter(
            Ticket.ticket_code == str(ticket_code or "").strip(),
            Ticket.ticket_type == "service_request",
            Ticket.submitter == user.id,
            Ticket.is_deleted.is_(False),
        )
        .with_for_update()
        .first()
    )
    if not ticket:
        # 对越权访问和不存在统一返回 NOT_FOUND，避免枚举他人单据。
        raise AppError("NOT_FOUND", "未找到该服务请求", 404)
    return ticket


def _confirmation_task(db: Session, ticket: Ticket, user: AuthUser):
    task = process_engine.current_pending_task(db, tickets.entity_type_of(ticket), ticket.id)
    if (
        not task
        or not task.step
        or task.step.default_role != "requester"
        or not process_engine.can_act_on_task(db, user, task)
    ):
        raise AppError("NOT_PENDING_CONFIRMATION", "该服务请求当前不等待您确认", 409)
    return task


def _safe_summary(ticket: Ticket) -> dict:
    solution = str(ticket.solution or "").strip()
    return {
        "ticket_code": ticket.ticket_code,
        "title": ticket.title,
        "priority": ticket.priority,
        "status": ticket.status,
        "service_item_name": ticket.service_item.name if ticket.service_item else None,
        "solution": solution[:500] if solution else None,
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
        "confirmation_due_at": (
            ticket.confirmation_due_at.isoformat() if ticket.confirmation_due_at else None
        ),
        "reopen_count": ticket.reopen_count or 0,
    }


def pending_confirmations(db: Session, user: AuthUser) -> list[dict]:
    rows = (
        db.query(Ticket)
        .filter(
            Ticket.ticket_type == "service_request",
            Ticket.submitter == user.id,
            Ticket.status == "resolved",
            Ticket.is_deleted.is_(False),
        )
        .order_by(Ticket.resolved_at.asc(), Ticket.ticket_code.asc())
        .all()
    )
    return [_safe_summary(row) for row in rows]


def reopen_from_confirmation(
    db: Session,
    user: AuthUser,
    ticket: Ticket,
    task,
    feedback: str,
    *,
    source: str,
) -> dict:
    """从用户确认节点回退到最近的实际处理节点；供 Web 与 MCP 共用。"""
    normalized_feedback = str(feedback or "").strip()
    if len(normalized_feedback) < 2:
        raise AppError("FEEDBACK_REQUIRED", "问题仍未解决时，请说明尚未解决的情况")
    if len(normalized_feedback) > 500:
        raise AppError("FEEDBACK_TOO_LONG", "反馈不能超过 500 个字符")
    if ticket.submitter != user.id or ticket.status != "resolved":
        raise AppError("NOT_PENDING_CONFIRMATION", "该服务请求当前不等待您确认", 409)
    if not task.step or task.step.default_role != "requester":
        raise AppError("NOT_PENDING_CONFIRMATION", "当前流程节点不是用户确认", 409)

    instance = db.get(ProcessInstance, task.instance_id)
    if not instance:
        raise AppError("PROCESS_REOPEN_UNAVAILABLE", "服务请求流程暂时无法重开", 409)
    live_steps = sorted(
        (step for step in instance.definition.steps if not step.is_deleted),
        key=lambda step: step.seq,
    )
    previous = next(
        (
            step
            for step in reversed(live_steps)
            if step.seq < task.step.seq and step.default_role != "requester"
        ),
        None,
    )
    if not previous:
        raise AppError("PROCESS_REOPEN_UNAVAILABLE", "流程没有可回退的处理节点", 409)
    tickets.do_transition(db, ticket, "processing", {}, user, system=True, commit=False)
    rewound = process_engine.rewind_to_step(
        db,
        tickets.entity_type_of(ticket),
        ticket.id,
        previous.seq,
        preferred_assignee=ticket.assignee,
    )
    if not rewound:
        raise AppError("PROCESS_REOPEN_UNAVAILABLE", "服务请求流程暂时无法重开", 409)
    note = f"[用户反馈仍未解决] {normalized_feedback}"
    ticket.remarks = f"{ticket.remarks}\n{note}" if ticket.remarks else note
    pending = process_engine.current_pending_task(db, tickets.entity_type_of(ticket), ticket.id)
    if pending and pending.assignee:
        notifier.notify(
            db,
            "ticket.reopened",
            "ticket",
            ticket.id,
            [pending.assignee],
            f"用户反馈仍未解决：{ticket.ticket_code} {ticket.title}",
            content=normalized_feedback,
            link=f"/itsm/tickets/{ticket.id}",
        )
    audit(
        db,
        "ticket",
        ticket.id,
        "user_reopen",
        user,
        {"code": ticket.ticket_code, "feedback": normalized_feedback, "source": source},
    )
    return {
        "ticket_code": ticket.ticket_code,
        "status": "processing",
        "status_name": "处理中",
        "closed": False,
        "reopened": True,
        "reopen_count": ticket.reopen_count,
        "idempotent_replay": False,
        "message": "已将服务请求重新打开并反馈给 IT 处理人员。",
    }


def confirm_resolution(
    db: Session,
    user: AuthUser,
    ticket_code: str,
    resolved: bool,
    feedback: str,
    idempotency_key: str,
) -> tuple[dict, Ticket | None]:
    normalized_feedback = str(feedback or "").strip()
    if not resolved and len(normalized_feedback) < 2:
        raise AppError("FEEDBACK_REQUIRED", "问题仍未解决时，请说明尚未解决的情况")
    if len(normalized_feedback) > 500:
        raise AppError("FEEDBACK_TOO_LONG", "反馈不能超过 500 个字符")
    payload = {
        "ticket_code": str(ticket_code or "").strip(),
        "resolved": bool(resolved),
        "feedback": normalized_feedback,
    }
    intent, replay = mcp_intents.begin_direct_action(
        db,
        user,
        "confirm_service_request_resolution",
        payload,
        idempotency_key,
    )
    if replay:
        result = dict(intent.result_snapshot or {})
        result["idempotent_replay"] = True
        return result, None

    ticket = _own_service_request(db, user, payload["ticket_code"])
    if ticket.status != "resolved":
        raise AppError("NOT_PENDING_CONFIRMATION", "该服务请求当前不等待确认", 409)
    task = _confirmation_task(db, ticket, user)

    if resolved:
        process_engine.complete_task(db, task.id, user, normalized_feedback)
        tickets.do_transition(
            db,
            ticket,
            "closed",
            {"closure_code": ticket.closure_code or "resolved"},
            user,
            system=True,
            commit=False,
        )
        audit(
            db,
            "ticket",
            ticket.id,
            "user_confirm_resolution",
            user,
            {"code": ticket.ticket_code},
        )
        result = {
            "ticket_code": ticket.ticket_code,
            "status": "closed",
            "status_name": "已关闭",
            "closed": True,
            "reopened": False,
            "idempotent_replay": False,
            "message": "已确认问题解决并关闭服务请求，请继续评价本次 IT 服务。",
        }
    else:
        result = reopen_from_confirmation(
            db,
            user,
            ticket,
            task,
            normalized_feedback,
            source="aily",
        )

    mcp_intents.mark_executed(intent, "ticket", ticket.id, result)
    return result, ticket


def rate_request(
    db: Session,
    user: AuthUser,
    ticket_code: str,
    score: int,
    tags: list[str] | None,
    comment: str,
    idempotency_key: str,
) -> tuple[dict, Ticket | None]:
    payload = {
        "ticket_code": str(ticket_code or "").strip(),
        "score": int(score),
        "tags": list(tags or []),
        "comment": str(comment or "").strip(),
    }
    intent, replay = mcp_intents.begin_direct_action(
        db,
        user,
        "rate_service_request",
        payload,
        idempotency_key,
    )
    if replay:
        result = dict(intent.result_snapshot or {})
        result["idempotent_replay"] = True
        return result, None

    ticket = _own_service_request(db, user, payload["ticket_code"])
    existing = (
        db.query(TicketSatisfaction)
        .filter(
            TicketSatisfaction.ticket_id == ticket.id,
            TicketSatisfaction.is_deleted.is_(False),
        )
        .first()
    )
    rating = tickets.rate_satisfaction(
        db,
        ticket,
        payload["score"],
        user,
        tags=payload["tags"],
        comment=payload["comment"],
        source="aily",
        commit=False,
    )
    result = {
        "ticket_code": ticket.ticket_code,
        "score": rating.score,
        "tags": rating.tags or [],
        "comment": rating.comment,
        "source": rating.source,
        "created": existing is None,
        "idempotent_replay": False,
        "message": "评价已记录，感谢您的反馈。",
    }
    mcp_intents.mark_executed(intent, "ticket_satisfaction", rating.id, result)
    return result, ticket
