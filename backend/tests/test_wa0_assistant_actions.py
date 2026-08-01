"""WA0 L3 actions require authoritative preview, explicit confirmation, and reauthorization."""

from datetime import datetime, timedelta, timezone
import json

import pytest
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Query

from app.assistant.registry import register_capability, registry
from app.assistant.types import (
    AssistantChannel,
    CapabilityDefinition,
    CapabilityResult,
    RiskLevel,
)
from app.core.errors import AppError
from app.db import SessionLocal
from app.models import (
    AiAction,
    AiAgentProfile,
    AiAgentProfileVersion,
    AiConversation,
    AuditLog,
    AuthUser,
    ServiceItem,
    Ticket,
)
from app.services import assistant_actions


CAPABILITY_CODE = "wa0.test.confirmed_ticket_action"


class _ActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticket_code: str = Field(min_length=3, max_length=64)
    note: str = Field(min_length=2, max_length=500)


class _TicketActionHandler:
    """Test domain handler with separate preview, record guard, and mutation phases."""

    @staticmethod
    def _ticket(db, data: _ActionInput, *, lock: bool = False) -> Ticket:
        query = db.query(Ticket).filter(
            Ticket.ticket_code == data.ticket_code,
            Ticket.ticket_type == "service_request",
            Ticket.is_deleted.is_(False),
        )
        if lock:
            query = query.with_for_update()
        ticket = query.first()
        if ticket is None:
            raise AppError("TEST_TICKET_NOT_FOUND", "目标服务请求不存在", 404)
        return ticket

    def preview(self, db, actor: AuthUser, data: _ActionInput) -> CapabilityResult:
        ticket = self._ticket(db, data)
        return CapabilityResult(
            status="prepared",
            data={
                "ticket_code": ticket.ticket_code,
                "current_status": ticket.status,
                "sla": {"response_minutes": 30, "resolution_hours": 4},
                "queue": "authoritative-support-queue",
                "workflow": "authoritative-service-flow",
            },
            message="等待本人确认",
        )

    def authorize_record(self, db, actor: AuthUser, data: _ActionInput) -> None:
        ticket = self._ticket(db, data, lock=True)
        if ticket.status != "new":
            raise AppError("TEST_RECORD_STATE_CHANGED", "目标记录状态已变化", 409)
        if not actor.person_id or ticket.assignee != actor.person_id:
            raise AppError("TEST_ASSIGNMENT_CHANGED", "当前处理人已变化", 409)

    def __call__(self, db, actor: AuthUser, data: _ActionInput) -> CapabilityResult:
        ticket = self._ticket(db, data, lock=True)
        ticket.remarks = data.note
        if data.note.startswith("explode"):
            raise RuntimeError(f"handler exploded with {data.note}")
        if data.note.startswith("commit-directly"):
            db.commit()
        return CapabilityResult(
            status="succeeded",
            data={
                "entity_type": "ticket",
                "entity_id": ticket.id,
                "ticket_code": ticket.ticket_code,
                "status": "updated",
                "provider_debug": "Authorization: Bearer result-secret-raw",
            },
            message="操作已提交",
        )


HANDLER = _TicketActionHandler()


def _assert_code(exc: pytest.ExceptionInfo[AppError], code: str) -> None:
    assert exc.value.code == code


