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

    # 置 50 → 仍已延期（已过计划结束）；填写不晚于今天的实际结束后自动完成。
    client.patch(f"/api/wbs/{t['id']}", json={"progress": 50}, headers=h)
    row = next(w for w in client.get(f"/api/projects/{pid}/wbs", headers=h).json()["data"] if w["id"] == t["id"])
    assert row["status"] == "已延期"
    client.patch(f"/api/wbs/{t['id']}", json={"actual_end": str(TODAY)}, headers=h)
    row = next(w for w in client.get(f"/api/projects/{pid}/wbs", headers=h).json()["data"] if w["id"] == t["id"])
    assert row["progress"] == 100 and row["status"] == "已完成"
    assert row["schedule_deviation"] == 1  # 实际结束(今天) - 计划结束(昨天)


def test_wbs_actual_date_completion_lock_and_reopen(client, ctx):
    """实际结束触发完成；未来日期、完成锁定、重开冲突及日期先后关系均由服务端兜底。"""
    pid, h = ctx["pid"], ctx["h"]
    task = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "实际日期规则任务", "assignee": ctx["dev"],
        "start_date": str(TODAY - timedelta(days=5)), "end_date": str(TODAY + timedelta(days=5)),
    }, headers=h).json()["data"]

    future = client.patch(
        f"/api/wbs/{task['id']}",
        json={"actual_end": str(TODAY + timedelta(days=1))},
        headers=h,
    )
    assert future.status_code == 400
    assert future.json()["error"]["code"] == "WBS_ACTUAL_END_IN_FUTURE"

    invalid_range = client.patch(
        f"/api/wbs/{task['id']}",
        json={"actual_start": str(TODAY), "actual_end": str(TODAY - timedelta(days=1))},
        headers=h,
    )
    assert invalid_range.status_code == 400
    assert invalid_range.json()["error"]["code"] == "WBS_ACTUAL_DATES_INVALID"

    completed = client.patch(
        f"/api/wbs/{task['id']}",
        json={"actual_start": str(TODAY - timedelta(days=2)), "actual_end": str(TODAY)},
        headers=h,
    )
    assert completed.status_code == 200
    completed_row = completed.json()["data"]
    assert completed_row["progress"] == 100 and completed_row["status"] == "已完成"
    assert completed_row["actual_end"] == str(TODAY)
    first_completed_at = completed_row["completed_at"]
    assert first_completed_at is not None and completed_row["completed_locked"] is True

    locked = client.patch(
        f"/api/wbs/{task['id']}",
        json={"actual_start": str(TODAY - timedelta(days=3))},
        headers=h,
    )
    assert locked.status_code == 400
    assert locked.json()["error"]["code"] == "WBS_ACTUAL_DATES_LOCKED"

    conflict = client.patch(
        f"/api/wbs/{task['id']}",
        json={"progress": 50, "actual_end": str(TODAY - timedelta(days=1))},
        headers=h,
    )
    assert conflict.status_code == 400
    assert conflict.json()["error"]["code"] == "WBS_REOPEN_ACTUAL_DATES_CONFLICT"
    assert conflict.json()["error"]["message"] == "请先重新打开任务，再修改实际日期"

    reopened = client.patch(f"/api/wbs/{task['id']}", json={"progress": 50}, headers=h)
    assert reopened.status_code == 200
    reopened_row = reopened.json()["data"]
    assert reopened_row["progress"] == 50 and reopened_row["completed_locked"] is False
    assert reopened_row["actual_end"] is None
    assert reopened_row["actual_start"] == str(TODAY - timedelta(days=2))
    assert reopened_row["completed_at"] == first_completed_at

    recompleted = client.patch(
        f"/api/wbs/{task['id']}",
        json={"actual_start": str(TODAY - timedelta(days=3)), "actual_end": str(TODAY - timedelta(days=1))},
        headers=h,
    )
    assert recompleted.status_code == 200
    assert recompleted.json()["data"]["progress"] == 100
    assert recompleted.json()["data"]["completed_at"] == first_completed_at


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

    # 已完成父项是交付基线，不允许再新增子项改变其层级或完成度。
    child_c = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "新增校验", "assignee": ctx["dev"], "parent_task_id": root["id"],
        "start_date": str(TODAY), "end_date": str(TODAY + timedelta(days=1)),
    }, headers=h)
    assert child_c.status_code == 400
    assert child_c.json()["error"]["code"] == "WBS_STRUCTURE_LOCKED"

    # 项目汇总只按末级任务计权，父项不会因级联而重复计入。
    detail = client.get(f"/api/projects/{pid}", headers=h).json()["data"]
    assert detail["progress"] == 100.0 and detail["task_total"] == 2 and detail["task_done"] == 2


