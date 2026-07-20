"""M41：业务域从组织架构选择服务部门。"""

from app.db import SessionLocal
from app.models import Department, OrgMember


def _create_department(client, headers, code, name, dept_type="business", parent_id=None):
    response = client.post(
        "/api/admin/departments",
        json={"code": code, "name": name, "dept_type": dept_type, "parent_id": parent_id},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["id"]


def test_domain_departments_read_from_org_and_replace(client, admin_headers):
    parent = _create_department(client, admin_headers, "m41_fin", "财务中心")
    child = _create_department(client, admin_headers, "m41_ap", "应付部", parent_id=parent)
    it_dept = _create_department(client, admin_headers, "m41_it", "技术中心", dept_type="it")
    domain_response = client.post(
        "/api/admin/business-domains",
        json={"code": "m41_finance", "name": "财务服务域"},
        headers=admin_headers,
    )
    domain_id = domain_response.json()["data"]["id"]

    saved = client.put(
        f"/api/admin/business-domains/{domain_id}/departments",
        json={"department_ids": [parent, child, parent], "include_children": True},
        headers=admin_headers,
    )
    assert saved.status_code == 200
    assert saved.json()["data"] == {"id": domain_id, "count": 2, "include_children": True}

    rows = client.get("/api/admin/business-domains", headers=admin_headers).json()["data"]
    domain = next(row for row in rows if row["id"] == domain_id)
    assert {item["name"] for item in domain["departments"]} == {"财务中心", "应付部"}
    assert all(item["include_children"] for item in domain["departments"])
    assert next(item for item in domain["departments"] if item["id"] == child)["parent_id"] == parent

    replaced = client.put(
        f"/api/admin/business-domains/{domain_id}/departments",
        json={"department_ids": [child], "include_children": False},
        headers=admin_headers,
    )
    assert replaced.status_code == 200
    rows = client.get("/api/admin/business-domains", headers=admin_headers).json()["data"]
    domain = next(row for row in rows if row["id"] == domain_id)
    assert domain["departments"] == [{
        "id": child, "name": "应付部", "parent_id": parent,
        "active": True, "include_children": False,
    }]

    rejected = client.put(
        f"/api/admin/business-domains/{domain_id}/departments",
        json={"department_ids": [it_dept], "include_children": True},
        headers=admin_headers,
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "INVALID_DEPARTMENT"


def test_create_domain_with_departments_and_restrict_people_to_it_team(client, admin_headers):
    service_dept = _create_department(client, admin_headers, "m41_sales", "销售中心")
    with SessionLocal() as db:
        it_dept = Department(code="m41_digital", name="数字化团队", dept_type="it")
        other_dept = Department(code="m41_other", name="其他业务团队", dept_type="business")
        db.add_all([it_dept, other_dept]); db.flush()
        it_person = OrgMember(name="M41数字化负责人", department_id=it_dept.id)
        other_person = OrgMember(name="M41业务人员", department_id=other_dept.id)
        db.add_all([it_person, other_person]); db.commit()
        it_id, other_id = it_person.id, other_person.id

    created = client.post(
        "/api/admin/business-domains",
        json={
            "code": "m41_sales_domain", "name": "销售服务域", "owner_id": it_id,
            "department_ids": [service_dept], "include_children": True,
        },
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    domain_id = created.json()["data"]["id"]
    rows = client.get("/api/admin/business-domains", headers=admin_headers).json()["data"]
    domain = next(row for row in rows if row["id"] == domain_id)
    assert domain["owner_name"] == "M41数字化负责人"
    assert [item["id"] for item in domain["departments"]] == [service_dept]

    rejected_owner = client.post(
        "/api/admin/business-domains",
        json={"code": "m41_bad_owner", "name": "非法负责人域", "owner_id": other_id},
        headers=admin_headers,
    )
    assert rejected_owner.status_code == 400
    assert rejected_owner.json()["error"]["code"] == "NOT_IT_TEAM_MEMBER"

    rejected_team = client.put(
        f"/api/admin/business-domains/{domain_id}/members",
        json={"person_ids": [other_id]}, headers=admin_headers,
    )
    assert rejected_team.status_code == 400
    assert rejected_team.json()["error"]["code"] == "NOT_IT_TEAM_MEMBER"