def _create_user(client, admin_headers, username: str, roles: list[str] | None = None) -> dict:
    person = client.post("/api/members", json={"name": username}, headers=admin_headers).json()["data"]
    created = client.post(
        "/api/admin/users",
        json={
            "username": username,
            "password": "pass1234",
            "roles": roles or ["requester"],
            "person_id": person["id"],
        },
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    login = client.post("/api/auth/login", json={"username": username, "password": "pass1234"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['data']['token']}"}


@pytest.fixture(scope="module", autouse=True)
def action_capability_and_profile(client):
    if registry.get(CAPABILITY_CODE) is None:
        register_capability(CapabilityDefinition(
            code=CAPABILITY_CODE,
            channels=frozenset({AssistantChannel.WEB}),
            audiences=frozenset({"requester"}),
            module="ticket_sr",
            action="create",
            risk=RiskLevel.L3,
            input_model=_ActionInput,
            handler=HANDLER,
            requires_confirmation=True,
            description="Confirmed test ticket action",
        ))
    with SessionLocal() as db:
        profile = AiAgentProfile(
            code="wa0-action-requester",
            name="WA0 action requester",
            audience="requester",
            enabled=True,
            status="published",
            max_risk_level="L3",
            retention_days=30,
        )
        db.add(profile)
        db.flush()
        version = AiAgentProfileVersion(
            profile_id=profile.id,
            version=1,
            status="published",
            system_prompt_zh="你是 ITOM 助手。",
            system_prompt_en="You are an ITOM assistant.",
            enabled_capabilities=[CAPABILITY_CODE],
            knowledge_scope=["public"],
            config_snapshot={
                "schema_version": 1,
                "name": profile.name,
                "default_provider_id": None,
                "retention_days": 30,
                "enabled": True,
            },
            max_risk_level="L3",
            published_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(version)
        db.commit()
        yield profile.id, version.id


def _context(username: str, profile_id: str, version_id: str, *, suffix: str = "") -> tuple[str, str, str]:
    with SessionLocal() as db:
        actor = db.query(AuthUser).filter(AuthUser.username == username).one()
        item = db.query(ServiceItem).filter(
            ServiceItem.status == "上架",
            ServiceItem.is_deleted.is_(False),
        ).first()
        assert item is not None
        ticket = Ticket(
            ticket_code=f"TK-WA0-ACTION-{username[-12:]}{suffix}",
            title="WA0 confirmed action",
            ticket_type="service_request",
            priority="P3",
            description="Verify preview and confirmation safety.",
            status="new",
            submitter=actor.id,
            assignee=actor.person_id,
            service_item_id=item.id,
        )
        conversation = AiConversation(
            auth_user_id=actor.id,
            profile_id=profile_id,
            profile_version_id=version_id,
            language="zh-CN",
            page_context={"route": "/itsm/tickets"},
        )
        db.add_all([ticket, conversation])
        db.commit()
        return actor.id, conversation.id, ticket.ticket_code


def _prepare(username: str, conversation_id: str, ticket_code: str, key: str, note: str = "approved note") -> dict:
    with SessionLocal() as db:
        actor = db.query(AuthUser).filter(AuthUser.username == username).one()
        return assistant_actions.prepare_action(
            db,
            actor,
            conversation_id,
            CAPABILITY_CODE,
            {"ticket_code": ticket_code, "note": note},
            key,
        )


def test_prepare_uses_registered_schema_and_authoritative_preview_with_one_time_token(
    client, admin_headers, action_capability_and_profile
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_action_prepare")
    actor_id, conversation_id, ticket_code = _context("wa0_action_prepare", profile_id, version_id)

    first = _prepare("wa0_action_prepare", conversation_id, ticket_code, "prepare-key-0001")
    assert first["status"] == "prepared"
    assert first["preview"] == {
        "ticket_code": ticket_code,
        "current_status": "new",
        "sla": {"response_minutes": 30, "resolution_hours": 4},
        "queue": "authoritative-support-queue",
        "workflow": "authoritative-service-flow",
    }
    assert first["confirmation_token"]
    assert first["confirmation_expires_at"]

    replay = _prepare("wa0_action_prepare", conversation_id, ticket_code, "prepare-key-0001")
    assert replay["action_id"] == first["action_id"]
    assert replay["status"] == "prepared"
    assert "confirmation_token" not in replay

    with SessionLocal() as db:
        row = db.get(AiAction, first["action_id"])
        persisted = json.dumps({
            "payload": row.normalized_payload,
            "result": row.result_summary,
            "token_hash": row.token_hash,
        })
        assert row.auth_user_id == actor_id
        assert row.conversation_id == conversation_id
        assert row.token_hash != first["confirmation_token"]
        assert first["confirmation_token"] not in persisted
        assert row.payload_digest and len(row.payload_digest) == 64

    invalid_secret = "Bearer validation-secret-raw"
    with pytest.raises(AppError) as invalid:
        with SessionLocal() as db:
            actor = db.get(AuthUser, actor_id)
            assistant_actions.prepare_action(
                db,
                actor,
                conversation_id,
                CAPABILITY_CODE,
                {
                    "ticket_code": ticket_code,
                    "note": invalid_secret,
                    "sla": {"hours": 999},
                },
                "prepare-key-0002",
            )
    _assert_code(invalid, "AI_ACTION_PAYLOAD_INVALID")
    assert invalid_secret not in invalid.value.message


def test_same_key_different_canonical_payload_conflicts(client, admin_headers, action_capability_and_profile):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_action_conflict")
    _, conversation_id, ticket_code = _context("wa0_action_conflict", profile_id, version_id)
    _prepare("wa0_action_conflict", conversation_id, ticket_code, "conflict-key-001", "first note")

    with pytest.raises(AppError) as raised:
        _prepare("wa0_action_conflict", conversation_id, ticket_code, "conflict-key-001", "second note")
    _assert_code(raised, "AI_ACTION_IDEMPOTENCY_CONFLICT")


def test_other_user_wrong_token_and_cancel_are_owner_scoped(
    client, admin_headers, action_capability_and_profile
):
    profile_id, version_id = action_capability_and_profile
    owner_headers = _create_user(client, admin_headers, "wa0_action_owner")
    other_headers = _create_user(client, admin_headers, "wa0_action_other")
    _, conversation_id, ticket_code = _context("wa0_action_owner", profile_id, version_id)
    prepared = _prepare("wa0_action_owner", conversation_id, ticket_code, "owner-key-00001")

    wrong_owner = client.post(
        f"/api/assistant/actions/{prepared['action_id']}/confirm",
        headers=other_headers,
        json={"confirmation_token": prepared["confirmation_token"]},
    )
    assert wrong_owner.status_code == 404, wrong_owner.text
    assert wrong_owner.json()["error"]["code"] == "AI_ACTION_NOT_FOUND"
    wrong_cancel = client.post(
        f"/api/assistant/actions/{prepared['action_id']}/cancel",
        headers=other_headers,
    )
    assert wrong_cancel.status_code == 404, wrong_cancel.text

    wrong_token = client.post(
        f"/api/assistant/actions/{prepared['action_id']}/confirm",
        headers=owner_headers,
        json={"confirmation_token": "wrong-token-value"},
    )
    assert wrong_token.status_code == 403, wrong_token.text
    assert wrong_token.json()["error"]["code"] == "AI_ACTION_TOKEN_INVALID"
    with SessionLocal() as db:
        assert db.get(AiAction, prepared["action_id"]).status == "prepared"


def test_expiry_and_cancel_then_confirm_fail_closed(client, admin_headers, action_capability_and_profile):
    profile_id, version_id = action_capability_and_profile
    headers = _create_user(client, admin_headers, "wa0_action_expire")
    _, conversation_id, ticket_code = _context("wa0_action_expire", profile_id, version_id)
    expired = _prepare("wa0_action_expire", conversation_id, ticket_code, "expiry-key-0001")
    with SessionLocal() as db:
        expired_row = db.get(AiAction, expired["action_id"])
        expired_row.expires_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        )
        db.commit()
    response = client.post(
        f"/api/assistant/actions/{expired['action_id']}/confirm",
        headers=headers,
        json={"confirmation_token": expired["confirmation_token"]},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "AI_ACTION_EXPIRED"
    with SessionLocal() as db:
        assert db.get(AiAction, expired["action_id"]).status == "expired"

    _, second_conversation, second_ticket = _context(
        "wa0_action_expire", profile_id, version_id, suffix="-CANCEL"
    )
    cancelled = _prepare("wa0_action_expire", second_conversation, second_ticket, "cancel-key-0001")
    cancel = client.post(
        f"/api/assistant/actions/{cancelled['action_id']}/cancel", headers=headers
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["data"]["status"] == "cancelled"
    confirm = client.post(
        f"/api/assistant/actions/{cancelled['action_id']}/confirm",
        headers=headers,
        json={"confirmation_token": cancelled["confirmation_token"]},
    )
    assert confirm.status_code == 409, confirm.text
    assert confirm.json()["error"]["code"] == "AI_ACTION_NOT_PREPARED"


def test_permission_revocation_and_auditor_write_fail_closed(
    client, admin_headers, action_capability_and_profile
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_action_revoked")
    actor_id, conversation_id, ticket_code = _context("wa0_action_revoked", profile_id, version_id)
    prepared = _prepare("wa0_action_revoked", conversation_id, ticket_code, "revoke-key-0001")
    with SessionLocal() as db:
        db.get(AuthUser, actor_id).roles = ["auditor"]
        db.commit()
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        with pytest.raises(AppError) as raised:
            assistant_actions.confirm_action(
                db, actor, prepared["action_id"], prepared["confirmation_token"]
            )
        _assert_code(raised, "AI_ACTION_REAUTHORIZATION_FAILED")
    with SessionLocal() as db:
        assert db.get(AiAction, prepared["action_id"]).status == "failed"

    _create_user(client, admin_headers, "wa0_action_auditor", roles=["auditor"])
    auditor_id, auditor_conversation, auditor_ticket = _context(
        "wa0_action_auditor", profile_id, version_id
    )
    with SessionLocal() as db:
        auditor = db.get(AuthUser, auditor_id)
        with pytest.raises(AppError) as raised:
            assistant_actions.prepare_action(
                db,
                auditor,
                auditor_conversation,
                CAPABILITY_CODE,
                {"ticket_code": auditor_ticket, "note": "auditor write"},
                "auditor-key-001",
            )
        _assert_code(raised, "AI_ACTION_CAPABILITY_UNAVAILABLE")


@pytest.mark.parametrize(
    "change,expected_code",
    [("status", "TEST_RECORD_STATE_CHANGED"), ("assignee", "TEST_ASSIGNMENT_CHANGED")],
)
def test_record_state_or_assignment_change_is_reauthorized_at_confirmation(
    client, admin_headers, action_capability_and_profile, change, expected_code
):
    profile_id, version_id = action_capability_and_profile
    username = f"wa0_action_{change}"
    _create_user(client, admin_headers, username)
    actor_id, conversation_id, ticket_code = _context(username, profile_id, version_id)
    prepared = _prepare(username, conversation_id, ticket_code, f"{change}-key-0001")
    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        if change == "status":
            ticket.status = "processing"
        else:
            ticket.assignee = None
        db.commit()
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        with pytest.raises(AppError) as raised:
            assistant_actions.confirm_action(
                db, actor, prepared["action_id"], prepared["confirmation_token"]
            )
        _assert_code(raised, expected_code)
    with SessionLocal() as db:
        assert db.get(AiAction, prepared["action_id"]).status == "failed"


def test_success_is_atomic_single_use_and_uses_a_row_lock(
    client, admin_headers, action_capability_and_profile, monkeypatch
):
    profile_id, version_id = action_capability_and_profile
    headers = _create_user(client, admin_headers, "wa0_action_success")
    _, conversation_id, ticket_code = _context("wa0_action_success", profile_id, version_id)
    prepared = _prepare("wa0_action_success", conversation_id, ticket_code, "success-key-0001")
    lock_calls: list[bool] = []
    original_with_for_update = Query.with_for_update

    def observed_with_for_update(self, *args, **kwargs):
        lock_calls.append(True)
        return original_with_for_update(self, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", observed_with_for_update)
    confirmed = client.post(
        f"/api/assistant/actions/{prepared['action_id']}/confirm",
        headers=headers,
        json={"confirmation_token": prepared["confirmation_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()["data"]
    assert result["status"] == "succeeded"
    assert result["result"]["ticket_code"] == ticket_code
    assert "result-secret-raw" not in json.dumps(result)
    assert lock_calls, "confirmation must request a row lock before mutation"

    with SessionLocal() as db:
        action = db.get(AiAction, prepared["action_id"])
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        success_audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "ai_action",
            AuditLog.entity_id == action.id,
            AuditLog.action == "succeeded",
        ).one()
        assert action.status == "succeeded"
        assert action.consumed_at is not None
        assert ticket.remarks == "approved note"
        assert success_audit.summary["payload_digest"] == action.payload_digest
        assert "approved note" not in json.dumps(success_audit.summary)

    replay = client.post(
        f"/api/assistant/actions/{prepared['action_id']}/confirm",
        headers=headers,
        json={"confirmation_token": prepared["confirmation_token"]},
    )
    assert replay.status_code == 409, replay.text
    assert replay.json()["error"]["code"] == "AI_ACTION_NOT_PREPARED"
    same_key = _prepare(
        "wa0_action_success", conversation_id, ticket_code, "success-key-0001"
    )
    assert same_key["status"] == "succeeded"
    assert same_key["result"]["ticket_code"] == ticket_code
    assert "confirmation_token" not in same_key


def test_handler_exception_rolls_back_business_change_then_commits_redacted_failure(
    client, admin_headers, action_capability_and_profile
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_action_handler_fail")
    actor_id, conversation_id, ticket_code = _context(
        "wa0_action_handler_fail", profile_id, version_id
    )
    secret_note = "explode Authorization: Bearer handler-secret-raw"
    prepared = _prepare(
        "wa0_action_handler_fail",
        conversation_id,
        ticket_code,
        "handler-fail-key",
        secret_note,
    )
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        with pytest.raises(AppError) as raised:
            assistant_actions.confirm_action(
                db, actor, prepared["action_id"], prepared["confirmation_token"]
            )
        _assert_code(raised, "AI_ACTION_EXECUTION_FAILED")
        assert "created" not in raised.value.message.lower()
        assert "closed" not in raised.value.message.lower()
        assert "handler-secret-raw" not in raised.value.message

    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        action = db.get(AiAction, prepared["action_id"])
        rendered = json.dumps({
            "payload": action.normalized_payload,
            "result": action.result_summary,
            "audits": [row.summary for row in db.query(AuditLog).filter(
                AuditLog.entity_type == "ai_action", AuditLog.entity_id == action.id
            )],
        })
        assert ticket.remarks is None
        assert action.status == "failed"
        assert action.result_code == "AI_ACTION_EXECUTION_FAILED"
        assert "handler-secret-raw" not in rendered


def test_success_audit_failure_rolls_back_domain_write_and_never_claims_success(
    client, admin_headers, action_capability_and_profile, monkeypatch
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_action_audit_fail")
    actor_id, conversation_id, ticket_code = _context(
        "wa0_action_audit_fail", profile_id, version_id
    )
    prepared = _prepare(
        "wa0_action_audit_fail", conversation_id, ticket_code, "audit-fail-key-1"
    )

    def fail_success_audit(*_args, **_kwargs):
        raise RuntimeError("audit persistence failed after handler")

    monkeypatch.setattr(assistant_actions, "audit", fail_success_audit)
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        with pytest.raises(AppError) as raised:
            assistant_actions.confirm_action(
                db, actor, prepared["action_id"], prepared["confirmation_token"]
            )
        _assert_code(raised, "AI_ACTION_EXECUTION_FAILED")

    with SessionLocal() as db:
        assert db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one().remarks is None
        action = db.get(AiAction, prepared["action_id"])
        assert action.status == "failed"
        assert action.result_code == "AI_ACTION_EXECUTION_FAILED"


def test_handler_cannot_commit_outside_the_action_audit_transaction(
    client, admin_headers, action_capability_and_profile
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_action_handler_commit")
    actor_id, conversation_id, ticket_code = _context(
        "wa0_action_handler_commit", profile_id, version_id
    )
    prepared = _prepare(
        "wa0_action_handler_commit",
        conversation_id,
        ticket_code,
        "handler-commit-key",
        "commit-directly before action audit",
    )
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        with pytest.raises(AppError) as raised:
            assistant_actions.confirm_action(
                db, actor, prepared["action_id"], prepared["confirmation_token"]
            )
        _assert_code(raised, "AI_ACTION_TRANSACTION_VIOLATION")

    with SessionLocal() as db:
        assert db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one().remarks is None
        action = db.get(AiAction, prepared["action_id"])
        assert action.status == "failed"
        assert action.result_code == "AI_ACTION_TRANSACTION_VIOLATION"


def test_prepare_and_result_remove_secret_assignments_from_db_audit_and_errors(
    client, admin_headers, action_capability_and_profile
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_action_secrets")
    _, conversation_id, ticket_code = _context("wa0_action_secrets", profile_id, version_id)
    raw_secret = "Bearer payload-secret-raw"
    prepared = _prepare(
        "wa0_action_secrets",
        conversation_id,
        ticket_code,
        "secret-key-00001",
        f"Please inspect Authorization: {raw_secret}",
    )
    assert raw_secret not in json.dumps(prepared, default=str)
    with SessionLocal() as db:
        action = db.get(AiAction, prepared["action_id"])
        rows = db.query(AuditLog).filter(
            AuditLog.entity_type == "ai_action", AuditLog.entity_id == action.id
        ).all()
        assert raw_secret not in json.dumps({
            "payload": action.normalized_payload,
            "result": action.result_summary,
            "audits": [row.summary for row in rows],
        })
