import pytest


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    """准备：一个 it_ops 成员账号 + manager 账号 + 服务项。"""
    def member_and_user(name, username, roles):
        m = client.post("/api/members", json={"name": name, "dept": "IT部"}, headers=admin_headers).json()["data"]
        client.post(
            "/api/admin/users",
            json={"username": username, "password": "pass123", "roles": roles, "person_id": m["id"]},
            headers=admin_headers,
        )
        token = client.post("/api/auth/login", json={"username": username, "password": "pass123"}).json()["data"]["token"]
        return m["id"], {"Authorization": f"Bearer {token}"}

    ops_person, ops_headers = member_and_user("运维一号", "ops1", ["it_ops"])
    mgr_person, mgr_headers = member_and_user("负责人", "mgr1", ["manager"])

    item_id = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    return {
        "ops_person": ops_person, "ops": ops_headers,
        "mgr_person": mgr_person, "mgr": mgr_headers,
        "item": item_id,
    }


def _create(client, headers, item, **kw):
    payload = {
        "title": "测试工单", "ticket_type": "incident", "priority": "P3",
        "description": "描述", "service_item_id": item, **kw,
    }
    resp = client.post("/api/tickets", json=payload, headers=headers)
    assert resp.json()["success"], resp.text
    return resp.json()["data"]


def test_create_auto_fields(client, ctx):
    t = _create(client, ctx["ops"], ctx["item"], assignee=ctx["ops_person"])
    assert t["ticket_code"].startswith("TK-")
    assert t["status"] == "new"
    assert t["submitter_name"] == "运维一号"
    assert t["service_line"]  # 服务线由服务项带出
    assert t["sla_resolution_hours"] == 24  # P3 策略

    detail = client.get(f"/api/tickets/{t['id']}", headers=ctx["ops"]).json()["data"]
    assert detail["process"] is not None and detail["process"]["definition_name"] == "事件处理流程"
    assert [s["task_status"] for s in detail["process"]["steps"]][0] == "待处理"


def test_ticket_lifecycle_and_sla(client, ctx):
    t = _create(client, ctx["ops"], ctx["item"], priority="P1")
    tid = t["id"]

    # 非法跳转：new → closed
    resp = client.post(f"/api/tickets/{tid}/transition", json={"to": "closed", "fields": {}}, headers=ctx["ops"])
    assert resp.json()["error"]["code"] == "INVALID_TRANSITION"

    # 受理 → first_response 打点
    client.post(f"/api/tickets/{tid}/transition", json={"to": "processing", "fields": {}}, headers=ctx["ops"])
    detail = client.get(f"/api/tickets/{tid}", headers=ctx["ops"]).json()["data"]
    assert detail["first_response_at"] is not None
    assert detail["sla_response_met"] is True  # 立即受理必然达标

    # 解决时缺 solution 被拒
    resp = client.post(f"/api/tickets/{tid}/transition", json={"to": "resolved", "fields": {}}, headers=ctx["ops"])
    assert resp.json()["error"]["code"] == "STAGE_FIELD_REQUIRED"

    client.post(
        f"/api/tickets/{tid}/transition",
        json={"to": "resolved", "fields": {"solution": "已修复"}},
        headers=ctx["ops"],
    )
    detail = client.get(f"/api/tickets/{tid}", headers=ctx["ops"]).json()["data"]
    assert detail["sla_resolution_met"] is True and detail["first_time_fix"] is True

    # 关闭需 closure_code
    resp = client.post(
        f"/api/tickets/{tid}/transition",
        json={"to": "closed", "fields": {"closure_code": "resolved"}},
        headers=ctx["ops"],
    )
    assert resp.json()["data"]["status"] == "closed"

    # 提交人评价
    resp = client.post(f"/api/tickets/{tid}/satisfaction", json={"score": 5}, headers=ctx["ops"])
    assert resp.json()["data"]["satisfaction"] == 5


