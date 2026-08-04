"""M95：业务域以业务 BDO 代替历史备份负责人。"""

from app.db import SessionLocal
from app.models import BusinessDomain
from app.services.perf_bplus import _domain_scope


def _department(client, headers, code, name, *, parent_id=None, dept_type="business"):
    response = client.post(
        "/api/admin/departments",
        json={"code": code, "name": name, "parent_id": parent_id, "dept_type": dept_type},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["id"]


def _member(client, headers, name, department_id):
    response = client.post(
        "/api/members", json={"name": name, "department_id": department_id}, headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["id"]


def _user(client, headers, username, person_id, roles):
    response = client.post(
        "/api/admin/users",
        json={"username": username, "password": "pass123", "person_id": person_id, "roles": roles},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def test_business_domain_uses_scoped_bdo_and_preserves_legacy_backup_data(client, admin_headers):
    """BDO 必须在服务部门范围内；旧 backup_owner 不会被转义为 BDO 或人效范围。"""
    it_department = _department(client, admin_headers, "m95_it", "M95 数字化团队", dept_type="it")
    served_department = _department(client, admin_headers, "m95_fin", "M95 财务中心")
    served_child = _department(client, admin_headers, "m95_ap", "M95 应付部", parent_id=served_department)
    other_department = _department(client, admin_headers, "m95_sales", "M95 销售中心")
    bm_id = _member(client, admin_headers, "M95 IT BM", it_department)
    bdo_id = _member(client, admin_headers, "M95 应付 BDO", served_child)
    outside_bdo_id = _member(client, admin_headers, "M95 销售 BDO", other_department)
    non_bdo_id = _member(client, admin_headers, "M95 普通业务用户", served_child)
    _user(client, admin_headers, "m95_bdo", bdo_id, ["bdo"])
    _user(client, admin_headers, "m95_bdo_outside", outside_bdo_id, ["bdo"])
    _user(client, admin_headers, "m95_business", non_bdo_id, ["requester"])

    candidates = client.get("/api/admin/business-domains/bdo-candidates", headers=admin_headers)
    assert candidates.status_code == 200, candidates.text
    assert {row["id"] for row in candidates.json()["data"]} >= {bdo_id, outside_bdo_id}

    created = client.post(
        "/api/admin/business-domains",
        json={
            "code": "m95_finance", "name": "M95 财务服务域", "owner_id": bm_id,
            "business_bdo_id": bdo_id, "department_ids": [served_department], "include_children": True,
        },
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    domain_id = created.json()["data"]["id"]

    listed = client.get("/api/admin/business-domains", headers=admin_headers).json()["data"]
    domain = next(row for row in listed if row["id"] == domain_id)
    assert domain["business_bdo_id"] == bdo_id
    assert domain["business_bdo_name"] == "M95 应付 BDO"
    assert "backup_owner_id" not in domain

    outside = client.patch(
        f"/api/admin/business-domains/{domain_id}", json={"business_bdo_id": outside_bdo_id}, headers=admin_headers,
    )
    assert outside.status_code == 400
    assert outside.json()["error"]["code"] == "BDO_OUT_OF_SCOPE"

    non_bdo = client.patch(
        f"/api/admin/business-domains/{domain_id}", json={"business_bdo_id": non_bdo_id}, headers=admin_headers,
    )
    assert non_bdo.status_code == 400
    assert non_bdo.json()["error"]["code"] == "BDO_REQUIRED"

    # 模拟升级前遗留的 IT 备份负责人数据：它不自动变为 BDO，也不再进入 IT 人效域范围。
    with SessionLocal() as db:
        persisted = db.get(BusinessDomain, domain_id)
        persisted.backup_owner_id = bdo_id
        db.commit()
        scoped_domains, evaluators = _domain_scope(db, bdo_id)
    assert domain_id not in scoped_domains
    assert bm_id not in evaluators


def test_business_bdo_must_remain_valid_when_service_departments_change(client, admin_headers):
    """修改服务部门覆盖范围不能留下超出范围的 BDO。"""
    it_department = _department(client, admin_headers, "m95b_it", "M95B 数字化团队", dept_type="it")
    finance = _department(client, admin_headers, "m95b_fin", "M95B 财务中心")
    sales = _department(client, admin_headers, "m95b_sales", "M95B 销售中心")
    bm_id = _member(client, admin_headers, "M95B IT BM", it_department)
    bdo_id = _member(client, admin_headers, "M95B 财务 BDO", finance)
    _user(client, admin_headers, "m95b_bdo", bdo_id, ["bdo"])
    created = client.post(
        "/api/admin/business-domains",
        json={
            "code": "m95b_finance", "name": "M95B 财务服务域", "owner_id": bm_id,
            "business_bdo_id": bdo_id, "department_ids": [finance], "include_children": False,
        },
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    domain_id = created.json()["data"]["id"]

    changed = client.put(
        f"/api/admin/business-domains/{domain_id}/departments",
        json={"department_ids": [sales], "include_children": False},
        headers=admin_headers,
    )
    assert changed.status_code == 400
    assert changed.json()["error"]["code"] == "BDO_OUT_OF_SCOPE"


def test_requirement_acceptance_is_assigned_to_business_bdo(client, admin_headers):
    """需求评审仍是 IT BM，交付后的业务验收改由该域 BDO 承接。"""
    it_department = _department(client, admin_headers, "m95c_it", "M95C 数字化团队", dept_type="it")
    business_department = _department(client, admin_headers, "m95c_biz", "M95C 业务中心")
    bm_id = _member(client, admin_headers, "M95C IT BM", it_department)
    developer_id = _member(client, admin_headers, "M95C 开发人员", it_department)
    bdo_id = _member(client, admin_headers, "M95C 业务 BDO", business_department)
    _user(client, admin_headers, "m95c_bdo", bdo_id, ["bdo"])
    domain = client.post(
        "/api/admin/business-domains",
        json={
            "code": "m95c_domain", "name": "M95C 业务域", "owner_id": bm_id,
            "business_bdo_id": bdo_id, "department_ids": [business_department], "include_children": True,
        },
        headers=admin_headers,
    )
    assert domain.status_code == 200, domain.text
    domain_id = domain.json()["data"]["id"]
    requirement = client.post(
        "/api/requirements",
        json={"title": "M95C BDO 验收指派", "req_type": "功能", "business_domain_id": domain_id, "description": "d"},
        headers=admin_headers,
    )
    assert requirement.status_code == 200, requirement.text
    requirement_id = requirement.json()["data"]["id"]
    registered = client.get(f"/api/requirements/{requirement_id}", headers=admin_headers).json()["data"]
    assert registered["process"]["steps"][0]["assignee_name"] == "M95C IT BM"

    approved = client.post(
        f"/api/requirements/{requirement_id}/score",
        json={
            "d1_strategy": 5, "d2_value": 4, "d3_tech": 4,
            "d4_org": 4, "d5_risk": 2, "d6_speed": 4, "decision": "通过",
        },
        headers=admin_headers,
    )
    assert approved.status_code == 200, approved.text
    configured = client.patch(
        f"/api/requirements/{requirement_id}", json={"solution_type": "二次开发", "dev_effort": 8}, headers=admin_headers,
    )
    assert configured.status_code == 200, configured.text
    moved = client.post(
        f"/api/requirements/{requirement_id}/to-dev", json={"owner_id": developer_id}, headers=admin_headers,
    )
    assert moved.status_code == 200, moved.text
    detail = client.get(f"/api/requirements/{requirement_id}", headers=admin_headers).json()["data"]
    delivery = next(step for step in detail["process"]["steps"] if "实现交付" in step["name"])
    assert delivery["assignee_name"] == "M95C 开发人员"

    completed = client.post(
        f"/api/process-tasks/{delivery['task_id']}/complete", json={"comment": "开发已交付"}, headers=admin_headers,
    )
    assert completed.status_code == 200, completed.text
    detail = client.get(f"/api/requirements/{requirement_id}", headers=admin_headers).json()["data"]
    acceptance = next(step for step in detail["process"]["steps"] if "验收" in step["name"])
    assert detail["process"]["current_step_seq"] == acceptance["seq"]
    assert acceptance["assignee_name"] == "M95C 业务 BDO"
