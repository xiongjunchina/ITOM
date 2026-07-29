"""飞书服务台回调与工单交接接口。

原服务台会话中的稳定入口先引导员工登录，随后由
``POST /intakes/{intake_id}/handoff`` 重新核验实时工单身份并签发一次性链接；
旧的受信任服务端/机器人 ``POST /handoffs`` 与动态卡片保留为兼容兜底。
服务请求或需求创建完成后交接令牌立即失效。
"""

import hmac
import json
import os
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import get_current_user
from app.models import AuthUser, FeishuHelpdeskIntake, FeishuHelpdeskSyncEvent
from app.models import ServiceCatalog, ServiceItem
from app.schemas.common import ok
from app.services.feishu_helpdesk import (
    consume_handoff,
    build_handoff_card,
    issue_card_handoff,
    send_choice_card,
    event_verification_token,
    get_handoff,
    issue_handoff,
    issue_intake_handoff,
    queue_sync_event,
)

router = APIRouter(prefix="/api/integrations/feishu/helpdesk", tags=["feishu-helpdesk"])


class HandoffIn(BaseModel):
    ticket_id: str = Field(min_length=1, max_length=128)
    action: str = Field(pattern="^(service_request|requirement)$")


class ConsumeIn(BaseModel):
    entity_type: str = Field(min_length=1, max_length=32)
    entity_id: str = Field(min_length=1, max_length=26)


class CardSendIn(BaseModel):
    ticket_id: str = Field(min_length=1, max_length=128)


class IntakeHandoffIn(BaseModel):
    action: str = Field(pattern="^(service_request|requirement)$")


def _event_type(payload: dict[str, Any]) -> str:
    header = payload.get("header") or {}
    return str(header.get("event_type") or payload.get("event_type") or payload.get("type") or "")


def _event_token(payload: dict[str, Any]) -> str:
    header = payload.get("header") or {}
    event = payload.get("event") or {}
    # Feishu card.action.trigger payloads may carry the verification token in
    # the event object (the SDK model exposes ``event.token``), while URL
    # verification and some HTTP callback variants place it in the header.
    return str(header.get("token") or event.get("token") or payload.get("token") or "")


def _tokens_match(expected: str, supplied: str) -> bool:
    """Compare Feishu verification tokens without restricting them to ASCII.

    ``hmac.compare_digest(str, str)`` raises ``TypeError`` when either value
    contains non-ASCII characters.  Feishu then receives a 500 response rather
    than the JSON challenge response, which is reported as an invalid JSON
    callback.  Comparing UTF-8 bytes keeps the constant-time comparison while
    accepting any token value that can be stored in the configuration.
    """
    if not expected or not supplied:
        return False
    return hmac.compare_digest(str(expected).encode("utf-8"), str(supplied).encode("utf-8"))


