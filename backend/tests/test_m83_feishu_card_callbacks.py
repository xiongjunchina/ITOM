"""P2.1：飞书交互卡片验签、点击人授权、重开、关闭和评价闭环。"""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from types import SimpleNamespace

from app.db import SessionLocal
from app.models import Ticket, TicketSatisfaction
from app.services.feishu_card_callbacks import verify_and_decode_callback
from app.services.secrets_store import encrypt_secret
from tests.test_m81_aily_mcp_p1 import (
    AGENT_ID,
    OTHER_SUBJECT,
    REQUESTER_SUBJECT,
    TENANT_ID,
    p1,
)
from tests.test_m82_aily_mcp_p2 import _complete_current_task, _create_request


CARD_APP_ID = "cli_card_callbacks"
CARD_VERIFICATION_TOKEN = "card-verification-token-p2"
CARD_ENCRYPT_KEY = "card-encrypt-key-p2"
CARD_TENANT_KEY = "feishu-card-tenant-key-p2"


@pytest.fixture(scope="module")
def card_ready(client, admin_headers, p1):
    response = client.put(
        "/api/admin/integrations/aily",
        json={
            "enabled": True,
            "allowed_tenant_ids": [TENANT_ID],
            "allowed_agent_ids": [AGENT_ID],
            "bot_app_id": CARD_APP_ID,
            "bot_app_secret": secrets.token_urlsafe(24),
            "message_enabled": True,
            "card_callback_verification_token": CARD_VERIFICATION_TOKEN,
            "card_callback_encrypt_key": CARD_ENCRYPT_KEY,
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["interactive_cards_ready"] is True
    return response.json()["data"]


def _encrypt_payload(payload: dict, encrypt_key: str = CARD_ENCRYPT_KEY) -> str:
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    iv = b"itom-card-iv-001"
    key = hashlib.sha256(encrypt_key.encode()).digest()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode()


def _signed_post(
    client,
    payload: dict,
    *,
    encrypted: bool = False,
    signature: str | None = None,
    include_signature_headers: bool = True,
    timestamp: str | None = None,
):
    envelope = {"encrypt": _encrypt_payload(payload)} if encrypted else payload
    raw_body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = timestamp or str(int(datetime.now(timezone.utc).timestamp()))
    nonce = secrets.token_hex(8)
    valid_signature = hashlib.sha256(
        timestamp.encode()
        + nonce.encode()
        + CARD_ENCRYPT_KEY.encode()
        + raw_body
    ).hexdigest()
    headers = {"content-type": "application/json"}
    if include_signature_headers:
        headers.update(
            {
                "x-lark-request-timestamp": timestamp,
                "x-lark-request-nonce": nonce,
                "x-lark-signature": signature or valid_signature,
            }
        )
    return client.post(
        "/api/integrations/feishu/card-actions",
        content=raw_body,
        headers=headers,
    )


def _action_payload(
    ticket_code: str,
    operation: str,
    idempotency_key: str,
    *,
    subject: str = REQUESTER_SUBJECT,
    tenant_key: str = CARD_TENANT_KEY,
    score: int | None = None,
    feedback: str | None = None,
) -> dict:
    value = {
        "itom_action": operation,
        "ticket_code": ticket_code,
        "idempotency_key": idempotency_key,
    }
    if score is not None:
        value["score"] = score
    action = {"tag": "button", "name": operation, "value": value}
    if feedback is not None:
        action["form_value"] = {"feedback": feedback}
    return {
        "schema": "2.0",
        "header": {
            "event_id": secrets.token_hex(16),
            "token": CARD_VERIFICATION_TOKEN,
            "create_time": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
            "event_type": "card.action.trigger",
            "tenant_key": tenant_key,
            "app_id": CARD_APP_ID,
        },
        "event": {
            "operator": {"tenant_key": tenant_key, "open_id": subject},
            "action": action,
            "host": "im_message",
            "context": {"open_message_id": "om_test", "open_chat_id": "oc_test"},
        },
    }


def test_card_callback_challenge_is_signed_token_checked_and_decrypted(client, card_ready):
    challenge = {
        "type": "url_verification",
        "token": CARD_VERIFICATION_TOKEN,
        "challenge": "challenge-p2-card",
    }
    response = _signed_post(
        client,
        challenge,
        encrypted=True,
        include_signature_headers=False,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"challenge": "challenge-p2-card"}

    invalid = _signed_post(client, challenge, signature="0" * 64)
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "FEISHU_CARD_SIGNATURE_INVALID"

    unsigned_action = _signed_post(
        client,
        _action_payload("TK-UNSIGNED", "confirm_resolved", "card:unsigned:confirm"),
        encrypted=True,
        include_signature_headers=False,
    )
    assert unsigned_action.status_code == 401
    assert unsigned_action.json()["error"]["code"] == "FEISHU_CARD_SIGNATURE_MISSING"


def test_unsigned_encrypted_challenge_accepts_non_ascii_verification_token():
    verification_token = "回调验证令牌-测试"
    encrypt_key = "加密密钥-测试"
    payload = {
        "type": "url_verification",
        "token": verification_token,
        "challenge": "challenge-unicode-token",
    }
    config = SimpleNamespace(
        enabled=True,
        card_callback_verification_token_encrypted=encrypt_secret(verification_token),
        card_callback_encrypt_key_encrypted=encrypt_secret(encrypt_key),
    )
    raw_body = json.dumps(
        {"encrypt": _encrypt_payload(payload, encrypt_key)},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()

    decoded = verify_and_decode_callback(
        raw_body=raw_body,
        timestamp=None,
        nonce=None,
        signature=None,
        config=config,
    )

    assert decoded == payload


def test_signed_callback_accepts_go_style_timestamp_from_live_aily(client, card_ready):
    now = datetime.now(timezone(timedelta(hours=8)))
    go_timestamp = (
        now.strftime("%Y-%m-%d %H:%M:%S.%f")
        + "123 +0800 CST m=+72889.432249819"
    )
    response = _signed_post(
        client,
        _action_payload("TK-GO-TIMESTAMP", "confirm_resolved", "card:go:confirm"),
        encrypted=True,
        timestamp=go_timestamp,
    )
    assert response.status_code == 200, response.text
    assert response.json()["toast"]["type"] == "error"
    assert response.json()["toast"]["content"]


def test_distinct_card_tenant_rejects_unmapped_operator(client, card_ready):
    response = _signed_post(
        client,
        _action_payload(
            "TK-UNMAPPED-CARD-USER",
            "confirm_resolved",
            "card:unmapped:confirm",
            subject="ou_unmapped_card_user",
        ),
        encrypted=True,
    )
    assert response.status_code == 200, response.text
    assert response.json()["toast"] == {
        "type": "error",
        "content": "卡片回调租户或点击人身份尚未获 ITOM 授权",
    }


def test_card_callback_reopen_close_and_rate_same_ticket(client, p1, card_ready):
    ticket_code = _create_request(client, p1, "p2-card-callback-001")
    _complete_current_task(client, p1, ticket_code, "卡片回调验证：已受理")
    _complete_current_task(client, p1, ticket_code, "卡片回调验证：已恢复")

    show_form = _signed_post(
        client,
        _action_payload(
            ticket_code,
            "show_reopen_form",
            f"card:{ticket_code}:reopen:0",
        ),
        encrypted=True,
    )
    assert show_form.status_code == 200, show_form.text
    assert show_form.json()["toast"]["type"] == "info"
    assert show_form.json()["card"]["type"] == "raw"
    assert set(show_form.json()["card"]) == {"type", "data"}
    form = show_form.json()["card"]["data"]["elements"][1]
    assert form["tag"] == "form"
    assert form["elements"][0]["name"] == "feedback"
    assert form["elements"][0]["required"] is True
    assert form["elements"][1]["value"]["itom_action"] == "reopen"

    other_user = _signed_post(
        client,
        _action_payload(
            ticket_code,
            "show_reopen_form",
            f"card:{ticket_code}:other:0",
            subject=OTHER_SUBJECT,
        ),
    )
    assert other_user.status_code == 200
    assert other_user.json()["toast"]["type"] == "error"

    missing_feedback = _signed_post(
        client,
        _action_payload(
            ticket_code,
            "reopen",
            f"card:{ticket_code}:reopen:0",
            feedback="",
        ),
    )
    assert missing_feedback.json()["toast"]["type"] == "error"
    with SessionLocal() as db:
        assert db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one().status == "resolved"

    reopened = _signed_post(
        client,
        _action_payload(
            ticket_code,
            "reopen",
            f"card:{ticket_code}:reopen:0",
            feedback="无线网络仍会间歇断开，请继续排查",
        ),
        encrypted=True,
    )
    assert reopened.json()["toast"] == {"type": "success", "content": "服务请求已重新打开"}
    assert reopened.json()["card"]["type"] == "raw"
    assert reopened.json()["card"]["data"]["header"]["template"] == "orange"
    replay = _signed_post(
        client,
        _action_payload(
            ticket_code,
            "reopen",
            f"card:{ticket_code}:reopen:0",
            feedback="无线网络仍会间歇断开，请继续排查",
        ),
    )
    assert replay.json()["toast"]["type"] == "success"
    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        assert ticket.status == "processing"
        assert ticket.reopen_count == 1
        assert "无线网络仍会间歇断开" in ticket.remarks

    _complete_current_task(client, p1, ticket_code, "卡片回调验证：调整无线策略后恢复")
    closed = _signed_post(
        client,
        _action_payload(
            ticket_code,
            "confirm_resolved",
            f"card:{ticket_code}:confirm:1",
        ),
        encrypted=True,
    )
    assert closed.json()["toast"] == {"type": "success", "content": "服务请求已关闭"}
    assert closed.json()["card"]["type"] == "raw"
    assert closed.json()["card"]["data"]["header"]["template"] == "green"
    close_replay = _signed_post(
        client,
        _action_payload(
            ticket_code,
            "confirm_resolved",
            f"card:{ticket_code}:confirm:1",
        ),
    )
    assert close_replay.json()["toast"]["type"] == "success"

    rated = _signed_post(
        client,
        _action_payload(
            ticket_code,
            "rate",
            f"card:{ticket_code}:rate:5",
            score=5,
        ),
        encrypted=True,
    )
    assert rated.json()["toast"] == {"type": "success", "content": "已提交 5 星评价"}
    assert rated.json()["card"]["type"] == "raw"
    assert rated.json()["card"]["data"]["header"]["template"] == "green"
    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        assert ticket.status == "closed"
        assert ticket.satisfaction == 5
        satisfaction = db.query(TicketSatisfaction).filter(
            TicketSatisfaction.ticket_id == ticket.id,
            TicketSatisfaction.is_deleted.is_(False),
        ).one()
        assert satisfaction.source == "feishu_card"