def test_reopen_clears_first_time_fix(client, ctx):
    t = _create(client, ctx["ops"], ctx["item"])
    tid = t["id"]
    client.post(f"/api/tickets/{tid}/transition", json={"to": "resolved", "fields": {"solution": "fix"}}, headers=ctx["ops"])
    client.post(f"/api/tickets/{tid}/transition", json={"to": "processing", "fields": {}}, headers=ctx["ops"])
    client.post(f"/api/tickets/{tid}/transition", json={"to": "resolved", "fields": {}}, headers=ctx["ops"])
    detail = client.get(f"/api/tickets/{tid}", headers=ctx["ops"]).json()["data"]
    assert detail["reopen_count"] == 1 and detail["first_time_fix"] is False


def test_change_approval_flow(client, ctx):
    t = _create(
        client, ctx["ops"], ctx["item"],
        ticket_type="change", change_type="普通", risk_level="中", rollback_plan="回退方案",
    )
    tid = t["id"]
    client.post(f"/api/tickets/{tid}/transition", json={"to": "pending_approval", "fields": {}}, headers=ctx["ops"])

    # it_ops 无权审批
    resp = client.post(f"/api/tickets/{tid}/transition", json={"to": "approved", "fields": {}}, headers=ctx["ops"])
    assert resp.status_code == 403

    # manager 审批通过
    resp = client.post(
        f"/api/tickets/{tid}/transition",
        json={"to": "approved", "fields": {"approval_comment": "同意"}},
        headers=ctx["mgr"],
    )
    assert resp.json()["data"]["status"] == "approved"
    detail = client.get(f"/api/tickets/{tid}", headers=ctx["mgr"]).json()["data"]
    assert detail["approved_at"] and detail["approval_comment"] == "同意"

    # 变更流程实例应为 change_flow
    assert detail["process"]["definition_name"] == "变更管理流程"

    # manager 收到过审批通知
    notif = client.get("/api/notifications", headers=ctx["mgr"]).json()["data"]
    assert any("变更待审批" in n["title"] for n in notif)


def test_change_requires_change_type(client, ctx):
    resp = client.post(
        "/api/tickets",
        json={"title": "变更缺类型", "ticket_type": "change", "priority": "P3",
              "description": "d", "service_item_id": ctx["item"]},
        headers=ctx["ops"],
    )
    assert resp.json()["error"]["code"] == "STAGE_FIELD_REQUIRED"


def test_requester_only_sees_own_tickets(client, ctx, admin_headers):
    client.post(
        "/api/admin/users",
        json={"username": "req01", "password": "pass123", "roles": ["requester"]},
        headers=admin_headers,
    )
    token = client.post("/api/auth/login", json={"username": "req01", "password": "pass123"}).json()["data"]["token"]
    req_headers = {"Authorization": f"Bearer {token}"}

    mine = _create(client, req_headers, ctx["item"], title="业务用户的工单")
    listing = client.get("/api/tickets", headers=req_headers).json()
    assert all(row["submitter_name"] == "req01" for row in listing["data"])
    assert any(row["id"] == mine["id"] for row in listing["data"])

    # 不能看别人的工单
    other = _create(client, ctx["ops"], ctx["item"], title="他人工单")
    assert client.get(f"/api/tickets/{other['id']}", headers=req_headers).status_code == 403


def test_process_task_complete_advances(client, ctx):
    t = _create(client, ctx["ops"], ctx["item"], assignee=ctx["ops_person"])
    detail = client.get(f"/api/tickets/{t['id']}", headers=ctx["ops"]).json()["data"]
    first_task = detail["process"]["steps"][0]["task_id"]
    resp = client.post(f"/api/process-tasks/{first_task}/complete", json={"comment": "done"}, headers=ctx["ops"])
    assert resp.json()["data"]["current_step_seq"] == 2

    detail = client.get(f"/api/tickets/{t['id']}", headers=ctx["ops"]).json()["data"]
    steps = detail["process"]["steps"]
    assert steps[0]["task_status"] == "已完成" and steps[1]["task_status"] == "待处理"


def test_sla_dashboard_and_main_dashboard(client, ctx):
    resp = client.get("/api/sla/dashboard", headers=ctx["ops"]).json()["data"]
    assert "by_priority" in resp and resp["by_priority"]["P3"]["resolved"] >= 1

    dash = client.get("/api/dashboard", headers=ctx["ops"]).json()["data"]
    assert dash["service"]["open_tickets"] >= 1
    assert dash["service"]["sla_rate"] is not None
