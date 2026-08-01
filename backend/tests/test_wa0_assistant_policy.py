"""WA0 capability discovery must derive authority from persisted ITOM state."""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.assistant.policy import capabilities_for_user
from app.assistant.registry import CapabilityRegistry
from app.assistant.types import AssistantChannel, CapabilityDefinition, CapabilityResult, RiskLevel
from app.db import SessionLocal
from app.models import AiAgentProfile, AiAgentProfileVersion, AuthUser, UserGroup, UserGroupMember


class _CapabilityInput(BaseModel):
    subject: str


def _handler(*_args):
    return CapabilityResult(status="ok", data={})


def _definition(code, *, audiences, module, action, risk=RiskLevel.L2, confirmation=False):
    return CapabilityDefinition(
        code=code,
        channels=frozenset({AssistantChannel.WEB}),
        audiences=frozenset(audiences),
        module=module,
        action=action,
        risk=risk,
        input_model=_CapabilityInput,
        handler=_handler,
        requires_confirmation=confirmation,
    )


def _registry():
    registry = CapabilityRegistry()
    for definition in (
        _definition("service_request.prepare", audiences={"requester", "bdo", "it", "admin"}, module="ticket_sr", action="create"),
        _definition("requirement.prepare", audiences={"bdo", "it", "admin"}, module="requirements", action="create"),
        _definition("knowledge.search", audiences={"requester", "bdo", "it", "admin", "auditor"}, module="knowledge", action="view", risk=RiskLevel.L1),
        _definition("incident.create", audiences={"it", "admin"}, module="ticket_incident", action="create", risk=RiskLevel.L3, confirmation=True),
        _definition("process_task.complete", audiences={"it", "admin"}, module="task_development", action="edit", risk=RiskLevel.L3, confirmation=True),
    ):
        registry.register(definition)
    return registry


