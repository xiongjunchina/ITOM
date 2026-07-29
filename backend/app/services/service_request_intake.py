"""服务请求受理编排：检索、动态表单、预览确认和幂等提交。"""

from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AuthUser, ProcessDefinition, ServiceItem, Ticket
from app.services import dispatch, mcp_intents, process_engine, service_forms, sla, tickets
from app.services.service_audience import service_item_visible_to_user


def _public_item(db: Session, item_code: str, user: AuthUser) -> ServiceItem:
    item = (
        db.query(ServiceItem)
        .filter(
            ServiceItem.item_code == str(item_code or "").strip(),
            ServiceItem.status == "上架",
            ServiceItem.is_example.is_(False),
            ServiceItem.is_deleted.is_(False),
        )
        .first()
    )
    if (
        not item
        or not item.catalog
        or item.catalog.is_deleted
        or item.catalog.status != "上架"
        or not service_item_visible_to_user(db, item, user)
    ):
        raise AppError("NOT_FOUND", "服务项不存在或当前账号不可申请", 404)
    return item


def _process_summary(db: Session, item: ServiceItem) -> dict:
    definition = process_engine.resolve_definition(
        db,
        "ticket",
        {"ticket_type": "service_request"},
        definition_id=item.process_definition_id,
    )
    if not definition:
        raise AppError("SERVICE_PROCESS_UNAVAILABLE", "服务项尚未绑定可用的服务请求流程")
    return {
        "name": definition.name,
        "version": definition.version,
        "requires_approval": any(
            step.node_type == "approval" and not step.is_deleted
            for step in definition.steps
        ),
        "steps": [
            {"name": step.name, "type": step.node_type}
            for step in definition.steps
            if not step.is_deleted
        ],
    }


def search_items(db: Session, user: AuthUser, query: str, limit: int = 5) -> list[dict]:
    keyword = str(query or "").strip().lower()
    if not keyword:
        raise AppError("QUERY_REQUIRED", "请描述需要办理的 IT 服务")
    safe_limit = min(max(int(limit or 5), 1), 20)
    rows = (
        db.query(ServiceItem)
        .filter(
            ServiceItem.status == "上架",
            ServiceItem.is_example.is_(False),
            ServiceItem.is_deleted.is_(False),
        )
        .order_by(ServiceItem.created_at)
        .all()
    )
    ranked: list[tuple[int, ServiceItem, list[str]]] = []
    query_tokens = {keyword, *[part for part in keyword.replace("，", " ").split() if part]}
    for item in rows:
        if not item.catalog or item.catalog.is_deleted or item.catalog.status != "上架":
            continue
        if not service_item_visible_to_user(db, item, user):
            continue
        fields = {
            "服务项名称": [item.name],
            "关键词": item.search_keywords or [],
            "同义词": item.search_synonyms or [],
            "典型场景": item.typical_scenarios or [],
            "描述": [item.description or ""],
        }
        exclusions = " ".join(str(x).lower() for x in (item.exclusion_scenarios or []))
        if exclusions and any(token in exclusions for token in query_tokens):
            continue
        score = 0
        reasons: list[str] = []
        for label, values in fields.items():
            normalized_values = [str(value).strip().lower() for value in values if str(value).strip()]
            matched = [
                value
                for value in normalized_values
                if value in keyword or keyword in value
                or any(token in value or value in token for token in query_tokens)
            ]
            if matched:
                weight = {"服务项名称": 8, "关键词": 6, "同义词": 6, "典型场景": 4, "描述": 2}[label]
                score += weight * len(matched)
                reasons.append(f"{label}匹配")
        if score:
            ranked.append((score, item, reasons))
    ranked.sort(key=lambda row: (-row[0], row[1].name, row[1].item_code))
    return [
        {
            "service_item_id": item.item_code,
            "name": item.name,
            "catalog_name": item.catalog.name if item.catalog else None,
            "service_type": item.service_type,
            "description": item.description,
            "match_reasons": reasons,
        }
        for _, item, reasons in ranked[:safe_limit]
    ]


def item_form(db: Session, user: AuthUser, item_code: str) -> dict:
    item = _public_item(db, item_code, user)
    form = service_forms.active_form(db, item)
    response_min, resolution_hours = sla.resolve_targets(db, item.default_priority, item)
    decision = dispatch.preview(db, item)
    return {
        "service_item": {
            "service_item_id": item.item_code,
            "name": item.name,
            "catalog_name": item.catalog.name if item.catalog else None,
        },
        "form": service_forms.form_row(form),
        "sla": {
            "priority": item.default_priority,
            "response_minutes": response_min,
            "resolution_hours": resolution_hours,
        },
        "process": _process_summary(db, item),
        "expected_support_group": decision.support_label,
    }


