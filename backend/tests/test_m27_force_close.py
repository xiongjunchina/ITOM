"""M28（用户定稿）：事件/变更/问题必须走流程自动闭环，强制关闭仅系统管理员；
服务请求/需求/项目登记人可关（理由+审计）。"""
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


def test_incident_force_close_admin_only(client, ctx):
    """登记人 403；节点处理人 403；IT运维负责人/信安也 403（M28 收回）；仅 admin 放行。"""
    t = _incident(client, ctx, "M28-登记人不可强关")
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "登记人试图强关"}, headers=ctx["ops_h"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORCE_CLOSE_FORBIDDEN"

    # 当前节点处理人本人也不能强关（走流程步骤）
    proc = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]["process"]
    cur = next(s for s in proc["steps"] if s["seq"] == proc["current_step_seq"])
    client.post(f"/api/process-tasks/{cur['task_id']}/reassign",
                json={"assignee": ctx["ops_pid"]}, headers=ctx["admin"])
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "处理人试图强关"}, headers=ctx["ops_h"])
    assert r.status_code == 403

    # IT运维负责人 / 信息安全负责人：M28 起同样 403
    for h in (ctx["leader_h"], ctx["ismgr_h"]):
        r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "管理角色试图强关"}, headers=h)
        assert r.status_code == 403

    # 仅 admin 可强制关闭
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "重复事件，管理员强制关闭"}, headers=ctx["admin"])
    assert r.json()["success"], r.text
    assert r.json()["data"]["status"] == "closed"


def test_in_progress_change_same_rule(client, ctx):
    t = client.post("/api/tickets", json={
        "title": "M27-变更强关", "ticket_type": "change", "priority": "P3",
        "description": "d", "service_item_id": ctx["item"],
        "change_type": "标准", "risk_level": "低",
    }, headers=ctx["admin"]).json()["data"]
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "运维试图强关变更"}, headers=ctx["ops_h"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORCE_CLOSE_FORBIDDEN"
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "负责人也不可强关变更"}, headers=ctx["leader_h"])
    assert r.status_code == 403
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "变更作废，管理员关闭"}, headers=ctx["admin"])
    assert r.json()["success"], r.text


def test_service_request_submitter_can_close_handler_cannot(client, ctx):
    """M28：服务请求登记人本人可关；流程处理节点（非登记人）不可关。"""
    t = client.post("/api/tickets", json={
        "title": "M28-登记人关单", "ticket_type": "service_request", "priority": "P4",
        "description": "d", "service_item_id": ctx["item"],
    }, headers=ctx["ops_h"]).json()["data"]
    # 把当前节点任务改派给 leader → 处理人（非登记人）不可关
    proc = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]["process"]
    cur = next(s for s in proc["steps"] if s["seq"] == proc["current_step_seq"])
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "处理人试图关单"}, headers=ctx["leader_h"])
    assert r.status_code == 403
    # 登记人本人可关（无论流程在哪个节点）
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "自行解决，登记人撤回"}, headers=ctx["ops_h"])
    assert r.json()["success"], r.text
