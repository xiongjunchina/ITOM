from datetime import date

from app.db import SessionLocal
from app.events.bus import publish
from app.models import PointEntry
from app.services.perf import _score_bug_fix_delivery, _score_delegated_work_delivery, period_range


def _person_and_user(client, admin_headers, name: str, username: str, roles: list[str]):
    member = client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]
    created = client.post(
        "/api/admin/users",
        json={"username": username, "password": "pass123", "roles": roles, "person_id": member["id"]},
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    token = client.post("/api/auth/login", json={"username": username, "password": "pass123"}).json()["data"]["token"]
    return member["id"], {"Authorization": f"Bearer {token}"}


def test_bug_and_delegated_delivery_metrics_and_idempotent_points(client, admin_headers):
    dev_id, dev_headers = _person_and_user(client, admin_headers, "M82绩效开发", "m82_perf_dev", ["it_dev"])
    pm_id, pm_headers = _person_and_user(client, admin_headers, "M82绩效产品", "m82_perf_pm", ["it_pdm"])
    leader_id, leader_headers = _person_and_user(client, admin_headers, "M82绩效负责人", "m82_perf_leader", ["it_dev_leader"])
    ci = client.post(
        "/api/cis",
        json={"name": "M82绩效系统", "category": "app", "owner": dev_id, "product_manager_id": pm_id},
        headers=admin_headers,
    ).json()["data"]

    bug = client.post(
        "/api/task-management/bugs",
        json={"title": "M82绩效 Bug", "description": "用于验证交付指标", "ci_id": ci["id"]},
        headers=dev_headers,
    ).json()["data"]
    assert client.post(f"/api/task-management/bugs/{bug['id']}/confirm", json={}, headers=pm_headers).status_code == 200
    generated = client.post(
        f"/api/task-management/bugs/{bug['id']}/fix-tasks",
        json={"tasks": [{"name": "修复指标样例", "assignee": dev_id, "plan_date": date.today().isoformat()}]},
        headers=leader_headers,
    )
    assert generated.status_code == 200, generated.text
    fix_id = generated.json()["data"]["tasks"][0]["id"]
    for status in ("排期", "执行", "关闭"):
        response = client.patch(
            f"/api/task-management/bug-fix-tasks/{fix_id}", json={"status": status}, headers=dev_headers,
        )
        assert response.status_code == 200, response.text

    work = client.post(
        "/api/task-management/work-tasks",
        json={
            "title": "M82绩效委派样例", "description": "用于验证委派交付指标", "task_type": "系统优化",
            "assignee": dev_id, "plan_date": date.today().isoformat(),
        },
        headers=dev_headers,
    )
    assert work.status_code == 200, work.text
    work_id = work.json()["data"]["id"]
    for status in ("排期", "执行", "关闭"):
        response = client.post(
            f"/api/task-management/work-tasks/{work_id}/transition",
            json={"to": status, "reason": "完成"}, headers=admin_headers,
        )
        assert response.status_code == 200, response.text
    with SessionLocal() as db:
        start, end = period_range(f"{date.today().year}-Q{(date.today().month - 1) // 3 + 1}")
        assert _score_bug_fix_delivery(db, [dev_id], start, end)[dev_id] == 100.0
        assert _score_delegated_work_delivery(db, [dev_id], start, end)[dev_id] == 100.0
        # 同一领域事件被重复投递时，不得重复发放积分。
        publish(db, "work_task.closed", "work_task", work_id, {"task_code": work_id})
        publish(db, "work_task.closed", "work_task", work_id, {"task_code": work_id})
        db.commit()
        fix_points = db.query(PointEntry).filter(PointEntry.source_type == "bug_fix_task_done", PointEntry.source_ref == fix_id).all()
        work_points = db.query(PointEntry).filter(PointEntry.source_type == "delegated_work_done", PointEntry.source_ref == work_id).all()
        assert len(fix_points) == 1 and fix_points[0].contribution_bucket == "role_result"
        assert len(work_points) == 1 and work_points[0].contribution_bucket == "role_result"

    invalid_team_bucket = client.post(
        "/api/task-management/work-tasks",
        json={"title": "不合规团队贡献映射", "description": "必须拒绝", "task_type": "系统优化", "performance_bucket": "team_contribution"},
        headers=dev_headers,
    )
    assert invalid_team_bucket.status_code == 400
    assert invalid_team_bucket.json()["error"]["code"] == "INVALID_PERFORMANCE_CATEGORY"

    team_task = client.post(
        "/api/task-management/work-tasks",
        json={
            "title": "技术研究团队贡献", "description": "明确归入学习成长", "task_type": "技术研究",
            "performance_bucket": "team_contribution", "assignee": dev_id,
        },
        headers=dev_headers,
    )
    assert team_task.status_code == 200, team_task.text
    team_id = team_task.json()["data"]["id"]
    for status in ("排期", "执行", "关闭"):
        assert client.post(
            f"/api/task-management/work-tasks/{team_id}/transition",
            json={"to": status, "reason": "完成"}, headers=admin_headers,
        ).status_code == 200
    with SessionLocal() as db:
        entry = db.query(PointEntry).filter(PointEntry.source_type == "work_task_learning_growth", PointEntry.source_ref == team_id).one()
        assert entry.contribution_bucket == "team_contribution"
        assert entry.contribution_dimension == "learning_growth"
