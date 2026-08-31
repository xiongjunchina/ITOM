"""平台产品运营 P0：档案、数据范围、容量版本、幂等和报表。"""
from datetime import date, datetime

from app.core.security import hash_password
from app.db import SessionLocal
from app.models import (
    AuditLog,
    AuthUser,
    BusinessDomain,
    BusinessDomainMember,
    OrgMember,
    Requirement,
    ServiceCatalog,
    ServiceItem,
)


def _quarter(day: date) -> str:
    return f"{day.year}-Q{((day.month - 1) // 3) + 1}"


def _login(client, username: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": "pass1234"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['token']}"}


def _seed_baseline():
    with SessionLocal() as db:
        owner = OrgMember(name="平台运营测试负责人", employee_no="POPS-001", status="在岗")
        fdse = OrgMember(name="平台运营测试 FDSE", employee_no="POPS-002", status="在岗")
        cio = OrgMember(name="平台运营测试 CIO", employee_no="POPS-003", status="在岗")
        domain_a = BusinessDomain(code="platform-domain-a", name="平台测试业务域 A", active=True)
        domain_b = BusinessDomain(code="platform-domain-b", name="平台测试业务域 B", active=True)
        catalog = ServiceCatalog(code="platform-test-catalog", name="平台运营测试目录", status="上架")
        db.add_all([owner, fdse, cio, domain_a, domain_b, catalog])
        db.flush()
        item = ServiceItem(
            item_code="SI-PLATFORM-P0-001", name="统一开发平台", catalog_id=catalog.id,
            service_type="平台产品", owner=owner.id, status="上架",
        )
        req_a = Requirement(
            requirement_code="RQ-PLATFORM-P0-001", title="业务域 A 平台需求", req_type="功能",
            business_domain_id=domain_a.id, description="验证 FDSE 授权范围", status="registered",
            registered_at=datetime.now(),
        )
        req_b = Requirement(
            requirement_code="RQ-PLATFORM-P0-002", title="业务域 B 平台需求", req_type="功能",
            business_domain_id=domain_b.id, description="验证 FDSE 越权拒绝", status="registered",
            registered_at=datetime.now(),
        )
        db.add_all([item, req_a, req_b])
        db.flush()
        db.add(BusinessDomainMember(domain_id=domain_a.id, person_id=fdse.id))
        db.add_all([
            AuthUser(username="platform_fdse", password_hash=hash_password("pass1234"), person_id=fdse.id, roles=["it_bp"], is_active=True),
            AuthUser(username="platform_pdm", password_hash=hash_password("pass1234"), person_id=owner.id, roles=["it_pdm"], is_active=True),
            AuthUser(username="platform_cio", password_hash=hash_password("pass1234"), person_id=cio.id, roles=["cio"], is_active=True),
        ])
        db.commit()
        return {
            "owner_id": owner.id, "domain_a": domain_a.id, "domain_b": domain_b.id,
            "service_item_id": item.id, "requirement_a": req_a.id, "requirement_b": req_b.id,
        }


def test_platform_profiles_and_fdse_domain_scope(client, admin_headers):
    ids = _seed_baseline()
    enabled = client.post("/api/platform/services", headers=admin_headers, json={
        "service_item_id": ids["service_item_id"], "owner_id": ids["owner_id"],
        "lifecycle": "active", "value_proposition": "提供复用开发与交付能力",
        "management_scope": {"audience": "IT"},
    })
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["data"]["lifecycle"] == "active"
    invalid_recovery = client.patch(f"/api/platform/services/{ids['service_item_id']}", headers=admin_headers, json={
        "lifecycle": "candidate",
    })
    assert invalid_recovery.status_code == 422
    assert invalid_recovery.json()["error"]["code"] == "PLATFORM_LIFECYCLE_REASON_REQUIRED"
    recovered = client.patch(f"/api/platform/services/{ids['service_item_id']}", headers=admin_headers, json={
        "lifecycle": "candidate", "lifecycle_change_reason": "重新进入候选池进行产品重构",
    })
    assert recovered.status_code == 200
    assert client.patch(f"/api/platform/services/{ids['service_item_id']}", headers=admin_headers, json={"lifecycle": "pilot"}).status_code == 200
    assert client.patch(f"/api/platform/services/{ids['service_item_id']}", headers=admin_headers, json={"lifecycle": "active"}).status_code == 200

    fdse_headers = _login(client, "platform_fdse")
    denied_service = client.post("/api/platform/services", headers=fdse_headers, json={
        "service_item_id": ids["service_item_id"], "lifecycle": "candidate",
    })
    assert denied_service.status_code == 403

    accepted = client.post("/api/platform/demands", headers=fdse_headers, json={
        "requirement_id": ids["requirement_a"], "service_item_id": ids["service_item_id"],
        "business_domain_id": ids["domain_a"], "demand_class": "business",
        "expected_outcome": "缩短一线需求交付周期", "target_quarter": _quarter(date.today()),
        "capacity_class": "medium",
    })
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["requirement_id"] == ids["requirement_a"]

    denied = client.post("/api/platform/demands", headers=fdse_headers, json={
        "requirement_id": ids["requirement_b"], "service_item_id": ids["service_item_id"],
        "business_domain_id": ids["domain_b"], "demand_class": "technology",
        "expected_outcome": "不应跨域登记", "target_quarter": _quarter(date.today()),
        "capacity_class": "small",
    })
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "PLATFORM_DOMAIN_FORBIDDEN"

    listed = client.get("/api/platform/demands", headers=fdse_headers)
    assert listed.status_code == 200, listed.text
    assert [row["requirement_id"] for row in listed.json()["data"]] == [ids["requirement_a"]]
    with SessionLocal() as db:
        actions = {(row.entity_type, row.action) for row in db.query(AuditLog).filter(
            AuditLog.entity_type.in_(["platform_service_profile", "platform_demand_profile"])
        ).all()}
        assert ("platform_service_profile", "create") in actions
        assert ("platform_demand_profile", "create") in actions


