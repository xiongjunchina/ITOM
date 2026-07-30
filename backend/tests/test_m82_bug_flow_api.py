import pytest

from app.db import SessionLocal
from app.models import ProcessInstance, ProcessTask


@pytest.fixture(scope="module")
def actors(client, admin_headers):
    def create_actor(name: str, username: str, role: str):
        member = client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]
        response = client.post(
            "/api/admin/users",
            json={"username": username, "password": "pass123", "roles": [role], "person_id": member["id"]},
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        token = client.post(
            "/api/auth/login", json={"username": username, "password": "pass123"}
        ).json()["data"]["token"]
        return member["id"], {"Authorization": f"Bearer {token}"}

    dev_id, dev_headers = create_actor("Bug 登记开发", "m82_bug_dev", "it_dev")
    pm_id, pm_headers = create_actor("Bug 产品经理", "m82_bug_pm", "it_pdm")
    leader_id, leader_headers = create_actor("Bug 开发负责人", "m82_bug_leader", "it_dev_leader")
    requester_id, requester_headers = create_actor("Bug 普通用户", "m82_bug_requester", "requester")
    ci = client.post(
        "/api/cis",
        json={"name": "供应链管理系统-M82", "category": "app", "owner": dev_id, "product_manager_id": pm_id},
        headers=admin_headers,
    )
    assert ci.status_code == 200, ci.text
    return {
        "admin": admin_headers,
        "dev": dev_headers,
        "pm": pm_headers,
        "leader": leader_headers,
        "requester": requester_headers,
        "dev_id": dev_id,
        "pm_id": pm_id,
        "leader_id": leader_id,
        "requester_id": requester_id,
        "ci_id": ci.json()["data"]["id"],
    }


def _register_bug(client, actors, title="供应链接口异常"):
    response = client.post(
        "/api/task-management/bugs",
        json={
            "title": title,
            "description": "供应链系统提交订单时返回 500",
            "ci_id": actors["ci_id"],
            "priority": "P2",
            "reproduction": "提交一条订单即可复现",
            "expected_result": "订单成功提交",
            "actual_result": "接口返回 500",
            "environment": "测试",
        },
        headers=actors["dev"],
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_bug_registration_confirmation_multi_tasks_and_verification_close(client, actors):
    bug = _register_bug(client, actors)
    assert bug["status"] == "registered"
    assert bug["product_manager_id"] == actors["pm_id"]

    forbidden = client.get("/api/task-management/bugs", headers=actors["requester"])
    assert forbidden.status_code == 403

    confirmed = client.post(
        f"/api/task-management/bugs/{bug['id']}/confirm",
        json={"comment": "确认属于供应链系统缺陷"},
        headers=actors["pm"],
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] == "confirmed"
    assert confirmed.json()["data"]["dev_leader_id"] == actors["leader_id"]

    generated = client.post(
        f"/api/task-management/bugs/{bug['id']}/fix-tasks",
        json={
            "tasks": [
                {"name": "修复订单接口", "task_type": "开发", "assignee": actors["dev_id"], "plan_effort": 1.5},
                {"name": "补充回归测试", "task_type": "测试", "assignee": actors["leader_id"], "plan_effort": 0.5},
            ]
        },
        headers=actors["leader"],
    )
    assert generated.status_code == 200, generated.text
    with SessionLocal() as db:
        instance = db.query(ProcessInstance).filter(ProcessInstance.entity_type == "bug", ProcessInstance.entity_id == bug["id"]).one()
        current = db.query(ProcessTask).filter(
            ProcessTask.instance_id == instance.id,
            ProcessTask.status == "待处理",
            ProcessTask.is_deleted.is_(False),
        ).one()
        assert current.step.seq == 4
        assert current.assignee is None
    tasks = generated.json()["data"]["tasks"]
    assert len(tasks) == 2

    for task in tasks:
        response = client.patch(
            f"/api/task-management/bug-fix-tasks/{task['id']}",
            json={"status": "排期"},
            headers=actors["leader"] if task["assignee"] == actors["leader_id"] else actors["dev"],
        )
        assert response.status_code == 200, response.text
        response = client.patch(
            f"/api/task-management/bug-fix-tasks/{task['id']}",
            json={"status": "执行"},
            headers=actors["leader"] if task["assignee"] == actors["leader_id"] else actors["dev"],
        )
        assert response.status_code == 200, response.text
        response = client.patch(
            f"/api/task-management/bug-fix-tasks/{task['id']}",
            json={"status": "关闭", "actual_effort": 1, "completion_note": "已完成并自测"},
            headers=actors["leader"] if task["assignee"] == actors["leader_id"] else actors["dev"],
        )
        assert response.status_code == 200, response.text

    verified = client.post(
        f"/api/task-management/bugs/{bug['id']}/verify",
        json={"verified": True, "note": "产品经理验证通过"},
        headers=actors["pm"],
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["data"]["status"] == "closed"

    listed = client.get("/api/task-management/bugs?q=供应链接口", headers=actors["dev"])
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


def test_bug_reject_and_reopen_keep_reason(client, actors):
    bug = _register_bug(client, actors, "需要补充证据的 Bug")
    rejected = client.post(
        f"/api/task-management/bugs/{bug['id']}/reject-confirm",
        json={"reason": "当前证据不足，请补充完整复现步骤"},
        headers=actors["pm"],
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["status"] == "rejected"

    reopened = client.post(
        f"/api/task-management/bugs/{bug['id']}/reopen",
        json={"reason": "补充日志后重新提交确认"},
        headers=actors["dev"],
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["data"]["status"] == "registered"


def test_bug_verification_rejection_reopens_fix_stage(client, actors):
    bug = _register_bug(client, actors, "验证不通过后重新修复")
    assert client.post(
        f"/api/task-management/bugs/{bug['id']}/confirm", json={}, headers=actors["pm"]
    ).status_code == 200
    generated = client.post(
        f"/api/task-management/bugs/{bug['id']}/fix-tasks",
        json={"tasks": [{"name": "修复并回归", "task_type": "开发", "assignee": actors["dev_id"]}]},
        headers=actors["leader"],
    )
    assert generated.status_code == 200, generated.text
    task_id = generated.json()["data"]["tasks"][0]["id"]
    for status in ("排期", "执行", "关闭"):
        response = client.patch(
            f"/api/task-management/bug-fix-tasks/{task_id}",
            json={"status": status},
            headers=actors["dev"],
        )
        assert response.status_code == 200, response.text
    rejected = client.post(
        f"/api/task-management/bugs/{bug['id']}/verify",
        json={"verified": False, "note": "仍可复现，请继续修复"},
        headers=actors["pm"],
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["status"] == "fixing"
    assert rejected.json()["data"]["fix_tasks"][0]["status"] == "执行"