def _card_action(payload: dict[str, Any]) -> tuple[dict[str, Any], str, str | None]:
    event = payload.get("event") or {}
    action = event.get("action") or payload.get("action") or {}
    value = action.get("value") if isinstance(action, dict) else {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = {}
    value = value if isinstance(value, dict) else {}
    operator = event.get("operator") or {}
    source_open_id = operator.get("open_id") or operator.get("user_id") or event.get("open_id")
    header = payload.get("header") or {}
    event_id = header.get("event_id") or payload.get("event_id")
    return value, str(source_open_id or ""), str(event_id) if event_id else None


def _public_url(request: Request) -> str:
    return os.getenv("ITOM_PUBLIC_URL", "").strip() or str(request.base_url).rstrip("/")


def _card_callback_response(card: dict[str, Any]) -> dict[str, Any]:
    """Build the response envelope expected by ``card.action.trigger``.

    The callback protocol does not accept a card JSON document directly at
    ``response.card``.  It expects a ``CallBackCard`` object whose ``type`` is
    ``raw`` and whose ``data`` is the card object.  Returning the card itself
    makes Feishu reject an otherwise successful HTTP response (error 200672).
    """
    return {
        "toast": {"type": "success", "content": "ITOM 入口已生成"},
        "card": {"type": "raw", "data": card},
    }


def _handle_card_callback(payload: dict[str, Any], request: Request, db: Session) -> dict:
    verify = event_verification_token(db)
    supplied = _event_token(payload)
    if not _tokens_match(verify, supplied):
        raise AppError("FEISHU_EVENT_TOKEN_INVALID", "飞书卡片回调校验失败", 401)
    value, source_open_id, event_id = _card_action(payload)
    action_map = {
        "create_service_request": "service_request",
        "create_requirement": "requirement",
    }
    action = action_map.get(str(value.get("action") or ""))
    ticket_id = str(value.get("ticket_id") or "").strip()
    if not action or not ticket_id:
        raise AppError("FEISHU_CARD_ACTION_INVALID", "飞书卡片操作缺少有效的 ITOM 动作或工单 ID", 422)
    if not source_open_id:
        raise AppError("FEISHU_CARD_IDENTITY_MISSING", "飞书卡片回调缺少点击人身份", 422)
    result = issue_card_handoff(
        db,
        ticket_id,
        action,
        source_open_id,
        _public_url(request),
        callback_event_id=event_id,
    )
    # The card action opens the actual ITOM create form.  The read-only
    # handoff page remains available through result["url"] for diagnostics and
    # legacy links, but employees should not have to click through it.
    return _card_callback_response(build_handoff_card(result["action"], result["entry_url"]))


def _handle_url_verification(payload: dict[str, Any], db: Session) -> dict | None:
    """处理事件/回调地址保存时飞书发送的 URL verification。"""
    if _event_type(payload) != "url_verification":
        return None
    verify = event_verification_token(db)
    supplied = _event_token(payload)
    if not _tokens_match(verify, supplied):
        raise AppError("FEISHU_EVENT_TOKEN_INVALID", "飞书事件校验失败", 401)
    challenge = payload.get("challenge")
    if not challenge:
        raise AppError("FEISHU_EVENT_CHALLENGE_MISSING", "飞书事件校验缺少 challenge", 422)
    return {"challenge": challenge}


def _require_sync_view(db: Session, user: AuthUser) -> None:
    """待分流/同步状态只向 IT 管理角色开放，业务用户不获得跨用户工单列表。"""
    from app.core.rbac import ADMIN, CIO, IT_BM, IT_PMO, IT_TM
    from app.services.rbac import effective_roles

    if not ({ADMIN, CIO, IT_BM, IT_TM, IT_PMO} & effective_roles(db, user)):
        raise AppError("FORBIDDEN", "当前角色无权查看飞书服务台同步记录", 403)


@router.post("/cards")
def send_choice_card_api(
    body: CardSendIn,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None, alias="X-Lark-Helpdesk-Authorization"),
):
    """向飞书工单申请人发送“服务请求/IT 需求”动态卡片。

    该接口供受信任的机器人或中间层调用，不能从浏览器直接调用。
    """
    return ok(send_choice_card(db, body.ticket_id, authorization))


@router.post("/handoffs")
def create_handoff(
    body: HandoffIn,
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None, alias="X-Lark-Helpdesk-Authorization"),
):
    """为飞书动态卡片/机器人菜单创建一次性交接链接。

    ``X-Lark-Helpdesk-Authorization`` 是服务台 ID 与 Token 的 base64 组合，
    只允许服务端调用；浏览器端不应携带或保存该凭证。
    """
    public_url = os.getenv("ITOM_PUBLIC_URL", "").strip() or str(request.base_url).rstrip("/")
    return ok(issue_handoff(db, body.ticket_id, body.action, authorization, public_url))


