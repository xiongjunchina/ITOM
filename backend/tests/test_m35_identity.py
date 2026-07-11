"""M3.5：部门/业务域/开通规则/组带角色/auditor 只读/JIT 开通。"""
import pytest


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    """建部门：IT部(it)/财务部(business)/审计部(audit)。"""
    depts = {}
    for code, name, dtype in (("it", "IT部", "it"), ("fin", "财务部", "business"), ("audit", "审计部", "audit")):
        r = client.post(
            "/api/admin/departments",
            json={"code": code, "name": name, "dept_type": dtype},
            headers=admin_headers,
        )
        depts[code] = r.json()["data"]["id"]

    def member_and_user(name, username, dept_code, roles=None):
        m = client.post(
            "/api/members",
            json={"name": name, "department_id": depts[dept_code]},
            headers=admin_headers,
        ).json()["data"]
        payload = {"username": username, "password": "pass123", "person_id": m["id"]}
        if roles is not None:
            payload["roles"] = roles
        client.post("/api/admin/users", json=payload, headers=admin_headers)
        token = client.post("/api/auth/login", json={"username": username, "password": "pass123"}).json()["data"]["token"]
        return m["id"], {"Authorization": f"Bearer {token}"}

    return {"depts": depts, "member_and_user": member_and_user}


def test_department_crud_and_protection(client, admin_headers, ctx):
    r = client.get("/api/admin/departments", headers=admin_headers).json()
    assert r["total"] >= 3
    # 有人员归属的部门不可删
    ctx["member_and_user"]("占位员工", "hold01", "fin")
    fin_id = ctx["depts"]["fin"]
    resp = client.delete(f"/api/admin/departments/{fin_id}", headers=admin_headers)
    assert resp.json()["error"]["code"] == "DEPT_IN_USE"


def test_provision_default_roles_business_dept(client, admin_headers, ctx):
    """财务部员工建账号不指定角色 → 按规则默认 requester；审计部同样默认 requester（不自动 auditor）。"""
    _, fin_headers = ctx["member_and_user"]("财务小王", "fin01", "fin")
    me = client.get("/api/auth/me", headers=fin_headers).json()["data"]
    assert me["roles"] == ["requester"]

    _, audit_headers = ctx["member_and_user"]("审计小李", "aud01", "audit")
    me = client.get("/api/auth/me", headers=audit_headers).json()["data"]
    assert me["roles"] == ["requester"]  # auditor 需手工授予，绝不自动


def test_explicit_roles_never_overridden(client, admin_headers, ctx):
    """显式指定多角色时规则不干预——用户永远可多角色。"""
    _, h = ctx["member_and_user"]("多面手", "multi01", "it", roles=["it_dev", "it_ops", "manager"])
    me = client.get("/api/auth/me", headers=h).json()["data"]
    assert set(me["roles"]) >= {"it_dev", "it_ops", "manager"}


def test_group_grants_roles(client, admin_headers, ctx):
    """组带角色：人进组自动获得组授予的角色（ServiceNow 式）。"""
    person, h = ctx["member_and_user"]("新运维", "newops01", "it")  # 默认仅 requester
    me = client.get("/api/auth/me", headers=h).json()["data"]
    assert me["roles"] == ["requester"]

    g = client.post(
        "/api/admin/groups",
        json={"code": "ops_team", "name": "运维组", "roles": ["it_ops"]},
        headers=admin_headers,
    ).json()["data"]
    assert g["roles"] == ["it_ops"]
    client.put(f"/api/admin/groups/{g['id']}/members", json={"person_ids": [person]}, headers=admin_headers)

    me = client.get("/api/auth/me", headers=h).json()["data"]
    assert set(me["roles"]) == {"requester", "it_ops"}
    assert me["direct_roles"] == ["requester"]  # 直接角色未变，it_ops 来自组

    # 组授予的 it_ops 实际生效：可以维护供应商（require_roles(IT_OPS, MANAGER)）
    resp = client.post("/api/vendors", json={"name": "组授权测试供应商"}, headers=h)
    assert resp.json()["success"], resp.text

    # admin 不允许经组授予
    resp = client.patch(f"/api/admin/groups/{g['id']}", json={"roles": ["admin"]}, headers=admin_headers)
    assert resp.json()["error"]["code"] == "INVALID_ROLE"


