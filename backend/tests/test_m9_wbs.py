"""WBS 主表新字段——完成度 0-100%、状态/偏差计算、里程碑=WBS 标志、里程碑跟踪派生。"""
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

    # 完成度支持任意 0-100 整数，越界值拒绝
    assert client.patch(f"/api/wbs/{t['id']}", json={"progress": 30}, headers=h).json()["success"]
    assert client.patch(f"/api/wbs/{t['id']}", json={"progress": 101}, headers=h).status_code == 422

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


def test_wbs_progress_cascade_and_rollup(client, ctx):
    h = ctx["h"]
    project = client.post("/api/projects", json={
        "name": "M9层级进度项目", "pm": ctx["pm"],
        "planned_start": str(TODAY), "planned_end": str(TODAY + timedelta(days=30)),
    }, headers=h).json()["data"]
    pid = project["id"]
    root = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "平台建设", "assignee": ctx["pm"],
        "start_date": str(TODAY), "end_date": str(TODAY + timedelta(days=10)),
    }, headers=h).json()["data"]
    child_a = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "基础设施", "assignee": ctx["dev"], "parent_task_id": root["id"],
        "start_date": str(TODAY), "end_date": str(TODAY + timedelta(days=4)),
    }, headers=h).json()["data"]
    child_b = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "应用部署", "assignee": ctx["dev"], "parent_task_id": root["id"],
        "start_date": str(TODAY), "end_date": str(TODAY + timedelta(days=4)),
    }, headers=h).json()["data"]
    grandchild = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "数据库部署", "assignee": ctx["dev"], "parent_task_id": child_b["id"],
        "start_date": str(TODAY), "end_date": str(TODAY + timedelta(days=2)),
    }, headers=h).json()["data"]

    # 子项变更按直接子项平均值向上回算：50% 与 0% → 父项 25%。
    client.patch(f"/api/wbs/{child_a['id']}", json={"progress": 50}, headers=h)
    rows = {row["id"]: row for row in client.get(f"/api/projects/{pid}/wbs", headers=h).json()["data"]}
    assert rows[root["id"]]["progress"] == 25
    # 父级除显式 100% 外是派生值，直接提交其它比例也不会脱离子项平均值。
    client.patch(f"/api/wbs/{root['id']}", json={"progress": 75}, headers=h)
    rows = {row["id"]: row for row in client.get(f"/api/projects/{pid}/wbs", headers=h).json()["data"]}
    assert rows[root["id"]]["progress"] == 25

    # 显式将父项设为 100% 时，所有层级后代同步完成。
    client.patch(f"/api/wbs/{root['id']}", json={"progress": 100}, headers=h)
    rows = {row["id"]: row for row in client.get(f"/api/projects/{pid}/wbs", headers=h).json()["data"]}
    assert all(rows[item_id]["progress"] == 100 for item_id in (root["id"], child_a["id"], child_b["id"], grandchild["id"]))

    # 已完成父项新增子项后，父项立即恢复为新的子项平均值；再次显式完成可重新级联。
    child_c = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "新增校验", "assignee": ctx["dev"], "parent_task_id": root["id"],
        "start_date": str(TODAY), "end_date": str(TODAY + timedelta(days=1)),
    }, headers=h).json()["data"]
    rows = {row["id"]: row for row in client.get(f"/api/projects/{pid}/wbs", headers=h).json()["data"]}
    assert rows[root["id"]]["progress"] == 67 and rows[child_c["id"]]["progress"] == 0
    client.patch(f"/api/wbs/{root['id']}", json={"progress": 100}, headers=h)

    # 项目汇总只按末级任务计权，父项不会因级联而重复计入。
    detail = client.get(f"/api/projects/{pid}", headers=h).json()["data"]
    assert detail["progress"] == 100.0 and detail["task_total"] == 3 and detail["task_done"] == 3