@router.get("/handoffs/{raw_token}")
def read_handoff(raw_token: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    row = get_handoff(db, raw_token, user, allow_consumed=True)
    if row.status == "consumed":
        return ok({
            "status": "consumed",
            "action": row.action,
            "ticket_id": row.ticket_id,
            "consumed_entity_type": row.consumed_entity_type,
            "consumed_entity_id": row.consumed_entity_id,
        })
    snapshot = row.ticket_snapshot or {}
    category = snapshot.get("service_category") or ""
    matched_service_item_id = None
    if category:
        candidates = (
            db.query(ServiceItem)
            .join(ServiceCatalog, ServiceCatalog.id == ServiceItem.catalog_id)
            .filter(ServiceItem.is_deleted.is_(False), ServiceItem.status == "上架")
            .filter((ServiceCatalog.name == category) | (ServiceItem.name == category))
            .all()
        )
        if len(candidates) == 1:
            matched_service_item_id = candidates[0].id
    return ok({
        "status": "issued",
        "action": row.action,
        "ticket_id": row.ticket_id,
        "expires_at": row.expires_at,
        "prefill": {
            "title": snapshot.get("title"),
            "description": snapshot.get("description"),
            "priority": snapshot.get("priority"),
            "service_category": snapshot.get("service_category"),
            "service_item_id": matched_service_item_id,
            "other_info": snapshot.get("other_info"),
            "source": "feishu_helpdesk",
        },
        "source": {
            "guest_name": (snapshot.get("guest") or {}).get("name"),
            "agent_name": (snapshot.get("agent") or {}).get("name"),
        },
    })


@router.post("/handoffs/{raw_token}/consume")
def consume_handoff_api(
    raw_token: str,
    body: ConsumeIn,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    row = get_handoff(db, raw_token, user)
    if body.entity_type not in {"ticket", "requirement"}:
        raise AppError("FEISHU_HANDOFF_ENTITY_INVALID", "交接目标类型无效", 422)
    consume_handoff(db, row, body.entity_type, body.entity_id)
    return ok({"consumed": True, "entity_type": body.entity_type, "entity_id": body.entity_id})


@router.post("/intakes/{intake_id}/handoff")
def create_intake_handoff(
    intake_id: str,
    body: IntakeHandoffIn,
    request: Request,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    """稳定会话入口：登录并核验飞书身份后签发短时交接令牌。"""
    return ok(issue_intake_handoff(db, intake_id, body.action, user, _public_url(request)))


@router.get("/intakes")
def list_intakes(
    page: int = 1,
    page_size: int = 20,
    status: str = "",
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    """系统管理员/IT 管理角色查看待分流及跨系统关联状态。"""
    from app.schemas.common import paginate

    _require_sync_view(db, user)
    query = db.query(FeishuHelpdeskIntake).filter(FeishuHelpdeskIntake.is_deleted.is_(False))
    if status:
        query = query.filter(FeishuHelpdeskIntake.classification == status)
    rows, total = paginate(query.order_by(FeishuHelpdeskIntake.created_at.desc()), page, page_size)
    return ok([{
        "id": row.id, "ticket_id": row.ticket_id, "helpdesk_id": row.helpdesk_id,
        "guest_name": row.guest_name, "agent_name": row.agent_name,
        "classification": row.classification, "linked_entity_type": row.linked_entity_type,
        "linked_entity_id": row.linked_entity_id, "feishu_status": row.feishu_status,
        "feishu_stage": row.feishu_stage, "choice_card_sent_at": row.choice_card_sent_at,
        "routing_prompt_sent_at": row.routing_prompt_sent_at,
        "routing_prompt_channel": row.routing_prompt_channel,
        "routing_prompt_message_id": row.routing_prompt_message_id,
        "last_synced_at": row.last_synced_at, "last_error": row.last_error,
    } for row in rows], total=total, page=page)


@router.get("/sync-events")
def list_sync_events(
    page: int = 1,
    page_size: int = 20,
    status: str = "",
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    """运维排障用事件队列状态，便于确认幂等/重试是否生效。"""
    from app.schemas.common import paginate

    _require_sync_view(db, user)
    query = db.query(FeishuHelpdeskSyncEvent).filter(FeishuHelpdeskSyncEvent.is_deleted.is_(False))
    if status:
        query = query.filter(FeishuHelpdeskSyncEvent.status == status)
    rows, total = paginate(query.order_by(FeishuHelpdeskSyncEvent.created_at.desc()), page, page_size)
    return ok([{
        "id": row.id, "event_id": row.event_id, "event_type": row.event_type,
        "ticket_id": row.ticket_id, "status": row.status, "attempts": row.attempts,
        "next_attempt_at": row.next_attempt_at, "last_error": row.last_error,
        "processed_at": row.processed_at,
    } for row in rows], total=total, page=page)


@router.post("/events")
def receive_event(payload: dict, request: Request, db: Session = Depends(get_db)):
    """飞书事件订阅地址：校验后快速入队，后台异步拉取工单详情并重试。

    飞书会重复投递或在短时间内重试事件；数据库唯一 event_id 保证幂等。
    这里不调用远端详情接口，避免超过飞书回调的响应时限。
    """
    event_type = _event_type(payload)
    if event_type == "card.action.trigger":
        return _handle_card_callback(payload, request, db)
    verified = _handle_url_verification(payload, db)
    if verified is not None:
        return verified
    verify = event_verification_token(db)
    supplied = _event_token(payload)
    if not _tokens_match(verify, supplied):
        raise AppError("FEISHU_EVENT_TOKEN_INVALID", "飞书事件校验失败", 401)
    row, created = queue_sync_event(db, payload, event_type)
    return ok({"received": True, "queued": created, "event_id": row.event_id, "event_type": event_type})


@router.post("/card-callback")
def receive_card_callback(payload: dict, request: Request, db: Session = Depends(get_db)):
    """飞书卡片专用回调地址；与统一 ``/events`` 地址行为一致。"""
    verified = _handle_url_verification(payload, db)
    if verified is not None:
        return verified
    return _handle_card_callback(payload, request, db)
