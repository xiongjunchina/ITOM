import pytest


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    """准备：一个 it_ops 成员账号 + manager 账号 + 服务项。"""
    def member_and_user(name, username, roles):
        m = client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]
        client.post(
            "/api/admin/users",
            json={"username": username, "password": "pass123", "roles": roles, "person_id": m["id"]},
            headers=admin_headers,
        )
        token = client.post("/api/auth/login", json={"username": username, "password": "pass123"}).json()["data"]["token"]
        return m["id"], {"Authorization": f"Bearer {token}"}

    ops_person, ops_headers = member_and_user("运维一号", "ops1", ["it_ops"])
    mgr_person, mgr_headers = member_and_user("负责人", "mgr1", ["cio"])

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


def test_service_request_preserves_request_form_fields(client, ctx):
    t = _create(
        client,
        ctx["ops"],
        ctx["item"],
        ticket_type="service_request",
        service_category="电脑与终端",
        other_info="办公地点：广州；方便联系时间：工作日",
    )
    detail = client.get(f"/api/tickets/{t['id']}", headers=ctx["ops"]).json()["data"]
    assert detail["service_category"] == "电脑与终端"
    assert detail["other_info"] == "办公地点：广州；方便联系时间：工作日"


def test_service_request_draft_attachments_bind_atomically(client, ctx, monkeypatch, tmp_path):
    """建单前附件只属于上传人，创建成功后才与服务请求一起成为正式证据。"""
    monkeypatch.setattr("app.core.config.settings.upload_dir", str(tmp_path))
    upload = client.post(
        "/api/attachments/ticket-drafts",
        files={"file": ("现场截图.png", b"png-content", "image/png")},
        headers=ctx["ops"],
    )
    assert upload.status_code == 200, upload.text
    draft = upload.json()["data"]

    # 草稿文件没有单据语义，不能通过通用附件清单或下载接口泄露。
    hidden = client.get(
        f"/api/attachments?entity_type=ticket_draft&entity_id={draft['id']}", headers=ctx["ops"],
    )
    assert hidden.status_code == 403
    assert client.get(f"/api/attachments/{draft['id']}/download", headers=ctx["ops"]).status_code == 403
    bypass = client.post(
        f"/api/attachments?entity_type=ticket_draft&entity_id={draft['id']}",
        files={"file": ("bypass.exe", b"binary", "application/octet-stream")},
        headers=ctx["ops"],
    )
    assert bypass.status_code == 403

    ticket = _create(
        client,
        ctx["ops"],
        ctx["item"],
        ticket_type="service_request",
        title="带截图的服务请求",
        attachment_ids=[draft["id"]],
    )
    attachments = client.get(
        f"/api/attachments?entity_type=ticket&entity_id={ticket['id']}", headers=ctx["ops"],
    )
    assert attachments.status_code == 200, attachments.text
    assert attachments.json()["total"] == 1
    bound = attachments.json()["data"][0]
    assert bound["id"] == draft["id"] and bound["filename"] == "现场截图.png"
    download = client.get(f"/api/attachments/{bound['id']}/download", headers=ctx["ops"])
    assert download.status_code == 200 and download.content == b"png-content"

    unsupported = client.post(
        "/api/attachments/ticket-drafts",
        files={"file": ("not-allowed.exe", b"binary", "application/octet-stream")},
        headers=ctx["ops"],
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == "ATTACHMENT_TYPE_UNSUPPORTED"


def test_ticket_list_returns_real_total_beyond_page_size(client, ctx):
    """API total 必须保持全部匹配记录数，前端据此分页，不得退化成当前页 20 条。"""
    for index in range(22):
        _create(client, ctx["ops"], ctx["item"], title=f"分页总数回归-{index:02d}")
    listing = client.get("/api/tickets?page=1&page_size=20", headers=ctx["ops"])
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert len(body["data"]) == 20
    assert body["total"] >= 22


def test_ticket_lifecycle_and_sla(client, ctx, admin_headers):
    t = _create(client, ctx["ops"], ctx["item"], priority="P1")
    tid = t["id"]

    # 非法跳转：new → closed
    resp = client.post(f"/api/tickets/{tid}/transition", json={"to": "closed", "fields": {}}, headers=admin_headers)
    assert resp.json()["error"]["code"] == "INVALID_TRANSITION"

    # 受理 → first_response 打点（M31：手动流转归 admin；日常由完成流程步骤自动同步）
    client.post(f"/api/tickets/{tid}/transition", json={"to": "processing", "fields": {}}, headers=admin_headers)
    detail = client.get(f"/api/tickets/{tid}", headers=ctx["ops"]).json()["data"]
    assert detail["first_response_at"] is not None
    assert detail["sla_response_met"] is True  # 立即受理必然达标

    # 解决时缺 solution 被拒
    resp = client.post(f"/api/tickets/{tid}/transition", json={"to": "resolved", "fields": {}}, headers=admin_headers)
    assert resp.json()["error"]["code"] == "STAGE_FIELD_REQUIRED"

    client.post(
        f"/api/tickets/{tid}/transition",
        json={"to": "resolved", "fields": {"solution": "已修复"}},
        headers=admin_headers,
    )
    detail = client.get(f"/api/tickets/{tid}", headers=ctx["ops"]).json()["data"]
    assert detail["sla_resolution_met"] is True and detail["first_time_fix"] is True

    # 关闭需 closure_code；M28：手动流转到已关闭=强制关闭，仅系统管理员
    resp = client.post(
        f"/api/tickets/{tid}/transition",
        json={"to": "closed", "fields": {"closure_code": "resolved"}},
        headers=ctx["ops"],
    )
    assert resp.status_code == 403
    resp = client.post(
        f"/api/tickets/{tid}/transition",
        json={"to": "closed", "fields": {"closure_code": "resolved"}},
        headers=admin_headers,
    )
    assert resp.json()["data"]["status"] == "closed"

    # 提交人评价
    resp = client.post(f"/api/tickets/{tid}/satisfaction", json={"score": 5}, headers=ctx["ops"])
    assert resp.json()["data"]["satisfaction"] == 5


def test_reopen_clears_first_time_fix(client, ctx, admin_headers):
    t = _create(client, ctx["ops"], ctx["item"])
    tid = t["id"]
    client.post(f"/api/tickets/{tid}/transition", json={"to": "resolved", "fields": {"solution": "fix"}}, headers=admin_headers)
    client.post(f"/api/tickets/{tid}/transition", json={"to": "processing", "fields": {}}, headers=admin_headers)
    client.post(f"/api/tickets/{tid}/transition", json={"to": "resolved", "fields": {}}, headers=admin_headers)
    detail = client.get(f"/api/tickets/{tid}", headers=ctx["ops"]).json()["data"]
    assert detail["reopen_count"] == 1 and detail["first_time_fix"] is False


def test_change_approval_flow(client, ctx, admin_headers):
    t = _create(
        client, ctx["ops"], ctx["item"],
        ticket_type="change", change_type="普通", risk_level="中", rollback_plan="回退方案",
    )
    tid = t["id"]
    # M25：普通流转归流程当前处理人——此处用 admin 提交审批（提单人不再有此按钮）
    client.post(f"/api/tickets/{tid}/transition", json={"to": "pending_approval", "fields": {}}, headers=admin_headers)

    # it_ops 无权审批
    resp = client.post(f"/api/tickets/{tid}/transition", json={"to": "approved", "fields": {}}, headers=ctx["ops"])
    assert resp.status_code == 403

    # cio 审批通过
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

    # M17.2：业务用户仅可提服务请求（事件/变更 403）
    denied = client.post("/api/tickets", json={"title": "越权事件", "ticket_type": "incident", "priority": "P3",
                                               "description": "d", "service_item_id": ctx["item"]}, headers=req_headers)
    assert denied.status_code == 403
    mine = _create(client, req_headers, ctx["item"], title="业务用户的工单", ticket_type="service_request")
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


def test_sla_dashboard_and_main_dashboard(client, ctx, admin_headers):
    resp = client.get("/api/sla/dashboard", headers=ctx["ops"]).json()["data"]
    assert "by_priority" in resp and resp["by_priority"]["P3"]["resolved"] >= 1

    dash = client.get("/api/dashboard", headers=ctx["ops"]).json()["data"]
    assert dash["service"]["open_tickets"] >= 1
    assert dash["service"]["sla_rate"] is not None