def test_wbs_structure_move_and_completion_lock(client, ctx):
    """当前 100% 任务锁定结构；修正回非 100% 后立即解锁且保留完成审计时间。"""
    h = ctx["h"]
    project = client.post("/api/projects", json={
        "name": "M9 WBS 结构调整项目", "pm": ctx["pm"],
        "planned_start": str(TODAY), "planned_end": str(TODAY + timedelta(days=30)),
    }, headers=h).json()["data"]
    pid = project["id"]
    root_a = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "一级 A", "assignee": ctx["pm"],
        "start_date": str(TODAY), "end_date": str(TODAY + timedelta(days=10)),
    }, headers=h).json()["data"]
    root_b = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "一级 B", "assignee": ctx["pm"],
        "start_date": str(TODAY), "end_date": str(TODAY + timedelta(days=10)),
    }, headers=h).json()["data"]
    child = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "待移动子任务", "assignee": ctx["dev"], "parent_task_id": root_a["id"],
        "start_date": str(TODAY), "end_date": str(TODAY + timedelta(days=5)),
    }, headers=h).json()["data"]

    # 同时调整层级与顺序：将子任务移到一级 B 下，WBS 编号随之重建。
    moved = client.post(f"/api/wbs/{child['id']}/move", json={
        "parent_task_id": root_b["id"], "before_task_id": None,
    }, headers=h)
    assert moved.status_code == 200
    rows = {row["id"]: row for row in client.get(f"/api/projects/{pid}/wbs", headers=h).json()["data"]}
    assert rows[child["id"]]["parent_task_id"] == root_b["id"]
    assert rows[root_a["id"]]["wbs_code"] == "1"
    assert rows[root_b["id"]]["wbs_code"] == "2"
    assert rows[child["id"]]["wbs_code"] == "2.1"

    # 未开始的一级 B 可排序到一级 A 前，其未开始子任务随树一起保留层级。
    reordered = client.post(f"/api/wbs/{root_b['id']}/move", json={
        "parent_task_id": None, "before_task_id": root_a["id"],
    }, headers=h)
    assert reordered.status_code == 200
    rows = {row["id"]: row for row in client.get(f"/api/projects/{pid}/wbs", headers=h).json()["data"]}
    assert rows[root_b["id"]]["wbs_code"] == "1"
    assert rows[child["id"]]["wbs_code"] == "1.1"
    assert rows[root_a["id"]]["wbs_code"] == "2"

    # 移动到自身的后代会形成循环，必须拒绝。
    cycle = client.post(f"/api/wbs/{root_b['id']}/move", json={
        "parent_task_id": child["id"], "before_task_id": None,
    }, headers=h)
    assert cycle.status_code == 400
    assert cycle.json()["error"]["code"] == "WBS_CYCLE"

    # 完成即成为交付记录：不允许删除，也不允许再做结构性调整。
    assert client.patch(f"/api/wbs/{child['id']}", json={"progress": 100}, headers=h).status_code == 200
    deleted = client.delete(f"/api/wbs/{child['id']}", headers=h)
    assert deleted.status_code == 400
    assert deleted.json()["error"]["code"] == "WBS_COMPLETED_LOCKED"
    locked_move = client.post(f"/api/wbs/{child['id']}/move", json={
        "parent_task_id": None, "before_task_id": None,
    }, headers=h)
    assert locked_move.status_code == 400
    assert locked_move.json()["error"]["code"] == "WBS_STRUCTURE_LOCKED"

    completed_rows = {
        row["id"]: row
        for row in client.get(f"/api/projects/{pid}/wbs", headers=h).json()["data"]
    }
    first_completed_at = completed_rows[child["id"]]["completed_at"]
    assert first_completed_at is not None
    assert completed_rows[child["id"]]["completed_locked"] is True
    assert completed_rows[child["id"]]["structure_locked"] is True

    # 授权修正完成度后，应按当前进度重新开放结构操作；completed_at 只保留
    # 首次完成的审计证据，不能继续把任务锁死。
    corrected = client.patch(f"/api/wbs/{child['id']}", json={"progress": 50}, headers=h)
    assert corrected.status_code == 200
    corrected_rows = {
        row["id"]: row
        for row in client.get(f"/api/projects/{pid}/wbs", headers=h).json()["data"]
    }
    assert corrected_rows[child["id"]]["progress"] == 50
    assert corrected_rows[child["id"]]["completed_at"] == first_completed_at
    assert corrected_rows[child["id"]]["completed_locked"] is False
    assert corrected_rows[child["id"]]["structure_locked"] is False

    grandchild = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "修正后新增子任务", "assignee": ctx["dev"], "parent_task_id": child["id"],
        "start_date": str(TODAY), "end_date": str(TODAY + timedelta(days=2)),
    }, headers=h)
    assert grandchild.status_code == 200
    assert client.delete(f"/api/wbs/{grandchild.json()['data']['id']}", headers=h).status_code == 200

    unlocked_move = client.post(f"/api/wbs/{child['id']}/move", json={
        "parent_task_id": root_a["id"], "before_task_id": None,
    }, headers=h)
    assert unlocked_move.status_code == 200
    assert client.delete(f"/api/wbs/{child['id']}", headers=h).status_code == 200