def test_auditor_readonly(client, admin_headers, ctx):
    person, h = ctx["member_and_user"]("IT审计员", "auditor01", "audit", roles=["auditor"])
    # 可读：工单全局列表 / 审计日志
    assert client.get("/api/tickets", headers=h).status_code == 200
    assert client.get("/api/admin/audit-logs", headers=h).status_code == 200
    # 不可写：建工单 / 建知识 都被只读中间件拦截
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    resp = client.post(
        "/api/tickets",
        json={"title": "审计员试图建单", "ticket_type": "incident", "priority": "P3",
              "description": "x", "service_item_id": item},
        headers=h,
    )
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "READ_ONLY"
    # auditor + 其他角色则不受限（多角色不绑死）
    users = client.get("/api/admin/users?q=auditor01", headers=admin_headers).json()["data"]
    client.patch(f"/api/admin/users/{users[0]['id']}", json={"roles": ["auditor", "it_ops"]}, headers=admin_headers)
    resp = client.post(
        "/api/tickets",
        json={"title": "审计员兼运维建单", "ticket_type": "incident", "priority": "P3",
              "description": "x", "service_item_id": item},
        headers=h,
    )
    assert resp.json()["success"], resp.text


def test_business_domain_owner(client, admin_headers, ctx):
    person, _ = ctx["member_and_user"]("业务线BP", "bp01", "it", roles=["it_bp"])
    r = client.post(
        "/api/admin/business-domains",
        json={"code": "retail", "name": "零售业务线", "owner_id": person, "description": "门店与电商"},
        headers=admin_headers,
    )
    assert r.json()["success"], r.text
    domains = client.get("/api/admin/business-domains", headers=admin_headers).json()["data"]
    row = next(d for d in domains if d["code"] == "retail")
    assert row["owner_name"] == "业务线BP"  # 负责人是字段不是角色


def test_provision_rules_editable(client, admin_headers, ctx):
    """开通规则可配置：把审计部（精确部门规则）默认角色改为 requester+auditor 也是允许的——规则只影响首次开通。"""
    rules = client.get("/api/admin/provision-rules", headers=admin_headers).json()["data"]
    new_rules = [
        {"match_type": r["match_type"], "match_value": r["match_value"],
         "default_roles": r["default_roles"], "sort": r["sort"], "active": r["active"]}
        for r in rules
    ]
    new_rules.append({"match_type": "department", "match_value": ctx["depts"]["audit"],
                      "default_roles": ["requester", "auditor"], "sort": 1, "active": True})
    r = client.put("/api/admin/provision-rules", json=new_rules, headers=admin_headers)
    assert r.json()["success"], r.text

    _, h = ctx["member_and_user"]("审计新人", "aud02", "audit")
    me = client.get("/api/auth/me", headers=h).json()["data"]
    assert set(me["roles"]) == {"requester", "auditor"}

    # 非法角色被拒
    bad = new_rules + [{"match_type": "dept_type", "match_value": "it", "default_roles": ["ghost"], "sort": 99, "active": True}]
    r = client.put("/api/admin/provision-rules", json=bad, headers=admin_headers)
    assert r.json()["error"]["code"] == "INVALID_RULE"


def test_jit_provision_service(client, admin_headers, ctx):
    """JIT 开通：模拟外部认证源画像 → 自动建账号+档案+默认角色；二次开通不重复建、不动角色。"""
    from app.db import SessionLocal
    from app.models import Department
    from app.services.provisioning import ProvisionProfile, provision_user

    with SessionLocal() as db:
        dept = db.get(Department, ctx["depts"]["fin"])
        dept.external_source = "feishu"
        dept.external_id = "od-finance"
        db.commit()

        profile = ProvisionProfile(
            username="feishu_zhang", name="张飞书", name_en="Zhang Feishu",
            email="zf@corp.com", mobile="13800000000",
            department_external_id="od-finance", external_id="ou_abc123",
        )
        user = provision_user(db, "feishu", profile)
        db.commit()
        assert user.auth_source == "feishu" and user.roles == ["requester"]
        assert user.person.department_id == ctx["depts"]["fin"]
        assert user.person.name_en == "Zhang Feishu"

        # 二次登录：同 external_id 不重复建档，改名同步，角色不被规则覆盖
        user.roles = ["requester", "it_bp"]
        db.commit()
        profile.name = "张飞书改名"
        user2 = provision_user(db, "feishu", profile)
        db.commit()
        assert user2.id == user.id
        assert user2.person.name == "张飞书改名"
        assert set(user2.roles) == {"requester", "it_bp"}  # 角色未被重置
