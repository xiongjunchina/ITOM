"""M25：流程驱动单据的状态操作权跟随流程当前处理人。

用户实测：钟俊歌（IT运维）创建事件单，第 1 步「受理定级」指派 IT运维负责人，
但发起人页面上仍有「处理中/已解决」按钮——状态按钮只查模块权限、不看流程走到谁手里。
统一规则：有活跃流程时，状态流转/一键关单仅当前节点处理人或 admin；无活跃流程回退模块权限。
"""
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

    ops_pid, ops_h = member_and_user("运维发起人M25", "m25_ops", ["it_ops"])
    leader_pid, leader_h = member_and_user("运维负责人M25", "m25_leader", ["it_op_leader"])
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    return {"admin": admin_headers, "ops_pid": ops_pid, "ops_h": ops_h,
            "leader_pid": leader_pid, "leader_h": leader_h, "item": item}


def _incident(client, ctx, title):
    """事件单：把首步任务改派给运维负责人，模拟用户的流程配置（受理定级=IT运维负责人）。"""
    t = client.post("/api/tickets", json={
        "title": title, "ticket_type": "incident", "priority": "P2",
        "description": "IDC 海外出口线路断网", "service_item_id": ctx["item"],
    }, headers=ctx["ops_h"]).json()["data"]
    proc = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]["process"]
    cur = next(s for s in proc["steps"] if s["seq"] == proc["current_step_seq"])
    client.post(f"/api/process-tasks/{cur['task_id']}/reassign",
                json={"assignee": ctx["leader_pid"]}, headers=ctx["admin"])
    return t


def test_initiator_has_no_transition_buttons_or_api(client, ctx):
    """发起人（IT运维，有模块 edit 权限）：节点在负责人手里 → 无按钮、接口 403。"""
    t = _incident(client, ctx, "断网-发起人无权流转")
    d = client.get(f"/api/tickets/{t['id']}", headers=ctx["ops_h"]).json()["data"]
    assert d["allowed_transitions"] == []  # 按钮不下发
    assert d["flow_operator_name"] == "运维负责人M25"

    r = client.post(f"/api/tickets/{t['id']}/transition", json={"to": "processing", "fields": {}}, headers=ctx["ops_h"])
    assert r.status_code == 403  # M31：手动流转收敛，提示走流程步骤
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "发起人试图关单"}, headers=ctx["ops_h"])
    assert r.status_code == 403


def test_current_operator_and_admin_can_transition(client, ctx):
    """M31：处理人通过完成步骤推进（状态自动同步 processing）；admin 手动流转恒可。"""
    t = _incident(client, ctx, "断网-处理人步骤推进")
    d = client.get(f"/api/tickets/{t['id']}", headers=ctx["leader_h"]).json()["data"]
    assert all(x["to"] != "processing" for x in d["allowed_transitions"])  # 手动流转按钮已收敛
    proc = d["process"]
    cur = next(s for s in proc["steps"] if s["seq"] == proc["current_step_seq"])
    r = client.post(f"/api/process-tasks/{cur['task_id']}/complete", json={"comment": "受理定级完成"}, headers=ctx["leader_h"])
    assert r.json()["success"], r.text
    d = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]
    assert d["status"] == "processing"  # 编排自动同步（首响 SLA 打点）

    t2 = _incident(client, ctx, "断网-admin恒可")
    r = client.post(f"/api/tickets/{t2['id']}/transition", json={"to": "processing", "fields": {}}, headers=ctx["admin"])
    assert r.json()["success"], r.text


def test_flow_finished_falls_back_to_module_perm(client, ctx):
    """流程走完后（无活跃节点）：回退模块 edit 权限——运维可做状态修正。"""
    t = _incident(client, ctx, "断网-流程完成后修正")
    # admin 走完全部流程步骤（完成时 M23 自动闭环 → closed）
    while True:
        proc = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]["process"]
        if proc["status"] == "completed":
            break
        cur = next(s for s in proc["steps"] if s["seq"] == proc["current_step_seq"])
        client.post(f"/api/process-tasks/{cur['task_id']}/complete", json={"comment": "完成节点"}, headers=ctx["admin"])
    d = client.get(f"/api/tickets/{t['id']}", headers=ctx["ops_h"]).json()["data"]
    assert d["status"] == "closed"
    # 终态修正口子归 admin（M31：非 admin 手动流转统一收敛为 USE_PROCESS_STEP）
    r = client.post(f"/api/tickets/{t['id']}/transition", json={"to": "processing", "fields": {}}, headers=ctx["ops_h"])
    assert r.json().get("error", {}).get("code") in ("USE_PROCESS_STEP", "INVALID_TRANSITION")


