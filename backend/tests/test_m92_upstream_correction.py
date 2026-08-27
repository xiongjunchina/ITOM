"""M92: upstream correction window for workflow-driven records.

The test deliberately uses an ordinary requester without ``ticket_sr.edit`` or
``ticket_sr.delete``.  A successful first-node correction therefore proves that
the narrowly scoped workflow grant works; a later 403 proves that ordinary
module permissions cannot bypass the first real view.
"""
import pytest


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    def member_and_user(name, username, roles):
        member = client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]
        created = client.post(
            "/api/admin/users",
            json={"username": username, "password": "pass123", "roles": roles, "person_id": member["id"]},
            headers=admin_headers,
        )
        assert created.status_code in {200, 409}, created.text
        token = client.post("/api/auth/login", json={"username": username, "password": "pass123"}).json()["data"]["token"]
        return member["id"], {"Authorization": f"Bearer {token}"}

    requester_id, requester_headers = member_and_user("更正窗口申请人M92", "m92_requester", ["requester"])
    operator_id, operator_headers = member_and_user("更正窗口处理人M92", "m92_operator", ["it_ops"])
    reviewer_id, reviewer_headers = member_and_user("更正窗口下游处理人M92", "m92_reviewer", ["it_ops"])
    item_id = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    return {
        "admin": admin_headers,
        "requester_id": requester_id,
        "requester": requester_headers,
        "operator_id": operator_id,
        "operator": operator_headers,
        "reviewer_id": reviewer_id,
        "reviewer": reviewer_headers,
        "item_id": item_id,
    }


def _create_ticket(client, ctx, title: str):
    response = client.post(
        "/api/tickets",
        json={
            "title": title,
            "ticket_type": "service_request",
            "priority": "P4",
            "description": "用于验证未查阅前更正窗口",
            "service_item_id": ctx["item_id"],
        },
        headers=ctx["requester"],
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _current_step(detail: dict) -> dict:
    return next(step for step in detail["process"]["steps"] if step["seq"] == detail["process"]["current_step_seq"])


def _assign_current_task_for_test(ticket_id: str, assignee: str):
    """Keep the test deterministic without using reassign (which rightly counts as a view)."""
    from app.db import SessionLocal
    from app.services import process_engine

    db = SessionLocal()
    try:
        task = process_engine.current_pending_task(db, "ticket", ticket_id)
        assert task is not None
        task.assignee = assignee
        db.commit()
    finally:
        db.close()


def test_creator_can_edit_and_delete_before_first_handler_view(client, ctx):
    ticket = _create_ticket(client, ctx, "M92 首节点可更正")
    _assign_current_task_for_test(ticket["id"], ctx["operator_id"])

    detail = client.get(f"/api/tickets/{ticket['id']}", headers=ctx["requester"]).json()["data"]
    assert detail["can_edit"] is True
    assert detail["can_delete"] is True
    assert detail["workflow_edit_mode"] == "upstream_creator"

    changed = client.patch(
        f"/api/tickets/{ticket['id']}", json={"title": "M92 首节点已更正"}, headers=ctx["requester"]
    )
    assert changed.status_code == 200, changed.text

    route_change = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"assignee": ctx["requester_id"]},
        headers=ctx["requester"],
    )
    assert route_change.status_code == 403
    assert route_change.json()["error"]["code"] == "WORKFLOW_CORRECTION_FIELD_FORBIDDEN"

    disposable = _create_ticket(client, ctx, "M92 首节点可删除")
    _assign_current_task_for_test(disposable["id"], ctx["operator_id"])
    deleted = client.delete(f"/api/tickets/{disposable['id']}", headers=ctx["requester"])
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"]["process_instances"] == 1


def test_admin_reassign_does_not_count_as_next_handler_view(client, ctx):
    """管理员调度给真实处理人不能提前关闭提交人的更正窗口。"""
    ticket = _create_ticket(client, ctx, "M92 管理员改派不算查阅")
    detail = client.get(f"/api/tickets/{ticket['id']}", headers=ctx["admin"]).json()["data"]
    task = _current_step(detail)
    reassigned = client.post(
        f"/api/process-tasks/{task['task_id']}/reassign",
        json={"assignee": ctx["operator_id"]},
        headers=ctx["admin"],
    )
    assert reassigned.status_code == 200, reassigned.text

    after_reassign = client.get(f"/api/tickets/{ticket['id']}", headers=ctx["requester"]).json()["data"]
    assert after_reassign["can_edit"] is True
    assert after_reassign["workflow_edit_mode"] == "upstream_creator"


