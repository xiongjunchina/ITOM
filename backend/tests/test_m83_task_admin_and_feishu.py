"""M83：任务管理补强、流程顺序与飞书业务用户自动开户。"""

from app.core.security import hash_password
from app.db import SessionLocal
from app.models import AuthUser, Department, OrgMember, PointEntry, Role
from app.services.points import current_period
from app.services.perf_bplus import _person_roles


def test_bug_reference_comes_from_cmdb_and_dashboard_exposes_tasks(client, admin_headers):
    with SessionLocal() as db:
        dept = Department(code="m83_cmdb_it", name="M83 CMDB IT", dept_type="it")
        owner = OrgMember(name="M83 CMDB负责人", department=dept)
        db.add_all([dept, owner])
        db.commit()
        owner_id = owner.id
    ci = client.post(
        "/api/cis",
        json={"name": "M83 供应链系统", "category": "app", "status": "运行中", "owner": owner_id, "product_manager_id": owner_id},
        headers=admin_headers,
    ).json()["data"]
    references = client.get("/api/task-management/reference/cis", headers=admin_headers)
    assert references.status_code == 200, references.text
    assert any(row["id"] == ci["id"] and row["name"] == "M83 供应链系统" for row in references.json()["data"])

    dashboard = client.get("/api/dashboard", headers=admin_headers)
    assert dashboard.status_code == 200, dashboard.text
    assert set(dashboard.json()["data"]["task"]) == {
        "open_total", "open_bugs", "open_bug_fix_tasks", "open_delegated_tasks",
        "open_requirement_tasks", "open_project_tasks",
    }


def test_process_definition_order_matches_left_menu(client, admin_headers):
    rows = client.get("/api/admin/process-definitions", headers=admin_headers).json()["data"]
    position = {code: index for index, code in enumerate(row["code"] for row in rows)}
    assert [position[code] for code in ["sr_flow", "change_flow", "incident_flow", "problem_flow", "project_flow", "requirement_flow", "bug_flow"]] == sorted(
        position[code] for code in ["sr_flow", "change_flow", "incident_flow", "problem_flow", "project_flow", "requirement_flow", "bug_flow"]
    )


def test_custom_system_role_uses_base_role_for_performance(client, admin_headers):
    with SessionLocal() as db:
        dept = Department(code="m83_role_it", name="M83 角色测试 IT", dept_type="it")
        member = OrgMember(name="M83 自定义角色人员", department=dept)
        role = Role(code="m83_dev_specialist", name="M83 开发专员", base_role="it_dev", is_builtin=False)
        db.add_all([dept, member, role])
        db.flush()
        db.add(AuthUser(
            username="m83_role_user",
            password_hash=hash_password("M83-password"),
            auth_source="local",
            person_id=member.id,
            roles=[role.code],
            is_active=True,
        ))
        db.commit()
        member_id = member.id

    with SessionLocal() as db:
        member = db.get(OrgMember, member_id)
        assert member is not None
        assert "it_dev" in _person_roles(db, member)


def test_feishu_business_member_is_auto_provisioned_but_it_member_stays_pending(client, admin_headers):
    with SessionLocal() as db:
        business = Department(code="m83_auto_business", name="M83 自动开户业务部", dept_type="business")
        it_dept = Department(code="m83_auto_it", name="M83 自动开户 IT 部", dept_type="it")
        business_member = OrgMember(
            name="M83 业务原名", email="m83.business@example.com",
            external_source="feishu", external_id="ou_m83_business", department=business,
        )
        it_member = OrgMember(
            name="M83 IT人员", email="m83.it@example.com",
            external_source="feishu", external_id="ou_m83_it", department=it_dept,
        )
        db.add_all([business, it_dept, business_member, it_member])
        db.commit()

    active = client.post("/api/auth/feishu/scan", json={
        "external_id": "ou_m83_business", "display_name": "M83 业务用户", "email": "m83.business@example.com",
    })
    assert active.status_code == 200, active.text
    active_data = active.json()["data"]
    assert active_data["status"] == "active"
    assert active_data["user"]["username"] == "m83.business"
    assert active_data["user"]["roles"] == ["requester"]

    with SessionLocal() as db:
        user = db.query(AuthUser).filter(AuthUser.username == "m83.business").one()
        assert user.external_id == "ou_m83_business"
        assert user.password_set_at is None
        assert user.initial_password_ciphertext

    pending = client.post("/api/auth/feishu/scan", json={
        "external_id": "ou_m83_it", "display_name": "M83 IT人员", "email": "m83.it@example.com",
    })
    assert pending.status_code == 200, pending.text
    assert pending.json()["data"]["status"] == "pending"


def test_points_leaderboard_includes_source_breakdown(client, admin_headers):
    with SessionLocal() as db:
        dept = Department(code="m83_points_it", name="M83 积分 IT", dept_type="it")
        member = OrgMember(name="M83 积分人员", department=dept)
        db.add_all([dept, member])
        db.flush()
        db.add_all([
            PointEntry(person_id=member.id, points=30, source_type="bug_fix_task_done", period=current_period()),
            PointEntry(person_id=member.id, points=20, source_type="delegated_work_done", period=current_period()),
        ])
        db.commit()

    response = client.get("/api/points/leaderboard", headers=admin_headers)
    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["data"]["board"] if item["person_name"] == "M83 积分人员")
    assert row["points"] == 50.0
    assert {item["source_type"]: item["points"] for item in row["breakdown"]} == {
        "bug_fix_task_done": 30.0, "delegated_work_done": 20.0,
    }
