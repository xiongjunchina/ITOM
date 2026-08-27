"""M40 团队管理统一限定 IT 团队范围。"""

from app.db import SessionLocal
from app.models import Department, OrgMember, PointEntry, Position
from app.services.points import current_period


def _seed_scope_people():
    with SessionLocal() as db:
        it_dept = Department(code="m40_it", name="M40 信息技术部", dept_type="it")
        biz_dept = Department(code="m40_biz", name="M40 业务部", dept_type="business")
        pos = Position(name="M40 通用岗位", headcount=3)
        db.add_all([it_dept, biz_dept, pos]); db.flush()
        it_member = OrgMember(name="M40 IT成员", department_id=it_dept.id, position_id=pos.id)
        biz_member = OrgMember(name="M40 业务成员", department_id=biz_dept.id, position_id=pos.id)
        db.add_all([it_member, biz_member]); db.flush()
        db.add_all([
            PointEntry(person_id=it_member.id, points=10, source_type="manual", period=current_period()),
            PointEntry(person_id=biz_member.id, points=999, source_type="manual", period=current_period()),
        ])
        db.commit()
        return it_member.id, biz_member.id, pos.id


def test_team_endpoints_exclude_business_people(client, admin_headers):
    it_id, biz_id, pos_id = _seed_scope_people()
    members = client.get("/api/members?scope=it&page_size=2000", headers=admin_headers).json()["data"]
    member_ids = {m["id"] for m in members}
    assert it_id in member_ids and biz_id not in member_ids

    overview = client.get("/api/team/overview", headers=admin_headers).json()["data"]
    workload_names = {row["person_name"] for row in overview["workload"]}
    points_names = {row["person_name"] for row in overview["points_board"]}
    assert "M40 IT成员" in workload_names
    assert "M40 业务成员" not in workload_names | points_names

    board = client.get("/api/points/leaderboard", headers=admin_headers).json()["data"]["board"]
    assert "M40 IT成员" in {row["person_name"] for row in board}
    assert "M40 业务成员" not in {row["person_name"] for row in board}

    performance = client.get("/api/team/performance", headers=admin_headers).json()["data"]["rows"]
    assert "M40 IT成员" in {row["person_name"] for row in performance}
    assert "M40 业务成员" not in {row["person_name"] for row in performance}

    positions = client.get("/api/positions", headers=admin_headers).json()["data"]
    assert next(item for item in positions if item["id"] == pos_id)["onboard"] == 1


def test_team_overview_returns_every_active_it_member_workload(client, admin_headers):
    """团队总览的人员负载不可在后端静默截断为前 20 人。"""
    with SessionLocal() as db:
        department = Department(code="m94_workload", name="M94 负载测试部", dept_type="it")
        db.add(department)
        db.flush()
        names = {f"M94 负载成员 {index:02d}" for index in range(21)}
        db.add_all([OrgMember(name=name, department_id=department.id) for name in names])
        db.commit()

    overview = client.get("/api/team/overview", headers=admin_headers).json()["data"]
    workload_names = {row["person_name"] for row in overview["workload"]}
    assert names <= workload_names
    assert overview["onboard_count"] >= len(names)


def test_business_member_cannot_receive_team_campaign_award(client, admin_headers):
    with SessionLocal() as db:
        biz_id = db.query(OrgMember).filter(OrgMember.name == "M40 业务成员").first().id
    active = client.post("/api/campaigns", json={
        "name": "M40 IT团队活动", "period_label": "2026-Q3",
        "start_date": "2026-07-01", "end_date": "2026-09-30",
        "tasks": [{"name": "M40任务", "points": 5, "max_times": 1}],
    }, headers=admin_headers).json()["data"]
    client.post(f"/api/campaigns/{active['id']}/status", json={"status": "active"}, headers=admin_headers)
    response = client.post(
        f"/api/campaigns/{active['id']}/awards",
        json={"person_id": biz_id, "task_id": active["tasks"][0]["id"]}, headers=admin_headers,
    )
    assert response.json()["error"]["code"] == "NOT_IT_TEAM_MEMBER"
