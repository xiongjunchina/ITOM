"""P2：Aily 服务请求解决确认、重开、关闭评价与可靠消息闭环。"""

from datetime import datetime, timedelta

from app.db import SessionLocal
from app.models import (
    AilyIntegrationConfig,
    NotificationOutbox,
    ProcessInstance,
    ProcessTask,
    Ticket,
    TicketSatisfaction,
)
from app.services import process_engine
from app.services.aily_ticket_notifications import scan_pending_confirmation_reminders
from app.services.secrets_store import encrypt_secret

from tests.test_m81_aily_mcp_p1 import (
    OTHER_SUBJECT,
    ORIGIN,
    _mcp_call,
    p1,
)


def _create_request(client, p1, key: str) -> str:
    prepared = _mcp_call(
        client,
        "prepare_service_request",
        {
            "service_item_id": p1["item"]["item_code"],
            "answers": {
                "title": f"P2 VPN 闭环验证 {key}",
                "description": "VPN 客户端持续提示证书错误，需要 IT 协助处理",
                "priority": "P2",
                "contact_method": "飞书",
                "suspected_major_impact": False,
            },
            "idempotency_key": f"{key}-prepare",
        },
    )
    assert prepared["ready_for_confirmation"] is True
    submitted = _mcp_call(
        client,
        "submit_service_request",
        {
            "confirmation_token": prepared["confirmation_token"],
            "idempotency_key": f"{key}-prepare",
        },
    )
    assert submitted["created"] is True
    return submitted["ticket_code"]


def _complete_current_task(client, p1, ticket_code: str, comment: str) -> None:
    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        task = process_engine.current_pending_task(db, "ticket", ticket.id)
        assert task is not None
        task_id = task.id
    response = client.post(
        f"/api/process-tasks/{task_id}/complete",
        json={"comment": comment},
        headers=p1["support_headers"],
    )
    assert response.status_code == 200, response.text


