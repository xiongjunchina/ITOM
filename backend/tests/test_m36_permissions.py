"""M3.6：权限矩阵/角色改名/模板复制/矩阵组织（域团队+组负责人）。"""
import pytest


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    def member_and_user(name, username, roles):
        m = client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]
        client.post(
            "/api/admin/users",
            json={"username": username, "password": "pass123", "roles": roles, "person_id": m["id"]},
            headers=admin_headers,
        )
        token = client.post("/api/auth/login", json={"username": username, "password": "pass123"}).json()["data"]["token"]
        return m["id"], {"Authorization": f"Bearer {token}"}

    return {"member_and_user": member_and_user}


def test_login_returns_permissions(client, admin_headers, ctx):
    _, h = ctx["member_and_user"]("开发甲", "dev_a", ["it_dev"])
    me = client.get("/api/auth/me", headers=h).json()["data"]
    assert "permissions" in me
    assert "view" in me["permissions"]["ticket_sr"] and "create" in me["permissions"]["ticket_sr"]
    assert "cmdb" in me["permissions"] and me["permissions"]["cmdb"] == ["view"]

    admin_me = client.get("/api/auth/me", headers=admin_headers).json()["data"]
    assert admin_me["permissions"] == {"*": ["view", "create", "edit", "delete"]}


def test_matrix_edit_changes_access(client, admin_headers, ctx):
    """把 it_dev 的 vendors 权限从 view 提到 create，再撤销——矩阵实时生效。"""
    _, h = ctx["member_and_user"]("开发乙", "dev_b", ["it_dev"])
    r = client.post("/api/vendors", json={"name": "矩阵测试供应商"}, headers=h)
    assert r.status_code == 403  # 默认 it_dev 无 vendors.create

    rows = client.get("/api/admin/permissions?role=it_dev", headers=admin_headers).json()["data"]
    entries = [{"module": x["module"], "actions": x["actions"]} for x in rows]
    for e in entries:
        if e["module"] == "vendors":
            e["actions"] = ["view", "create"]
    client.put("/api/admin/permissions", json={"role_code": "it_dev", "entries": entries}, headers=admin_headers)

    r = client.post("/api/vendors", json={"name": "矩阵测试供应商"}, headers=h)
    assert r.json()["success"], r.text

    # admin 矩阵不可配
    r = client.put("/api/admin/permissions", json={"role_code": "admin", "entries": []}, headers=admin_headers)
    assert r.json()["error"]["code"] == "ADMIN_LOCKED"


def test_dashboard_sections_trimmed_by_permission(client, admin_headers, ctx):
    """M22：总览聚合按权限裁剪——requester 只见服务请求块与需求段，无项目/团队。"""
    _, h = ctx["member_and_user"]("业务丁", "req_d", ["requester"])
    d = client.get("/api/dashboard", headers=h).json()["data"]
    assert set(d["service"]["itsm_blocks"].keys()) == {"service_request"}
    assert "requirement" in d and "project" not in d and "team" not in d
    assert all(a["type"] == "sla_warning" for a in d["alerts"])  # 合同/项目告警不下发

    da = client.get("/api/dashboard", headers=admin_headers).json()["data"]
    assert set(da["service"]["itsm_blocks"].keys()) == {"service_request", "change", "incident", "problem"}
    assert "project" in da and "team" in da and "requirement" in da


def test_dashboard_gated_by_matrix(client, admin_headers, ctx):
    """M19：关掉角色的总览可见后，/api/dashboard 接口层 403（不只菜单隐藏）。"""
    _, h = ctx["member_and_user"]("业务丙", "req_c", ["requester"])
    assert client.get("/api/dashboard", headers=h).json()["success"]

    rows = client.get("/api/admin/permissions?role=requester", headers=admin_headers).json()["data"]
    entries = [{"module": x["module"], "actions": [] if x["module"] == "dashboard" else x["actions"]} for x in rows]
    client.put("/api/admin/permissions", json={"role_code": "requester", "entries": entries}, headers=admin_headers)
    assert client.get("/api/dashboard", headers=h).status_code == 403

    # 还原，避免影响同模块其他用例
    for e in entries:
        if e["module"] == "dashboard":
            e["actions"] = ["view"]
    client.put("/api/admin/permissions", json={"role_code": "requester", "entries": entries}, headers=admin_headers)


def test_new_matrix_roles_seeded(client, admin_headers):
    roles = {r["code"]: r for r in client.get("/api/admin/roles", headers=admin_headers).json()["data"]}
    assert {"cio", "it_bm", "it_tm"} <= set(roles)
    perms = client.get("/api/admin/permissions?role=cio", headers=admin_headers).json()["data"]
    cio_modules = {p["module"]: p["actions"] for p in perms}
    assert "edit" in cio_modules["projects"] and "view" in cio_modules["performance"]


