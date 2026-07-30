"""P0：Aily MCP 身份边界、协议入口、审计、主动消息与清理计划。"""
from datetime import datetime, timedelta, timezone
import secrets

import jwt
import pytest

from app.core.errors import AppError
from app.db import SessionLocal
from app.mcp.identity import resolve_aily_principal
from app.models import ExternalIdentity, McpToolCall, NotificationOutbox
from app.scripts.migrate_aily_mcp import render_plan
from app.services.aily import deliver_aily_outbox_row, queue_aily_card, queue_aily_text
from app.services.aily_cards import build_rating_card, build_resolution_confirmation_card
from app.services.feishu import FeishuClient


JWT_SECRET = secrets.token_urlsafe(32)
BOT_SECRET = secrets.token_urlsafe(24)
CARD_VERIFICATION_TOKEN = secrets.token_urlsafe(24)
CARD_ENCRYPT_KEY = secrets.token_urlsafe(24)
TENANT_ID = "tenant-p0"
AGENT_ID = "agent-p0"
APP_ID = "agent-p0"
SUBJECT_ID = "ou_p0_admin"
ORIGIN = "https://aily.feishu.cn"


def _token(**overrides) -> str:
    payload = {
        "tenant_id": TENANT_ID,
        "agent_id": AGENT_ID,
        "app_id": APP_ID,
        "open_id": SUBJECT_ID,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    payload.update(overrides)
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def aily_ready(client, admin_headers):
    users = client.get("/api/admin/users", params={"q": "admin", "page_size": 20}, headers=admin_headers).json()["data"]
    admin = next(user for user in users if user["username"] == "admin")
    response = client.put("/api/admin/integrations/aily", json={
        "enabled": True,
        "mcp_jwt_secret": JWT_SECRET,
        "allowed_tenant_ids": [TENANT_ID],
        "allowed_agent_ids": [AGENT_ID],
        "allowed_origins": [ORIGIN],
    }, headers=admin_headers)
    assert response.status_code == 200, response.text
    identity = client.post("/api/admin/integrations/aily/identities", json={
        "provider": "feishu",
        "tenant_id": TENANT_ID,
        "app_id": APP_ID,
        "subject_type": "open_id",
        "subject_id": SUBJECT_ID,
        "auth_user_id": admin["id"],
    }, headers=admin_headers)
    assert identity.status_code == 200, identity.text
    return {"admin": admin, "identity": identity.json()["data"]}


def test_registration_mode_requires_origin_but_not_jwt(client, admin_headers):
    response = client.put("/api/admin/integrations/aily", json={
        "enabled": True,
        "allowed_tenant_ids": [],
        "allowed_agent_ids": [AGENT_ID],
        "allowed_origins": [ORIGIN],
    }, headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["mcp_discovery_ready"] is True
    assert response.json()["data"]["mcp_tool_calls_ready"] is False
    assert response.json()["data"]["mcp_path"] == "/mcp/"

    discovery_headers = {"origin": ORIGIN, "accept": "application/json, text/event-stream"}
    initialize = client.post("/mcp/", headers=discovery_headers, json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "aily-registration", "version": "1.0"},
        },
    })
    assert initialize.status_code == 200, initialize.text
    tools = client.post("/mcp/", headers=discovery_headers, json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/list",
    })
    assert tools.status_code == 200, tools.text
    call = client.post("/mcp/", headers=discovery_headers, json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "get_current_user_context", "arguments": {}},
    })
    assert call.status_code == 503
    assert call.json()["error"]["data"]["code"] == "AILY_MCP_NOT_CONFIGURED"


