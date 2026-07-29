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
from app.services.aily import queue_aily_text
from app.services.feishu import FeishuClient


JWT_SECRET = secrets.token_urlsafe(32)
BOT_SECRET = secrets.token_urlsafe(24)
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


def test_cleanup_is_preview_only_without_confirm():
    plan = render_plan()
    assert "DROP TABLE IF EXISTS feishu_helpdesk_intake" in plan
    assert "helpdesk_token_encrypted" in plan
