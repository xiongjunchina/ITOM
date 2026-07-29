"""飞书服务台工单交接：安全令牌、字段归一化和身份绑定。"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import json
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import SessionLocal
from app.models import (
    AuthUser,
    FeishuHelpdeskHandoff,
    FeishuHelpdeskIntake,
    FeishuHelpdeskOutbox,
    FeishuHelpdeskSyncEvent,
)
from app.events.bus import publish, subscribe
from app.services.feishu import build_helpdesk_client
from app.services.secrets_store import decrypt_secret

HANDOFF_TTL_MINUTES = 10
ALLOWED_ACTIONS = {"service_request", "requirement"}
SYNC_MAX_ATTEMPTS = 8
SYNC_BATCH_SIZE = 20
logger = logging.getLogger("aom.feishu.helpdesk")
_OPTION_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)


def _configured_public_url(cfg: Any) -> str:
    """Resolve the externally reachable ITOM root used in Helpdesk links."""
    configured = os.getenv("ITOM_PUBLIC_URL", "").strip().rstrip("/")
    if configured:
        return configured
    event_url = str(getattr(cfg, "helpdesk_event_url", "") or "").strip()
    parsed = urlsplit(event_url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    raise AppError(
        "ITOM_PUBLIC_URL_MISSING",
        "未配置 ITOM 对外访问地址，请设置 ITOM_PUBLIC_URL 或保存完整的飞书服务台事件回调地址",
        501,
    )


def _routing_prompt_urls(public_url: str, intake_id: str) -> tuple[str, str]:
    base = f"{public_url.rstrip('/')}/feishu/helpdesk/entry"
    return (
        f"{base}?{urlencode({'intake': intake_id, 'action': 'service_request'})}",
        f"{base}?{urlencode({'intake': intake_id, 'action': 'requirement'})}",
    )


def _action_value(value: Any) -> dict:
    """兼容卡片回调 value 为对象或 JSON 字符串的两种形态。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def build_choice_card(ticket_id: str) -> dict:
    """生成飞书卡片：让员工选择服务请求或 IT 需求。"""
    def button(label: str, action: str, color: str) -> dict:
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": label},
            "type": color,
            "width": "fill",
            "behaviors": [{"type": "callback", "value": {"action": action, "ticket_id": ticket_id}}],
        }

    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": "请选择 ITOM 后续处理方式"},
            "template": "blue",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": [
                {"tag": "markdown", "content": "人工客服已完成初步确认，请选择要创建的 ITOM 单据。"},
                # Schema 2.0 不再支持旧版 action 容器；按钮作为独立元素发送。
                button("创建 IT 服务请求", "create_service_request", "primary"),
                button("登记 IT 需求", "create_requirement", "default"),
            ],
        },
    }


def build_handoff_card(action: str, url: str) -> dict:
    label = "进入 ITOM 创建服务请求" if action == "service_request" else "进入 ITOM 登记需求"
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": "ITOM 入口已生成"},
            "template": "green",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": [
                {"tag": "markdown", "content": "链接有效期 10 分钟，请使用与飞书账号绑定的 ITOM 账号打开。"},
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": label},
                    "type": "primary",
                    "width": "fill",
                    "behaviors": [{"type": "open_url", "default_url": url}],
                },
            ],
        },
    }


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _text(value: Any, limit: int = 4000) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        # Helpdesk custom-field values can be returned as a display object
        # (for example {text/value/display_name}) rather than a plain string.
        value = (
            value.get("text")
            or value.get("value")
            or value.get("display_name")
            or value.get("name")
            or value.get("content")
            or ""
        )
    if isinstance(value, list):
        value = "; ".join(_text(v, 500) for v in value)
    return str(value).strip()[:limit]


def _field_map(ticket: dict) -> dict[str, Any]:
    """兼容飞书不同版本工单字段返回结构，统一成 label/code → value。"""
    result: dict[str, Any] = {}
    raw_sources = (
        ticket.get("fields"), ticket.get("custom_fields"), ticket.get("form_fields"),
        ticket.get("customized_fields"),
    )
    for raw in raw_sources:
        if isinstance(raw, dict):
            result.update({str(key): value for key, value in raw.items()})
            continue
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            value = item.get("value") if "value" in item else item.get("text")
            # The Helpdesk ticket-detail API names these fields key_name and
            # display_name.  Keep both aliases so the mapping works regardless
            # of whether the tenant returns Chinese labels or stable field keys.
            keys = [
                item.get("name"), item.get("label"), item.get("field_name"), item.get("key"),
                item.get("key_name"), item.get("display_name"),
            ]
            for key in keys:
                if key:
                    result[str(key)] = value
    return result