def test_config_never_returns_secrets(client, admin_headers):
    response = client.put("/api/admin/integrations/aily", json={
        "enabled": True,
        "allowed_origins": [],
    }, headers=admin_headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AILY_MCP_CONFIG_INCOMPLETE"

    response = client.put("/api/admin/integrations/aily", json={
        "mcp_jwt_secret": JWT_SECRET,
        "allowed_tenant_ids": [TENANT_ID],
        "allowed_agent_ids": [AGENT_ID],
        "allowed_origins": [ORIGIN],
    }, headers=admin_headers)
    data = response.json()["data"]
    assert data["has_mcp_jwt_secret"] is True
    assert data["mcp_tool_calls_ready"] is True
    assert JWT_SECRET not in str(data)

    incomplete = client.put("/api/admin/integrations/aily", json={
        "card_callback_verification_token": CARD_VERIFICATION_TOKEN,
    }, headers=admin_headers)
    assert incomplete.status_code == 400
    assert incomplete.json()["error"]["code"] == "AILY_CARD_CALLBACK_CONFIG_INCOMPLETE"
    response = client.put("/api/admin/integrations/aily", json={
        "card_callback_verification_token": CARD_VERIFICATION_TOKEN,
        "card_callback_encrypt_key": CARD_ENCRYPT_KEY,
    }, headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["has_card_callback_verification_token"] is True
    assert response.json()["data"]["has_card_callback_encrypt_key"] is True
    assert response.json()["data"]["interactive_cards_ready"] is False
    assert CARD_VERIFICATION_TOKEN not in str(response.json())
    assert CARD_ENCRYPT_KEY not in str(response.json())


def test_public_base_url_is_normalized_and_rejects_unsafe_components(client, admin_headers):
    response = client.put("/api/admin/integrations/aily", json={
        "public_base_url": "https://itom.snnc.cc:30443/",
    }, headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["public_base_url"] == "https://itom.snnc.cc:30443"

    for invalid_url in (
        "https://itom.snnc.cc:30443/mcp/",
        "https://itom.snnc.cc:30443?source=aily",
        "https://itom.snnc.cc:30443#callback",
        "https://user:password@itom.snnc.cc:30443",
        "ftp://itom.snnc.cc:30443",
        "https://itom.snnc.cc:70000",
    ):
        invalid = client.put("/api/admin/integrations/aily", json={
            "public_base_url": invalid_url,
        }, headers=admin_headers)
        assert invalid.status_code == 422, invalid_url
        assert invalid.json()["error"]["code"] == "AILY_PUBLIC_BASE_URL_INVALID"

    current = client.get("/api/admin/integrations/aily", headers=admin_headers)
    assert current.status_code == 200, current.text
    assert current.json()["data"]["public_base_url"] == "https://itom.snnc.cc:30443"

    cleared = client.put("/api/admin/integrations/aily", json={
        "public_base_url": " ",
    }, headers=admin_headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["public_base_url"] == ""


def test_verified_but_unapproved_aily_identity_is_recorded_pending(client, admin_headers):
    client.put("/api/admin/integrations/aily", json={
        "enabled": True,
        "mcp_jwt_secret": JWT_SECRET,
        "allowed_tenant_ids": [],
        "allowed_agent_ids": [AGENT_ID],
        "allowed_origins": [ORIGIN],
    }, headers=admin_headers)
    token = _token(open_id=None, feishu_open_id="7620774801438674448", tenant_id="7283059256756502547")
    response = client.post("/mcp/", headers={
        "origin": ORIGIN,
        "x-aily-jwt": token,
        "accept": "application/json, text/event-stream",
    }, json={
        "jsonrpc": "2.0", "id": 10, "method": "tools/call",
        "params": {"name": "get_current_user_context", "arguments": {}},
    })
    assert response.status_code == 403
    assert response.json()["error"]["data"]["code"] == "AILY_TENANT_FORBIDDEN"
    with SessionLocal() as db:
        pending = db.query(ExternalIdentity).filter(
            ExternalIdentity.tenant_id == "7283059256756502547",
            ExternalIdentity.subject_id == "7620774801438674448",
        ).one()
        assert pending.status == "pending"
        assert pending.auth_user_id is None


def test_exact_identity_mapping_and_cross_user_rejection(client, admin_headers, aily_ready):
    with SessionLocal() as db:
        principal = resolve_aily_principal(db, token=_token(), origin=ORIGIN, session_ref="session-p0")
    assert principal.auth_user_id == aily_ready["admin"]["id"]
    assert principal.session_ref_hash and "session-p0" not in principal.session_ref_hash

    with SessionLocal() as db, pytest.raises(AppError) as unmapped:
        resolve_aily_principal(db, token=_token(open_id="ou_other_user"), origin=ORIGIN, session_ref=None)
    assert unmapped.value.code == "AILY_IDENTITY_UNMAPPED"

    with SessionLocal() as db, pytest.raises(AppError) as tenant_denied:
        resolve_aily_principal(db, token=_token(tenant_id="tenant-other"), origin=ORIGIN, session_ref=None)
    assert tenant_denied.value.code == "AILY_TENANT_FORBIDDEN"

    with SessionLocal() as db, pytest.raises(AppError) as origin_denied:
        resolve_aily_principal(db, token=_token(), origin="https://evil.example", session_ref=None)
    assert origin_denied.value.code == "AILY_ORIGIN_FORBIDDEN"


def test_streamable_http_tool_call_records_audit(client, aily_ready):
    headers = {
        "x-aily-jwt": _token(),
        "origin": ORIGIN,
        "accept": "application/json, text/event-stream",
    }
    initialize = client.post("/mcp/", headers=headers, json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1.0"},
        },
    })
    assert initialize.status_code == 200, initialize.text
    response = client.post("/mcp/", headers=headers, json={
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "get_current_user_context", "arguments": {}},
    })
    assert response.status_code == 200, response.text
    body = response.json()
    text_result = body["result"]["content"][0]["text"]
    compact_result = text_result.replace(" ", "")
    assert '"identity_verified":true' in compact_result
    assert '"account_name":"admin"' in compact_result
    assert aily_ready["admin"]["id"] not in text_result
    assert TENANT_ID not in text_result
    assert AGENT_ID not in text_result
    assert SUBJECT_ID not in text_result

    with SessionLocal() as db:
        audit = db.query(McpToolCall).filter(McpToolCall.tool_name == "get_current_user_context").order_by(McpToolCall.created_at.desc()).first()
        assert audit and audit.result_code == "OK"
        assert audit.auth_user_id == aily_ready["admin"]["id"]
        assert SUBJECT_ID not in audit.external_subject
        assert audit.external_subject.startswith("open_id:sha256:")


def test_mcp_discovery_allows_missing_jwt_but_tool_call_rejects_it(client):
    headers = {"origin": ORIGIN, "accept": "application/json, text/event-stream"}
    response = client.post("/mcp/", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 200
    response = client.post("/mcp/", headers=headers, json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "get_current_user_context", "arguments": {}},
    })
    assert response.status_code == 401
    assert response.json()["error"]["data"]["code"] == "AILY_JWT_MISSING"


