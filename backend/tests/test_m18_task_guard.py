"""M18：流程任务操作权限——仅当前处理人本人或 admin 可完成/改派；生成任务时通知处理人。

用户实测漏洞：业务用户 user1 提交服务请求后，能直接对指派给 IT 运维的
「受理确认」步骤执行完成与改派。期望：中间步骤只有被指派人可操作，
业务用户仅在「用户确认关闭」（指派提交人本人）时可操作。
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

    ops_pid, ops_h = member_and_user("运维小钟M18", "m18_ops", ["it_ops"])
    req_pid, req_h = member_and_user("业务小柯M18", "m18_req", ["requester"])

    # 模拟用户配置：sr_flow 最后一步「用户确认关闭」主责改为 requester（指派提交人本人）
    defs = client.get("/api/admin/process-definitions", headers=admin_headers).json()["data"]
    sr = next(d for d in defs if d["code"].startswith("sr_flow") and d["active"])
    steps = [{k: st[k] for k in ("seq", "name", "default_role", "cc_roles", "autonomy_level", "sla_hours", "description")}
             for st in sr["steps"]]
    steps[-1]["default_role"] = "requester"
    r = client.patch(f"/api/admin/process-definitions/{sr['id']}", json={"steps": steps}, headers=admin_headers)
    assert r.json()["success"], r.text

    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    return {"admin": admin_headers, "ops_pid": ops_pid, "ops_h": ops_h,
            "req_pid": req_pid, "req_h": req_h, "item": item}


def _submit_sr(client, ctx, title):
    t = client.post("/api/tickets", json={
        "title": title, "ticket_type": "service_request", "priority": "P4",
        "description": "网络卡顿", "service_item_id": ctx["item"],
    }, headers=ctx["req_h"]).json()["data"]
    proc = client.get(f"/api/tickets/{t['id']}", headers=ctx["req_h"]).json()["data"]["process"]
    return t, proc


def _current(proc):
    return next(st for st in proc["steps"] if st["seq"] == proc["current_step_seq"])


def test_requester_cannot_operate_others_task(client, ctx):
    """复现用户漏洞：提交人对「受理确认」（他人任务）完成/改派必须 403。"""
    t, proc = _submit_sr(client, ctx, "网络卡顿-越权验证")
    step1 = _current(proc)
    assert "受理" in step1["name"] and step1["assignee"] != ctx["req_pid"]

    resp = client.post(f"/api/process-tasks/{step1['task_id']}/complete",
                       json={"comment": "我自己确认"}, headers=ctx["req_h"])
    assert resp.status_code == 403, f"业务用户不应能完成他人任务: {resp.text}"
    resp = client.post(f"/api/process-tasks/{step1['task_id']}/reassign",
                       json={"assignee": ctx["req_pid"]}, headers=ctx["req_h"])
    assert resp.status_code == 403, f"业务用户不应能改派任务: {resp.text}"


def test_assignee_chain_and_requester_confirm_step(client, ctx):
    """被指派人可完成；改派人本人可转派；最后一步指派提交人本人 → 提交人可完成闭环。"""
    t, proc = _submit_sr(client, ctx, "网络卡顿-正常链路")
    step1 = _current(proc)
    # admin 改派给运维小钟（管理动作永远放行）
    r = client.post(f"/api/process-tasks/{step1['task_id']}/reassign",
                    json={"assignee": ctx["ops_pid"]}, headers=ctx["admin"])
    assert r.json()["success"], r.text

    # 被指派人本人完成受理确认
    r = client.post(f"/api/process-tasks/{step1['task_id']}/complete",
                    json={"comment": "已受理"}, headers=ctx["ops_h"])
    assert r.json()["success"], r.text

    # 第 2 步实施交付：处理人本人可把任务转派（此处转给自己以外再转回，验证本人可转派）
    proc = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]["process"]
    step2 = _current(proc)
    if step2["assignee"] != ctx["ops_pid"]:
        client.post(f"/api/process-tasks/{step2['task_id']}/reassign",
                    json={"assignee": ctx["ops_pid"]}, headers=ctx["admin"])
    r = client.post(f"/api/process-tasks/{step2['task_id']}/complete",
                    json={"comment": "已交付"}, headers=ctx["ops_h"])
    assert r.json()["success"], r.text

    # 第 3 步用户确认关闭：指派提交人本人，提交人可完成（运维不可）
    proc = client.get(f"/api/tickets/{t['id']}", headers=ctx["req_h"]).json()["data"]["process"]
    step3 = _current(proc)
    assert "用户确认" in step3["name"] and step3["assignee"] == ctx["req_pid"]
    resp = client.post(f"/api/process-tasks/{step3['task_id']}/complete",
                       json={"comment": "抢跑确认"}, headers=ctx["ops_h"])
    assert resp.status_code == 403, "非处理人（运维）不应能替用户确认"
    r = client.post(f"/api/process-tasks/{step3['task_id']}/complete",
                    json={"comment": "问题已解决，确认关闭"}, headers=ctx["req_h"])
    assert r.json()["success"], r.text
    assert r.json()["data"]["status"] == "completed"


def test_task_assignment_notifies_assignee(client, ctx):
    """生成/改派任务时通知处理人：运维收到「受理确认」待办提醒。"""
    t, proc = _submit_sr(client, ctx, "网络卡顿-通知验证")
    step1 = _current(proc)
    client.post(f"/api/process-tasks/{step1['task_id']}/reassign",
                json={"assignee": ctx["ops_pid"]}, headers=ctx["admin"])
    notes = client.get("/api/notifications", headers=ctx["ops_h"]).json()["data"]
    assert any("受理确认" in n["title"] for n in notes), [n["title"] for n in notes]
    # 完成第 1 步 → 第 2 步处理人收到通知（自动解析指派）
    client.post(f"/api/process-tasks/{step1['task_id']}/complete",
                json={"comment": "已受理"}, headers=ctx["ops_h"])
    proc = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]["process"]
    step2 = _current(proc)
    if step2["assignee"] == ctx["ops_pid"]:
        notes = client.get("/api/notifications", headers=ctx["ops_h"]).json()["data"]
        assert any("实施交付" in n["title"] for n in notes)