def prepare_request(
    db: Session,
    user: AuthUser,
    item_code: str,
    answers: dict,
    idempotency_key: str,
) -> dict:
    item = _public_item(db, item_code, user)
    form = service_forms.active_form(db, item)
    validation = service_forms.validate_answers(db, form.schema, answers)
    if validation["missing"] or validation["errors"]:
        return {
            "ready_for_confirmation": False,
            "missing_fields": validation["missing"],
            "validation_errors": validation["errors"],
        }
    normalized = validation["normalized"]
    priority = normalized.get("priority") or item.default_priority
    response_min, resolution_hours = sla.resolve_targets(db, priority, item)
    decision = dispatch.preview(db, item)
    process = _process_summary(db, item)
    payload = {
        "service_item_id": item.id,
        "service_item_code": item.item_code,
        "request_form_version_id": form.id,
        "request_form_version": form.version,
        "request_form_checksum": form.checksum,
        "request_data": normalized,
        "title": normalized["title"],
        "description": normalized["description"],
        "priority": priority,
        "suspected_major_impact": bool(normalized.get("suspected_major_impact", False)),
    }
    intent, token = mcp_intents.prepare(
        db, user, "submit_service_request", payload, idempotency_key
    )
    if intent.status == "executed":
        return {
            "ready_for_confirmation": True,
            "already_submitted": True,
            "preview": intent.result_snapshot,
        }
    return {
        "ready_for_confirmation": True,
        "confirmation_token": token,
        "confirmation_expires_at": intent.expires_at.isoformat(),
        "preview": {
            "ticket_type": "service_request",
            "service_item_id": item.item_code,
            "service_item_name": item.name,
            "catalog_name": item.catalog.name if item.catalog else None,
            "title": payload["title"],
            "description": payload["description"],
            "priority": priority,
            "suspected_major_impact": payload["suspected_major_impact"],
            "answers": service_forms.masked_preview(form.schema, normalized),
            "sla": {
                "response_minutes": response_min,
                "resolution_hours": resolution_hours,
            },
            "process": process,
            "expected_support_group": decision.support_label,
        },
    }


def submit_request(
    db: Session,
    user: AuthUser,
    confirmation_token: str,
    idempotency_key: str,
) -> tuple[dict, Ticket | None]:
    intent, replay = mcp_intents.require_prepared(
        db, user, "submit_service_request", idempotency_key, confirmation_token
    )
    if replay:
        snapshot = dict(intent.result_snapshot or {})
        snapshot.update({"created": False, "idempotent_replay": True})
        return snapshot, None
    payload = dict(intent.normalized_payload or {})
    item = db.get(ServiceItem, payload.get("service_item_id"))
    if (
        not item
        or item.is_deleted
        or item.status != "上架"
        or item.is_example
        or not item.catalog
        or item.catalog.is_deleted
        or item.catalog.status != "上架"
        or not service_item_visible_to_user(db, item, user)
    ):
        raise AppError("SERVICE_ITEM_CHANGED", "服务项已下架或当前账号不再可申请，请重新选择", 409)
    form = service_forms.active_form(db, item)
    if form.id != payload.get("request_form_version_id") or form.checksum != payload.get("request_form_checksum"):
        raise AppError("SERVICE_FORM_CHANGED", "服务表单已更新，请重新填写并确认", 409)
    validation = service_forms.validate_answers(db, form.schema, payload.get("request_data"))
    if validation["missing"] or validation["errors"]:
        raise AppError("FORM_VALIDATION_FAILED", "表单内容已不符合当前规则，请重新填写")
    ticket = tickets.create_ticket(
        db,
        {
            "title": payload["title"],
            "ticket_type": "service_request",
            "priority": payload["priority"],
            "description": payload["description"],
            "service_item_id": item.id,
            "request_data": validation["normalized"],
            "request_form_version_id": form.id,
            "suspected_major_impact": bool(payload.get("suspected_major_impact")),
        },
        user,
        commit=False,
    )
    result = {
        "ticket_code": ticket.ticket_code,
        "status": ticket.status,
        "status_name": "待受理",
        "created": True,
        "idempotent_replay": False,
        "submitted_at": ticket.submitted_at.isoformat() if ticket.submitted_at else datetime.now().isoformat(),
    }
    mcp_intents.mark_executed(intent, "ticket", ticket.id, result)
    return result, ticket


def own_ticket(db: Session, user: AuthUser, ticket_code: str) -> Ticket:
    row = (
        db.query(Ticket)
        .filter(
            Ticket.ticket_code == str(ticket_code or "").strip(),
            Ticket.ticket_type == "service_request",
            Ticket.submitter == user.id,
            Ticket.is_deleted.is_(False),
        )
        .first()
    )
    if not row:
        raise AppError("NOT_FOUND", "未找到该服务请求", 404)
    return row


def ticket_summary(ticket: Ticket) -> dict:
    return {
        "ticket_code": ticket.ticket_code,
        "title": ticket.title,
        "priority": ticket.priority,
        "status": ticket.status,
        "service_item_name": ticket.service_item.name if ticket.service_item else None,
        "submitted_at": ticket.submitted_at.isoformat() if ticket.submitted_at else None,
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
        "closed_at": ticket.closed_at.isoformat() if ticket.closed_at else None,
    }