def test_bot_message_is_reliable_and_idempotent(client, admin_headers, aily_ready, monkeypatch):
    client.put("/api/admin/integrations/aily", json={
        "bot_app_id": "cli_bot_p0",
        "bot_app_secret": BOT_SECRET,
        "message_enabled": True,
    }, headers=admin_headers)
    calls = []
    monkeypatch.setattr(FeishuClient, "send_app_text", lambda self, recipient_id, recipient_type, text: calls.append((recipient_id, recipient_type, text)) or "om_p0")
    response = client.post("/api/admin/integrations/aily/test-message", json={
        "identity_id": aily_ready["identity"]["id"], "text": "P0 主动消息测试",
    }, headers=admin_headers)
    assert response.status_code == 200, response.text
    assert calls == [(SUBJECT_ID, "open_id", "P0 主动消息测试")]
    with SessionLocal() as db:
        row = db.query(NotificationOutbox).filter(NotificationOutbox.provider_message_id == "om_p0").one()
        assert row.status == "sent" and row.idempotency_key

    with SessionLocal() as db:
        first = queue_aily_text(
            db,
            recipient_type="open_id",
            recipient_id=SUBJECT_ID,
            text="只应入队一次",
            idempotency_key="p0-fixed-idempotency-key",
        )
        db.commit()
        first_id = first.id
    with SessionLocal() as db:
        repeated = queue_aily_text(
            db,
            recipient_type="open_id",
            recipient_id=SUBJECT_ID,
            text="重复调用不新增",
            idempotency_key="p0-fixed-idempotency-key",
        )
        assert repeated.id == first_id
        assert db.query(NotificationOutbox).filter(
            NotificationOutbox.idempotency_key == "p0-fixed-idempotency-key"
        ).count() == 1


def test_interactive_card_outbox_and_feishu_callback_contract(client, admin_headers, monkeypatch):
    config = client.put("/api/admin/integrations/aily", json={
        "enabled": True,
        "bot_app_id": "cli_bot_p0",
        "bot_app_secret": BOT_SECRET,
        "message_enabled": True,
        "card_callback_verification_token": CARD_VERIFICATION_TOKEN,
        "card_callback_encrypt_key": CARD_ENCRYPT_KEY,
    }, headers=admin_headers)
    assert config.status_code == 200, config.text
    assert config.json()["data"]["interactive_cards_ready"] is True
    resolved_card = build_resolution_confirmation_card(
        ticket_code="TK-P0-CARD",
        title="交互卡片验证",
        solution="已恢复服务",
        confirmation_due_at="2026-07-31 12:00",
        reopen_count=1,
    )
    rating_card = build_rating_card(
        ticket_code="TK-P0-CARD",
        title="交互卡片验证",
    )
    confirm_actions = resolved_card["elements"][1]["actions"]
    assert len(confirm_actions) == 2
    assert confirm_actions[0]["value"]["itom_action"] == "confirm_resolved"
    assert confirm_actions[1]["value"]["itom_action"] == "show_reopen_form"
    assert "skill_id" not in confirm_actions[0]["value"]
    assert len(rating_card["elements"][1]["actions"]) == 5
    assert rating_card["elements"][1]["actions"][4]["value"]["score"] == 5

    calls = []
    monkeypatch.setattr(
        FeishuClient,
        "send_interactive_card",
        lambda self, recipient_id, recipient_type, card: calls.append(
            (recipient_id, recipient_type, card)
        ) or "om_card_p0",
    )
    with SessionLocal() as db:
        row = queue_aily_card(
            db,
            recipient_type="open_id",
            recipient_id=SUBJECT_ID,
            card=resolved_card,
            fallback_text="交互卡片回退文本",
            idempotency_key="p0-card-idempotency-key",
            event_type="ticket.resolved",
        )
        deliver_aily_outbox_row(db, row)
        db.commit()
        assert row.status == "sent"
        assert row.provider_message_id == "om_card_p0"
        assert row.payload["message_type"] == "interactive"
    assert calls == [(SUBJECT_ID, "open_id", resolved_card)]


def test_cleanup_is_preview_only_without_confirm():
    plan = render_plan()
    assert "DROP TABLE IF EXISTS feishu_helpdesk_intake" in plan
    assert "helpdesk_token_encrypted" in plan