def test_admin_passive_detail_view_does_not_lock_creator_correction(client, ctx):
    """管理员可查看/调度，但不能伪造为下游处理人已查阅。"""
    ticket = _create_ticket(client, ctx, "M92 管理员查看不算查阅")
    _assign_current_task_for_test(ticket["id"], ctx["operator_id"])
    detail = client.get(f"/api/tickets/{ticket['id']}", headers=ctx["admin"]).json()["data"]
    task = _current_step(detail)

    passive_view = client.post(f"/api/process-tasks/{task['task_id']}/view", headers=ctx["admin"])
    assert passive_view.status_code == 200, passive_view.text
    assert passive_view.json()["data"]["newly_viewed"] is False
    assert passive_view.json()["data"]["viewed_at"] is None

    requester_detail = client.get(f"/api/tickets/{ticket['id']}", headers=ctx["requester"]).json()["data"]
    assert requester_detail["can_edit"] is True
    assert requester_detail["workflow_edit_mode"] == "upstream_creator"


def test_first_actual_view_locks_creator_correction_and_records_viewer(client, ctx):
    ticket = _create_ticket(client, ctx, "M92 查阅后锁定")
    _assign_current_task_for_test(ticket["id"], ctx["operator_id"])
    detail = client.get(f"/api/tickets/{ticket['id']}", headers=ctx["admin"]).json()["data"]
    task = _current_step(detail)
    assert task["viewed_at"] is None

    viewed = client.post(f"/api/process-tasks/{task['task_id']}/view", headers=ctx["operator"])
    assert viewed.status_code == 200, viewed.text
    assert viewed.json()["data"]["newly_viewed"] is True
    assert viewed.json()["data"]["viewed_by"] == ctx["operator_id"]

    after = client.get(f"/api/tickets/{ticket['id']}", headers=ctx["requester"]).json()["data"]
    assert after["can_edit"] is False
    assert after["can_delete"] is False
    assert after["workflow_edit_locked_reason"] == "当前节点已被查阅或处理"

    denied_edit = client.patch(
        f"/api/tickets/{ticket['id']}", json={"title": "不应允许"}, headers=ctx["requester"]
    )
    assert denied_edit.status_code == 403
    assert denied_edit.json()["error"]["code"] == "WORKFLOW_EDIT_LOCKED"
    denied_delete = client.delete(f"/api/tickets/{ticket['id']}", headers=ctx["requester"])
    assert denied_delete.status_code == 403
    assert denied_delete.json()["error"]["code"] == "WORKFLOW_DELETE_LOCKED"


def test_existing_pending_tasks_remain_outside_the_new_window(client, ctx):
    """The migration's false default protects in-flight IDC records at rollout."""
    from app.db import SessionLocal
    from app.services import process_engine

    ticket = _create_ticket(client, ctx, "M92 存量任务兼容")
    _assign_current_task_for_test(ticket["id"], ctx["operator_id"])
    db = SessionLocal()
    try:
        task = process_engine.current_pending_task(db, "ticket", ticket["id"])
        assert task is not None
        task.upstream_correction_enabled = False
        db.commit()
    finally:
        db.close()

    denied = client.patch(
        f"/api/tickets/{ticket['id']}", json={"title": "不应对存量任务放权"}, headers=ctx["requester"]
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "WORKFLOW_EDIT_LOCKED"


def test_previous_handler_can_correct_until_next_handler_views(client, ctx):
    """非首节点：上一节点的实际处理人只在下游首次实际查阅前可回改。"""
    ticket = _create_ticket(client, ctx, "M92 上一节点回改")
    _assign_current_task_for_test(ticket["id"], ctx["operator_id"])

    first = client.get(f"/api/tickets/{ticket['id']}", headers=ctx["admin"]).json()["data"]
    first_task = _current_step(first)
    completed = client.post(
        f"/api/process-tasks/{first_task['task_id']}/complete",
        json={"comment": "上一节点已完成"},
        headers=ctx["operator"],
    )
    assert completed.status_code == 200, completed.text

    # 新节点由另一位 IT 人员办理，避免默认角色解析恰好仍分配给上一处理人。
    _assign_current_task_for_test(ticket["id"], ctx["reviewer_id"])

    # 新节点尚未查阅：上一实际处理人获得 upstream_handler 回改权，而不是永久 module edit 权。
    before_next_view = client.get(f"/api/tickets/{ticket['id']}", headers=ctx["operator"]).json()["data"]
    assert before_next_view["can_edit"] is True
    assert before_next_view["can_delete"] is False
    assert before_next_view["workflow_edit_mode"] == "upstream_handler"
    corrected = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"title": "M92 上一节点已回改"},
        headers=ctx["operator"],
    )
    assert corrected.status_code == 200, corrected.text

    next_detail = client.get(f"/api/tickets/{ticket['id']}", headers=ctx["admin"]).json()["data"]
    next_task = _current_step(next_detail)
    viewed = client.post(f"/api/process-tasks/{next_task['task_id']}/view", headers=ctx["reviewer"])
    assert viewed.status_code == 200, viewed.text

    after_next_view = client.get(f"/api/tickets/{ticket['id']}", headers=ctx["operator"]).json()["data"]
    assert after_next_view["can_edit"] is False
    assert after_next_view["workflow_edit_locked_reason"] == "当前节点已被查阅或处理"
    denied = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"title": "下游已看不得回改"},
        headers=ctx["operator"],
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "WORKFLOW_EDIT_LOCKED"