def _create_user(client, admin_headers, username, roles):
    person = client.post("/api/members", json={"name": username}, headers=admin_headers).json()["data"]
    response = client.post(
        "/api/admin/users",
        json={"username": username, "password": "pass123", "roles": roles, "person_id": person["id"]},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        return db.query(AuthUser).filter_by(username=username).one().id, person["id"]


def _publish_profile(db, code, audience, enabled_capabilities, max_risk="L3"):
    code = f"{code}-{db.query(AiAgentProfile).count()}"
    profile = AiAgentProfile(
        code=code,
        audience=audience,
        enabled=True,
        status="published",
        max_risk_level=max_risk,
    )
    db.add(profile)
    db.flush()
    db.add(AiAgentProfileVersion(
        profile_id=profile.id,
        version=1,
        status="published",
        enabled_capabilities=enabled_capabilities,
        max_risk_level=max_risk,
    ))


def _published_profiles(db, *, max_risk="L3", requester_codes=None):
    all_codes = [
        "service_request.prepare", "requirement.prepare", "knowledge.search", "incident.create", "process_task.complete",
    ]
    _publish_profile(db, "wa0-requester", "requester", requester_codes or all_codes, max_risk)
    _publish_profile(db, "wa0-bdo", "bdo", all_codes, max_risk)
    _publish_profile(db, "wa0-it", "it", all_codes, max_risk)
    _publish_profile(db, "wa0-admin", "admin", all_codes, max_risk)
    _publish_profile(db, "wa0-auditor", "auditor", all_codes, max_risk)
    db.commit()


def _codes(db, user_id, registry, **kwargs):
    return {item.code for item in capabilities_for_user(
        db, SimpleNamespace(id=user_id, roles=["admin"]), channel="web", registry=registry, **kwargs
    )}


def test_requester_and_bdo_discovery_are_isolated_by_persisted_roles(client, admin_headers):
    """A role/audience expansion must not expose internal IT capabilities to a requester or BDO."""
    requester_id, _ = _create_user(client, admin_headers, "wa0_requester", ["requester"])
    bdo_id, _ = _create_user(client, admin_headers, "wa0_bdo", ["bdo"])
    registry = _registry()
    with SessionLocal() as db:
        _published_profiles(db)
        requester_codes = _codes(db, requester_id, registry, max_risk="L3")
        bdo_codes = _codes(db, bdo_id, registry, max_risk="L3")

    assert {"service_request.prepare", "knowledge.search"} <= requester_codes
    assert not {"requirement.prepare", "incident.create", "process_task.complete"} & requester_codes
    assert bdo_codes - requester_codes == {"requirement.prepare"}
    assert not {"incident.create", "process_task.complete"} & bdo_codes


def test_direct_and_group_granted_it_roles_take_effect(client, admin_headers):
    """Removing either direct or group role expansion must hide the IT-only capability."""
    direct_id, _ = _create_user(client, admin_headers, "wa0_direct_it", ["it_dev"])
    grouped_id, grouped_person_id = _create_user(client, admin_headers, "wa0_group_it", ["requester"])
    registry = _registry()
    with SessionLocal() as db:
        _published_profiles(db)
        group = UserGroup(code="wa0-it-group", name="WA0 IT group", roles=["it_dev"])
        db.add(group)
        db.flush()
        db.add(UserGroupMember(group_id=group.id, person_id=grouped_person_id))
        db.commit()
        assert "incident.create" in _codes(db, direct_id, registry, max_risk="L3")
        assert "incident.create" in _codes(db, grouped_id, registry, max_risk="L3")


def test_auditor_admin_inactive_and_profile_constraints_are_fail_closed(client, admin_headers):
    """A policy regression must not let audit-only, inactive, or profile-limited users discover writes."""
    auditor_id, _ = _create_user(client, admin_headers, "wa0_auditor", ["auditor"])
    admin_id, _ = _create_user(client, admin_headers, "wa0_admin", ["admin"])
    inactive_id, _ = _create_user(client, admin_headers, "wa0_inactive", ["requester"])
    requester_id, _ = _create_user(client, admin_headers, "wa0_limited", ["requester"])
    registry = _registry()
    with SessionLocal() as db:
        _published_profiles(db, max_risk="L3", requester_codes=["knowledge.search"])
        inactive = db.get(AuthUser, inactive_id)
        inactive.is_active = False
        db.commit()

        assert _codes(db, auditor_id, registry, max_risk="L3") == {"knowledge.search"}
        admin_codes = _codes(db, admin_id, registry, max_risk="L3")
        assert "incident.create" in admin_codes
        assert all(item.risk is not RiskLevel.L4 for item in capabilities_for_user(
            db, SimpleNamespace(id=admin_id), channel="web", registry=registry, max_risk="L3"
        ))
        assert _codes(db, inactive_id, registry, max_risk="L3") == set()
        assert _codes(db, requester_id, registry, max_risk="L3") == {"knowledge.search"}


def test_discovery_reloads_database_identity_and_never_exports_internal_registry_details(client, admin_headers):
    """Trusting caller roles or exposing handlers/policy data would break this server-boundary contract."""
    requester_id, _ = _create_user(client, admin_headers, "wa0_no_client_role", ["requester"])
    registry = _registry()
    with SessionLocal() as db:
        _published_profiles(db)
        visible = capabilities_for_user(
            db, SimpleNamespace(id=requester_id, roles=["admin"]), channel="web", registry=registry, max_risk="L3"
        )

    codes = {item.code for item in visible}
    assert "incident.create" not in codes
    model_schema = visible[0].model_schema()
    assert {"handler", "audiences", "module", "action", "requires_confirmation"}.isdisjoint(model_schema)
    assert model_schema["code"] in codes


def test_registry_rejects_unsafe_or_unbound_capability_definitions():
    """Relaxing registration invariants would permit arbitrary or unconfirmed executable actions."""
    registry = CapabilityRegistry()
    valid = _definition("safe.read", audiences={"requester"}, module="knowledge", action="view", risk=RiskLevel.L1)
    registry.register(valid)
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(valid)
    with pytest.raises(ValueError, match="confirmation"):
        registry.register(_definition("unsafe.write", audiences={"it"}, module="ticket_incident", action="create", risk=RiskLevel.L3))
    with pytest.raises(ValueError, match="L4"):
        registry.register(_definition("forbidden.delete", audiences={"admin"}, module="ticket_incident", action="delete", risk=RiskLevel.L4, confirmation=True))
    with pytest.raises(ValueError, match="Pydantic"):
        registry.register(CapabilityDefinition(
            code="bad.model", channels=frozenset({AssistantChannel.WEB}), audiences=frozenset({"requester"}),
            module=None, action=None, risk=RiskLevel.L0, input_model=object, handler=_handler,
        ))
    with pytest.raises(ValueError, match="handler"):
        registry.register(CapabilityDefinition(
            code="bad.handler", channels=frozenset({AssistantChannel.WEB}), audiences=frozenset({"requester"}),
            module=None, action=None, risk=RiskLevel.L0, input_model=_CapabilityInput, handler=None,
        ))
