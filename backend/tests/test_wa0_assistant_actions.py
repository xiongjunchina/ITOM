"""WA0 L3 actions require authoritative preview, explicit confirmation, and reauthorization."""

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
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
    AiProviderConfig,
    AuditLog,
    AuthUser,
    ServiceItem,
    Ticket,
)
from app.services import assistant_actions, assistant_config, assistant_conversations


CAPABILITY_CODE = "wa0.test.confirmed_ticket_action"


class _ActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticket_code: str = Field(min_length=3, max_length=64)
    note: str = Field(min_length=2, max_length=500)


class _TicketActionHandler:
    """Test domain handler with separate preview, record guard, and mutation phases."""

    preview_calls = 0
    authorize_preview_calls = 0
    authorize_record_calls = 0
    execute_calls = 0
    preview_session_ids: list[int] = []
    preview_db_type_names: list[str] = []
    preview_actor_is_orm: list[bool] = []
    authorize_record_db_type_names: list[str] = []
    execute_db_type_names: list[str] = []

    @staticmethod
    def _ticket(db, data: _ActionInput, *, lock: bool = False) -> Ticket:
        statement = (
            select(Ticket)
            .where(
                Ticket.ticket_code == data.ticket_code,
                Ticket.ticket_type == "service_request",
                Ticket.is_deleted.is_(False),
            )
            .limit(1)
        )
        if hasattr(db, "fetch_first"):
            ticket = db.fetch_first(statement, with_for_update=lock)
        else:
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

    @staticmethod
    def _preview_surface_blocked(operation) -> bool:
        try:
            operation()
        except Exception:
            return True
        return False

    @staticmethod
    def _preview_surface_violation() -> AppError:
        return AppError(
            "AI_ACTION_PREVIEW_TRANSACTION_VIOLATION",
            "动作预览不得修改数据或控制事务",
            409,
        )

    def preview(self, db, actor: AuthUser, data: _ActionInput) -> CapabilityResult:
        type(self).preview_calls += 1
        type(self).preview_session_ids.append(id(db))
        type(self).preview_db_type_names.append(type(db).__name__)
        type(self).preview_actor_is_orm.append(hasattr(actor, "_sa_instance_state"))
        ticket = self._ticket(db, data)
        if data.note == "preview-insert":
            db.add(AiAction(
                conversation_id="preview-mutation",
                auth_user_id=actor.id,
                capability_code="preview.mutation",
                risk_level="L3",
                normalized_payload={},
                payload_digest="0" * 64,
                token_hash="0" * 64,
                idempotency_key="preview-mutation",
                status="prepared",
            ))
        elif data.note == "preview-update":
            ticket.remarks = "preview mutated business state"
        elif data.note == "preview-dml-update":
            db.execute(
                update(Ticket)
                .where(Ticket.id == ticket.id)
                .values(remarks="preview DML mutated business state")
            )
        elif data.note == "preview-actor-mutation":
            try:
                actor.preferences = {"preview_mutated": True}
            except Exception:
                pass
        elif data.note == "preview-bind":
            if self._preview_surface_blocked(lambda: getattr(db, "bind")):
                raise self._preview_surface_violation()
            raise AssertionError("preview bind unexpectedly exposed")
        elif data.note == "preview-get-bind":
            if self._preview_surface_blocked(lambda: db.get_bind()):
                raise self._preview_surface_violation()
            raise AssertionError("preview get_bind unexpectedly exposed")
        elif data.note == "preview-connection":
            if self._preview_surface_blocked(lambda: db.connection()):
                raise self._preview_surface_violation()
            raise AssertionError("preview connection unexpectedly exposed")
        elif data.note == "preview-scalar":
            if self._preview_surface_blocked(lambda: db.scalar(select(Ticket.ticket_code).limit(1))):
                raise self._preview_surface_violation()
            raise AssertionError("preview scalar unexpectedly exposed")
        elif data.note == "preview-scalars":
            if self._preview_surface_blocked(lambda: db.scalars(select(Ticket))):
                raise self._preview_surface_violation()
            raise AssertionError("preview scalars unexpectedly exposed")
        elif data.note == "preview-begin":
            if self._preview_surface_blocked(lambda: getattr(db, "begin")):
                raise self._preview_surface_violation()
            raise AssertionError("preview begin unexpectedly exposed")
        elif data.note == "preview-get-transaction":
            if self._preview_surface_blocked(lambda: db.get_transaction()):
                raise self._preview_surface_violation()
            raise AssertionError("preview get_transaction unexpectedly exposed")
        elif data.note == "preview-flush":
            db.flush()
        elif data.note == "preview-commit":
            db.commit()
        elif data.note == "preview-rollback":
            db.rollback()
        elif data.note == "preview-text-commit":
            if self._preview_surface_blocked(lambda: db.execute(text("COMMIT"))):
                raise self._preview_surface_violation()
            raise AssertionError("preview text COMMIT unexpectedly exposed")
        elif data.note == "preview-transaction-commit":
            if self._preview_surface_blocked(lambda: db.get_transaction().commit()):
                raise self._preview_surface_violation()
            raise AssertionError("preview transaction commit unexpectedly exposed")
        elif data.note == "preview-invalid-status":
            return CapabilityResult(status="succeeded", data={"ticket_code": ticket.ticket_code})
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

    def authorize_preview(self, db, actor: AuthUser, data: _ActionInput) -> None:
        type(self).authorize_preview_calls += 1
        try:
            ticket = self._ticket(db, data)
        except AppError:
            raise AppError("TEST_PREVIEW_RECORD_MISSING", "internal missing record fact", 404)
        if not actor.person_id or ticket.assignee != actor.person_id:
            raise AppError("TEST_PREVIEW_RECORD_FORBIDDEN", "internal ownership fact", 403)

    def authorize_record(self, db, actor: AuthUser, data: _ActionInput) -> None:
        type(self).authorize_record_calls += 1
        type(self).authorize_record_db_type_names.append(type(db).__name__)
        ticket = self._ticket(db, data, lock=True)
        if ticket.status != "new":
            raise AppError("TEST_RECORD_STATE_CHANGED", "目标记录状态已变化", 409)
        if not actor.person_id or ticket.assignee != actor.person_id:
            raise AppError("TEST_ASSIGNMENT_CHANGED", "当前处理人已变化", 409)

    def __call__(self, db, actor: AuthUser, data: _ActionInput) -> CapabilityResult:
        type(self).execute_calls += 1
        type(self).execute_db_type_names.append(type(db).__name__)
        ticket = self._ticket(db, data, lock=True)
        ticket.remarks = data.note
        if data.note.startswith("explode"):
            raise RuntimeError("handler exploded with Authorization: Bearer handler-secret-raw")
        if data.note.startswith("commit-directly"):
            db.commit()
        if data.note == "uow-connection-commit":
            try:
                db.connection().commit()
            except Exception as exc:
                raise AppError("AI_ACTION_TRANSACTION_VIOLATION", "禁止原始事务提交", 409) from exc
            raise AssertionError("uow connection unexpectedly exposed")
        if data.note == "uow-text-commit":
            try:
                db.execute(text("COMMIT"))
            except Exception as exc:
                raise AppError("AI_ACTION_TRANSACTION_VIOLATION", "禁止原始事务提交", 409) from exc
            raise AssertionError("uow text COMMIT unexpectedly exposed")
        if data.note == "uow-transaction-commit":
            try:
                db.get_transaction().commit()
            except Exception as exc:
                raise AppError("AI_ACTION_TRANSACTION_VIOLATION", "禁止原始事务提交", 409) from exc
            raise AssertionError("uow get_transaction unexpectedly exposed")
        if data.note == "uow-nested-commit":
            try:
                db.begin_nested().commit()
            except Exception as exc:
                raise AppError("AI_ACTION_TRANSACTION_VIOLATION", "禁止原始事务提交", 409) from exc
            raise AssertionError("uow begin_nested unexpectedly exposed")
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
        provider = AiProviderConfig(
            code="wa0-action-provider",
            name="WA0 action provider",
            provider_type="openai_compatible",
            model="wa0-action-model",
            enabled=True,
            probe_status="success",
            last_probed_at=datetime.now(timezone.utc).replace(tzinfo=None),
            capability_probe={
                "authentication": True,
                "supports_streaming": True,
                "supports_tools": True,
                "supports_json_schema": True,
            },
        )
        db.add(provider)
        db.flush()
        profile = AiAgentProfile(
            code="wa0-action-requester",
            name="WA0 action requester",
            audience="requester",
            enabled=True,
            status="published",
            max_risk_level="L3",
            retention_days=30,
            default_provider_id=provider.id,
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
                "default_provider_id": provider.id,
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
        ticket_slug = f"{username.replace('_', '-')}{suffix}"
        ticket = Ticket(
            ticket_code=f"TK-WA0-ACTION-{ticket_slug}",
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
    authorize_record_calls_before = HANDLER.authorize_record_calls
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
    assert HANDLER.authorize_record_calls == authorize_record_calls_before + 1

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


def test_confirm_uses_action_unit_of_work_and_locks_conversation_before_runtime_and_record_checks(
    client, admin_headers, action_capability_and_profile, monkeypatch
):
    profile_id, version_id = action_capability_and_profile
    headers = _create_user(client, admin_headers, "wa0_confirm_uow")
    _, conversation_id, ticket_code = _context("wa0_confirm_uow", profile_id, version_id)
    prepared = _prepare(
        "wa0_confirm_uow",
        conversation_id,
        ticket_code,
        "confirm-uow-key",
        "uow-safe-contract",
    )
    lock_events: list[str] = []
    original_with_for_update = Query.with_for_update
    original_lock_governance = assistant_config.lock_profile_runtime_governance

    def observed_with_for_update(self, *args, **kwargs):
        entity = self.column_descriptions[0].get("entity") if self.column_descriptions else None
        if entity is AiAction:
            lock_events.append("action")
        elif entity is AiConversation:
            lock_events.append("conversation")
        elif entity is Ticket:
            lock_events.append("record")
        return original_with_for_update(self, *args, **kwargs)

    def observed_lock_governance(db):
        lock_events.append("governance")
        return original_lock_governance(db)

    monkeypatch.setattr(Query, "with_for_update", observed_with_for_update)
    monkeypatch.setattr(
        assistant_config, "lock_profile_runtime_governance", observed_lock_governance
    )
    confirmed = client.post(
        f"/api/assistant/actions/{prepared['action_id']}/confirm",
        headers=headers,
        json={"confirmation_token": prepared["confirmation_token"]},
    )

    assert confirmed.status_code == 200, confirmed.text
    assert HANDLER.authorize_record_db_type_names[-1] == "ActionUnitOfWork"
    assert HANDLER.execute_db_type_names[-1] == "ActionUnitOfWork"
    assert lock_events.index("action") < lock_events.index("conversation")
    assert lock_events.index("conversation") < lock_events.index("governance")
    assert lock_events.index("governance") < lock_events.index("record")


@pytest.mark.parametrize(
    "mode",
    [
        "uow-connection-commit",
        "uow-text-commit",
        "uow-transaction-commit",
        "uow-nested-commit",
    ],
)
def test_action_unit_of_work_blocks_raw_transaction_surfaces_without_business_change(
    client, admin_headers, action_capability_and_profile, mode
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, f"wa0_{mode.replace('-', '_')}")
    actor_id, conversation_id, ticket_code = _context(
        f"wa0_{mode.replace('-', '_')}", profile_id, version_id
    )
    prepared = _prepare(
        f"wa0_{mode.replace('-', '_')}",
        conversation_id,
        ticket_code,
        f"{mode}-key",
        mode,
    )
    execute_calls_before = HANDLER.execute_calls
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        with pytest.raises(AppError) as raised:
            assistant_actions.confirm_action(
                db, actor, prepared["action_id"], prepared["confirmation_token"]
            )
        _assert_code(raised, "AI_ACTION_TRANSACTION_VIOLATION")

    with SessionLocal() as db:
        assert db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one().remarks is None
        assert db.get(AiAction, prepared["action_id"]).status == "failed"
    assert HANDLER.execute_calls == execute_calls_before + 1


def test_confirm_fails_before_runtime_governance_when_archive_wins_after_prepare(
    client, admin_headers, action_capability_and_profile, monkeypatch
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_confirm_archive")
    actor_id, conversation_id, ticket_code = _context(
        "wa0_confirm_archive", profile_id, version_id
    )
    prepared = _prepare(
        "wa0_confirm_archive",
        conversation_id,
        ticket_code,
        "confirm-archive-key",
    )
    with SessionLocal() as archive_db:
        archive_actor = archive_db.get(AuthUser, actor_id)
        assistant_conversations.archive_own_conversation(
            archive_db, archive_actor, conversation_id
        )
    governance_events: list[str] = []
    execute_calls_before = HANDLER.execute_calls
    original_lock_governance = assistant_config.lock_profile_runtime_governance

    def observed_lock_governance(db):
        governance_events.append("governance")
        return original_lock_governance(db)

    monkeypatch.setattr(
        assistant_config, "lock_profile_runtime_governance", observed_lock_governance
    )
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        with pytest.raises(AppError):
            assistant_actions.confirm_action(
                db, actor, prepared["action_id"], prepared["confirmation_token"]
            )

    assert governance_events == []
    assert HANDLER.execute_calls == execute_calls_before
    with SessionLocal() as db:
        assert db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one().remarks is None
        assert db.get(AiAction, prepared["action_id"]).status == "failed"


def test_handler_exception_rolls_back_business_change_then_commits_redacted_failure(
    client, admin_headers, action_capability_and_profile
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_action_handler_fail")
    actor_id, conversation_id, ticket_code = _context(
        "wa0_action_handler_fail", profile_id, version_id
    )
    secret_note = "explode after domain mutation"
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
        begin_nested_calls = 0
        original_begin_nested = db.begin_nested

        def observed_begin_nested(*args, **kwargs):
            nonlocal begin_nested_calls
            begin_nested_calls += 1
            return original_begin_nested(*args, **kwargs)

        monkeypatch.setattr(db, "begin_nested", observed_begin_nested)
        with pytest.raises(AppError) as raised:
            assistant_actions.confirm_action(
                db, actor, prepared["action_id"], prepared["confirmation_token"]
            )
        _assert_code(raised, "AI_ACTION_EXECUTION_FAILED")
        assert begin_nested_calls == 1

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


def test_result_removes_secret_assignments_from_db_audit_and_response(
    client, admin_headers, action_capability_and_profile
):
    profile_id, version_id = action_capability_and_profile
    headers = _create_user(client, admin_headers, "wa0_action_secrets")
    _, conversation_id, ticket_code = _context("wa0_action_secrets", profile_id, version_id)
    prepared = _prepare(
        "wa0_action_secrets",
        conversation_id,
        ticket_code,
        "secret-key-00001",
        "safe result redaction note",
    )
    confirmed = client.post(
        f"/api/assistant/actions/{prepared['action_id']}/confirm",
        headers=headers,
        json={"confirmation_token": prepared["confirmation_token"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    raw_secret = "Bearer result-secret-raw"
    assert raw_secret not in confirmed.text
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


def test_l3_registry_requires_complete_preview_and_record_authorization_contract():
    class _IncompleteHandler:
        def preview(self, db, actor, data):
            return CapabilityResult(status="prepared")

        def authorize_record(self, db, actor, data):
            return None

        def __call__(self, db, actor, data):
            return CapabilityResult(status="succeeded")

    code = "wa0.test.incomplete_preview_contract"
    try:
        with pytest.raises(ValueError, match="authorize_preview"):
            register_capability(CapabilityDefinition(
                code=code,
                channels=frozenset({AssistantChannel.WEB}),
                audiences=frozenset({"requester"}),
                module="ticket_sr",
                action="create",
                risk=RiskLevel.L3,
                input_model=_ActionInput,
                handler=_IncompleteHandler(),
                requires_confirmation=True,
            ))
    finally:
        registry._definitions.pop(code, None)


def test_preview_uses_an_independent_session_and_postgresql_read_only_sql(
    client, admin_headers, action_capability_and_profile
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_action_preview_session")
    actor_id, conversation_id, ticket_code = _context(
        "wa0_action_preview_session", profile_id, version_id
    )
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        caller_session_id = id(db)
        prepared = assistant_actions.prepare_action(
            db,
            actor,
            conversation_id,
            CAPABILITY_CODE,
            {"ticket_code": ticket_code, "note": "safe preview note"},
            "preview-session-key",
        )
    assert prepared["status"] == "prepared"
    assert HANDLER.preview_session_ids[-1] != caller_session_id

    statements: list[str] = []
    fake_postgres_session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        execute=lambda statement: statements.append(str(statement)),
    )
    assistant_actions._set_preview_transaction_read_only(fake_postgres_session)
    assert statements == ["SET TRANSACTION READ ONLY"]


def test_preview_uses_read_only_action_data_and_actor_mutation_never_touches_the_caller_session(
    client, admin_headers, action_capability_and_profile
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_action_preview_actor")
    actor_id, conversation_id, ticket_code = _context(
        "wa0_action_preview_actor", profile_id, version_id
    )

    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        prepared = assistant_actions.prepare_action(
            db,
            actor,
            conversation_id,
            CAPABILITY_CODE,
            {"ticket_code": ticket_code, "note": "preview-actor-mutation"},
            "preview-actor-key",
        )

    assert prepared["status"] == "prepared"
    assert HANDLER.preview_db_type_names[-1] == "ReadOnlyActionData"
    assert HANDLER.preview_actor_is_orm[-1] is False
    with SessionLocal() as db:
        assert "preview_mutated" not in (db.get(AuthUser, actor_id).preferences or {})


@pytest.mark.parametrize(
    "mode",
    [
        "preview-bind",
        "preview-get-bind",
        "preview-connection",
        "preview-scalar",
        "preview-scalars",
        "preview-begin",
        "preview-get-transaction",
        "preview-text-commit",
        "preview-transaction-commit",
    ],
)
def test_preview_read_only_action_data_blocks_raw_session_surfaces_without_durable_change(
    client, admin_headers, action_capability_and_profile, mode
):
    profile_id, version_id = action_capability_and_profile
    username = f"wa0_{mode.replace('-', '_')}"
    _create_user(client, admin_headers, username)
    actor_id, conversation_id, ticket_code = _context(username, profile_id, version_id)
    key = f"{mode}-key-raw-facade"
    with SessionLocal() as db:
        prepared_audit_count_before = db.query(AuditLog).filter(
            AuditLog.entity_type == "ai_action",
            AuditLog.action == "prepared",
        ).count()
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        with pytest.raises(AppError) as raised:
            assistant_actions.prepare_action(
                db,
                actor,
                conversation_id,
                CAPABILITY_CODE,
                {"ticket_code": ticket_code, "note": mode},
                key,
            )
        _assert_code(raised, "AI_ACTION_PREVIEW_TRANSACTION_VIOLATION")

    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        prepared_audit_count_after = db.query(AuditLog).filter(
            AuditLog.entity_type == "ai_action",
            AuditLog.action == "prepared",
        ).count()
        assert ticket.remarks is None
        assert db.query(AiAction).filter(AiAction.idempotency_key == key).count() == 0
        assert prepared_audit_count_after == prepared_audit_count_before


def test_prepare_locks_the_conversation_row_before_any_action_row_persistence(
    client, admin_headers, action_capability_and_profile, monkeypatch
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_prepare_lock_order")
    actor_id, conversation_id, ticket_code = _context(
        "wa0_prepare_lock_order", profile_id, version_id
    )
    lock_events: list[str] = []
    original_with_for_update = Query.with_for_update

    def observed_with_for_update(self, *args, **kwargs):
        entity = self.column_descriptions[0].get("entity") if self.column_descriptions else None
        if entity is AiConversation:
            lock_events.append("conversation")
        elif entity is AiAction:
            lock_events.append("action")
        return original_with_for_update(self, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", observed_with_for_update)
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        prepared = assistant_actions.prepare_action(
            db,
            actor,
            conversation_id,
            CAPABILITY_CODE,
            {"ticket_code": ticket_code, "note": "prepare row lock ordering"},
            "prepare-lock-order-key",
        )

    assert prepared["status"] == "prepared"
    assert lock_events
    assert lock_events[0] == "conversation"


def test_prepare_fails_closed_if_archive_commits_after_preview_before_persistence_lock(
    client, admin_headers, action_capability_and_profile, monkeypatch
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_prepare_archive")
    actor_id, conversation_id, ticket_code = _context(
        "wa0_prepare_archive", profile_id, version_id
    )
    original_preview = assistant_actions._run_rollback_only_preview

    def archive_after_preview(handler, actor, data):
        result = original_preview(handler, actor, data)
        with SessionLocal() as archive_db:
            archive_actor = archive_db.get(AuthUser, actor.id)
            assistant_conversations.archive_own_conversation(
                archive_db, archive_actor, conversation_id
            )
        return result

    monkeypatch.setattr(
        assistant_actions,
        "_run_rollback_only_preview",
        archive_after_preview,
    )
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        with pytest.raises(AppError) as raised:
            assistant_actions.prepare_action(
                db,
                actor,
                conversation_id,
                CAPABILITY_CODE,
                {"ticket_code": ticket_code, "note": "archive before persistence"},
                "prepare-archive-key",
            )
        _assert_code(raised, "AI_CONVERSATION_NOT_FOUND")

    with SessionLocal() as db:
        assert db.get(AiConversation, conversation_id).status == "archived"
        assert db.query(AiAction).filter(
            AiAction.idempotency_key == "prepare-archive-key"
        ).count() == 0


@pytest.mark.parametrize(
    "mode",
    [
        "preview-insert",
        "preview-update",
        "preview-dml-update",
        "preview-flush",
        "preview-commit",
        "preview-rollback",
    ],
)
def test_preview_mutation_modes_fail_closed_without_business_action_or_audit(
    client, admin_headers, action_capability_and_profile, mode
):
    profile_id, version_id = action_capability_and_profile
    username = f"wa0_{mode.replace('-', '_')}"
    _create_user(client, admin_headers, username)
    actor_id, conversation_id, ticket_code = _context(username, profile_id, version_id)
    key = f"{mode}-key"
    with SessionLocal() as db:
        prepared_audit_count_before = db.query(AuditLog).filter(
            AuditLog.entity_type == "ai_action",
            AuditLog.action == "prepared",
        ).count()
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        with pytest.raises(AppError) as raised:
            assistant_actions.prepare_action(
                db,
                actor,
                conversation_id,
                CAPABILITY_CODE,
                {"ticket_code": ticket_code, "note": mode},
                key,
            )
        _assert_code(raised, "AI_ACTION_PREVIEW_TRANSACTION_VIOLATION")

    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one()
        actions = db.query(AiAction).filter(AiAction.idempotency_key == key).all()
        prepared_audit_count_after = db.query(AuditLog).filter(
            AuditLog.entity_type == "ai_action",
            AuditLog.action == "prepared",
        ).count()
        assert ticket.remarks is None
        assert actions == []
        assert prepared_audit_count_after == prepared_audit_count_before


@pytest.mark.parametrize("record_case", ["cross-user", "unassigned", "nonexistent"])
def test_preview_record_authorization_is_uniform_and_runs_before_preview(
    client, admin_headers, action_capability_and_profile, record_case
):
    profile_id, version_id = action_capability_and_profile
    owner = f"wa0_preview_owner_{record_case.replace('-', '_')}"
    actor_name = f"wa0_preview_actor_{record_case.replace('-', '_')}"
    _create_user(client, admin_headers, owner)
    _create_user(client, admin_headers, actor_name)
    _, owner_conversation, owner_ticket = _context(
        owner, profile_id, version_id, suffix="-OWNER"
    )
    actor_id, actor_conversation, actor_ticket = _context(
        actor_name, profile_id, version_id, suffix="-ACTOR"
    )
    del owner_conversation
    target_ticket = actor_ticket
    if record_case == "cross-user":
        target_ticket = owner_ticket
    elif record_case == "unassigned":
        with SessionLocal() as db:
            db.query(Ticket).filter(Ticket.ticket_code == actor_ticket).one().assignee = None
            db.commit()
    else:
        target_ticket = "TK-NOT-EXISTENT"

    preview_calls_before = HANDLER.preview_calls
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        with pytest.raises(AppError) as raised:
            assistant_actions.prepare_action(
                db,
                actor,
                actor_conversation,
                CAPABILITY_CODE,
                {"ticket_code": target_ticket, "note": "preview authorization"},
                f"preview-auth-{record_case}",
            )
    _assert_code(raised, "AI_ACTION_PREVIEW_UNAVAILABLE")
    assert raised.value.message == "当前记录不可用于该动作预览"
    assert HANDLER.preview_calls == preview_calls_before
    with SessionLocal() as db:
        assert db.query(AiAction).filter(
            AiAction.idempotency_key == f"preview-auth-{record_case}"
        ).count() == 0


@pytest.mark.parametrize(
    "sensitive_value",
    [
        "Authorization: Bearer action-alpha-secret",
        "Bearer action-beta-secret",
        "api_key=action-gamma-secret",
        "password=action-delta-secret",
    ],
)
def test_sensitive_normalized_payload_is_rejected_without_consuming_idempotency_key(
    client, admin_headers, action_capability_and_profile, caplog, sensitive_value
):
    profile_id, version_id = action_capability_and_profile
    suffix = sensitive_value.split("action-")[1].split("-")[0]
    username = f"wa0_sensitive_{suffix}"
    _create_user(client, admin_headers, username)
    actor_id, conversation_id, ticket_code = _context(username, profile_id, version_id)
    key = f"sensitive-reuse-{suffix}"
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        with pytest.raises(AppError) as raised:
            assistant_actions.prepare_action(
                db,
                actor,
                conversation_id,
                CAPABILITY_CODE,
                {"ticket_code": ticket_code, "note": sensitive_value},
                key,
            )
    _assert_code(raised, "AI_ACTION_PAYLOAD_INVALID")
    assert sensitive_value not in raised.value.message
    assert sensitive_value not in caplog.text
    with SessionLocal() as db:
        assert db.query(AiAction).filter(AiAction.idempotency_key == key).count() == 0
        assert sensitive_value not in json.dumps([row.summary for row in db.query(AuditLog).all()])

    safe = _prepare(username, conversation_id, ticket_code, key, "legitimate non-secret note")
    assert safe["status"] == "prepared"
    assert safe["confirmation_token"]


@pytest.mark.parametrize(
    "invalidation",
    [
        "provider-disabled",
        "provider-unhealthy",
        "provider-incompatible",
        "malformed-snapshot",
        "current-version-replaced",
        "profile-replaced",
        "profile-withdrawn",
        "conversation-profile-mismatch",
    ],
)
def test_confirm_revalidates_complete_conversation_bound_runtime_profile(
    client, admin_headers, action_capability_and_profile, invalidation, monkeypatch
):
    profile_id, version_id = action_capability_and_profile
    username = f"wa0_runtime_{invalidation.replace('-', '_')}"
    _create_user(client, admin_headers, username)
    actor_id, conversation_id, ticket_code = _context(username, profile_id, version_id)
    prepared = _prepare(username, conversation_id, ticket_code, f"runtime-{invalidation}")
    governance_events: list[str] = []
    original_lock_governance = assistant_config.lock_profile_runtime_governance
    original_runtime_profile = assistant_config.runtime_published_profile

    def observed_lock_governance(db):
        governance_events.append("governance")
        return original_lock_governance(db)

    def observed_runtime_profile(db, profile, *, audience=None):
        governance_events.append("runtime")
        return original_runtime_profile(db, profile, audience=audience)

    monkeypatch.setattr(
        assistant_config, "lock_profile_runtime_governance", observed_lock_governance
    )
    monkeypatch.setattr(
        assistant_config, "runtime_published_profile", observed_runtime_profile
    )
    replacement_ids: list[str] = []
    with SessionLocal() as db:
        profile = db.get(AiAgentProfile, profile_id)
        version = db.get(AiAgentProfileVersion, version_id)
        provider = db.get(AiProviderConfig, profile.default_provider_id)
        conversation = db.get(AiConversation, conversation_id)
        original = {
            "profile_enabled": profile.enabled,
            "profile_status": profile.status,
            "profile_deleted": profile.is_deleted,
            "provider_enabled": provider.enabled,
            "provider_probe_status": provider.probe_status,
            "provider_probe": dict(provider.capability_probe),
            "version_snapshot": dict(version.config_snapshot),
            "conversation_profile_id": conversation.profile_id,
            "conversation_version_id": conversation.profile_version_id,
        }
        if invalidation == "provider-disabled":
            provider.enabled = False
        elif invalidation == "provider-unhealthy":
            provider.probe_status = "failed"
        elif invalidation == "provider-incompatible":
            provider.capability_probe = {**provider.capability_probe, "supports_tools": False}
        elif invalidation == "malformed-snapshot":
            version.config_snapshot = {"schema_version": 1}
        elif invalidation == "current-version-replaced":
            replacement = AiAgentProfileVersion(
                profile_id=profile.id,
                version=2,
                status="published",
                system_prompt_zh=version.system_prompt_zh,
                system_prompt_en=version.system_prompt_en,
                enabled_capabilities=list(version.enabled_capabilities),
                knowledge_scope=list(version.knowledge_scope),
                config_snapshot=dict(version.config_snapshot),
                max_risk_level=version.max_risk_level,
                published_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(replacement)
            db.flush()
            replacement_ids.append(replacement.id)
        elif invalidation == "profile-replaced":
            profile.enabled = False
            replacement = AiAgentProfile(
                code=f"replacement-{username}",
                name=profile.name,
                audience=profile.audience,
                default_provider_id=profile.default_provider_id,
                max_risk_level=profile.max_risk_level,
                status="published",
                enabled=True,
                retention_days=profile.retention_days,
            )
            db.add(replacement)
            db.flush()
            replacement_version = AiAgentProfileVersion(
                profile_id=replacement.id,
                version=1,
                status="published",
                system_prompt_zh=version.system_prompt_zh,
                system_prompt_en=version.system_prompt_en,
                enabled_capabilities=list(version.enabled_capabilities),
                knowledge_scope=list(version.knowledge_scope),
                config_snapshot={**version.config_snapshot},
                max_risk_level=version.max_risk_level,
                published_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(replacement_version)
            db.flush()
            replacement_ids.extend([replacement_version.id, replacement.id])
        elif invalidation == "profile-withdrawn":
            profile.status = "draft"
        elif invalidation == "conversation-profile-mismatch":
            conversation.profile_id = "profile-mismatch"
        db.commit()

    try:
        with SessionLocal() as db:
            actor = db.get(AuthUser, actor_id)
            with pytest.raises(AppError) as raised:
                assistant_actions.confirm_action(
                    db, actor, prepared["action_id"], prepared["confirmation_token"]
                )
            _assert_code(raised, "AI_ACTION_REAUTHORIZATION_FAILED")
        if invalidation == "profile-withdrawn":
            assert governance_events == ["governance"]
        else:
            assert governance_events[:2] == ["governance", "runtime"]
        with SessionLocal() as db:
            assert db.get(AiAction, prepared["action_id"]).status == "failed"
            assert db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one().remarks is None
    finally:
        with SessionLocal() as db:
            profile = db.get(AiAgentProfile, profile_id)
            version = db.get(AiAgentProfileVersion, version_id)
            provider = db.get(AiProviderConfig, profile.default_provider_id)
            conversation = db.get(AiConversation, conversation_id)
            profile.enabled = original["profile_enabled"]
            profile.status = original["profile_status"]
            profile.is_deleted = original["profile_deleted"]
            provider.enabled = original["provider_enabled"]
            provider.probe_status = original["provider_probe_status"]
            provider.capability_probe = original["provider_probe"]
            version.config_snapshot = original["version_snapshot"]
            conversation.profile_id = original["conversation_profile_id"]
            conversation.profile_version_id = original["conversation_version_id"]
            for row_id in replacement_ids:
                row = db.get(AiAgentProfileVersion, row_id) or db.get(AiAgentProfile, row_id)
                if row is not None:
                    db.delete(row)
            db.commit()


class _NamedConstraintError(Exception):
    def __init__(self, constraint_name: str):
        self.diag = SimpleNamespace(constraint_name=constraint_name)
        super().__init__(f"constraint {constraint_name}")


@pytest.mark.parametrize("same_payload", [True, False])
def test_concurrent_prepare_named_idempotency_race_reloads_winner_without_token_reissue(
    client, admin_headers, action_capability_and_profile, monkeypatch, same_payload
):
    profile_id, version_id = action_capability_and_profile
    username = f"wa0_race_{'same' if same_payload else 'different'}"
    _create_user(client, admin_headers, username)
    actor_id, conversation_id, ticket_code = _context(username, profile_id, version_id)
    key = f"prepare-race-{'same' if same_payload else 'different'}"
    winner = _prepare(username, conversation_id, ticket_code, key, "winner payload")
    preview_calls_before = HANDLER.preview_calls

    original_first = Query.first
    hidden = False

    def hide_initial_winner(query):
        nonlocal hidden
        entity = query.column_descriptions[0].get("entity") if query.column_descriptions else None
        if entity is AiAction and not hidden:
            hidden = True
            return None
        return original_first(query)

    token_calls = 0

    def loser_token(_size):
        nonlocal token_calls
        token_calls += 1
        return "loser-raw-token-must-never-return"

    monkeypatch.setattr(Query, "first", hide_initial_winner)
    monkeypatch.setattr(assistant_actions.secrets, "token_urlsafe", loser_token)
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        original_flush = db.flush

        def race_flush(*args, **kwargs):
            if any(isinstance(item, AiAction) for item in db.new):
                raise IntegrityError(
                    "INSERT ai_action",
                    {},
                    _NamedConstraintError("uq_ai_action_user_capability_idempotency"),
                )
            return original_flush(*args, **kwargs)

        monkeypatch.setattr(db, "flush", race_flush)
        if same_payload:
            replay = assistant_actions.prepare_action(
                db,
                actor,
                conversation_id,
                CAPABILITY_CODE,
                {"ticket_code": ticket_code, "note": "winner payload"},
                key,
            )
            assert replay["action_id"] == winner["action_id"]
            assert "confirmation_token" not in replay
        else:
            with pytest.raises(AppError) as raised:
                assistant_actions.prepare_action(
                    db,
                    actor,
                    conversation_id,
                    CAPABILITY_CODE,
                    {"ticket_code": ticket_code, "note": "different payload"},
                    key,
                )
            _assert_code(raised, "AI_ACTION_IDEMPOTENCY_CONFLICT")
    assert token_calls == 1
    assert HANDLER.preview_calls == preview_calls_before + 1


def test_prepare_does_not_swallow_unrelated_integrity_error(
    client, admin_headers, action_capability_and_profile, monkeypatch
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_race_unrelated")
    actor_id, conversation_id, ticket_code = _context(
        "wa0_race_unrelated", profile_id, version_id
    )
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)

        def unrelated_flush(*_args, **_kwargs):
            raise IntegrityError(
                "INSERT ai_action",
                {},
                _NamedConstraintError("uq_some_unrelated_constraint"),
            )

        monkeypatch.setattr(db, "flush", unrelated_flush)
        with pytest.raises(IntegrityError):
            assistant_actions.prepare_action(
                db,
                actor,
                conversation_id,
                CAPABILITY_CODE,
                {"ticket_code": ticket_code, "note": "unrelated constraint"},
                "unrelated-race-key",
            )


def test_confirm_handler_failure_uses_savepoint_keeps_outer_lock_and_waiter_never_executes(
    client, admin_headers, action_capability_and_profile, monkeypatch
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_confirm_savepoint")
    actor_id, conversation_id, ticket_code = _context(
        "wa0_confirm_savepoint", profile_id, version_id
    )
    prepared = _prepare(
        "wa0_confirm_savepoint",
        conversation_id,
        ticket_code,
        "confirm-savepoint-key",
        "explode after domain mutation",
    )
    execute_calls_before = HANDLER.execute_calls
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        begin_nested_calls = 0
        rollback_calls = 0
        original_begin_nested = db.begin_nested
        original_rollback = db.rollback

        def observed_begin_nested(*args, **kwargs):
            nonlocal begin_nested_calls
            begin_nested_calls += 1
            return original_begin_nested(*args, **kwargs)

        def observed_rollback(*args, **kwargs):
            nonlocal rollback_calls
            rollback_calls += 1
            return original_rollback(*args, **kwargs)

        monkeypatch.setattr(db, "begin_nested", observed_begin_nested)
        monkeypatch.setattr(db, "rollback", observed_rollback)
        with pytest.raises(AppError) as raised:
            assistant_actions.confirm_action(
                db, actor, prepared["action_id"], prepared["confirmation_token"]
            )
        _assert_code(raised, "AI_ACTION_EXECUTION_FAILED")
        assert begin_nested_calls == 1
        assert rollback_calls == 0

    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        with pytest.raises(AppError) as waiting:
            assistant_actions.confirm_action(
                db, actor, prepared["action_id"], prepared["confirmation_token"]
            )
        _assert_code(waiting, "AI_ACTION_NOT_PREPARED")
    assert HANDLER.execute_calls == execute_calls_before + 1


def test_confirm_failure_state_persistence_error_is_bounded_and_not_silently_swallowed(
    client, admin_headers, action_capability_and_profile, monkeypatch
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_failure_persistence")
    actor_id, conversation_id, ticket_code = _context(
        "wa0_failure_persistence", profile_id, version_id
    )
    prepared = _prepare(
        "wa0_failure_persistence",
        conversation_id,
        ticket_code,
        "failure-persistence-key",
        "explode before failure persistence",
    )
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        original_commit = db.commit
        begin_nested_calls = 0
        original_begin_nested = db.begin_nested

        def observed_begin_nested(*args, **kwargs):
            nonlocal begin_nested_calls
            begin_nested_calls += 1
            return original_begin_nested(*args, **kwargs)

        def fail_terminal_commit():
            row = db.get(AiAction, prepared["action_id"])
            if row is not None and row.status == "failed":
                raise RuntimeError("database unavailable with secret internal detail")
            return original_commit()

        monkeypatch.setattr(db, "commit", fail_terminal_commit)
        monkeypatch.setattr(db, "begin_nested", observed_begin_nested)
        with pytest.raises(AppError) as raised:
            assistant_actions.confirm_action(
                db, actor, prepared["action_id"], prepared["confirmation_token"]
            )
        _assert_code(raised, "AI_ACTION_FAILURE_PERSISTENCE_FAILED")
        assert "secret internal detail" not in raised.value.message
        assert begin_nested_calls == 1

    with SessionLocal() as db:
        assert db.get(AiAction, prepared["action_id"]).status == "prepared"
        assert db.query(Ticket).filter(Ticket.ticket_code == ticket_code).one().remarks is None


def test_preview_result_status_must_be_exactly_prepared(
    client, admin_headers, action_capability_and_profile
):
    profile_id, version_id = action_capability_and_profile
    _create_user(client, admin_headers, "wa0_preview_status")
    actor_id, conversation_id, ticket_code = _context(
        "wa0_preview_status", profile_id, version_id
    )
    with SessionLocal() as db:
        actor = db.get(AuthUser, actor_id)
        with pytest.raises(AppError) as raised:
            assistant_actions.prepare_action(
                db,
                actor,
                conversation_id,
                CAPABILITY_CODE,
                {"ticket_code": ticket_code, "note": "preview-invalid-status"},
                "preview-status-key",
            )
        _assert_code(raised, "AI_ACTION_PREVIEW_INVALID")
    with SessionLocal() as db:
        assert db.query(AiAction).filter(
            AiAction.idempotency_key == "preview-status-key"
        ).count() == 0
