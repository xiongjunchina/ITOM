"""P1：Aily MCP 服务请求与 IT 需求登记端到端契约。"""

from datetime import datetime, timedelta, timezone
import json
import secrets

import jwt
import pytest

from app.db import SessionLocal
from app.models import McpToolCall, ProcessInstance, Requirement, Ticket


JWT_SECRET = secrets.token_urlsafe(32)
TENANT_ID = "tenant-p1"
AGENT_ID = "agent-p1"
APP_ID = "agent-p1"
ORIGIN = "https://aily.feishu.cn"
REQUESTER_SUBJECT = "ou_p1_requester"
OTHER_SUBJECT = "ou_p1_other"
REQUESTER_ONLY_SUBJECT = "ou_p1_requester_only"


def _token(subject: str = REQUESTER_SUBJECT) -> str:
    return jwt.encode(
        {
            "tenant_id": TENANT_ID,
            "agent_id": AGENT_ID,
            "app_id": APP_ID,
            "feishu_open_id": subject,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def _mcp_call(client, name: str, arguments: dict, subject: str = REQUESTER_SUBJECT) -> dict:
    response = client.post(
        "/mcp/",
        headers={
            "origin": ORIGIN,
            "x-aily-jwt": _token(subject),
            "accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": secrets.randbelow(100000),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "error" not in body, body
    return json.loads(body["result"]["content"][0]["text"])


def _login(client, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "pass123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['token']}"}


@pytest.fixture(scope="module")
def p1(client, admin_headers):
    client.put(
        "/api/admin/integrations/aily",
        json={
            "enabled": True,
            "mcp_jwt_secret": JWT_SECRET,
            "allowed_tenant_ids": [TENANT_ID],
            "allowed_agent_ids": [AGENT_ID],
            "allowed_origins": [ORIGIN],
        },
        headers=admin_headers,
    )

    business_department = client.post(
        "/api/admin/departments",
        json={"code": "p1_business", "name": "P1 业务部门", "dept_type": "business"},
        headers=admin_headers,
    ).json()["data"]
    support_department = client.post(
        "/api/admin/departments",
        json={"code": "p1_support", "name": "P1 IT 支持组", "dept_type": "it"},
        headers=admin_headers,
    ).json()["data"]

    def create_account(name: str, username: str, roles: list[str], department_id: str):
        person = client.post(
            "/api/members",
            json={"name": name, "department_id": department_id},
            headers=admin_headers,
        ).json()["data"]
        user = client.post(
            "/api/admin/users",
            json={
                "username": username,
                "password": "pass123",
                "roles": roles,
                "person_id": person["id"],
            },
            headers=admin_headers,
        ).json()["data"]
        return person, user

    requester_person, requester_user = create_account(
        "P1 BDO", "p1_requester", ["bdo"], business_department["id"]
    )
    other_person, other_user = create_account(
        "P1 其他 BDO", "p1_other", ["bdo"], business_department["id"]
    )
    requester_only_person, requester_only_user = create_account(
        "P1 普通业务用户", "p1_requester_only", ["requester"], business_department["id"]
    )
    support_person, support_user = create_account(
        "P1 支持工程师", "p1_supporter", ["it_ops"], support_department["id"]
    )
    requester_headers = _login(client, "p1_requester")
    support_headers = _login(client, "p1_supporter")

    for subject, user in (
        (REQUESTER_SUBJECT, requester_user),
        (OTHER_SUBJECT, other_user),
        (REQUESTER_ONLY_SUBJECT, requester_only_user),
    ):
        response = client.post(
            "/api/admin/integrations/aily/identities",
            json={
                "provider": "feishu",
                "tenant_id": TENANT_ID,
                "app_id": APP_ID,
                "subject_type": "open_id",
                "subject_id": subject,
                "auth_user_id": user["id"],
            },
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text

    process_definitions = client.get(
        "/api/admin/process-definitions", headers=admin_headers
    ).json()["data"]
    service_request_process = next(
        row for row in process_definitions if row["code"] == "sr_flow"
    )

    catalog = client.post(
        "/api/catalogs",
        json={"name": "P1 账号与网络服务", "tier": "gold"},
        headers=admin_headers,
    ).json()["data"]
    item_response = client.post(
        "/api/service-items",
        json={
            "name": "VPN 访问故障与开通",
            "catalog_id": catalog["id"],
            "service_type": "网络与权限",
            "description": "处理 VPN 无法连接、证书异常与访问开通",
            "search_keywords": ["VPN", "远程办公", "无法连接"],
            "search_synonyms": ["远程接入", "拨号失败"],
            "typical_scenarios": ["VPN 客户端提示证书错误"],
            "exclusion_scenarios": ["新建业务系统"],
            "default_priority": "P3",
            "process_definition_id": service_request_process["id"],
        },
        headers=admin_headers,
    )
    assert item_response.status_code == 200, item_response.text
    item = item_response.json()["data"]

    form_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "description", "contact_method"],
        "properties": {
            "title": {
                "type": "string",
                "title": "标题",
                "minLength": 2,
                "maxLength": 200,
            },
            "description": {
                "type": "string",
                "title": "问题描述",
                "minLength": 5,
                "maxLength": 2000,
                "x-itom-field-type": "long_text",
            },
            "priority": {
                "type": "string",
                "title": "紧急程度",
                "enum": ["P1", "P2", "P3", "P4"],
                "default": "P3",
            },
            "contact_method": {
                "type": "string",
                "title": "方便联系的方式",
                "enum": ["飞书", "电话"],
            },
            "expected_date": {
                "type": "string",
                "title": "期望处理日期",
                "format": "date",
            },
            "suspected_major_impact": {
                "type": "boolean",
                "title": "疑似影响多人",
                "default": False,
            },
        },
    }
    form_response = client.post(
        f"/api/service-items/{item['id']}/form-versions",
        json={"schema": form_schema},
        headers=admin_headers,
    )
    assert form_response.status_code == 200, form_response.text
    form_version = form_response.json()["data"]
    publish_response = client.post(
        f"/api/service-items/{item['id']}/form-versions/{form_version['version']}/publish",
        headers=admin_headers,
    )
    assert publish_response.status_code == 200, publish_response.text

    dispatch_response = client.put(
        f"/api/service-items/{item['id']}/dispatch-rule",
        json={
            "name": "P1 VPN 专属支持",
            "target_type": "member",
            "target_id": support_person["id"],
            "strategy": "fixed",
            "priority": 1,
            "active": True,
        },
        headers=admin_headers,
    )
    assert dispatch_response.status_code == 200, dispatch_response.text

    hidden_item = client.post(
        "/api/service-items",
        json={
            "name": "仅其他员工可见 VPN 服务",
            "catalog_id": catalog["id"],
            "description": "不可被当前用户搜索到",
            "target_audience_mode": "custom",
            "target_audience_refs": [{"type": "member", "id": other_person["id"]}],
            "search_keywords": ["VPN"],
        },
        headers=admin_headers,
    ).json()["data"]

    domain_response = client.post(
        "/api/admin/business-domains",
        json={
            "code": "P1-DOMAIN",
            "name": "P1 供应链业务域",
            "owner_id": support_person["id"],
        },
        headers=admin_headers,
    )
    assert domain_response.status_code == 200, domain_response.text
    domain_id = domain_response.json()["data"]["id"]

    return {
        "requester_user": requester_user,
        "requester_person": requester_person,
        "requester_headers": requester_headers,
        "other_user": other_user,
        "requester_only_user": requester_only_user,
        "support_person": support_person,
        "support_user": support_user,
        "support_headers": support_headers,
        "item": item,
        "hidden_item": hidden_item,
        "form_version": form_version,
        "process": service_request_process,
        "domain_id": domain_id,
    }


def test_p1_tool_discovery_exposes_business_tools_but_not_incident(client, p1):
    response = client.post(
        "/mcp/",
        headers={"origin": ORIGIN, "accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 200, response.text
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert {
        "search_service_items",
        "get_service_item_form",
        "prepare_service_request",
        "submit_service_request",
        "get_my_service_request",
        "list_my_service_requests",
        "get_it_requirement_form",
        "prepare_it_requirement",
        "register_it_requirement",
        "get_my_it_requirement",
        "list_my_it_requirements",
    } <= names
    assert "create_incident" not in names
    assert "create_change" not in names


def test_service_search_and_form_use_real_catalog_and_audience(client, p1):
    result = _mcp_call(client, "search_service_items", {"query": "远程接入失败", "limit": 10})
    assert result["success"] is True
    assert [row["service_item_id"] for row in result["items"]] == [p1["item"]["item_code"]]
    assert result["items"][0]["catalog_name"] == "P1 账号与网络服务"
    assert result["items"][0]["match_reasons"]
    assert p1["hidden_item"]["item_code"] not in str(result)

    form = _mcp_call(
        client,
        "get_service_item_form",
        {"service_item_id": p1["item"]["item_code"]},
    )
    assert form["success"] is True
    assert form["form"]["version"] == p1["form_version"]["version"]
    assert "contact_method" in form["form"]["schema"]["required"]
    assert form["sla"]["resolution_hours"] is not None
    assert form["process"]["name"] == "服务请求交付流程"
    assert form["process"]["requires_approval"] is True
    assert form["expected_support_group"] == "P1 VPN 专属支持"


def test_dynamic_form_validation_is_shared_by_web_and_mcp(client, p1):
    current_form = client.get(
        f"/api/service-items/{p1['item']['id']}/form",
        headers=p1["requester_headers"],
    )
    assert current_form.status_code == 200, current_form.text
    assert current_form.json()["data"]["version"] == p1["form_version"]["version"]

    invalid = client.post(
        "/api/tickets",
        json={
            "title": "VPN 无法连接",
            "ticket_type": "service_request",
            "priority": "P3",
            "description": "客户端提示证书错误",
            "service_item_id": p1["item"]["id"],
            "request_data": {"title": "VPN 无法连接", "description": "客户端提示证书错误"},
            "request_form_version_id": p1["form_version"]["id"],
        },
        headers=p1["requester_headers"],
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "FORM_VALIDATION_FAILED"

    missing = _mcp_call(
        client,
        "prepare_service_request",
        {
            "service_item_id": p1["item"]["item_code"],
            "answers": {"title": "VPN 无法连接", "description": "客户端提示证书错误"},
            "idempotency_key": "p1-sr-missing-fields",
        },
    )
    assert missing["success"] is True
    assert missing["ready_for_confirmation"] is False
    assert missing["missing_fields"] == [
        {"code": "contact_method", "title": "方便联系的方式"}
    ]
    assert "confirmation_token" not in missing


def test_prepare_and_submit_service_request_is_confirmed_idempotent_and_dispatched(client, p1):
    answers = {
        "title": "VPN 客户端无法连接",
        "description": "客户端持续提示证书错误，今天无法远程办公",
        "priority": "P2",
        "contact_method": "飞书",
        "expected_date": "2026-07-31",
        "suspected_major_impact": True,
    }
    prepared = _mcp_call(
        client,
        "prepare_service_request",
        {
            "service_item_id": p1["item"]["item_code"],
            "answers": answers,
            "idempotency_key": "p1-sr-submit-once",
        },
    )
    assert prepared["success"] is True
    assert prepared["ready_for_confirmation"] is True
    assert prepared["preview"]["ticket_type"] == "service_request"
    assert prepared["preview"]["priority"] == "P2"
    assert prepared["preview"]["suspected_major_impact"] is True
    assert prepared["confirmation_token"]

    submitted = _mcp_call(
        client,
        "submit_service_request",
        {
            "confirmation_token": prepared["confirmation_token"],
            "idempotency_key": "p1-sr-submit-once",
        },
    )
    assert submitted["success"] is True
    assert submitted["created"] is True
    assert submitted["ticket_code"].startswith("TK-")

    repeated = _mcp_call(
        client,
        "submit_service_request",
        {
            "confirmation_token": prepared["confirmation_token"],
            "idempotency_key": "p1-sr-submit-once",
        },
    )
    assert repeated == {**submitted, "created": False, "idempotent_replay": True}

    with SessionLocal() as db:
        rows = db.query(Ticket).filter(Ticket.ticket_code == submitted["ticket_code"]).all()
        assert len(rows) == 1
        ticket = rows[0]
        assert ticket.ticket_type == "service_request"
        assert ticket.submitter == p1["requester_user"]["id"]
        assert ticket.assignee == p1["support_person"]["id"]
        assert ticket.dispatch_source == "service_item"
        assert ticket.request_data["contact_method"] == "飞书"
        assert ticket.request_form_snapshot["schema"]["properties"]["contact_method"]
        assert ticket.suspected_major_impact is True
        instance = db.query(ProcessInstance).filter(
            ProcessInstance.entity_type == "ticket", ProcessInstance.entity_id == ticket.id
        ).one()
        assert instance.definition_id == p1["process"]["id"]
        assert db.query(McpToolCall).filter(
            McpToolCall.tool_name == "submit_service_request",
            McpToolCall.entity_id == ticket.id,
        ).count() >= 1

    mine = _mcp_call(
        client, "get_my_service_request", {"ticket_code": submitted["ticket_code"]}
    )
    assert mine["ticket"]["ticket_code"] == submitted["ticket_code"]
    listing = _mcp_call(client, "list_my_service_requests", {"limit": 20})
    assert any(row["ticket_code"] == submitted["ticket_code"] for row in listing["items"])
    denied = _mcp_call(
        client,
        "get_my_service_request",
        {"ticket_code": submitted["ticket_code"]},
        subject=OTHER_SUBJECT,
    )
    assert denied["success"] is False
    assert denied["error"]["code"] == "NOT_FOUND"


def test_requirement_form_prepare_register_and_own_scope(client, p1):
    ordinary = _mcp_call(client, "get_it_requirement_form", {}, subject=REQUESTER_ONLY_SUBJECT)
    assert ordinary["success"] is False
    assert ordinary["error"]["code"] in {"FORBIDDEN", "BDO_REQUIRED"}

    form = _mcp_call(client, "get_it_requirement_form", {})
    assert form["success"] is True
    assert form["submission_available"] is True
    assert form["blocking_reason"] is None
    assert form["form"]["required"] == [
        "title", "req_type", "business_domain_id", "description"
    ]
    assert any(domain["id"] == p1["domain_id"] for domain in form["business_domains"])

    invalid = _mcp_call(
        client,
        "prepare_it_requirement",
        {
            "fields": {"title": "新建供应商门户"},
            "idempotency_key": "p1-req-missing",
        },
    )
    assert invalid["ready_for_confirmation"] is False
    assert {row["code"] for row in invalid["missing_fields"]} == {
        "req_type", "business_domain_id", "description"
    }

    prepared = _mcp_call(
        client,
        "prepare_it_requirement",
        {
            "fields": {
                "title": "新建供应商协同门户",
                "req_type": "功能",
                "business_domain_id": p1["domain_id"],
                "description": "需要供应商在线确认订单、交期和质量问题",
                "expected_date": "2026-12-31",
                "expected_effect": "缩短跨公司协同时间",
                "business_value_note": "减少人工邮件往返",
            },
            "idempotency_key": "p1-req-submit-once",
        },
    )
    assert prepared["ready_for_confirmation"] is True
    assert prepared["preview"]["business_domain_name"] == "P1 供应链业务域"

    registered = _mcp_call(
        client,
        "register_it_requirement",
        {
            "confirmation_token": prepared["confirmation_token"],
            "idempotency_key": "p1-req-submit-once",
        },
    )
    assert registered["created"] is True
    assert registered["requirement_code"].startswith("RQ-")
    repeated = _mcp_call(
        client,
        "register_it_requirement",
        {
            "confirmation_token": prepared["confirmation_token"],
            "idempotency_key": "p1-req-submit-once",
        },
    )
    assert repeated == {**registered, "created": False, "idempotent_replay": True}

    with SessionLocal() as db:
        requirement = db.query(Requirement).filter(
            Requirement.requirement_code == registered["requirement_code"]
        ).one()
        assert requirement.requester == p1["requester_user"]["id"]
        assert requirement.status == "evaluating"
        assert db.query(ProcessInstance).filter(
            ProcessInstance.entity_type == "requirement",
            ProcessInstance.entity_id == requirement.id,
        ).count() == 1

    mine = _mcp_call(
        client,
        "get_my_it_requirement",
        {"requirement_code": registered["requirement_code"]},
    )
    assert mine["requirement"]["requirement_code"] == registered["requirement_code"]
    listing = _mcp_call(client, "list_my_it_requirements", {"limit": 20})
    assert any(
        row["requirement_code"] == registered["requirement_code"]
        for row in listing["items"]
    )
    denied = _mcp_call(
        client,
        "get_my_it_requirement",
        {"requirement_code": registered["requirement_code"]},
        subject=OTHER_SUBJECT,
    )
    assert denied["success"] is False
    assert denied["error"]["code"] == "NOT_FOUND"
