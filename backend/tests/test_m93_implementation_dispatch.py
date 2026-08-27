"""M93：服务请求受理→实施交付的人工安排与分层派单。

覆盖用户报告的真实缺陷：首节点受理人完成后，第二节点不能再无条件按默认
it_ops 角色选取第一个人。所有用例使用隔离 SQLite 数据库，不触及 IDC 数据。
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
        token = client.post(
            "/api/auth/login", json={"username": username, "password": "pass123"}
        ).json()["data"]["token"]
        return member["id"], {"Authorization": f"Bearer {token}"}

    handler_id, handler_headers = member_and_user("M93受理人", "m93_handler", ["it_ops"])
    colleague_id, colleague_headers = member_and_user("M93实施同事", "m93_colleague", ["it_ops"])
    catalog = client.post(
        "/api/catalogs",
        json={"name": "M93服务目录", "tier": "gold", "status": "上架"},
        headers=admin_headers,
    ).json()["data"]
    item = client.post(
        "/api/service-items",
        json={
            "name": "M93应用支持",
            "catalog_id": catalog["id"],
            "status": "上架",
            "service_type": "支持类",
        },
        headers=admin_headers,
    )
    assert item.status_code == 200, item.text
    return {
        "admin": admin_headers,
        "handler_id": handler_id,
        "handler": handler_headers,
        "colleague_id": colleague_id,
        "colleague": colleague_headers,
        "catalog_id": catalog["id"],
        "item_id": item.json()["data"]["id"],
    }


def _create_service_request(client, ctx, title, *, assignee=None):
    response = client.post(
        "/api/tickets",
        json={
            "title": title,
            "ticket_type": "service_request",
            "priority": "P3",
            "description": "M93 验证服务请求",
            "service_item_id": ctx["item_id"],
            "assignee": assignee or ctx["handler_id"],
        },
        headers=ctx["handler"],
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _current_step(client, ticket_id, headers):
    detail = client.get(f"/api/tickets/{ticket_id}", headers=headers).json()["data"]
    process = detail["process"]
    return detail, next(step for step in process["steps"] if step["seq"] == process["current_step_seq"])


def _complete_receipt(client, ticket_id, headers, **payload):
    _detail, step = _current_step(client, ticket_id, headers)
    response = client.post(
        f"/api/process-tasks/{step['task_id']}/complete",
        json={"comment": "已受理", **payload},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return _current_step(client, ticket_id, headers)


def _rule(target_type, target_id, strategy="fixed"):
    return {
        "name": "M93 实施派单",
        "target_type": target_type,
        "target_id": target_id,
        "strategy": strategy,
        "priority": 1,
        "active": True,
        "fallback": False,
    }


def test_receipt_handler_can_keep_implementation_on_self(client, ctx):
    ticket = _create_service_request(client, ctx, "M93-本人实施")
    detail, next_step = _complete_receipt(
        client,
        ticket["id"],
        ctx["handler"],
        implementation_mode="self",
    )
    assert next_step["assignee"] == ctx["handler_id"]
    assert detail["implementation_assignee"] == ctx["handler_id"]
    assert detail["implementation_source"] == "self_selected"


def test_receipt_handler_can_assign_colleague_and_cannot_reassign_later_step_through_handoff(client, ctx):
    ticket = _create_service_request(client, ctx, "M93-指定同事")
    detail, next_step = _complete_receipt(
        client,
        ticket["id"],
        ctx["handler"],
        implementation_mode="member",
        implementation_assignee=ctx["colleague_id"],
    )
    assert next_step["assignee"] == ctx["colleague_id"]
    assert detail["implementation_assignee"] == ctx["colleague_id"]
    assert detail["implementation_source"] == "handler_selected"

    # M92 边界：实施节点不能借完成接口再次指定下一节点处理人。
    denied = client.post(
        f"/api/process-tasks/{next_step['task_id']}/complete",
        json={"comment": "完成交付", "implementation_mode": "self"},
        headers=ctx["colleague"],
    )
    assert denied.status_code == 400, denied.text
    assert denied.json()["error"]["code"] == "IMPLEMENTATION_ASSIGNMENT_NOT_AVAILABLE"


def test_item_catalog_global_implementation_rule_precedence_and_global_role_guard(client, ctx):
    item_path = f"/api/service-items/{ctx['item_id']}/implementation-dispatch-rule"
    catalog_path = f"/api/catalogs/{ctx['catalog_id']}/implementation-dispatch-rule"
    global_path = "/api/service-dispatch/implementation-fallback"

    # 全局兜底不能由普通 IT 角色修改。
    forbidden = client.put(global_path, json=_rule("member", ctx["handler_id"]), headers=ctx["handler"])
    assert forbidden.status_code == 403

    # 服务项规则优先。
    response = client.put(item_path, json=_rule("member", ctx["colleague_id"]), headers=ctx["admin"])
    assert response.status_code == 200, response.text
    ticket = _create_service_request(client, ctx, "M93-服务项规则")
    detail, step = _complete_receipt(client, ticket["id"], ctx["handler"], implementation_mode="auto")
    assert step["assignee"] == ctx["colleague_id"]
    assert detail["implementation_source"] == "service_item"

    # 删除服务项规则后，目录兜底接管。
    assert client.delete(item_path, headers=ctx["admin"]).status_code == 200
    response = client.put(catalog_path, json=_rule("member", ctx["handler_id"]), headers=ctx["admin"])
    assert response.status_code == 200, response.text
    ticket = _create_service_request(client, ctx, "M93-目录规则")
    detail, step = _complete_receipt(client, ticket["id"], ctx["handler"], implementation_mode="auto")
    assert step["assignee"] == ctx["handler_id"]
    assert detail["implementation_source"] == "catalog"

    # 目录规则移除后，全局兜底接管；无规则才会继续交给流程节点默认角色。
    assert client.delete(catalog_path, headers=ctx["admin"]).status_code == 200
    response = client.put(global_path, json=_rule("member", ctx["colleague_id"]), headers=ctx["admin"])
    assert response.status_code == 200, response.text
    ticket = _create_service_request(client, ctx, "M93-全局规则")
    detail, step = _complete_receipt(client, ticket["id"], ctx["handler"], implementation_mode="auto")
    assert step["assignee"] == ctx["colleague_id"]
    assert detail["implementation_source"] == "global"
    assert client.delete(global_path, headers=ctx["admin"]).status_code == 200


def test_manual_queue_is_left_unassigned_until_an_eligible_it_member_claims_it(client, ctx):
    group = client.post(
        "/api/admin/groups",
        json={"code": "m93_delivery_queue", "name": "M93实施人工队列"},
        headers=ctx["admin"],
    ).json()["data"]
    assert client.put(
        f"/api/admin/groups/{group['id']}/members",
        json={"person_ids": [ctx["handler_id"], ctx["colleague_id"]]},
        headers=ctx["admin"],
    ).status_code == 200
    item_path = f"/api/service-items/{ctx['item_id']}/implementation-dispatch-rule"
    response = client.put(
        item_path,
        json=_rule("group", group["id"], strategy="manual_queue"),
        headers=ctx["admin"],
    )
    assert response.status_code == 200, response.text

    ticket = _create_service_request(client, ctx, "M93-人工队列")
    detail, step = _complete_receipt(client, ticket["id"], ctx["handler"], implementation_mode="auto")
    assert step["assignee"] is None
    assert detail["implementation_source"] == "manual_queue"

    # 未指派任务仍按节点角色进行认领；认领事实写入 viewed_by/assignee。
    claimed = client.post(f"/api/process-tasks/{step['task_id']}/view", headers=ctx["colleague"])
    assert claimed.status_code == 200, claimed.text
    detail, claimed_step = _current_step(client, ticket["id"], ctx["colleague"])
    assert claimed_step["assignee"] == ctx["colleague_id"]
    assert claimed_step["viewed_by"] == ctx["colleague_id"]
    assert client.delete(item_path, headers=ctx["admin"]).status_code == 200