def _pick(ticket: dict, fields: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = ticket.get(key)
        if value not in (None, ""):
            return _text(value)
    for key, value in fields.items():
        key_text = str(key).lower()
        if any(alias.lower() in key_text for alias in keys):
            result = _text(value)
            if result:
                return result
    return ""


def _option_label_map(fields: list[dict]) -> dict[str, str]:
    """从服务台字段定义提取 dropdown tag → display_name 映射。"""
    result: dict[str, str] = {}

    def walk(options: Any) -> None:
        if isinstance(options, dict):
            option_id = options.get("tag") or options.get("id") or options.get("value") or options.get("key")
            label = (
                options.get("display_name") or options.get("name") or options.get("text")
                or options.get("label") or options.get("content")
            )
            if option_id and label:
                result[str(option_id).strip()] = _text(label, 256)
            for value in options.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(options, list):
            for value in options:
                walk(value)

    walk(fields)
    return result


def normalize_ticket(ticket: dict, category_labels: dict[str, str] | None = None) -> dict:
    """将飞书询前单字段映射为 ITOM 预填字段。

    服务类别只作为 ``service_category`` 保存，后续由 ITSM 服务目录/服务项选择
    完成映射；绝不写入需求的 business_domain_id。
    """
    fields = _field_map(ticket)
    guest = ticket.get("guest") or ticket.get("user") or {}
    raw_agent = (
        ticket.get("agent")
        or ticket.get("service_agent")
        or ticket.get("assignee")
        or ticket.get("agents")
        or {}
    )
    agent_members = raw_agent if isinstance(raw_agent, list) else [raw_agent]
    agent_members = [item for item in agent_members if isinstance(item, dict)]
    agent = agent_members[0] if agent_members else {}
    guest_id = _text(guest.get("open_id") or guest.get("id") or ticket.get("guest_open_id"), 128) if isinstance(guest, dict) else ""
    agent_id = _text(agent.get("open_id") or agent.get("id"), 128)
    agent_names = [
        _text(item.get("name") or item.get("display_name"), 128)
        for item in agent_members
        if item.get("name") or item.get("display_name")
    ]
    urgency = _pick(ticket, fields, "priority", "urgency", "紧急程度")
    urgency_lower = urgency.lower()
    # 飞书询前单的“紧急程度”与 ITOM P1-P4 保持同语义：紧急、高、一般、低。
    # 不把“高”误判成 P1，也不把“一般”误判成 P2，避免新建页显示错误等级。
    priority = "P1" if urgency in {"紧急", "urgent"} or urgency_lower == "p1" else (
        "P2" if urgency in {"高", "high"} or urgency_lower in {"p2", "high"} else (
            "P4" if urgency in {"低", "low"} or urgency_lower in {"p4", "low"} else "P3"
        )
    )
    title = _pick(ticket, fields, "title", "subject", "标题") or "飞书服务台工单"
    description = _pick(ticket, fields, "description", "content", "problem_description", "问题描述")
    other = _pick(ticket, fields, "other", "other_info", "additional", "其他补充信息")
    category = _pick(ticket, fields, "service_category", "category", "service_type", "服务类别")
    if category_labels:
        category = category_labels.get(category, category)
    return {
        "ticket_id": _text(ticket.get("ticket_id") or ticket.get("id"), 128),
        "title": title,
        "description": description or other or "请补充问题描述",
        "priority": priority,
        "service_category": category,
        "other_info": other,
        "guest": {
            "open_id": guest_id,
            "name": _text(guest.get("name") if isinstance(guest, dict) else "", 128),
            "email": _text(guest.get("email") if isinstance(guest, dict) else "", 256),
        },
        "agent": {
            "open_id": agent_id,
            "name": _text("、".join(dict.fromkeys(agent_names)), 256),
        },
        "raw_fields": {str(k): _text(v, 2000) for k, v in fields.items()},
    }


def normalize_helpdesk_ticket(client: Any, ticket: dict, helpdesk_id: str, helpdesk_token: str) -> dict:
    """归一化工单，并将服务类别下拉 UUID 转为飞书显示名称。

    服务台工单详情接口对下拉字段返回的是内部 ``tag``。只有在该值呈 UUID
    形式时才额外读取字段元数据，避免普通文本字段增加一次远端请求；元数据
    权限或接口不可用时保留原值，确保人工交接仍可继续。
    """
    snapshot = normalize_ticket(ticket)
    category = snapshot.get("service_category") or ""
    if not _OPTION_ID_RE.match(category):
        return snapshot
    try:
        fields = client.get_helpdesk_ticket_customized_fields(helpdesk_id, helpdesk_token)
        labels = _option_label_map(fields)
        label = labels.get(category)
        if label:
            snapshot["service_category"] = label
            return snapshot
        logger.warning("Feishu helpdesk category option %s has no display label", category)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unable to resolve Feishu helpdesk category option %s: %s", category, exc)
    return snapshot


def _require_action(action: str) -> str:
    if action not in ALLOWED_ACTIONS:
        raise AppError("FEISHU_HANDOFF_ACTION_INVALID", "交接类型必须为 service_request 或 requirement", 422)
    return action


def _verify_service_desk_header(db: Session, header: str | None) -> tuple[Any, str, str]:
    """验证服务台服务端回调使用的 X-Lark-Helpdesk-Authorization。"""
    if not header:
        raise AppError("FEISHU_HANDOFF_AUTH_REQUIRED", "缺少飞书服务台回调凭证", 401)
    import base64

    try:
        decoded = base64.b64decode(header).decode("utf-8")
        supplied_id, supplied_token = decoded.split(":", 1)
    except Exception as exc:  # noqa: BLE001
        raise AppError("FEISHU_HANDOFF_AUTH_INVALID", "飞书服务台回调凭证格式无效", 401) from exc
    client, cfg, helpdesk_id, helpdesk_token = build_helpdesk_client(db)
    if not (hmac.compare_digest(supplied_id, helpdesk_id) and hmac.compare_digest(supplied_token, helpdesk_token)):
        raise AppError("FEISHU_HANDOFF_AUTH_INVALID", "飞书服务台回调凭证无效", 401)
    return client, helpdesk_id, helpdesk_token


def _create_handoff(
    db: Session,
    ticket_id: str,
    action: str,
    helpdesk_id: str,
    snapshot: dict,
    public_url: str,
    callback_event_id: str | None = None,
) -> dict:
    action = _require_action(action)
    source_user_open_id = snapshot["guest"]["open_id"]
    if not source_user_open_id:
        raise AppError("FEISHU_TICKET_IDENTITY_MISSING", "飞书工单未返回用户身份，无法安全交接", 422)
    if callback_event_id:
        duplicate = db.query(FeishuHelpdeskHandoff).filter(
            FeishuHelpdeskHandoff.callback_event_id == callback_event_id,
            FeishuHelpdeskHandoff.is_deleted.is_(False),
        ).first()
        if duplicate:
            raise AppError("FEISHU_CARD_DUPLICATE", "该卡片操作已处理，请使用上一条 ITOM 入口", 409)
    raw_token = secrets.token_urlsafe(32)
    row = FeishuHelpdeskHandoff(
        ticket_id=ticket_id.strip(), action=action, source_user_open_id=source_user_open_id,
        source_agent_open_id=snapshot["agent"]["open_id"] or None, helpdesk_id=helpdesk_id,
        token_hash=token_hash(raw_token), ticket_snapshot=snapshot,
        expires_at=datetime.now() + timedelta(minutes=HANDOFF_TTL_MINUTES),
        callback_event_id=callback_event_id,
    )
    db.add(row)
    _upsert_intake(db, helpdesk_id, ticket_id.strip(), snapshot)
    db.commit()
    return {
        "handoff_token": raw_token,
        "action": action,
        "expires_at": row.expires_at,
        "url": f"{public_url.rstrip('/')}/feishu/helpdesk/handoff?token={raw_token}",
        "entry_url": (
            f"{public_url.rstrip('/')}/itsm/tickets?handoff={raw_token}"
            if action == "service_request"
            else f"{public_url.rstrip('/')}/requirements/overview?handoff={raw_token}"
        ),
        "ticket_id": ticket_id.strip(),
    }


def issue_handoff(db: Session, ticket_id: str, action: str, auth_header: str | None, public_url: str) -> dict:
    action = _require_action(action)
    client, helpdesk_id, helpdesk_token = _verify_service_desk_header(db, auth_header)
    ticket = client.get_helpdesk_ticket(ticket_id, helpdesk_id, helpdesk_token)
    return _create_handoff(
        db, ticket_id, action, helpdesk_id,
        normalize_helpdesk_ticket(client, ticket, helpdesk_id, helpdesk_token), public_url,
    )


def send_choice_card(db: Session, ticket_id: str, auth_header: str | None) -> dict:
    """读取服务台工单，并把 ITOM 分流选择卡片发送给工单申请人。

    该动作只允许受信任的服务端携带服务台凭证调用；卡片回调时仍会重新
    读取工单并核对点击人的 ``open_id``，因此这里不把工单快照或服务台凭证
    写入卡片内容。
    """
    client, helpdesk_id, helpdesk_token = _verify_service_desk_header(db, auth_header)
    ticket = client.get_helpdesk_ticket(ticket_id, helpdesk_id, helpdesk_token)
    snapshot = normalize_ticket(ticket)
    recipient_open_id = snapshot["guest"]["open_id"]
    if not recipient_open_id:
        raise AppError("FEISHU_TICKET_IDENTITY_MISSING", "飞书工单未返回申请人身份，无法发送选择卡片", 422)
    message_id = client.send_interactive_card(
        recipient_open_id,
        "open_id",
        build_choice_card(ticket_id),
    )
    return {
        "message_id": message_id,
        "ticket_id": ticket_id.strip(),
        "recipient_open_id": recipient_open_id,
    }


def issue_card_handoff(
    db: Session,
    ticket_id: str,
    action: str,
    expected_user_open_id: str,
    public_url: str,
    callback_event_id: str | None = None,
) -> dict:
    """卡片回调专用交接：服务端重新读取工单并核对点击人身份。"""
    action = _require_action(action)
    client, _, helpdesk_id, helpdesk_token = build_helpdesk_client(db)
    ticket = client.get_helpdesk_ticket(ticket_id, helpdesk_id, helpdesk_token)
    snapshot = normalize_helpdesk_ticket(client, ticket, helpdesk_id, helpdesk_token)
    if not expected_user_open_id or not hmac.compare_digest(
        expected_user_open_id, snapshot["guest"]["open_id"]
    ):
        raise AppError("FEISHU_CARD_IDENTITY_MISMATCH", "卡片点击人不是该飞书工单申请人", 403)
    return _create_handoff(
        db, ticket_id, action, helpdesk_id, snapshot, public_url,
        callback_event_id=callback_event_id,
    )


def issue_intake_handoff(
    db: Session,
    intake_id: str,
    action: str,
    user: AuthUser,
    public_url: str,
) -> dict:
    """Authenticate a stable Helpdesk entry before issuing its short-lived token.

    The URL written into the original Helpdesk conversation contains only an
    intake ID and action.  A one-time token is created here *after* ITOM login,
    after both the stored intake identity and a fresh Helpdesk ticket snapshot
    have been checked against the current account's Feishu ``open_id``.
    """
    action = _require_action(action)
    intake = db.query(FeishuHelpdeskIntake).filter(
        FeishuHelpdeskIntake.id == intake_id,
        FeishuHelpdeskIntake.is_deleted.is_(False),
    ).with_for_update().first()
    if not intake:
        raise AppError("FEISHU_INTAKE_NOT_FOUND", "待分流记录不存在或已失效", 404)
    if intake.classification == "cancelled":
        raise AppError("FEISHU_INTAKE_CANCELLED", "该飞书服务台工单已取消，不能创建 ITOM 单据", 409)
    if not user.external_id or not intake.guest_open_id or not hmac.compare_digest(
        user.external_id,
        intake.guest_open_id,
    ):
        raise AppError("FEISHU_HANDOFF_IDENTITY_MISMATCH", "当前 ITOM 账号与飞书工单用户不一致", 403)

    if intake.linked_entity_type and intake.linked_entity_id:
        path = (
            f"/itsm/tickets/{intake.linked_entity_id}"
            if intake.linked_entity_type == "ticket"
            else f"/requirements/{intake.linked_entity_id}"
        )
        return {
            "status": "linked",
            "action": action,
            "ticket_id": intake.ticket_id,
            "linked_entity_type": intake.linked_entity_type,
            "linked_entity_id": intake.linked_entity_id,
            "entry_url": f"{public_url.rstrip('/')}{path}",
        }

    client, cfg, helpdesk_id, helpdesk_token = build_helpdesk_client(db)
    if not hmac.compare_digest(helpdesk_id, intake.helpdesk_id):
        raise AppError("FEISHU_HELPDESK_MISMATCH", "待分流记录不属于当前配置的飞书服务台", 409)
    ticket = client.get_helpdesk_ticket(intake.ticket_id, helpdesk_id, helpdesk_token)
    snapshot = normalize_helpdesk_ticket(client, ticket, helpdesk_id, helpdesk_token)
    fresh_guest_open_id = str((snapshot.get("guest") or {}).get("open_id") or "")
    if not fresh_guest_open_id or not hmac.compare_digest(user.external_id, fresh_guest_open_id):
        raise AppError("FEISHU_HANDOFF_IDENTITY_MISMATCH", "飞书工单申请人与当前 ITOM 账号不一致", 403)

    # Keep only one live token per Helpdesk ticket.  A stable conversation URL
    # can be clicked repeatedly, but every click invalidates the older unconsumed
    # token before issuing a fresh ten-minute token.
    db.query(FeishuHelpdeskHandoff).filter(
        FeishuHelpdeskHandoff.helpdesk_id == helpdesk_id,
        FeishuHelpdeskHandoff.ticket_id == intake.ticket_id,
        FeishuHelpdeskHandoff.status == "issued",
        FeishuHelpdeskHandoff.is_deleted.is_(False),
    ).update({FeishuHelpdeskHandoff.status: "expired"}, synchronize_session=False)
    db.flush()
    result = _create_handoff(
        db,
        intake.ticket_id,
        action,
        helpdesk_id,
        snapshot,
        public_url or _configured_public_url(cfg),
    )
    result["status"] = "issued"
    return result


def get_handoff(
    db: Session,
    raw_token: str,
    user: AuthUser,
    *,
    allow_consumed: bool = False,
) -> FeishuHelpdeskHandoff:
    if not raw_token or len(raw_token) < 20:
        raise AppError("FEISHU_HANDOFF_INVALID", "交接链接无效或已过期", 410)
    row = db.query(FeishuHelpdeskHandoff).filter(FeishuHelpdeskHandoff.token_hash == token_hash(raw_token)).first()
    if not row or row.is_deleted:
        raise AppError("FEISHU_HANDOFF_INVALID", "交接链接无效或已过期", 410)
    # 先核对身份，再决定是否返回已消费结果，避免向其他账号泄露关联单据。
    if not user.external_id or not hmac.compare_digest(user.external_id, row.source_user_open_id):
        raise AppError("FEISHU_HANDOFF_IDENTITY_MISMATCH", "当前 ITOM 账号与飞书工单用户不一致", 403)
    if row.status == "consumed" and allow_consumed:
        return row
    if row.status != "issued":
        raise AppError("FEISHU_HANDOFF_USED", "该交接链接已使用，不能重复创建", 409)
    if row.expires_at < datetime.now():
        row.status = "expired"
        db.commit()
        raise AppError("FEISHU_HANDOFF_EXPIRED", "交接链接已过期，请从飞书重新发起", 410)
    return row


def consume_handoff(db: Session, row: FeishuHelpdeskHandoff, entity_type: str, entity_id: str) -> None:
    row.status = "consumed"
    row.consumed_at = datetime.now()
    row.consumed_entity_type = entity_type
    row.consumed_entity_id = entity_id
    intake = db.query(FeishuHelpdeskIntake).filter(
        FeishuHelpdeskIntake.helpdesk_id == row.helpdesk_id,
        FeishuHelpdeskIntake.ticket_id == row.ticket_id,
        FeishuHelpdeskIntake.is_deleted.is_(False),
    ).first()
    if intake:
        intake.classification = entity_type
        intake.linked_entity_type = entity_type
        intake.linked_entity_id = entity_id
        intake.last_error = None
        _enqueue_outbox(
            db,
            intake,
            "public_message",
            f"{row.ticket_id}:intake:{entity_type}:{entity_id}",
            {"text": f"ITOM 已登记你的{'服务请求' if entity_type == 'ticket' else 'IT 需求'}，后续进展会在本服务台会话中同步。"},
        )
        # 建单和流程实例启动发生在交接令牌消费之前，流程引擎的首个
        # ticket.assigned 事件可能早于 intake 关联而无法被订阅者看到。
        # 在关联完成后补发一次当前节点的分派事件，保证五个节奏点不丢失。
        if entity_type == "ticket":
            from app.models import Ticket
            from app.services.process_engine import current_pending_task

            ticket = db.get(Ticket, entity_id)
            pending = current_pending_task(db, "ticket", entity_id) if ticket else None
            if pending and pending.assignee:
                publish(
                    db,
                    "ticket.assigned",
                    "ticket",
                    entity_id,
                    {
                        "assignee": pending.assignee,
                        "step_code": pending.step.step_code or f"step_{pending.step.seq}",
                        "step_name": pending.step.name,
                    },
                )
    db.commit()


def event_verification_token(db: Session) -> str:
    from app.services.feishu import get_config

    return decrypt_secret(get_config(db).helpdesk_event_verification_token_encrypted)


# ---------- 可靠同步：飞书事件入站、待分流和用户可见进展出站 ----------

def _event_id(payload: dict[str, Any]) -> str:
    header = payload.get("header") or {}
    value = header.get("event_id") or payload.get("event_id")
    if value:
        return str(value)[:128]
    # 少数旧版回调没有 event_id；内容哈希仍可避免同一请求重复入队。
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _event_type_from_payload(payload: dict[str, Any]) -> str:
    header = payload.get("header") or {}
    return str(header.get("event_type") or payload.get("event_type") or payload.get("type") or "unknown")[:128]


def _find_value(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in keys and item not in (None, ""):
                return item
        for item in value.values():
            found = _find_value(item, keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_value(item, keys)
            if found not in (None, ""):
                return found
    return None


def event_ticket_id(payload: dict[str, Any]) -> str:
    value = _find_value(payload, {"ticket_id", "ticketid"})
    return _text(value, 128)


def _state_value(payload: dict[str, Any], keys: set[str]) -> str:
    return _text(_find_value(payload, keys), 64).lower()


def _is_human_service(snapshot: dict, payload: dict) -> bool:
    agent = snapshot.get("agent") or {}
    if isinstance(agent, dict) and (agent.get("open_id") or agent.get("name")):
        return True
    if isinstance(agent, list) and any(
        isinstance(item, dict) and (item.get("open_id") or item.get("id") or item.get("name"))
        for item in agent
    ):
        return True
    state = " ".join(
        x for x in (
            _state_value(payload, {"stage", "status", "service_type", "ticket_type"}),
            str(snapshot.get("feishu_stage") or "").lower(),
        ) if x
    )
    return any(word in state for word in ("human", "manual", "人工", "agent"))


def _rating(payload: dict, snapshot: dict) -> int | None:
    value = _find_value(payload, {"satisfaction", "rating", "score", "evaluation_score"})
    if value in (None, ""):
        value = _find_value(snapshot, {"satisfaction", "rating", "score"})

    def unwrap(raw: Any) -> Any:
        if isinstance(raw, dict):
            for key in ("score", "rating", "value", "level", "name", "text", "display_name"):
                if raw.get(key) not in (None, ""):
                    return unwrap(raw[key])
        return raw

    value = unwrap(value)
    if isinstance(value, str):
        value = value.strip().lower()
        # 飞书界面显示的是满意度文案，详情接口可能不再返回 1~5 数字。
        value = {"满意": 5, "非常满意": 5, "一般": 3, "不满意": 1, "非常不满意": 1}.get(value, value)
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        score = None
    if score is not None and 1 <= score <= 5:
        return score

    # There is no standalone rating event in Helpdesk.  After a user clicks a
    # rating, ticket_message.created_v1 contains text such as “你的打分为:
    # 😄 满意”.  Do not parse the prompt containing all three choices; require
    # the explicit result phrase.
    text = json.dumps(payload, ensure_ascii=False)
    if "打分" in text or "评分结果" in text:
        if "不满意" in text:
            return 1
        if "一般" in text:
            return 3
        if "满意" in text:
            return 5
    return None


def _remote_states(payload: dict, ticket: dict) -> set[str]:
    """提取服务台状态/阶段，兼容不同事件版本的字段命名。"""
    states: set[str] = set()
    for source in (payload, ticket):
        if not isinstance(source, dict):
            continue
        for key in ("status", "stage", "state", "ticket_status", "ticket_stage", "solve", "solved"):
            value = _state_value(source, {key})
            if value:
                # Helpdesk status values are numeric: 50/51 are robot/manual
                # close, while solved=2 means the user marked the service
                # solved. Keep the raw value too for diagnostics.
                states.add(value)
                if key == "status" and value in {"50", "51"}:
                    states.add("closed")
                if key in {"solve", "solved"} and value == "2":
                    states.add("solved")
    return states


def _remote_user_confirmed(states: set[str]) -> bool:
    return any(
        value in {"resolved", "completed", "finished", "confirmed", "user_confirmed", "closed", "已解决", "已完成", "已确认", "已关闭", "已结束"}
        or "confirm" in value
        or "确认" in value
        or value in {"solved", "已解决"}
        for value in states
    )


def _remote_closed(states: set[str]) -> bool:
    return any(
        value in {"closed", "completed", "finished", "已关闭", "已结束", "已完成"}
        or "close" in value
        or "结束" in value
        or value in {"50", "51"}
        for value in states
    )


def _sync_linked_ticket_state(db: Session, intake: FeishuHelpdeskIntake, payload: dict, ticket: dict) -> None:
    """把飞书用户确认/关闭动作推进到关联 ITSM 服务请求。

    飞书的事件只负责提供当前状态，ITOM 仍通过自己的流程引擎和状态机推进，
    避免直接写状态绕过流程任务、审计和 SLA 派生逻辑。
    """
    if intake.linked_entity_type != "ticket" or not intake.linked_entity_id:
        return
    from app.models import Ticket

    linked = db.get(Ticket, intake.linked_entity_id)
    if not linked or linked.is_deleted or linked.ticket_type != "service_request":
        return
    states = _remote_states(payload, ticket)
    if not states:
        return
    actor = db.get(AuthUser, linked.submitter) if linked.submitter else None
    if not actor:
        return

    confirmed = _remote_user_confirmed(states)
    closed = _remote_closed(states)
    if confirmed and linked.status not in ("closed", "rejected"):
        from app.services import process_engine
        from app.services.tickets import on_ticket_advanced

        pending = process_engine.current_pending_task(db, "ticket", linked.id)
        if pending and pending.step and pending.step.default_role == "requester":
            process_engine.complete_task(db, pending.id, actor, "飞书服务台用户确认")
            on_ticket_advanced(db, linked.id, actor)

    # 某些租户只发“已关闭”而不单独发用户确认事件；在这种情况下沿 ITOM
    # 状态机补齐收尾，确保飞书关单不会让 ITOM 永远停在 resolved/processing。
    if closed and linked.status not in ("closed", "rejected"):
        from app.services.tickets import quick_close

        try:
            quick_close(db, linked, "飞书服务台用户确认并关闭", actor)
        except AppError as exc:
            # 状态机若被管理员配置为暂不可达，不丢弃入站事件；下一次详情事件
            # 仍可重试，而管理员可从 intake.last_error 看到原因。
            intake.last_error = f"FEISHU_CLOSE_SYNC_BLOCKED: {exc.message}"
            logger.warning("Unable to close linked ticket %s from Feishu state: %s", linked.id, exc)


def _upsert_intake(db: Session, helpdesk_id: str, ticket_id: str, snapshot: dict, payload: dict | None = None) -> FeishuHelpdeskIntake:
    row = db.query(FeishuHelpdeskIntake).filter(
        FeishuHelpdeskIntake.helpdesk_id == helpdesk_id,
        FeishuHelpdeskIntake.ticket_id == ticket_id,
        FeishuHelpdeskIntake.is_deleted.is_(False),
    ).first()
    if not row:
        row = FeishuHelpdeskIntake(helpdesk_id=helpdesk_id, ticket_id=ticket_id)
        db.add(row)
    guest = snapshot.get("guest") or {}
    agent = snapshot.get("agent") or {}
    row.guest_open_id = guest.get("open_id") or row.guest_open_id
    row.guest_name = guest.get("name") or row.guest_name
    row.agent_open_id = agent.get("open_id") or row.agent_open_id
    row.agent_name = agent.get("name") or row.agent_name
    row.feishu_status = _state_value(payload or {}, {"status"}) or row.feishu_status
    row.feishu_stage = _state_value(payload or {}, {"stage"}) or row.feishu_stage
    row.snapshot = {**(row.snapshot or {}), **snapshot}
    row.last_synced_at = datetime.now()
    row.last_error = None
    return row


def _enqueue_outbox(db: Session, intake: FeishuHelpdeskIntake, kind: str, dedupe_key: str, payload: dict) -> FeishuHelpdeskOutbox:
    existing = db.query(FeishuHelpdeskOutbox).filter(FeishuHelpdeskOutbox.dedupe_key == dedupe_key).first()
    if existing:
        return existing
    row = FeishuHelpdeskOutbox(
        helpdesk_id=intake.helpdesk_id, ticket_id=intake.ticket_id, kind=kind,
        dedupe_key=dedupe_key, payload=payload, next_attempt_at=datetime.now(),
    )
    db.add(row)
    return row


def queue_sync_event(db: Session, payload: dict, event_type: str | None = None) -> tuple[FeishuHelpdeskSyncEvent, bool]:
    """把飞书事件落库；返回 (row, created)，依赖唯一 event_id 做幂等。"""
    eid = _event_id(payload)
    row = db.query(FeishuHelpdeskSyncEvent).filter(FeishuHelpdeskSyncEvent.event_id == eid).first()
    if row:
        return row, False
    row = FeishuHelpdeskSyncEvent(
        event_id=eid, event_type=event_type or _event_type_from_payload(payload),
        ticket_id=event_ticket_id(payload) or None, payload=payload,
        next_attempt_at=datetime.now(),
    )
    db.add(row)
    db.commit()
    return row, True


def process_sync_event(db: Session, row: FeishuHelpdeskSyncEvent) -> None:
    """消费一个入站事件。远端详情以当前值为准，事件体只负责触发。"""
    ticket_id = row.ticket_id or event_ticket_id(row.payload)
    if not ticket_id:
        row.status = "processed"
        row.processed_at = datetime.now()
        return
    client, _cfg, helpdesk_id, helpdesk_token = build_helpdesk_client(db)
    ticket = client.get_helpdesk_ticket(ticket_id, helpdesk_id, helpdesk_token)
    snapshot = normalize_helpdesk_ticket(client, ticket, helpdesk_id, helpdesk_token)
    intake = _upsert_intake(db, helpdesk_id, ticket_id, snapshot, row.payload)
    if _is_human_service(snapshot, row.payload) and not intake.routing_prompt_sent_at and not intake.linked_entity_id:
        _enqueue_outbox(
            db,
            intake,
            "routing_prompt",
            f"{helpdesk_id}:{ticket_id}:routing-prompt:v1",
            {},
        )
    _sync_linked_ticket_state(db, intake, row.payload, {**snapshot, **(ticket or {})})
    score = _rating(row.payload, {**snapshot, **(ticket or {})})
    if score and intake.linked_entity_type == "ticket" and intake.linked_entity_id:
        from app.models import Ticket
        linked = db.get(Ticket, intake.linked_entity_id)
        if linked and not linked.is_deleted:
            if linked.satisfaction != score:
                linked.satisfaction = score
                publish(
                    db,
                    "ticket.satisfaction_rated",
                    "ticket",
                    linked.id,
                    {"score": score, "source": "feishu_helpdesk"},
                )
    row.status = "processed"
    row.processed_at = datetime.now()
    row.last_error = None


def _retry_row(row: FeishuHelpdeskSyncEvent | FeishuHelpdeskOutbox, exc: Exception) -> None:
    row.attempts = (row.attempts or 0) + 1
    row.last_error = str(exc)[:1000]
    row.status = "failed" if row.attempts >= SYNC_MAX_ATTEMPTS else "pending"
    row.next_attempt_at = datetime.now() + timedelta(seconds=min(300, 2 ** min(row.attempts, 8)))


def scan_sync_events(limit: int = SYNC_BATCH_SIZE) -> int:
    from sqlalchemy import or_
    with SessionLocal() as db:
        rows = db.query(FeishuHelpdeskSyncEvent).filter(
            FeishuHelpdeskSyncEvent.status.in_(["pending", "failed"]),
            FeishuHelpdeskSyncEvent.attempts < SYNC_MAX_ATTEMPTS,
            or_(FeishuHelpdeskSyncEvent.next_attempt_at.is_(None), FeishuHelpdeskSyncEvent.next_attempt_at <= datetime.now()),
            FeishuHelpdeskSyncEvent.is_deleted.is_(False),
        ).order_by(FeishuHelpdeskSyncEvent.created_at).limit(limit).all()
        done = 0
        for row in rows:
            row_id = row.id
            row.status = "processing"
            try:
                process_sync_event(db, row)
                db.commit()
                done += 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                # rollback expires ORM instances.  Re-load by primary key
                # before writing the retry state, otherwise a failed remote
                # call can surface as ObjectDeletedError and stop the worker.
                retry_row = db.get(FeishuHelpdeskSyncEvent, row_id)
                if retry_row is not None:
                    _retry_row(retry_row, exc)
                    db.commit()
                    logger.warning("feishu helpdesk event retry %s (%s): %s", retry_row.event_id, retry_row.attempts, exc)
                else:
                    logger.warning("feishu helpdesk event disappeared during retry %s: %s", row_id, exc)
        return done


def _outbox_text(row: FeishuHelpdeskOutbox) -> str:
    return _text((row.payload or {}).get("text"), 2000)


def scan_outbox(limit: int = SYNC_BATCH_SIZE) -> int:
    from sqlalchemy import or_
    with SessionLocal() as db:
        rows = db.query(FeishuHelpdeskOutbox).filter(
            FeishuHelpdeskOutbox.status.in_(["pending", "failed"]),
            FeishuHelpdeskOutbox.attempts < SYNC_MAX_ATTEMPTS,
            or_(FeishuHelpdeskOutbox.next_attempt_at.is_(None), FeishuHelpdeskOutbox.next_attempt_at <= datetime.now()),
            FeishuHelpdeskOutbox.is_deleted.is_(False),
        ).order_by(FeishuHelpdeskOutbox.created_at).limit(limit).all()
        done = 0
        for row in rows:
            row_id = row.id
            row.status = "sending"
            row.attempts = (row.attempts or 0) + 1
            try:
                client, cfg, helpdesk_id, helpdesk_token = build_helpdesk_client(db)
                intake = db.query(FeishuHelpdeskIntake).filter(
                    FeishuHelpdeskIntake.helpdesk_id == row.helpdesk_id,
                    FeishuHelpdeskIntake.ticket_id == row.ticket_id,
                    FeishuHelpdeskIntake.is_deleted.is_(False),
                ).first()
                if not intake:
                    raise AppError("FEISHU_INTAKE_NOT_FOUND", "待分流记录不存在", 409)
                if row.kind == "routing_prompt":
                    if intake.routing_prompt_sent_at:
                        row.status = "sent"
                        db.commit()
                        done += 1
                        continue
                    public_url = _configured_public_url(cfg)
                    service_request_url, requirement_url = _routing_prompt_urls(public_url, intake.id)
                    try:
                        row.message_id, channel = client.send_helpdesk_routing_prompt(
                            row.ticket_id,
                            helpdesk_id,
                            helpdesk_token,
                            service_request_url,
                            requirement_url,
                        )
                    except Exception as exc:
                        # Give the original Helpdesk conversation two reliable
                        # retries.  A missing helpdesk:all scope is deterministic,
                        # so do not make the user wait for the retry backoff: use
                        # the independent application-bot card immediately and
                        # retain the permission error in the outbox audit.
                        permission_error = "helpdesk:all" in str(exc) or "99991672" in str(exc)
                        if row.attempts < 3 and not permission_error:
                            raise
                        recipient = intake.guest_open_id
                        if not recipient:
                            raise AppError("FEISHU_TICKET_IDENTITY_MISSING", "飞书工单申请人身份缺失", 422)
                        row.message_id = client.send_interactive_card(
                            recipient,
                            "open_id",
                            build_choice_card(row.ticket_id),
                        )
                        channel = "im_card_fallback"
                        intake.choice_card_sent_at = datetime.now()
                    intake.routing_prompt_sent_at = datetime.now()
                    intake.routing_prompt_channel = channel
                    intake.routing_prompt_message_id = row.message_id or None
                elif row.kind == "choice_card":
                    if intake.choice_card_sent_at:
                        row.status = "sent"
                        db.commit()
                        done += 1
                        continue
                    recipient = intake.guest_open_id
                    if not recipient:
                        raise AppError("FEISHU_TICKET_IDENTITY_MISSING", "飞书工单申请人身份缺失", 422)
                    row.message_id = client.send_interactive_card(recipient, "open_id", build_choice_card(row.ticket_id))
                    intake.choice_card_sent_at = datetime.now()
                else:
                    text = _outbox_text(row)
                    try:
                        row.message_id = client.send_helpdesk_message(
                            row.ticket_id, helpdesk_id, helpdesk_token, text,
                        )
                    except Exception as exc:
                        # ``helpdesk:all`` is required for messages inside the
                        # original Helpdesk ticket. A missing scope is a
                        # deterministic configuration error, so do not wait
                        # through eight exponential retries: deliver the same
                        # user-visible milestone through the app bot now.
                        permission_error = "helpdesk:all" in str(exc) or "99991672" in str(exc)
                        if not permission_error:
                            raise
                        if not intake.guest_open_id:
                            raise AppError("FEISHU_TICKET_IDENTITY_MISSING", "飞书工单申请人身份缺失", 422)
                        row.message_id = client.send_app_text(intake.guest_open_id, "open_id", text)
                        payload = dict(row.payload or {})
                        payload["delivery_channel"] = "im_text_fallback"
                        row.payload = payload
                row.status = "sent"
                row.sent_at = datetime.now()
                row.last_error = None
                db.commit()
                done += 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                retry_row = db.get(FeishuHelpdeskOutbox, row_id)
                if retry_row is not None:
                    _retry_row(retry_row, exc)
                    db.commit()
                    logger.warning("feishu helpdesk outbox retry %s (%s): %s", retry_row.dedupe_key, retry_row.attempts, exc)
                else:
                    logger.warning("feishu helpdesk outbox disappeared during retry %s: %s", row_id, exc)
        return done


def register_subscribers() -> None:
    """注册只发送用户可见阶段消息的内部事件订阅。"""
    global _SUBSCRIBERS_REGISTERED
    if _SUBSCRIBERS_REGISTERED:
        return

    @subscribe("ticket.*")
    def _ticket_progress(db: Session, event_type: str, entity_type: str, entity_id: str, payload: dict):
        intake = db.query(FeishuHelpdeskIntake).filter(
            FeishuHelpdeskIntake.linked_entity_type == "ticket",
            FeishuHelpdeskIntake.linked_entity_id == entity_id,
            FeishuHelpdeskIntake.is_deleted.is_(False),
        ).first()
        if not intake:
            return
        messages = {
            "ticket.created": "ITOM 已登记你的服务请求，后续进展会在本服务台会话中同步。",
            "ticket.assigned": "ITOM 已分派受理人，正在安排处理。",
            "ticket.processing": "ITOM 已受理，正在处理中。",
            "ticket.user_confirmed": "你已确认处理结果，工单正在关闭。",
            "ticket.resolved": "ITOM 已处理完成，请在飞书服务台确认结果并评价。",
            "ticket.closed": "工单已关闭，感谢你的评价。",
            "ticket.satisfaction_rated": "已记录你的服务评价，感谢反馈。",
        }
        text = messages.get(event_type)
        if text:
            _enqueue_outbox(db, intake, "public_message", f"{entity_id}:{event_type}", {"text": text})

    @subscribe("requirement.*")
    def _requirement_progress(db: Session, event_type: str, entity_type: str, entity_id: str, payload: dict):
        intake = db.query(FeishuHelpdeskIntake).filter(
            FeishuHelpdeskIntake.linked_entity_type == "requirement",
            FeishuHelpdeskIntake.linked_entity_id == entity_id,
            FeishuHelpdeskIntake.is_deleted.is_(False),
        ).first()
        if not intake:
            return
        stage = event_type.split(".", 1)[1]
        labels = {
            "registered": "需求已登记，进入评审。",
            "evaluating": "需求正在评审中。",
            "analyzing": "需求进入方案分析阶段。",
            "implementing": "需求进入实现阶段。",
            "closed": "需求已闭环，感谢你的确认。",
            "cancelled": "需求已关闭。",
        }
        text = labels.get(stage)
        if text:
            _enqueue_outbox(db, intake, "public_message", f"{entity_id}:{event_type}", {"text": text})

    _SUBSCRIBERS_REGISTERED = True


_SUBSCRIBERS_REGISTERED = False
