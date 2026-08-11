"""M84：任务关联可后补、追加式进度、项目开发和任务通知闭环。"""

from datetime import date, timedelta

import pytest


@pytest.fixture(scope="module")
def task_users(client, admin_headers):
    def create_user(name: str, username: str):
        member = client.post(
            "/api/members", json={"name": name}, headers=admin_headers,
        ).json()["data"]
        created = client.post(
            "/api/admin/users",
            json={
                "username": username,
                "password": "pass123",
                "roles": ["it_dev"],
                "person_id": member["id"],
            },
            headers=admin_headers,
        )
        assert created.status_code == 200, created.text
        token = client.post(
            "/api/auth/login", json={"username": username, "password": "pass123"},
        ).json()["data"]["token"]
        return member["id"], {"Authorization": f"Bearer {token}"}

    registrar_id, registrar = create_user("M84任务登记人", "m84_registrar")
    assignee_id, assignee = create_user("M84任务处理人", "m84_assignee")
    return {
        "admin": admin_headers,
        "registrar_id": registrar_id,
        "registrar": registrar,
        "assignee_id": assignee_id,
        "assignee": assignee,
    }


def _notification_titles(client, headers):
    response = client.get("/api/notifications", headers=headers)
    assert response.status_code == 200, response.text
    return [row["title"] for row in response.json()["data"]]


def test_requirement_task_can_start_unlinked_and_notify_progress(client, task_users):
    created = client.post(
        "/api/requirements/tasks",
        json={
            "name": "先开发后补需求关联",
            "description": "登记时不强制选择需求",
            "assignee": task_users["assignee_id"],
        },
        headers=task_users["registrar"],
    )
    assert created.status_code == 200, created.text
    task_id = created.json()["data"]["id"]
    assert any(
        title.startswith("开发任务指派：先开发后补需求关联")
        for title in _notification_titles(client, task_users["assignee"])
    )

    rows = client.get(
        "/api/requirements/tasks/active", headers=task_users["registrar"],
    ).json()["data"]
    task = next(row for row in rows if row["id"] == task_id)
    assert task["requirement_id"] is None
    assert task["requirement_code"] is None

    progressed = client.patch(
        f"/api/requirements/tasks/{task_id}",
        json={"status": "进行中", "actual_effort": 0.5},
        headers=task_users["assignee"],
    )
    assert progressed.status_code == 200, progressed.text
    assert any(
        title.startswith("需求开发任务进度更新：先开发后补需求关联")
        for title in _notification_titles(client, task_users["registrar"])
    )

    forbidden = client.delete(
        f"/api/requirements/tasks/{task_id}", headers=task_users["assignee"],
    )
    assert forbidden.status_code == 403
    assert client.delete(
        f"/api/requirements/tasks/{task_id}", headers=task_users["admin"],
    ).status_code == 200


def test_delegated_task_progress_is_append_only_and_notifies_registrar(client, task_users):
    created = client.post(
        "/api/task-management/work-tasks",
        json={
            "title": "追加式委派任务进度",
            "description": "每次进度批注都保留",
            "task_type": "跨团队支持",
            "assignee": task_users["assignee_id"],
        },
        headers=task_users["registrar"],
    )
    assert created.status_code == 200, created.text
    task_id = created.json()["data"]["id"]

    for percent, comment in ((30, "已完成现状访谈"), (60, "方案已提交评审")):
        response = client.post(
            f"/api/task-management/work-tasks/{task_id}/progress",
            json={"progress_percent": percent, "comment": comment},
            headers=task_users["assignee"],
        )
        assert response.status_code == 200, response.text

    detail = client.get(
        f"/api/task-management/work-tasks/{task_id}", headers=task_users["registrar"],
    ).json()["data"]
    assert [row["comment"] for row in detail["progress_entries"]] == [
        "方案已提交评审", "已完成现状访谈",
    ]
    assert sum(
        title.startswith("委派任务进度更新：追加式委派任务进度")
        for title in _notification_titles(client, task_users["registrar"])
    ) == 2

    admin_created = client.post(
        "/api/task-management/work-tasks",
        json={
            "title": "管理员登记委派任务",
            "description": "内置管理员无需绑定组织人员",
            "task_type": "其他",
            "assignee": task_users["assignee_id"],
        },
        headers=task_users["admin"],
    )
    assert admin_created.status_code == 200, admin_created.text
    assert admin_created.json()["data"]["registrar"] is None


def test_project_development_task_requires_project_but_not_wbs(client, task_users):
    today = date.today()
    project = client.post(
        "/api/projects",
        json={
            "name": "M84项目开发任务测试",
            "pm": task_users["registrar_id"],
            "planned_start": str(today),
            "planned_end": str(today + timedelta(days=30)),
        },
        headers=task_users["admin"],
    )
    assert project.status_code == 200, project.text
    project_id = project.json()["data"]["id"]

    created = client.post(
        "/api/task-management/project-tasks",
        json={
            "project_id": project_id,
            "title": "补充接口开发任务",
            "description": "WBS 未拆到开发活动时补充登记",
            "assignee": task_users["assignee_id"],
        },
        headers=task_users["registrar"],
    )
    assert created.status_code == 200, created.text
    row = created.json()["data"]
    task_id = row["id"]
    assert row["project_id"] == project_id
    assert row["wbs_task_id"] is None

    admin_created = client.post(
        "/api/task-management/project-tasks",
        json={
            "project_id": project_id,
            "title": "管理员补充项目开发任务",
            "description": "验证管理员隐式全权",
            "assignee": task_users["assignee_id"],
        },
        headers=task_users["admin"],
    )
    assert admin_created.status_code == 200, admin_created.text
    assert admin_created.json()["data"]["registrar"] is None

    progressed = client.patch(
        f"/api/task-management/project-tasks/{task_id}",
        json={"status": "进行中", "actual_effort": 1.5},
        headers=task_users["assignee"],
    )
    assert progressed.status_code == 200, progressed.text
    progressed_row = progressed.json()["data"]
    assert progressed_row["progress_entries"][0]["status_snapshot"] == "进行中"

    added = client.post(
        f"/api/task-management/project-tasks/{task_id}/progress",
        json={"progress_percent": 50, "comment": "接口联调完成一半"},
        headers=task_users["assignee"],
    )
    assert added.status_code == 200, added.text
    assert len(added.json()["data"]["progress_entries"]) == 2
    assert any(
        title.startswith("项目开发任务进度更新：补充接口开发任务")
        for title in _notification_titles(client, task_users["registrar"])
    )

    assert client.delete(
        f"/api/task-management/project-tasks/{task_id}",
        headers=task_users["assignee"],
    ).status_code == 403
    assert client.delete(
        f"/api/task-management/project-tasks/{task_id}",
        headers=task_users["admin"],
    ).status_code == 200
