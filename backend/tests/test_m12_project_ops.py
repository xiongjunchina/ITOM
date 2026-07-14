"""M12：项目重启(含流程回退) / 实际起止可编辑 / IT PMO 角色。"""
import pytest


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    m = client.post("/api/members", json={"name": "PM小赵M12"}, headers=admin_headers).json()["data"]
    p = client.post("/api/projects", json={
        "name": "M12重启验证项目", "pm": m["id"],
        "planned_start": "2026-07-01", "planned_end": "2026-09-30",
    }, headers=admin_headers).json()["data"]
    return {"pid": p["id"], "pm": m["id"]}


def _transition(client, headers, pid, to, fields=None):
    return client.post(f"/api/projects/{pid}/transition", json={"to": to, "fields": fields or {}}, headers=headers)


def _detail(client, headers, pid):
    return client.get(f"/api/projects/{pid}", headers=headers).json()["data"]


def test_pmo_role_and_project_flow(client, admin_headers, ctx):
    # 内置角色含 it_pmo，默认矩阵已种
    roles = client.get("/api/admin/roles", headers=admin_headers).json()["data"]
    pmo = next(r for r in roles if r["code"] == "it_pmo")
    assert pmo["is_builtin"] and "PMO" in pmo["name"]
    perms = client.get("/api/admin/permissions", params={"role": "it_pmo"}, headers=admin_headers).json()["data"]
    assert any(e["module"] == "projects" and "create" in e["actions"] for e in perms)

    # 新建项目的流程「收尾复盘」默认处理角色为 it_pmo
    d = _detail(client, admin_headers, ctx["pid"])
    closing = next(s for s in d["process"]["steps"] if s["name"] == "收尾复盘")
    assert closing["default_role"] == "it_pmo"


def test_actual_dates_editable_and_stamp_respect(client, admin_headers, ctx):
    pid = ctx["pid"]
    # 手动编辑实际起止
    r = client.patch(f"/api/projects/{pid}", json={"actual_start": "2026-07-02", "actual_end": "2026-09-01"},
                     headers=admin_headers)
    assert r.json()["success"], r.text
    d = _detail(client, admin_headers, pid)
    assert d["actual_start"] == "2026-07-02" and d["actual_end"] == "2026-09-01"

    # 转进行中：actual_start 已有值不覆盖
    _transition(client, admin_headers, pid, "active")
    d = _detail(client, admin_headers, pid)
    assert d["actual_start"] == "2026-07-02"

    # 转已完成：actual_end 已有手动值则尊重
    _transition(client, admin_headers, pid, "completed")
    d = _detail(client, admin_headers, pid)
    assert d["actual_end"] == "2026-09-01"


def test_restart_with_process_rewind(client, admin_headers, ctx):
    pid = ctx["pid"]
    d = _detail(client, admin_headers, pid)
    assert d["status"] == "completed"

    # 把流程推进到收尾复盘：完成 步骤1、步骤2
    for _ in range(2):
        d = _detail(client, admin_headers, pid)
        cur = next(s for s in d["process"]["steps"] if s["seq"] == d["process"]["current_step_seq"])
        assert cur["task_id"], d["process"]
        r = client.post(f"/api/process-tasks/{cur['task_id']}/complete", json={"comment": "阶段完成，材料齐备"},
                        headers=admin_headers)
        assert r.json()["success"], r.text
    d = _detail(client, admin_headers, pid)
    assert d["process"]["current_step_seq"] == 3  # 收尾复盘

    # 关闭（M14.1 起必填理由）→ 重启并回退到「执行监控」(seq=2)
    r = _transition(client, admin_headers, pid, "closed", fields={"reason": "项目验收完成，正式关闭"})
    assert r.json()["success"], r.text
    r = _transition(client, admin_headers, pid, "active", fields={"process_step_seq": 2})
    assert r.json()["data"]["status"] == "active", r.text

    d = _detail(client, admin_headers, pid)
    proc = d["process"]
    assert proc["status"] == "running" and proc["current_step_seq"] == 2
    step2 = next(s for s in proc["steps"] if s["seq"] == 2)
    step3 = next(s for s in proc["steps"] if s["seq"] == 3)
    assert step2["task_status"] == "待处理" and step2["task_id"]  # 回退后重新生成任务
    assert step3["task_status"] == "未开始"  # 收尾复盘作废回未开始
    step1 = next(s for s in proc["steps"] if s["seq"] == 1)
    assert step1["task_status"] == "已完成"  # 之前的立项启动保留
    # 实际结束被清空（重启语义）
    assert d["actual_end"] is None


def test_delete_any_state_and_reason_required(client, admin_headers, ctx):
    """M14.1：删除不限状态；暂停/关闭必填理由（落最新动态+审计）；级联软删并解除需求挂接。"""
    m = client.post("/api/members", json={"name": "删项目PM"}, headers=admin_headers).json()["data"]
    p = client.post("/api/projects", json={
        "name": "M14待删项目", "pm": m["id"],
        "planned_start": "2026-07-01", "planned_end": "2026-08-31",
    }, headers=admin_headers).json()["data"]
    pid = p["id"]
    # 加一个 WBS 任务 + 挂一条需求
    client.post(f"/api/projects/{pid}/wbs", json={
        "name": "任务A", "assignee": m["id"], "start_date": "2026-07-01", "end_date": "2026-07-10",
    }, headers=admin_headers)
    dom = client.post("/api/admin/business-domains", json={"code": "m14d", "name": "M14域"},
                      headers=admin_headers).json()["data"]
    req = client.post("/api/requirements", json={
        "title": "挂接需求M14", "req_type": "功能", "business_domain_id": dom["id"], "description": "d",
    }, headers=admin_headers).json()["data"]
    client.patch(f"/api/requirements/{req['id']}", json={"project_id": pid}, headers=admin_headers)

    # 暂停/关闭必填理由
    _transition(client, admin_headers, pid, "active")
    r = _transition(client, admin_headers, pid, "paused")
    assert r.json()["error"]["code"] == "REASON_REQUIRED"
    r = _transition(client, admin_headers, pid, "paused", fields={"reason": "预算冻结，等待 Q4 复批"})
    assert r.json()["success"], r.text
    d = _detail(client, admin_headers, pid)
    assert d["latest_update"] == "[暂停] 预算冻结，等待 Q4 复批"  # 理由落最新动态

    # 进行中也可直接删除（M14.1 放开状态限制）——先重启回进行中验证
    _transition(client, admin_headers, pid, "active")
    r = client.delete(f"/api/projects/{pid}", headers=admin_headers)
    assert r.json()["success"], r.text
    cascade = r.json()["data"]["cascade"]
    assert cascade["wbs"] == 1 and cascade["requirements_unlinked"] == 1 and cascade["process_instances"] == 1

    # 项目从列表消失；需求解除挂接；总览实时聚合不再计入
    listing = client.get("/api/projects?page_size=200", headers=admin_headers).json()["data"]
    assert all(x["id"] != pid for x in listing)
    detail = client.get(f"/api/requirements/{req['id']}", headers=admin_headers).json()["data"]
    assert detail["project_id"] is None and detail["project_name"] is None

