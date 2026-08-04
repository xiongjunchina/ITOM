import pytest

from app.core.config import settings
from app.db import SessionLocal
from app.models import Ci, ProcessInstance, ProcessTask


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


def test_cmdb_requires_product_manager_for_new_app_and_legacy_ci_can_be_repaired(client, actors):
    """新应用 CI 强制配置产品经理；历史空值仍能在 CMDB 补配后进入 Bug 流程。"""
    missing_on_create = client.post(
        "/api/cis",
        json={"name": "M84 后补产品经理系统", "category": "app", "owner": actors["dev_id"]},
        headers=actors["admin"],
    )
    assert missing_on_create.status_code == 422
    assert missing_on_create.json()["error"]["code"] == "PRODUCT_MANAGER_REQUIRED"
    with SessionLocal() as db:
        ci = Ci(ci_code="CI-M84-LEGACY", name="M84 历史应用系统", category="app", owner=actors["dev_id"])
        db.add(ci)
        db.commit()
        ci_id = ci.id

    missing_pm = client.post(
        "/api/task-management/bugs",
        json={"title": "M84 产品经理缺失", "description": "验证缺少产品经理时被拦截", "ci_id": ci_id},
        headers=actors["dev"],
    )
    assert missing_pm.status_code == 400
    assert missing_pm.json()["error"]["code"] == "PRODUCT_MANAGER_REQUIRED"

    configured = client.patch(
        f"/api/cis/{ci_id}",
        json={"product_manager_id": actors["pm_id"]},
        headers=actors["admin"],
    )
    assert configured.status_code == 200, configured.text

    registered = client.post(
        "/api/task-management/bugs",
        json={"title": "M84 产品经理已补配", "description": "验证 Bug 读取 CMDB 产品经理", "ci_id": ci_id},
        headers=actors["dev"],
    )
    assert registered.status_code == 200, registered.text
    assert registered.json()["data"]["product_manager_id"] == actors["pm_id"]


def test_bug_supports_evidence_attachment_upload_and_download(client, actors, tmp_path, monkeypatch):
    """Bug 创建后可使用通用附件能力上传截图，并在详情下载。"""
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    bug = _register_bug(client, actors, "带截图证据的 Bug")

    uploaded = client.post(
        f"/api/attachments?entity_type=bug&entity_id={bug['id']}",
        files={"file": ("error-screen.png", b"fake-png-content", "image/png")},
        headers=actors["dev"],
    )
    assert uploaded.status_code == 200, uploaded.text
    attachment = uploaded.json()["data"]
    assert attachment["filename"] == "error-screen.png"

    listed = client.get(
        f"/api/attachments?entity_type=bug&entity_id={bug['id']}", headers=actors["dev"]
    )
    assert listed.status_code == 200, listed.text
    assert [row["filename"] for row in listed.json()["data"]] == ["error-screen.png"]

    downloaded = client.get(f"/api/attachments/{attachment['id']}/download", headers=actors["dev"])
    assert downloaded.status_code == 200
    assert downloaded.content == b"fake-png-content"

    for endpoint in (
        f"/api/attachments?entity_type=bug&entity_id={bug['id']}",
        f"/api/attachments/{attachment['id']}/download",
    ):
        response = client.get(endpoint, headers=actors["requester"])
        assert response.status_code == 403

    forbidden_upload = client.post(
        f"/api/attachments?entity_type=bug&entity_id={bug['id']}",
        files={"file": ("not-allowed.txt", b"not-allowed", "text/plain")},
        headers=actors["requester"],
    )
    assert forbidden_upload.status_code == 403


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
