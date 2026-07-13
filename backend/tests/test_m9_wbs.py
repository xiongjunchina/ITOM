"""M9：WBS 主表新字段——完成度%三档、状态/偏差计算、里程碑=WBS 标志、里程碑跟踪派生。"""
from datetime import date, timedelta

import pytest

TODAY = date.today()


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    pm = client.post("/api/members", json={"name": "M9PM"}, headers=admin_headers).json()["data"]["id"]
    dev = client.post("/api/members", json={"name": "M9DEV"}, headers=admin_headers).json()["data"]["id"]
    p = client.post("/api/projects", json={
        "name": "M9项目", "pm": pm, "planned_start": str(TODAY - timedelta(days=10)),
        "planned_end": str(TODAY + timedelta(days=30)),
    }, headers=admin_headers).json()["data"]
    return {"pid": p["id"], "pm": pm, "dev": dev, "h": admin_headers}


def test_wbs_new_fields_and_computed(client, ctx):
    pid, h = ctx["pid"], ctx["h"]
    t = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "需求规格说明书", "assignee": ctx["dev"], "stage": "1.立项",
        "wbs_dict": "含需求背景；不含供应商选型", "deliverable": "SRS 签字确认",
        "is_milestone": True, "remarks": "关键节点",
        "start_date": str(TODAY - timedelta(days=5)), "end_date": str(TODAY - timedelta(days=1)),
    }, headers=h).json()["data"]
    # 新字段回显 + 未完成且已过计划结束 → 已延期；未填实际结束 → 偏差 None
    assert t["stage"] == "1.立项" and t["wbs_dict"].startswith("含") and t["is_milestone"] is True
    assert t["progress"] == 0 and t["status"] == "已延期" and t["schedule_deviation"] is None

    # 完成度只能 0/50/100
    assert client.patch(f"/api/wbs/{t['id']}", json={"progress": 30}, headers=h).status_code == 400

    # 置 50 → 仍已延期（已过计划结束）；置 100 + 实际结束晚 2 天 → 已完成、偏差=+2
    client.patch(f"/api/wbs/{t['id']}", json={"progress": 50}, headers=h)
    row = next(w for w in client.get(f"/api/projects/{pid}/wbs", headers=h).json()["data"] if w["id"] == t["id"])
    assert row["status"] == "已延期"
    client.patch(f"/api/wbs/{t['id']}", json={"progress": 100, "actual_end": str(TODAY + timedelta(days=1))}, headers=h)
    row = next(w for w in client.get(f"/api/projects/{pid}/wbs", headers=h).json()["data"] if w["id"] == t["id"])
    assert row["status"] == "已完成" and row["schedule_deviation"] == 2  # 实际结束(计划结束+2) - 计划结束


def test_milestone_tracking_derived(client, ctx):
    pid, h = ctx["pid"], ctx["h"]
    # 追加一个非里程碑任务，确认不进跟踪；里程碑任务进跟踪
    client.post(f"/api/projects/{pid}/wbs", json={
        "name": "普通任务", "assignee": ctx["dev"],
        "start_date": str(TODAY), "end_date": str(TODAY + timedelta(days=3)),
    }, headers=h)
    track = client.get(f"/api/projects/{pid}/milestone-tracking", headers=h).json()["data"]
    assert all(r["name"] != "普通任务" for r in track)  # 仅里程碑=是 的行
    assert any(r["name"] == "需求规格说明书" for r in track)
    row = next(r for r in track if r["name"] == "需求规格说明书")
    assert set(row) >= {"wbs_code", "name", "stage", "assignee_name", "end_date", "actual_end", "schedule_deviation", "status"}


def test_predecessor_shown_as_wbs_code(client, ctx):
    pid, h = ctx["pid"], ctx["h"]
    a = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "前置A", "assignee": ctx["dev"], "start_date": str(TODAY), "end_date": str(TODAY + timedelta(days=2)),
    }, headers=h).json()["data"]
    b = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "后置B", "assignee": ctx["dev"], "predecessor_ids": [a["id"]],
        "start_date": str(TODAY + timedelta(days=3)), "end_date": str(TODAY + timedelta(days=5)),
    }, headers=h).json()["data"]
    wbs = client.get(f"/api/projects/{pid}/wbs", headers=h).json()["data"]
    row_b = next(w for w in wbs if w["id"] == b["id"])
    code_a = next(w for w in wbs if w["id"] == a["id"])["wbs_code"]
    assert row_b["predecessor_codes"] == [code_a]  # 前置按 WBS 号展示