def test_capacity_idempotency_lock_override_revision_and_metrics(client, admin_headers):
    with SessionLocal() as db:
        service_item_id = db.query(ServiceItem).filter(ServiceItem.item_code == "SI-PLATFORM-P0-001").one().id
        requirement_id = db.query(Requirement).filter(Requirement.requirement_code == "RQ-PLATFORM-P0-001").one().id
    period = _quarter(date.today())
    create_headers = {**admin_headers, "Idempotency-Key": "platform-plan-create-001"}
    body = {
        "service_item_id": service_item_id, "period": period, "gross_days": "12.00",
        "planned_unavailable_days": "1.00", "bau_reserve_days": "1.00",
        "risk_buffer_days": "0.00", "notes": "季度初始容量",
    }
    first = client.post("/api/platform/capacity-plans", headers=create_headers, json=body)
    replay = client.post("/api/platform/capacity-plans", headers=create_headers, json=body)
    assert first.status_code == 200 and replay.status_code == 200
    assert first.json()["data"]["id"] == replay.json()["data"]["id"]
    plan_id = first.json()["data"]["id"]
    conflict = client.post("/api/platform/capacity-plans", headers=create_headers, json={**body, "gross_days": "13.00"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    commitment = {
        "subject_type": "requirement", "subject_id": requirement_id,
        "title": "业务域 A 平台需求承诺", "commitment_type": "demand",
        "capacity_days": "8.00", "lifecycle_stage": "demand",
        "investment_intent": "grow", "status": "planned",
    }
    commit_headers = {**admin_headers, "Idempotency-Key": "platform-commitment-001"}
    added = client.post(f"/api/platform/capacity-plans/{plan_id}/commitments", headers=commit_headers, json=commitment)
    again = client.post(f"/api/platform/capacity-plans/{plan_id}/commitments", headers=commit_headers, json=commitment)
    assert added.status_code == 200 and again.status_code == 200
    assert added.json()["data"]["id"] == again.json()["data"]["id"]

    exceeded = client.post(f"/api/platform/capacity-plans/{plan_id}/commitments", headers={
        **admin_headers, "Idempotency-Key": "platform-commitment-002",
    }, json={**commitment, "subject_type": "roadmap", "subject_id": None,
             "title": "路线图工作", "commitment_type": "roadmap", "capacity_days": "4.00"})
    assert exceeded.status_code == 409
    assert exceeded.json()["error"]["code"] == "CAPACITY_EXCEEDED"

    pdm_headers = _login(client, "platform_pdm")
    pdm_override = client.post(f"/api/platform/capacity-plans/{plan_id}/commitments", headers={
        **pdm_headers, "Idempotency-Key": "platform-commitment-pdm-001",
    }, json={**commitment, "subject_type": "roadmap", "subject_id": None,
             "title": "越权例外", "commitment_type": "roadmap", "capacity_days": "4.00",
             "allow_overcommit": True, "over_capacity_reason": "业务优先级临时提升"})
    assert pdm_override.status_code == 403
    assert pdm_override.json()["error"]["code"] == "CAPACITY_OVERRIDE_FORBIDDEN"

    admin_override = client.post(f"/api/platform/capacity-plans/{plan_id}/commitments", headers={
        **admin_headers, "Idempotency-Key": "platform-commitment-admin-003",
    }, json={**commitment, "subject_type": "roadmap", "subject_id": None,
             "title": "管理员不替代 CIO", "commitment_type": "roadmap", "capacity_days": "4.00",
             "allow_overcommit": True, "over_capacity_reason": "重大业务窗口必须按期兑现"})
    assert admin_override.status_code == 403
    assert admin_override.json()["error"]["code"] == "CAPACITY_OVERRIDE_FORBIDDEN"

    cio_headers = _login(client, "platform_cio")
    cio_override = client.post(f"/api/platform/capacity-plans/{plan_id}/commitments", headers={
        **cio_headers, "Idempotency-Key": "platform-commitment-cio-004",
    }, json={**commitment, "subject_type": "roadmap", "subject_id": None,
             "title": "CIO 例外路线图", "commitment_type": "roadmap", "capacity_days": "4.00",
             "allow_overcommit": True, "over_capacity_reason": "重大业务窗口必须按期兑现"})
    assert cio_override.status_code == 200, cio_override.text
    assert cio_override.json()["data"]["over_capacity_approved_by"]

    submitted = client.post(f"/api/platform/capacity-plans/{plan_id}/submit", headers=admin_headers)
    assert submitted.status_code == 200 and submitted.json()["data"]["status"] == "review"
    locked = client.patch(f"/api/platform/capacity-plans/{plan_id}", headers=admin_headers, json={"notes": "不应改写"})
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "CAPACITY_PLAN_LOCKED"
    admin_approval = client.post(f"/api/platform/capacity-plans/{plan_id}/approve", headers=admin_headers, json={"reason": "管理员不替代业务审批人"})
    assert admin_approval.status_code == 403
    assert admin_approval.json()["error"]["code"] == "CAPACITY_APPROVAL_FORBIDDEN"
    approved = client.post(f"/api/platform/capacity-plans/{plan_id}/approve", headers=cio_headers, json={"reason": "季度容量基线确认"})
    assert approved.status_code == 200 and approved.json()["data"]["status"] == "approved"
    after_approval = client.post(f"/api/platform/capacity-plans/{plan_id}/commitments", headers={
        **admin_headers, "Idempotency-Key": "platform-commitment-locked-004",
    }, json={**commitment, "capacity_days": "1.00"})
    assert after_approval.status_code == 409

    revision_headers = {**admin_headers, "Idempotency-Key": "platform-plan-revision-001"}
    revision_body = {
        "service_item_id": service_item_id, "period": period, "gross_days": "16.00",
        "planned_unavailable_days": "1.00", "bau_reserve_days": "1.00",
        "risk_buffer_days": "0.00", "notes": "", "revision_reason": "扩大季度交付容量",
    }
    revision = client.post(f"/api/platform/capacity-plans/{plan_id}/revisions", headers=revision_headers, json=revision_body)
    revision_replay = client.post(f"/api/platform/capacity-plans/{plan_id}/revisions", headers=revision_headers, json=revision_body)
    assert revision.status_code == 200, revision.text
    assert revision_replay.status_code == 200, revision_replay.text
    assert revision.json()["data"]["id"] == revision_replay.json()["data"]["id"]
    assert revision.json()["data"]["version"] == 2
    assert len(revision.json()["data"]["commitments"]) == 2

    metrics = client.post("/api/reports/query", headers=admin_headers, json={
        "metric_codes": [
            "platform.active_service_count", "platform.owner_coverage_rate",
            "platform.demand_backlog_count", "platform.demand_commitment_rate",
            "platform.net_capacity_days", "platform.committed_capacity_days",
            "platform.capacity_utilization_rate",
        ],
        "period_start": str(date.today().replace(day=1)), "period_end": str(date.today()),
        "filters": {"service_item_id": service_item_id},
    })
    assert metrics.status_code == 200, metrics.text
    values = {row["code"]: row["value"] for row in metrics.json()["data"]["metrics"]}
    assert values["platform.active_service_count"] == 1
    assert values["platform.owner_coverage_rate"] == 100.0
    assert values["platform.demand_backlog_count"] == 1
    assert values["platform.demand_commitment_rate"] == 100.0
    assert values["platform.net_capacity_days"] == "10.00"
    assert values["platform.committed_capacity_days"] == "12.00"
    assert values["platform.capacity_utilization_rate"] == 120.0
    detail = client.get("/api/reports/drilldown/platform.net_capacity_days", headers=admin_headers, params={
        "period_start": str(date.today().replace(day=1)), "period_end": str(date.today()),
        "service_item_id": service_item_id,
    })
    assert detail.status_code == 200, detail.text
    assert any(row["id"] == plan_id for row in detail.json()["data"])