def test_wbs_batch_delete_reuses_locks_and_deletes_children_first(client, ctx):
    """批量删除复用单条约束，并在父子同时选中时按子项优先执行。"""
    h = ctx["h"]
    project = client.post("/api/projects", json={
        "name": "M9 WBS 批量删除项目", "pm": ctx["pm"],
        "planned_start": str(TODAY), "planned_end": str(TODAY + timedelta(days=30)),
    }, headers=h).json()["data"]
    pid = project["id"]
    parent = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "待删除父任务", "assignee": ctx["pm"],
        "start_date": str(TODAY), "end_date": str(TODAY + timedelta(days=10)),
    }, headers=h).json()["data"]
    child = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "待删除子任务", "assignee": ctx["dev"], "parent_task_id": parent["id"],
        "start_date": str(TODAY), "end_date": str(TODAY + timedelta(days=5)),
    }, headers=h).json()["data"]
    completed = client.post(f"/api/projects/{pid}/wbs", json={
        "name": "已完成保留任务", "assignee": ctx["dev"],
        "start_date": str(TODAY), "end_date": str(TODAY + timedelta(days=5)),
    }, headers=h).json()["data"]
    assert client.patch(f"/api/wbs/{completed['id']}", json={"progress": 100}, headers=h).status_code == 200

    # 故意按父、完成、子顺序提交，服务端仍应先删子项再删父项。
    response = client.request(
        "DELETE",
        f"/api/projects/{pid}/wbs/batch-delete",
        json={"ids": [parent["id"], completed["id"], child["id"]]},
        headers=h,
    )
    assert response.status_code == 200
    result = response.json()["data"]
    assert set(result["deleted_ids"]) == {parent["id"], child["id"]}
    assert result["rejected"] == [{
        "id": completed["id"],
        "code": "WBS_COMPLETED_LOCKED",
        "message": "已完成的 WBS 任务是项目交付记录，不允许删除",
    }]
    remaining = client.get(f"/api/projects/{pid}/wbs", headers=h).json()["data"]
    assert [row["id"] for row in remaining] == [completed["id"]]
