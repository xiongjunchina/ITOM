"""将服务请求用户可见事件可靠写入 Aily 机器人发件箱。"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import AilyIntegrationConfig, ExternalIdentity, Ticket
from app.services.aily import queue_aily_card, queue_aily_text
from app.services.aily_cards import build_rating_card, build_resolution_confirmation_card


_REGISTERED = False


def _recipient_identity(
    db: Session,
    ticket: Ticket,
    cfg: AilyIntegrationConfig | None,
) -> ExternalIdentity | None:
    if not ticket.submitter:
        return None
    query = db.query(ExternalIdentity).filter(
        ExternalIdentity.provider == "feishu",
        ExternalIdentity.auth_user_id == ticket.submitter,
        ExternalIdentity.subject_type.in_(["open_id", "user_id", "union_id"]),
        ExternalIdentity.status == "active",
        ExternalIdentity.is_deleted.is_(False),
    )
    allowed_tenants = list(cfg.allowed_tenant_ids or []) if cfg else []
    if allowed_tenants:
        query = query.filter(ExternalIdentity.tenant_id.in_(allowed_tenants))
    return query.order_by(
        ExternalIdentity.last_used_at.desc(),
        ExternalIdentity.verified_at.desc(),
        ExternalIdentity.created_at.desc(),
    ).first()


def _queue(
    db: Session,
    event_type: str,
    ticket_id: str,
    text: str,
    idempotency_suffix: str,
    card: dict | None = None,
) -> None:
    ticket = db.get(Ticket, ticket_id)
    if not ticket or ticket.is_deleted or ticket.is_example or ticket.ticket_type != "service_request":
        return
    cfg = (
        db.query(AilyIntegrationConfig)
        .filter(AilyIntegrationConfig.is_deleted.is_(False))
        .first()
    )
    identity = _recipient_identity(db, ticket, cfg)
    if not identity:
        return
    common = {
        "recipient_type": identity.subject_type,
        "recipient_id": identity.subject_id,
        "idempotency_key": f"aily:ticket:{ticket.id}:{idempotency_suffix}",
        "event_type": event_type,
        "entity_type": "ticket",
        "entity_id": ticket.id,
    }
    if card:
        queue_aily_card(db, card=card, fallback_text=text, **common)
    else:
        queue_aily_text(db, text=text, **common)


def _resolution_card(
    ticket: Ticket,
    cfg: AilyIntegrationConfig | None,
    solution: str,
) -> dict | None:
    if not cfg or not cfg.card_action_skill_id:
        return None
    return build_resolution_confirmation_card(
        skill_id=cfg.card_action_skill_id,
        ticket_code=ticket.ticket_code,
        title=ticket.title,
        solution=solution,
        confirmation_due_at=(
            ticket.confirmation_due_at.strftime("%Y-%m-%d %H:%M")
            if ticket.confirmation_due_at
            else None
        ),
        reopen_count=ticket.reopen_count or 0,
    )


def scan_pending_confirmation_reminders() -> None:
    """确认期限使用到 80% 后提醒一次；每次重开后的确认周期独立幂等。"""
    from app.db import SessionLocal

    now = datetime.now()
    with SessionLocal() as db:
        cfg = (
            db.query(AilyIntegrationConfig)
            .filter(AilyIntegrationConfig.is_deleted.is_(False))
            .first()
        )
        rows = (
            db.query(Ticket)
            .filter(
                Ticket.ticket_type == "service_request",
                Ticket.status == "resolved",
                Ticket.resolved_at.isnot(None),
                Ticket.confirmation_due_at.isnot(None),
                Ticket.is_deleted.is_(False),
            )
            .all()
        )
        for ticket in rows:
            window = ticket.confirmation_due_at - ticket.resolved_at
            reminder_at = (
                ticket.resolved_at + window * 0.8
                if window.total_seconds() > 0
                else ticket.confirmation_due_at
            )
            if now < reminder_at:
                continue
            due_text = ticket.confirmation_due_at.strftime("%Y-%m-%d %H:%M")
            _queue(
                db,
                "ticket.confirmation_reminder",
                ticket.id,
                (
                    f"服务请求等待您确认：{ticket.ticket_code} {ticket.title}。"
                    f"请在 {due_text} 前确认是否已经解决；如仍未解决，请说明情况以便重新处理。"
                ),
                f"confirmation-reminder:{ticket.reopen_count or 0}",
                card=_resolution_card(
                    ticket,
                    cfg,
                    str(ticket.solution or "详见服务请求处理记录").strip()[:300],
                ),
            )
        db.commit()


def register_subscribers() -> None:
    """幂等注册服务请求闭环的 Aily 可靠消息订阅者。"""
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True

    from app.events.bus import subscribe

    @subscribe("ticket.accepted")
    def _accepted(db: Session, event_type, entity_type, entity_id, payload):
        ticket = db.get(Ticket, entity_id)
        if not ticket:
            return
        _queue(
            db,
            event_type,
            entity_id,
            f"服务请求已受理：{ticket.ticket_code} {ticket.title}。IT 团队已开始处理。",
            "accepted",
        )

    @subscribe("ticket.resolved")
    def _resolved(db: Session, event_type, entity_type, entity_id, payload):
        ticket = db.get(Ticket, entity_id)
        if not ticket:
            return
        solution = str(ticket.solution or "详见服务请求处理记录").strip()[:300]
        text = (
            f"服务请求待您确认：{ticket.ticket_code} {ticket.title}。"
            f"解决说明：{solution}。请在 Aily 中明确回复是否已经解决。"
        )
        cfg = (
            db.query(AilyIntegrationConfig)
            .filter(AilyIntegrationConfig.is_deleted.is_(False))
            .first()
        )
        _queue(
            db,
            event_type,
            entity_id,
            text,
            f"resolved:{ticket.reopen_count or 0}",
            card=_resolution_card(ticket, cfg, solution),
        )

    @subscribe("ticket.reopened")
    def _reopened(db: Session, event_type, entity_type, entity_id, payload):
        ticket = db.get(Ticket, entity_id)
        if not ticket:
            return
        _queue(
            db,
            event_type,
            entity_id,
            f"服务请求已重新打开：{ticket.ticket_code} {ticket.title}。您的反馈已交给 IT 继续处理。",
            f"reopened:{ticket.reopen_count or 0}",
        )

    @subscribe("ticket.closed")
    def _closed(db: Session, event_type, entity_type, entity_id, payload):
        ticket = db.get(Ticket, entity_id)
        if not ticket:
            return
        text = f"服务请求已关闭：{ticket.ticket_code} {ticket.title}。请对本次 IT 服务进行 1-5 星评价。"
        cfg = (
            db.query(AilyIntegrationConfig)
            .filter(AilyIntegrationConfig.is_deleted.is_(False))
            .first()
        )
        card = None
        if cfg and cfg.card_action_skill_id:
            card = build_rating_card(
                skill_id=cfg.card_action_skill_id,
                ticket_code=ticket.ticket_code,
                title=ticket.title,
            )
        _queue(
            db,
            event_type,
            entity_id,
            text,
            "closed",
            card=card,
        )

    @subscribe("ticket.satisfaction_saved")
    def _rated(db: Session, event_type, entity_type, entity_id, payload):
        ticket = db.get(Ticket, entity_id)
        if not ticket:
            return
        rated_at = str(payload.get("rated_at") or "saved").replace(":", "-")
        _queue(
            db,
            event_type,
            entity_id,
            f"评价已记录：{ticket.ticket_code}，{payload.get('score')} 星。感谢您的反馈。",
            f"rated:{rated_at}",
        )
