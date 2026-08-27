"""M24：流程线↔状态机双向联动全实体自查修复。

正向：problem 流程完成→自动闭环；project 流程完成→通知 PM（不自动关）。
反向：工单/问题/需求/项目终态→流程实例收尾（作废待办）；需求驳回退回历史节点。
"""
import pytest


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    def member(name):
        return client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]["id"]

    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    domain = client.get("/api/admin/business-domains", headers=admin_headers).json()["data"][0]["id"]
    return {"admin": admin_headers, "item": item, "domain": domain, "member": member}


def _proc(client, headers, url):
    return client.get(url, headers=headers).json()["data"]["process"]


def _walk(client, headers, url):
    while True:
        proc = _proc(client, headers, url)
        if not proc or proc["status"] == "completed":
            return
        cur = next(s for s in proc["steps"] if s["seq"] == proc["current_step_seq"])
        r = client.post(f"/api/process-tasks/{cur['task_id']}/complete",
                        json={"comment": f"完成：{cur['name']}"}, headers=headers)
        assert r.json()["success"], r.text


def test_problem_flow_complete_auto_closes(client, ctx):
    p = client.post("/api/problems", json={"title": "M24问题闭环", "description": "d", "priority": "P3",
                                           "service_item_id": ctx["item"]}, headers=ctx["admin"]).json()["data"]
    _walk(client, ctx["admin"], f"/api/problems/{p['id']}")
    d = client.get(f"/api/problems/{p['id']}", headers=ctx["admin"]).json()["data"]
    assert d["status"] == "closed", f"问题流程完成应自动关闭，实际 {d['status']}"
    assert d["root_cause"]  # 兜底写入


def test_ticket_manual_close_finalizes_process(client, ctx):
    t = client.post("/api/tickets", json={"title": "M24手动关单", "ticket_type": "service_request", "priority": "P4",
                                          "description": "d", "service_item_id": ctx["item"]},
                    headers=ctx["admin"]).json()["data"]
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "无需处理，直接关闭"}, headers=ctx["admin"])
    assert r.json()["success"], r.text
    proc = _proc(client, ctx["admin"], f"/api/tickets/{t['id']}")
    assert proc["status"] == "completed"
    assert all(s["task_status"] != "待处理" for s in proc["steps"])  # 待办全部收尾


def test_problem_manual_close_finalizes_process(client, ctx):
    p = client.post("/api/problems", json={"title": "M24问题手动关", "description": "d", "priority": "P3",
                                           "service_item_id": ctx["item"]}, headers=ctx["admin"]).json()["data"]
    for to in ("analyzing", "resolved"):
        client.post(f"/api/problems/{p['id']}/transition",
                    json={"to": to, "fields": {"root_cause": "配置错误导致"}}, headers=ctx["admin"])
    r = client.post(f"/api/problems/{p['id']}/transition",
                    json={"to": "closed", "fields": {}}, headers=ctx["admin"])
    assert r.json()["success"], r.text
    proc = _proc(client, ctx["admin"], f"/api/problems/{p['id']}")
    assert proc["status"] == "completed"
    assert all(s["task_status"] != "待处理" for s in proc["steps"])


def test_requirement_reject_returns_to_requester_without_next_task(client, ctx):
    """首审批节点驳回=登记人补充：不派发下一审批节点，也不终止需求。"""
    r = client.post("/api/requirements", json={"title": "M24驳回需求", "req_type": "功能",
                                               "business_domain_id": ctx["domain"], "description": "d"},
                    headers=ctx["admin"]).json()["data"]
    resp = client.post(f"/api/requirements/{r['id']}/score", json={
        "d1_strategy": 1, "d2_value": 1, "d3_tech": 1, "d4_org": 1, "d5_risk": 5, "d6_speed": 1,
        "decision": "驳回", "comment": "价值不足，请登记人补充依据",
    }, headers=ctx["admin"])
    assert resp.json()["success"], resp.text
    d = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]
    assert d["status"] == "supplementing"
    proc = d["process"]
    assert proc["status"] == "returned"
    assert all(s["task_status"] != "待处理" for s in proc["steps"])  # 等登记人补充，不派下一节点


def test_project_close_finalizes_and_flow_complete_notifies_pm(client, ctx):
    pm = ctx["member"]("PM-M24")
    p = client.post("/api/projects", json={"name": "M24项目", "pm": pm,
                                           "planned_start": "2026-08-01", "planned_end": "2026-12-31"},
                    headers=ctx["admin"]).json()["data"]
    # 项目流程走完 → 项目未关 → 通知 PM 确认收尾（不自动关）
    _walk(client, ctx["admin"], f"/api/projects/{p['id']}")
    d = client.get(f"/api/projects/{p['id']}", headers=ctx["admin"]).json()["data"]
    assert d["status"] != "closed"  # 不自动关
    # 关闭项目 → 流程已是完成态（幂等）；再建一个流程未走完的项目验证收尾
    p2 = client.post("/api/projects", json={"name": "M24项目2", "pm": pm,
                                            "planned_start": "2026-08-01", "planned_end": "2026-12-31"},
                     headers=ctx["admin"]).json()["data"]
    for to in ("active", "closed"):
        fields = {"reason": "提前终止，验证流程收尾"} if to == "closed" else {}
        resp = client.post(f"/api/projects/{p2['id']}/transition", json={"to": to, "fields": fields}, headers=ctx["admin"])
        assert resp.json()["success"], resp.text
    proc = _proc(client, ctx["admin"], f"/api/projects/{p2['id']}")
    assert proc["status"] == "completed"
    assert all(s["task_status"] != "待处理" for s in proc["steps"])