def test_problem_transition_follows_flow_operator(client, ctx):
    """问题单同规则：流程节点在他人手里 → 非处理人 403、无按钮。"""
    p = client.post("/api/problems", json={"title": "M25问题操作权", "description": "d", "priority": "P3",
                                           "service_item_id": ctx["item"]}, headers=ctx["admin"]).json()["data"]
    proc = client.get(f"/api/problems/{p['id']}", headers=ctx["admin"]).json()["data"]["process"]
    cur = next(s for s in proc["steps"] if s["seq"] == proc["current_step_seq"])
    client.post(f"/api/process-tasks/{cur['task_id']}/reassign",
                json={"assignee": ctx["leader_pid"]}, headers=ctx["admin"])

    d = client.get(f"/api/problems/{p['id']}", headers=ctx["ops_h"]).json()["data"]
    assert d["allowed_transitions"] == []
    r = client.post(f"/api/problems/{p['id']}/transition", json={"to": "analyzing", "fields": {}}, headers=ctx["ops_h"])
    assert r.status_code == 403
    # M31：问题状态全由编排同步，处理人手动 analyzing 也收敛（仅 admin 修数据）
    r = client.post(f"/api/problems/{p['id']}/transition", json={"to": "analyzing", "fields": {}}, headers=ctx["leader_h"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "USE_PROCESS_STEP"
    r = client.post(f"/api/problems/{p['id']}/transition", json={"to": "analyzing", "fields": {}}, headers=ctx["admin"])
    assert r.json()["success"], r.text


def test_unassigned_task_claimable_by_default_role(client, ctx):
    """未指派任务（角色无在岗用户）：默认角色持有者可认领操作，不会卡死等 admin。

    用户实测：TK-202607-0003 受理定级 default_role=IT运维负责人但库里无该角色用户 → 任务空指派。
    """
    # M33 变更流程五步：第 2 步「风险评估」default_role=is_mgr，本测试库尚无 is_mgr 用户 → 任务未指派
    t = client.post("/api/tickets", json={
        "title": "M25未指派认领", "ticket_type": "change", "priority": "P3",
        "description": "d", "service_item_id": ctx["item"],
        "change_type": "标准", "risk_level": "低",
    }, headers=ctx["admin"]).json()["data"]
    proc = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]["process"]
    cur = next(s for s in proc["steps"] if s["seq"] == proc["current_step_seq"])
    client.post(f"/api/process-tasks/{cur['task_id']}/complete", json={"comment": "变更登记完成"}, headers=ctx["admin"])
    proc = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]["process"]
    cur = next(s for s in proc["steps"] if s["seq"] == proc["current_step_seq"])
    assert cur["name"] == "风险评估" and cur["assignee"] is None

    # 非该角色（运维）不能完成
    r = client.post(f"/api/process-tasks/{cur['task_id']}/complete", json={"comment": "越权认领"}, headers=ctx["ops_h"])
    assert r.status_code == 403
    # 建 is_mgr 用户 → 可认领完成 + 有状态按钮
    m = client.post("/api/members", json={"name": "安全M25"}, headers=ctx["admin"]).json()["data"]
    client.post("/api/admin/users", json={"username": "m25_ismgr", "password": "pass123",
                                          "roles": ["is_mgr"], "person_id": m["id"]}, headers=ctx["admin"])
    tk = client.post("/api/auth/login", json={"username": "m25_ismgr", "password": "pass123"}).json()["data"]["token"]
    mgr_h = {"Authorization": f"Bearer {tk}"}
    d = client.get(f"/api/tickets/{t['id']}", headers=mgr_h).json()["data"]
    assert d["allowed_transitions"], "默认角色持有者应有状态按钮"
    r = client.post(f"/api/process-tasks/{cur['task_id']}/complete", json={"comment": "风险评估完成"}, headers=mgr_h)
    assert r.json()["success"], r.text


def test_requirement_transition_follows_flow_operator(client, ctx):
    """需求单同规则：评审节点在业务域负责人手里 → 其他人手动流转 403。"""
    domain = client.get("/api/admin/business-domains", headers=ctx["admin"]).json()["data"][0]["id"]
    r = client.post("/api/requirements", json={"title": "M25需求操作权", "req_type": "功能",
                                               "business_domain_id": domain, "description": "d"},
                    headers=ctx["admin"]).json()["data"]
    proc = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]["process"]
    cur = next(s for s in proc["steps"] if s["seq"] == proc["current_step_seq"])
    client.post(f"/api/process-tasks/{cur['task_id']}/reassign",
                json={"assignee": ctx["leader_pid"]}, headers=ctx["admin"])

    # ops 用户虽有 requirements.edit（staff 矩阵），但节点不在他手里
    resp = client.post(f"/api/requirements/{r['id']}/transition",
                       json={"to": "evaluating", "fields": {}}, headers=ctx["ops_h"])
    assert resp.status_code == 403
