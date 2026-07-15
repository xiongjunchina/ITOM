"""M27：进行中的事件/变更单强制关闭白名单——仅 admin/IT运维负责人/信息安全负责人/CIO。

用户实测：事件在「关闭复盘」节点，登记人（IT运维）在清单页仍见关闭入口。
新规则：流程进行中的事件/变更 = 强制关闭（管理动作）；登记人/普通处理人走流程步骤。
服务请求维持 M25 规则（流程当前处理人或 admin）。
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

    ops_pid, ops_h = member_and_user("运维登记人M27", "m27_ops", ["it_ops"])
    _, leader_h = member_and_user("运维负责人M27", "m27_leader", ["it_op_leader"])
    _, ismgr_h = member_and_user("信安M27", "m27_ismgr", ["is_mgr"])
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    return {"admin": admin_headers, "ops_pid": ops_pid, "ops_h": ops_h,
            "leader_h": leader_h, "ismgr_h": ismgr_h, "item": item}


def _incident(client, ctx, title):
    return client.post("/api/tickets", json={
        "title": title, "ticket_type": "incident", "priority": "P3",
        "description": "d", "service_item_id": ctx["item"],
    }, headers=ctx["ops_h"]).json()["data"]


def test_in_progress_incident_force_close_whitelist(client, ctx):
    """登记人（it_ops）403；即使是当前节点处理人（it_ops）也 403；负责人/信安/admin 放行。"""
    t = _incident(client, ctx, "M27-登记人不可强关")
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "登记人试图强关"}, headers=ctx["ops_h"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORCE_CLOSE_FORBIDDEN"

    # 把当前节点任务改派给登记人本人 → 仍不能强关（处理人应走流程步骤，不是强关）
    proc = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]["process"]
    cur = next(s for s in proc["steps"] if s["seq"] == proc["current_step_seq"])
    client.post(f"/api/process-tasks/{cur['task_id']}/reassign",
                json={"assignee": ctx["ops_pid"]}, headers=ctx["admin"])
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "处理人试图强关"}, headers=ctx["ops_h"])
    assert r.status_code == 403

    # IT运维负责人可强制关闭
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "重复事件，负责人强制关闭"}, headers=ctx["leader_h"])
    assert r.json()["success"], r.text
    assert r.json()["data"]["status"] == "closed"

    # 信息安全负责人同样可以（另开一单验证）
    t2 = _incident(client, ctx, "M27-信安强关")
    r = client.post(f"/api/tickets/{t2['id']}/close", json={"reason": "安全事件归并处理"}, headers=ctx["ismgr_h"])
    assert r.json()["success"], r.text


def test_in_progress_change_same_rule(client, ctx):
    t = client.post("/api/tickets", json={
        "title": "M27-变更强关", "ticket_type": "change", "priority": "P3",
        "description": "d", "service_item_id": ctx["item"],
        "change_type": "标准", "risk_level": "低",
    }, headers=ctx["admin"]).json()["data"]
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "运维试图强关变更"}, headers=ctx["ops_h"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORCE_CLOSE_FORBIDDEN"
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "变更作废，负责人关闭"}, headers=ctx["leader_h"])
    assert r.json()["success"], r.text


def test_service_request_keeps_flow_operator_rule(client, ctx):
    """服务请求不在白名单约束内：流程当前处理人可关（M25 规则不变）。"""
    t = client.post("/api/tickets", json={
        "title": "M27-服务请求处理人关单", "ticket_type": "service_request", "priority": "P4",
        "description": "d", "service_item_id": ctx["item"],
    }, headers=ctx["admin"]).json()["data"]
    proc = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]["process"]
    cur = next(s for s in proc["steps"] if s["seq"] == proc["current_step_seq"])
    client.post(f"/api/process-tasks/{cur['task_id']}/reassign",
                json={"assignee": ctx["ops_pid"]}, headers=ctx["admin"])
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "用户撤回申请，处理人关单"}, headers=ctx["ops_h"])
    assert r.json()["success"], r.text
