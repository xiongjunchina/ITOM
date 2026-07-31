"""M84：跨域单据关联关系的权限、幂等与可见性。"""

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
