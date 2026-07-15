"""M23：工单流程走完 → 状态机自动闭环（用户实测：变更复盘完成后工单仍显示待审批/新建）。"""
import pytest


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    return {"admin": admin_headers, "item": item}


def _walk_process(client, headers, ticket_id, steps_to_complete=None):
    """依次完成工单流程任务（admin）；steps_to_complete=None 走完全部。返回最终 detail。"""
    done = 0
    while True:
        d = client.get(f"/api/tickets/{ticket_id}", headers=headers).json()["data"]
        proc = d["process"]
        if not proc or proc["status"] == "completed":
            return d
        if steps_to_complete is not None and done >= steps_to_complete:
            return d
        cur = next(s for s in proc["steps"] if s["seq"] == proc["current_step_seq"])
        r = client.post(f"/api/process-tasks/{cur['task_id']}/complete",
                        json={"comment": f"完成步骤：{cur['name']}"}, headers=headers)
        assert r.json()["success"], r.text
        done += 1


def test_change_flow_complete_auto_closes(client, ctx):
    """变更 4 步流程（登记风险评估→审批→实施→复盘）全部完成 → 工单自动 closed。"""
    t = client.post("/api/tickets", json={
        "title": "服务器重启-M23", "ticket_type": "change", "priority": "P3",
        "description": "d", "service_item_id": ctx["item"],
        "change_type": "标准", "risk_level": "低",
    }, headers=ctx["admin"]).json()["data"]
    d = _walk_process(client, ctx["admin"], t["id"])
    final = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]
    assert final["status"] == "closed", f"流程完成后应自动关闭，实际 {final['status']}"
    assert final["solution"]  # 兜底写入闭环说明


def test_sr_flow_complete_auto_closes(client, ctx):
    """服务请求 3 步流程完成 → 自动 closed。"""
    t = client.post("/api/tickets", json={
        "title": "网络申请-M23", "ticket_type": "service_request", "priority": "P4",
        "description": "d", "service_item_id": ctx["item"],
    }, headers=ctx["admin"]).json()["data"]
    _walk_process(client, ctx["admin"], t["id"])
    final = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]
    assert final["status"] == "closed"


def test_incomplete_process_does_not_touch_status(client, ctx):
    """流程未走完：状态机保持原状（不提前闭环）。"""
    t = client.post("/api/tickets", json={
        "title": "变更未完待续-M23", "ticket_type": "change", "priority": "P3",
        "description": "d", "service_item_id": ctx["item"],
        "change_type": "普通", "risk_level": "中",
    }, headers=ctx["admin"]).json()["data"]
    _walk_process(client, ctx["admin"], t["id"], steps_to_complete=2)
    final = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]
    assert final["status"] == "new"  # 未动状态机