def test_p2_tool_discovery_is_narrow_and_user_scoped(client, p1):
    response = client.post(
        "/mcp/",
        headers={"origin": ORIGIN, "accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 82, "method": "tools/list"},
    )
    assert response.status_code == 200, response.text
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert {
        "get_my_pending_confirmations",
        "confirm_service_request_resolution",
        "rate_service_request",
    } <= names
    assert "transition_ticket" not in names
    assert "reassign_ticket" not in names


def test_p2_service_request_reopen_confirm_rate_and_outbox(client, p1):
    with SessionLocal() as db:
        cfg = db.query(AilyIntegrationConfig).filter(
            AilyIntegrationConfig.is_deleted.is_(False)
        ).one()
        cfg.bot_app_id = "cli_p2_card_bot"
        cfg.bot_app_secret_encrypted = encrypt_secret("p2-card-bot-secret")
        cfg.message_enabled = True
        cfg.card_callback_verification_token_encrypted = encrypt_secret("p2-verification-token")
        cfg.card_callback_encrypt_key_encrypted = encrypt_secret("p2-encrypt-key")
        db.commit()
    ticket_code = _create_request(client, p1, "p2-closure-001")

    _complete_current_task(client, p1, ticket_code, "已受理，开始排查证书")
    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        assert ticket.status == "processing"
        assert ticket.accepted_at is not None
        assert ticket.first_response_at == ticket.accepted_at

    _complete_current_task(client, p1, ticket_code, "已更新证书并恢复 VPN 连接")
    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        assert ticket.status == "resolved"
        assert ticket.resolved_at is not None
        assert ticket.confirmation_due_at is not None
        assert ticket.confirmation_due_at > ticket.resolved_at

    pending = _mcp_call(client, "get_my_pending_confirmations", {})
    match = next(row for row in pending["items"] if row["ticket_code"] == ticket_code)
    assert match["solution"] == "已更新证书并恢复 VPN 连接"
    assert "root_cause" not in match
    assert "remarks" not in match

    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        ticket.resolved_at = datetime.now() - timedelta(hours=24)
        ticket.confirmation_due_at = datetime.now() - timedelta(minutes=1)
        db.commit()
    scan_pending_confirmation_reminders()
    scan_pending_confirmation_reminders()

    denied = _mcp_call(
        client,
        "confirm_service_request_resolution",
        {
            "ticket_code": ticket_code,
            "resolved": True,
            "idempotency_key": "p2-other-confirm-001",
        },
        subject=OTHER_SUBJECT,
    )
    assert denied["success"] is False
    assert denied["error"]["code"] == "NOT_FOUND"

    reopened = _mcp_call(
        client,
        "confirm_service_request_resolution",
        {
            "ticket_code": ticket_code,
            "resolved": False,
            "feedback": "证书错误消失，但连接后仍无法访问内部系统",
            "idempotency_key": "p2-reopen-001",
        },
    )
    assert reopened["reopened"] is True
    assert reopened["reopen_count"] == 1
    replay = _mcp_call(
        client,
        "confirm_service_request_resolution",
        {
            "ticket_code": ticket_code,
            "resolved": False,
            "feedback": "证书错误消失，但连接后仍无法访问内部系统",
            "idempotency_key": "p2-reopen-001",
        },
    )
    assert replay["idempotent_replay"] is True
    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        assert ticket.status == "processing"
        assert ticket.reopen_count == 1
        assert ticket.confirmation_due_at is None
        instance = db.query(ProcessInstance).filter(
            ProcessInstance.entity_type == "ticket",
            ProcessInstance.entity_id == ticket.id,
            ProcessInstance.is_deleted.is_(False),
        ).one()
        assert instance.status == "running"
        assert instance.current_step_seq == 2

    _complete_current_task(client, p1, ticket_code, "已补充内网路由策略，业务系统访问恢复")
    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        assert ticket.status == "resolved"
        assert ticket.solution == "已补充内网路由策略，业务系统访问恢复"
        active_tasks = (
            db.query(ProcessTask)
            .join(ProcessInstance, ProcessInstance.id == ProcessTask.instance_id)
            .filter(
                ProcessInstance.entity_type == "ticket",
                ProcessInstance.entity_id == ticket.id,
                ProcessTask.is_deleted.is_(False),
            )
            .all()
        )
        assert len(active_tasks) == 3
        assert sum(task.status == "待处理" for task in active_tasks) == 1
    confirmed = _mcp_call(
        client,
        "confirm_service_request_resolution",
        {
            "ticket_code": ticket_code,
            "resolved": True,
            "feedback": "已验证恢复",
            "idempotency_key": "p2-confirm-001",
        },
    )
    assert confirmed["closed"] is True
    assert confirmed["status"] == "closed"
    confirmed_replay = _mcp_call(
        client,
        "confirm_service_request_resolution",
        {
            "ticket_code": ticket_code,
            "resolved": True,
            "feedback": "已验证恢复",
            "idempotency_key": "p2-confirm-001",
        },
    )
    assert confirmed_replay["idempotent_replay"] is True

    rated = _mcp_call(
        client,
        "rate_service_request",
        {
            "ticket_code": ticket_code,
            "score": 5,
            "tags": ["响应及时", "解决专业", "响应及时"],
            "comment": "处理过程清晰，问题已解决",
            "idempotency_key": "p2-rate-001",
        },
    )
    assert rated["created"] is True
    assert rated["tags"] == ["响应及时", "解决专业"]
    rated_replay = _mcp_call(
        client,
        "rate_service_request",
        {
            "ticket_code": ticket_code,
            "score": 5,
            "tags": ["响应及时", "解决专业", "响应及时"],
            "comment": "处理过程清晰，问题已解决",
            "idempotency_key": "p2-rate-001",
        },
    )
    assert rated_replay["idempotent_replay"] is True
    conflict = _mcp_call(
        client,
        "rate_service_request",
        {
            "ticket_code": ticket_code,
            "score": 4,
            "tags": ["响应及时"],
            "comment": "改用相同幂等键",
            "idempotency_key": "p2-rate-001",
        },
    )
    assert conflict["success"] is False
    assert conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    denied_rating = _mcp_call(
        client,
        "rate_service_request",
        {
            "ticket_code": ticket_code,
            "score": 5,
            "idempotency_key": "p2-other-rate-001",
        },
        subject=OTHER_SUBJECT,
    )
    assert denied_rating["success"] is False
    assert denied_rating["error"]["code"] == "NOT_FOUND"
    updated = _mcp_call(
        client,
        "rate_service_request",
        {
            "ticket_code": ticket_code,
            "score": 4,
            "tags": ["解决专业"],
            "comment": "补充评价：整体满意",
            "idempotency_key": "p2-rate-update-001",
        },
    )
    assert updated["created"] is False
    assert updated["score"] == 4

    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        assert ticket.status == "closed"
        assert ticket.satisfaction == 4
        assert ticket.reopen_count == 1
        rating = db.query(TicketSatisfaction).filter(
            TicketSatisfaction.ticket_id == ticket.id,
            TicketSatisfaction.is_deleted.is_(False),
        ).one()
        assert rating.source == "aily"
        assert rating.tags == ["解决专业"]
        assert rating.comment == "补充评价：整体满意"
        outbox = db.query(NotificationOutbox).filter(
            NotificationOutbox.entity_id == ticket.id,
            NotificationOutbox.channel == "feishu_aily",
        ).all()
        event_types = [row.event_type for row in outbox]
        assert event_types.count("ticket.accepted") == 1
        assert event_types.count("ticket.resolved") == 2
        assert event_types.count("ticket.confirmation_reminder") == 1
        assert event_types.count("ticket.reopened") == 1
        assert event_types.count("ticket.closed") == 1
        assert event_types.count("ticket.satisfaction_saved") == 2
        serialized = str([row.payload for row in outbox])
        assert "root_cause" not in serialized
        assert "用户反馈仍未解决" not in serialized
        resolved_rows = [row for row in outbox if row.event_type == "ticket.resolved"]
        assert all(row.payload.get("message_type") == "interactive" for row in resolved_rows)
        first_buttons = resolved_rows[0].payload["card"]["elements"][1]["actions"]
        assert first_buttons[0]["value"]["itom_action"] == "confirm_resolved"
        assert first_buttons[1]["value"]["itom_action"] == "show_reopen_form"
        closed_row = next(row for row in outbox if row.event_type == "ticket.closed")
        assert closed_row.payload.get("message_type") == "interactive"
        assert len(closed_row.payload["card"]["elements"][1]["actions"]) == 5
        reminder = next(row for row in outbox if row.event_type == "ticket.confirmation_reminder")
        assert reminder.payload.get("message_type") == "interactive"


def test_web_requester_confirmation_uses_same_reopen_and_close_semantics(client, p1, admin_headers):
    ticket_code = _create_request(client, p1, "p2-web-closure-001")
    _complete_current_task(client, p1, ticket_code, "网页闭环测试：已受理")
    _complete_current_task(client, p1, ticket_code, "网页闭环测试：首次处理完成")

    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        task = process_engine.current_pending_task(db, "ticket", ticket.id)
        assert task is not None
        task_id = task.id
    admin_denied = client.post(
        f"/api/process-tasks/{task_id}/approve",
        json={"comment": "管理员不能代替用户确认"},
        headers=admin_headers,
    )
    assert admin_denied.status_code == 403

    rejected = client.post(
        f"/api/process-tasks/{task_id}/reject",
        json={"reason": "网页验证后发现内网仍然无法访问"},
        headers=p1["requester_headers"],
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["reopened"] is True

    _complete_current_task(client, p1, ticket_code, "网页闭环测试：补充路由后恢复")
    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        task = process_engine.current_pending_task(db, "ticket", ticket.id)
        assert ticket.status == "resolved"
        assert task is not None
        task_id = task.id
    approved = client.post(
        f"/api/process-tasks/{task_id}/approve",
        json={"comment": "网页验证已恢复"},
        headers=p1["requester_headers"],
    )
    assert approved.status_code == 200, approved.text
    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        assert ticket.status == "closed"
        assert ticket.reopen_count == 1
