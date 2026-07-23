"""学习成长目标：进度、佐证和团队贡献积分折算。"""


def _member_and_user(client, admin_headers, name, username, roles):
    member = client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]
    client.post(
        "/api/admin/users",
        json={"username": username, "password": "pass123", "roles": roles, "person_id": member["id"]},
        headers=admin_headers,
    )
    token = client.post("/api/auth/login", json={"username": username, "password": "pass123"}).json()["data"]["token"]
    return member["id"], {"Authorization": f"Bearer {token}"}


def test_learning_growth_goal_progress_syncs_team_contribution(client, admin_headers):
    person_id, headers = _member_and_user(client, admin_headers, "学习成长员工", "learning_growth_user", ["it_dev"])
    first = client.post("/api/team/learning-growth", json={
        "period": "2026-Q3",
        "goal": "完成数据库性能调优实验",
        "target_description": "输出实验报告并完成分享",
        "progress": 50,
        "evidence": "报告链接 https://example.test/report",
        "note": "已完成基准测试",
    }, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["points"] == 15.0
    first_id = first.json()["data"]["id"]

    second = client.post("/api/team/learning-growth", json={
        "period": "2026-Q3", "goal": "完成安全认证课程", "progress": 100,
    }, headers=headers)
    assert second.status_code == 200, second.text
    # 两个目标等权：50% + 100% 的平均进度对应 22.5/30 分。
    items = client.get("/api/team/learning-growth", params={"period": "2026-Q3"}, headers=headers).json()["data"]
    assert len(items) == 2
    assert round(sum(item["points"] for item in items), 2) == 22.5

    recompute = client.post("/api/admin/performance/2026-Q3/recompute", headers=admin_headers)
    assert recompute.status_code == 200, recompute.text
    row = next(item for item in recompute.json()["data"]["rows"] if item["person_id"] == person_id)
    assert row["team_contribution_dimensions"]["learning_growth"] == 75.0

    updated = client.patch(f"/api/team/learning-growth/{first_id}", json={"progress": 100}, headers=headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["points"] == 15.0
    recompute = client.post("/api/admin/performance/2026-Q3/recompute", headers=admin_headers)
    row = next(item for item in recompute.json()["data"]["rows"] if item["person_id"] == person_id)
    assert row["team_contribution_dimensions"]["learning_growth"] == 100.0

    deleted = client.delete(f"/api/team/learning-growth/{second.json()['data']['id']}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    items = client.get("/api/team/learning-growth", params={"period": "2026-Q3"}, headers=headers).json()["data"]
    assert len(items) == 1 and items[0]["points"] == 30.0
