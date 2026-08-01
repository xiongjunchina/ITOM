import pytest


@pytest.fixture(scope="module")
def work_actor(client, admin_headers):
    member = client.post("/api/members", json={"name": "委派任务登记人"}, headers=admin_headers).json()["data"]
    client.post(
        "/api/admin/users",
        json={"username": "m82_work_actor", "password": "pass123", "roles": ["it_dev"], "person_id": member["id"]},
        headers=admin_headers,
    )
    token = client.post("/api/auth/login", json={"username": "m82_work_actor", "password": "pass123"}).json()["data"]["token"]
    return {"admin": admin_headers, "actor": {"Authorization": f"Bearer {token}"}, "person_id": member["id"]}


def test_unassigned_registered_task_can_be_deleted_by_registrar(client, work_actor):
    created = client.post(
        "/api/task-management/work-tasks",
        json={"title": "研究新型监控方案", "description": "评估是否引入", "task_type": "技术研究"},
        headers=work_actor["actor"],
    )
    assert created.status_code == 200, created.text
    task_id = created.json()["data"]["id"]
    deleted = client.delete(f"/api/task-management/work-tasks/{task_id}", headers=work_actor["actor"])
    assert deleted.status_code == 200, deleted.text

def test_assigned_task_uses_lightweight_lifecycle_and_admin_actions(client, work_actor):
    created = client.post(
        "/api/task-management/work-tasks",
        json={
            "title": "补充供应链系统监控项",
            "description": "为现有系统补充监控",
            "task_type": "系统优化",
            "assignee": work_actor["person_id"],
        },
        headers=work_actor["actor"],
    )
    assert created.status_code == 200, created.text
    task_id = created.json()["data"]["id"]

    forbidden = client.delete(f"/api/task-management/work-tasks/{task_id}", headers=work_actor["actor"])
    assert forbidden.status_code == 403

    for status in ("排期", "执行", "暂停", "执行", "关闭"):
        response = client.post(
            f"/api/task-management/work-tasks/{task_id}/transition",
            json={"to": status, "reason": "管理员推进任务"},
            headers=work_actor["admin"],
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == status

    deleted = client.delete(f"/api/task-management/work-tasks/{task_id}", headers=work_actor["admin"])
    assert deleted.status_code == 200, deleted.text