def test_custom_role_copies_template_matrix(client, admin_headers, ctx):
    client.post(
        "/api/admin/roles",
        json={"code": "ai_eng", "name": "AI工程师", "base_role": "it_dev", "description": "AI 专业线"},
        headers=admin_headers,
    )
    perms = client.get("/api/admin/permissions?role=ai_eng", headers=admin_headers).json()["data"]
    assert perms, "模板矩阵应被复制"
    modules = {p["module"]: p["actions"] for p in perms}
    assert "create" in modules["ticket_sr"]

    # 复制后独立：改 ai_eng 不影响 it_dev
    entries = [{"module": m, "actions": a} for m, a in modules.items() if m != "knowledge"]
    client.put("/api/admin/permissions", json={"role_code": "ai_eng", "entries": entries}, headers=admin_headers)
    _, h = ctx["member_and_user"]("AI小哥", "ai01", ["ai_eng"])
    r = client.post("/api/knowledge", json={"title": "AI 知识", "content": "x"}, headers=h)
    assert r.status_code == 403
    it_dev_perms = {p["module"] for p in client.get("/api/admin/permissions?role=it_dev", headers=admin_headers).json()["data"]}
    assert "knowledge" in it_dev_perms


def test_domain_members_and_group_owner(client, admin_headers, ctx):
    bm, _ = ctx["member_and_user"]("业务线负责人", "bm01", ["it_bm"])
    bp, _ = ctx["member_and_user"]("BP小姐", "bp02", ["it_bp"])
    dev, _ = ctx["member_and_user"]("随队开发", "dev_c", ["it_dev"])

    # 业务域：BM 负责人 + 服务团队成员
    d = client.post(
        "/api/admin/business-domains",
        json={"code": "hr_line", "name": "人力业务线", "owner_id": bm},
        headers=admin_headers,
    ).json()["data"]
    r = client.put(f"/api/admin/business-domains/{d['id']}/members", json={"person_ids": [bp, dev]}, headers=admin_headers)
    assert r.json()["data"]["count"] == 2
    domains = client.get("/api/admin/business-domains", headers=admin_headers).json()["data"]
    row = next(x for x in domains if x["code"] == "hr_line")
    assert row["owner_name"] == "业务线负责人"
    assert {m["name"] for m in row["members"]} == {"BP小姐", "随队开发"}

    # 用户组（专业线资源池）：负责人 TM + 授予角色
    tm, _ = ctx["member_and_user"]("开发TM", "tm01", ["it_tm"])
    g = client.post(
        "/api/admin/groups",
        json={"code": "dev_pool", "name": "开发资源池", "roles": ["it_dev"], "owner_id": tm},
        headers=admin_headers,
    ).json()["data"]
    assert g["owner_name"] == "开发TM" and g["roles"] == ["it_dev"]


def test_member_row_no_groups_field(client, admin_headers, ctx):
    """①人员主数据与用户组解耦：行数据不再返回 groups。"""
    rows = client.get("/api/members", headers=admin_headers).json()["data"]
    assert rows and "groups" not in rows[0]


def test_process_step_cc_notify(client, admin_headers, ctx):
    """知会人：仅收通知不产生任务、不阻塞流程；校验非法知会键被拒。"""
    cio_p, cio_h = ctx["member_and_user"]("知会CIO", "cc_cio", ["cio"])
    ops_p, ops_h = ctx["member_and_user"]("知会运维", "cc_ops", ["it_ops"])

    # 非法知会键
    r = client.post(
        "/api/admin/process-definitions",
        json={"code": "cc_bad", "name": "x", "entity_type": "ticket",
              "steps": [{"seq": 1, "name": "a", "cc_roles": ["ghost_role"]}]},
        headers=admin_headers,
    )
    assert r.json()["error"]["code"] == "INVALID_STEPS"

    # 停用 incident_flow, 建带知会的流程
    defs = client.get("/api/admin/process-definitions", headers=admin_headers).json()["data"]
    inc = next(d for d in defs if d["code"] == "incident_flow")
    client.patch(f"/api/admin/process-definitions/{inc['id']}", json={"active": False}, headers=admin_headers)
    r = client.post(
        "/api/admin/process-definitions",
        json={"code": "cc_flow", "name": "知会测试流程", "entity_type": "ticket",
              "trigger_condition": {"ticket_type": "incident"},
              "steps": [{"seq": 1, "name": "处理", "default_role": "it_ops", "cc_roles": ["cio"], "autonomy_level": "L3"}]},
        headers=admin_headers,
    )
    assert r.json()["success"], r.text

    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    t = client.post(
        "/api/tickets",
        json={"title": "知会验证", "ticket_type": "incident", "priority": "P3",
              "description": "d", "service_item_id": item},
        headers=ops_h,
    ).json()["data"]

    detail = client.get(f"/api/tickets/{t['id']}", headers=ops_h).json()["data"]
    step = detail["process"]["steps"][0]
    assert step["cc_roles"] == ["cio"]
    assert step["task_status"] == "待处理"  # 任务只给处理人

    # CIO 收到知会通知；且流程不因知会阻塞（处理人可直接完成步骤）
    notif = client.get("/api/notifications", headers=cio_h).json()["data"]
    assert any("流程知会" in n["title"] for n in notif)
    r = client.post(f"/api/process-tasks/{step['task_id']}/complete", json={"comment": "done"}, headers=ops_h)
    assert r.json()["data"]["status"] == "已完成"
