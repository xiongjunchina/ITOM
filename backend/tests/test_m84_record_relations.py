"""M84：跨域单据关联关系的权限、幂等与可见性。"""

from datetime import date, timedelta

import pytest

from app.core.errors import AppError
from app.db import SessionLocal
from app.models import AuditLog, AuthUser, RecordRelation, Ticket
from app.services.record_relations import create_record_relation


def _create_ticket(client, headers, service_item_id, *, title, ticket_type):
    response = client.post(
        "/api/tickets",
        json={
            "title": title,
            "ticket_type": ticket_type,
            "priority": "P3",
            "description": "M84 关联关系测试",
            "service_item_id": service_item_id,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_record_relation_is_idempotent_and_hides_invisible_counterpart(client, admin_headers):
    requester = client.post(
        "/api/admin/users",
        json={"username": "m84_relation_requester", "password": "pass123", "roles": ["requester"]},
        headers=admin_headers,
    )
    assert requester.status_code == 200, requester.text
    token = client.post(
        "/api/auth/login",
        json={"username": "m84_relation_requester", "password": "pass123"},
    ).json()["data"]["token"]
    requester_headers = {"Authorization": f"Bearer {token}"}
    service_item_id = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]

    service_request = _create_ticket(
        client,
        requester_headers,
        service_item_id,
        title="M84 影响范围扩大服务请求",
        ticket_type="service_request",
    )
    preflight = client.post(
        "/api/record-relations/prepare",
        json={
            "source_entity_type": "ticket",
            "source_entity_id": service_request["id"],
            "relation_type": "upgraded_to_incident",
        },
        headers=requester_headers,
    )
    assert preflight.status_code == 403
    incident = _create_ticket(
        client,
        admin_headers,
        service_item_id,
        title="M84 由服务请求升级的事件",
        ticket_type="incident",
    )

    with SessionLocal() as db:
        admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
        requester_user = db.query(AuthUser).filter(AuthUser.username == "m84_relation_requester").one()
        with pytest.raises(AppError, match="目标单据的创建权限"):
            create_record_relation(
                db,
                source_entity_type="ticket",
                source_entity_id=service_request["id"],
                target_entity_type="ticket",
                target_entity_id=incident["id"],
                relation_type="upgraded_to_incident",
                reason="影响范围扩大，需要按事件流程统一协调处理",
                idempotency_key="m84-requester-no-incident-create",
                actor=requester_user,
            )
        first, created = create_record_relation(
            db,
            source_entity_type="ticket",
            source_entity_id=service_request["id"],
            target_entity_type="ticket",
            target_entity_id=incident["id"],
            relation_type="upgraded_to_incident",
            reason="影响范围扩大，需要按事件流程统一协调处理",
            idempotency_key="m84-upgrade-service-request-001",
            actor=admin,
        )
        db.commit()
        second, created_again = create_record_relation(
            db,
            source_entity_type="ticket",
            source_entity_id=service_request["id"],
            target_entity_type="ticket",
            target_entity_id=incident["id"],
            relation_type="upgraded_to_incident",
            reason="影响范围扩大，需要按事件流程统一协调处理",
            idempotency_key="m84-upgrade-service-request-001",
            actor=admin,
        )
        db.commit()
        assert created is True
        assert created_again is False
        assert first.id == second.id
        assert db.query(RecordRelation).filter(RecordRelation.is_deleted.is_(False)).count() == 1
        assert db.query(AuditLog).filter(
            AuditLog.entity_type == "record_relation", AuditLog.entity_id == first.id, AuditLog.action == "create"
        ).count() == 1
        with pytest.raises(AppError, match="幂等键已用于不同的关联请求"):
            create_record_relation(
                db,
                source_entity_type="ticket",
                source_entity_id=service_request["id"],
                target_entity_type="ticket",
                target_entity_id=incident["id"],
                relation_type="upgraded_to_incident",
                reason="改为另一条不同的关联说明，必须拒绝重复幂等键",
                idempotency_key="m84-upgrade-service-request-001",
                actor=admin,
            )

    admin_relations = client.get(
        f"/api/records/ticket/{service_request['id']}/relations",
        headers=admin_headers,
    )
    assert admin_relations.status_code == 200, admin_relations.text
    assert admin_relations.json()["data"][0]["counterpart"]["id"] == incident["id"]

    requester_relations = client.get(
        f"/api/records/ticket/{service_request['id']}/relations",
        headers=requester_headers,
    )
    assert requester_relations.status_code == 200, requester_relations.text
    assert requester_relations.json()["data"] == []

    # 对端后续被软删除时，来源详情仍应可读，关系安全地不展示而非整体返回 404。
    with SessionLocal() as db:
        db.get(Ticket, incident["id"]).is_deleted = True
        db.commit()
    after_target_deleted = client.get(
        f"/api/records/ticket/{service_request['id']}/relations",
        headers=admin_headers,
    )
    assert after_target_deleted.status_code == 200, after_target_deleted.text
    assert after_target_deleted.json()["data"] == []


def _submit_relation(client, headers, source_entity_type, source_id, relation_type, reason, key, target):
    response = client.post(
        "/api/record-relations/submit",
        json={
            "source_entity_type": source_entity_type,
            "source_entity_id": source_id,
            "relation_type": relation_type,
            "reason": reason,
            "idempotency_key": key,
            "target": target,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_relation_submit_creates_targets_through_domain_flows_and_is_idempotent(client, admin_headers):
    """M84-C：四条转单路径各自启动目标流程，原单据不改类型且重复提交不重复建目标。"""
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]

    service_request = _create_ticket(
        client, admin_headers, item, title="M84-C 多办公室无法访问系统", ticket_type="service_request"
    )
    incident_payload = {
        "title": "M84-C 系统访问中断事件",
        "description": "来源服务请求影响范围已扩大，需要按事件统一协调。",
        "priority": "P1",
        "service_item_id": item,
    }
    incident_created = _submit_relation(
        client,
        admin_headers,
        "ticket",
        service_request["id"],
        "upgraded_to_incident",
        "多个办公区受到影响，需要按事件流程统一协调处理",
        "m84c-sr-to-incident-0001",
        incident_payload,
    )
    assert incident_created["target"]["record_type"] == "incident"
    assert incident_created["relation"]["relation_type"] == "upgraded_to_incident"
    assert client.get(f"/api/tickets/{service_request['id']}", headers=admin_headers).json()["data"]["ticket_type"] == "service_request"
    incident_detail = client.get(
        f"/api/tickets/{incident_created['target']['id']}", headers=admin_headers
    ).json()["data"]
    assert incident_detail["process"] is not None

    incident_retry = _submit_relation(
        client,
        admin_headers,
        "ticket",
        service_request["id"],
        "upgraded_to_incident",
        "多个办公区受到影响，需要按事件流程统一协调处理",
        "m84c-sr-to-incident-0001",
        incident_payload,
    )
    assert incident_retry["target"]["id"] == incident_created["target"]["id"]
    assert incident_retry["idempotent_replay"] is True
    conflict = client.post(
        "/api/record-relations/submit",
        json={
            "source_entity_type": "ticket",
            "source_entity_id": service_request["id"],
            "relation_type": "upgraded_to_incident",
            "reason": "多个办公区受到影响，需要按事件流程统一协调处理",
            "idempotency_key": "m84c-sr-to-incident-0001",
            "target": {**incident_payload, "title": "不同的重复提交内容"},
        },
        headers=admin_headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    problem_source = _create_ticket(
        client, admin_headers, item, title="M84-C 连续出现的登录失败", ticket_type="service_request"
    )
    problem_created = _submit_relation(
        client,
        admin_headers,
        "ticket",
        problem_source["id"],
        "root_cause_of",
        "本月多次出现相同现象，需要建立问题进行根因分析",
        "m84c-ticket-to-problem-0001",
        {
            "title": "M84-C 登录失败根因分析",
            "description": "由服务请求关联，需要查明重复登录失败的根本原因。",
            "priority": "P2",
            "service_item_id": item,
            "assigned_line": "ops",
        },
    )
    assert problem_created["target"]["entity_type"] == "problem"

    change_source = _create_ticket(
        client, admin_headers, item, title="M84-C 生产环境异常事件", ticket_type="incident"
    )
    change_created = _submit_relation(
        client,
        admin_headers,
        "ticket",
        change_source["id"],
        "remediated_by_change",
        "修复需要在生产窗口执行受控配置变更并准备回退方案",
        "m84c-incident-to-change-0001",
        {
            "title": "M84-C 生产配置修复变更",
            "description": "由事件关联，按变更流程执行生产修复。",
            "priority": "P2",
            "service_item_id": item,
            "change_type": "普通",
            "risk_level": "中",
            "change_reason": "解决持续发生的生产环境异常。",
            "rollback_plan": "验证异常时恢复变更前配置。",
            "implementation_plan": "在已批准窗口按步骤执行并验证。",
        },
    )
    assert change_created["target"]["record_type"] == "change"

    problem = client.post(
        "/api/problems",
        json={
            "title": "M84-C 已知错误需要修复",
            "description": "完成根因分析后，需要受控修改生产配置。",
            "priority": "P2",
            "service_item_id": item,
            "assigned_line": "ops",
        },
        headers=admin_headers,
    ).json()["data"]
    problem_change = _submit_relation(
        client,
        admin_headers,
        "problem",
        problem["id"],
        "remediated_by_change",
        "问题根因已明确，需通过受控变更永久修复",
        "m84c-problem-to-change-0001",
        {
            "title": "M84-C 已知错误永久修复变更",
            "description": "由问题关联，实施永久性生产修复。",
            "priority": "P2",
            "service_item_id": item,
            "change_type": "标准",
        },
    )
    assert problem_change["target"]["record_type"] == "change"

    pm = client.post("/api/members", json={"name": "M84-C 项目经理"}, headers=admin_headers).json()["data"]
    domain = client.post(
        "/api/admin/business-domains",
        json={"code": "m84c", "name": "M84-C 业务域"},
        headers=admin_headers,
    ).json()["data"]
    requirement = client.post(
        "/api/requirements",
        json={
            "title": "M84-C 新系统建设需求",
            "req_type": "功能",
            "business_domain_id": domain["id"],
            "description": "需要成立项目完成新系统建设与交付。",
        },
        headers=admin_headers,
    ).json()["data"]
    project_reason = "需求经评估需要项目化实施，并纳入章程和WBS管理"
    project_created = _submit_relation(
        client,
        admin_headers,
        "requirement",
        requirement["id"],
        "converted_to_project",
        project_reason,
        "m84c-requirement-to-project-0001",
        {
            "name": "M84-C 新系统建设项目",
            "pm": pm["id"],
            "planned_start": str(date.today()),
            "planned_end": str(date.today() + timedelta(days=30)),
            "description": "由 IT 需求创建的项目化交付。",
        },
    )
    assert project_created["target"]["entity_type"] == "project"
    requirement_detail = client.get(f"/api/requirements/{requirement['id']}", headers=admin_headers).json()["data"]
    assert requirement_detail["project_id"] == project_created["target"]["id"]
    assert requirement_detail["project_relation_reason"] == project_reason
    project_detail = client.get(f"/api/projects/{project_created['target']['id']}", headers=admin_headers).json()["data"]
    assert project_detail["linked_requirements"][0]["id"] == requirement["id"]
    assert project_detail["linked_requirements"][0]["relation_reason"] == project_reason
