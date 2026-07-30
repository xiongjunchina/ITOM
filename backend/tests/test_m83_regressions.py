"""M83 回归测试：活动积分隔离与人效角色快照刷新。"""

from app.db import SessionLocal
from app.models import PointEntry
from app.services.points import current_period


def _member_and_user(client, admin_headers, name, username, roles):
    member = client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]
    user = client.post(
        "/api/admin/users",
        json={"username": username, "password": "pass123", "roles": roles, "person_id": member["id"]},
        headers=admin_headers,
    )
    assert user.status_code == 200, user.text
    token = client.post("/api/auth/login", json={"username": username, "password": "pass123"}).json()["data"]["token"]
    return member["id"], user.json()["data"]["id"], {"Authorization": f"Bearer {token}"}


def test_activity_points_exclude_role_result_entries(client, admin_headers):
    person_id, _, user_headers = _member_and_user(client, admin_headers, "M83积分隔离", "m83_points", ["it_dev"])
    period = current_period()
    with SessionLocal() as db:
        db.add(PointEntry(person_id=person_id, points=50, source_type="milestone_achieved", period=period, contribution_bucket="role_result"))
        db.add(PointEntry(person_id=person_id, points=7, source_type="special_activity", period=period, contribution_bucket="team_contribution"))
        db.commit()

    leaderboard = client.get(f"/api/points/leaderboard?period={period}", headers=admin_headers)
    assert leaderboard.status_code == 200, leaderboard.text
    row = next(item for item in leaderboard.json()["data"]["board"] if item["person_name"] == "M83积分隔离")
    assert row["points"] == 7
    assert row["breakdown"] == [{"source_type": "special_activity", "points": 7.0}]

    mine = client.get("/api/points/mine", headers=user_headers)
    assert mine.status_code == 200, mine.text
    assert mine.json()["data"]["period_total"] == 7
    assert {item["source_type"] for item in mine.json()["data"]["entries"]} == {"special_activity"}

    overview = client.get("/api/team/overview", headers=admin_headers)
    assert overview.status_code == 200, overview.text
    overview_row = next(item for item in overview.json()["data"]["points_board"] if item["person_name"] == "M83积分隔离")
    assert overview_row["points"] == 7


def test_performance_overview_refreshes_role_snapshot_after_role_binding(client, admin_headers):
    person_id, user_id, _ = _member_and_user(client, admin_headers, "M83角色刷新", "m83_role_refresh", [])
    first = client.get("/api/team/performance/overview?period=2031-Q1", headers=admin_headers)
    assert first.status_code == 200, first.text

    updated = client.patch(f"/api/admin/users/{user_id}", json={"roles": ["it_dev"]}, headers=admin_headers)
    assert updated.status_code == 200, updated.text

    refreshed = client.get("/api/team/performance/overview?period=2031-Q1", headers=admin_headers)
    assert refreshed.status_code == 200, refreshed.text
    row = next(item for item in refreshed.json()["data"]["rows"] if item["person_id"] == person_id)
    assert any(role["role_code"] == "it_dev" for role in row["roles"])
