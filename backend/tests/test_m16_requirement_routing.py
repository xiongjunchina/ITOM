"""M16：需求评审分流全链路——二开(<阈值)→开发实现；新购/≥阈值→转项目→项目关闭自动闭环。"""
import pytest


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    it_dept = client.post(
        "/api/admin/departments",
        json={"code": "m16_it", "name": "M16数字化团队", "dept_type": "it"},
        headers=admin_headers,
    ).json()["data"]["id"]

    def member(name):
        return client.post(
            "/api/members", json={"name": name, "department_id": it_dept}, headers=admin_headers,
        ).json()["data"]["id"]

    bm = member("服务线负责人M16")
    pdm_leader = member("产品Leader M16")
    dev_leader = member("开发Leader M16")
    pm = member("项目经理M16")
    dev = member("开发小王M16")
    domain = client.post("/api/admin/business-domains",
                         json={"code": "m16dom", "name": "M16业务域", "owner_id": bm},
                         headers=admin_headers).json()["data"]
    # 配置方案评估指派（产品 leader 主责 / 开发 leader 知会）
    client.put("/api/requirements/scoring-config",
               json={"review_assignees": {"pdm_leader": pdm_leader, "dev_leader": dev_leader}},
               headers=admin_headers)
    return {"admin": admin_headers, "domain": domain["id"], "bm": bm,
            "pdm_leader": pdm_leader, "dev_leader": dev_leader, "pm": pm, "dev": dev}


def _register(client, headers, domain, title):
    return client.post("/api/requirements", json={
        "title": title, "req_type": "功能", "business_domain_id": domain, "description": "d",
    }, headers=headers).json()["data"]


def _approve(client, headers, rid):
    return client.post(f"/api/requirements/{rid}/score", json={
        "d1_strategy": 5, "d2_value": 4, "d3_tech": 4, "d4_org": 4, "d5_risk": 2, "d6_speed": 4,
        "decision": "通过",
    }, headers=headers)


def test_review_assignment_and_solution_review(client, ctx):
    """登记→评审任务指派域 owner；立项→方案评估任务指派产品 leader、开发 leader 知会。"""
    r = _register(client, ctx["admin"], ctx["domain"], "指派链路验证")
    detail = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]
    assert detail["process"]["steps"][0]["assignee_name"] == "服务线负责人M16"

    _approve(client, ctx["admin"], r["id"])
    detail = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]
    step2 = detail["process"]["steps"][1]
    assert "方案评估" in step2["name"] and step2["assignee_name"] == "产品Leader M16"


def test_route_dev_under_threshold(client, ctx):
    """二次开发 + 人天<20 → 固定指派评分配置开发负责人；无任务不能完成实现交付。"""
    r = _register(client, ctx["admin"], ctx["domain"], "小改造需求")
    _approve(client, ctx["admin"], r["id"])
    client.patch(f"/api/requirements/{r['id']}",
                 json={"solution_type": "二次开发", "dev_effort": 8},
                 headers=ctx["admin"])
    row = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]
    assert row["route"] == "需求开发实现"
    # 转项目动作被拒（不满足条件）
    resp = client.post(f"/api/requirements/{r['id']}/to-project", json={"pm_id": ctx["pm"]}, headers=ctx["admin"])
    assert resp.json()["error"]["code"] == "ROUTE_NOT_PROJECT"
    # 单据操作人不能改选其他开发人员，必须使用评分规则的开发负责人。
    denied = client.post(f"/api/requirements/{r['id']}/to-dev", json={"owner_id": ctx["dev"]}, headers=ctx["admin"])
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "DEV_LEADER_FIXED"
    # 转开发实现：固定使用评分规则的开发负责人 → implementing；流程「实现交付」任务指派该负责人。
    resp = client.post(f"/api/requirements/{r['id']}/to-dev", json={}, headers=ctx["admin"])
    assert resp.json()["data"]["status"] == "implementing", resp.text
    proc = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]["process"]
    step3 = next(st for st in proc["steps"] if "实现交付" in st["name"])
    assert proc["current_step_seq"] == step3["seq"] and step3["assignee_name"] == "开发Leader M16"
    assert client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]["implementation_route"] == "需求开发实现"
    # 实现交付不能跳过开发任务登记。
    blocked = client.post(f"/api/process-tasks/{step3['task_id']}/complete", json={"comment": "直接交付"}, headers=ctx["admin"])
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "REQUIREMENT_TASK_REQUIRED"
    # 登记任务 → 任务跟踪呈现（按总分排序）
    client.post(f"/api/requirements/{r['id']}/tasks", json={
        "name": "接口改造", "description": "评价数据接入", "assignee": ctx["dev"], "plan_effort": 3,
    }, headers=ctx["admin"])
    tasks = client.get("/api/requirements/tasks/active", headers=ctx["admin"]).json()["data"]
    mine = next(x for x in tasks if x["requirement_id"] == r["id"])
    assert mine["name"] == "接口改造" and mine["weighted_total"] is not None
    delivered = client.post(f"/api/process-tasks/{step3['task_id']}/complete", json={"comment": "开发任务已排期"}, headers=ctx["admin"])
    assert delivered.status_code == 200, delivered.text

    # 反向守卫：开发路径不可走转项目、转开发亦拒新购
    r2 = _register(client, ctx["admin"], ctx["domain"], "新购需求守卫")
    _approve(client, ctx["admin"], r2["id"])
    client.patch(f"/api/requirements/{r2['id']}", json={"solution_type": "新购系统"}, headers=ctx["admin"])
    resp = client.post(f"/api/requirements/{r2['id']}/to-dev", json={}, headers=ctx["admin"])
    assert resp.json()["error"]["code"] == "ROUTE_NOT_DEV"


def test_manual_review_then_score_does_not_skip_solution_or_implementation(client, ctx):
    """回归 RQ-202608-0014：第一步已完成后补评分，只能停在方案评估；路径决定仅推进到实现交付。"""
    r = _register(client, ctx["admin"], ctx["domain"], "人工评审后补评分")
    first = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]["process"]
    step1 = next(st for st in first["steps"] if st["seq"] == first["current_step_seq"])
    completed = client.post(f"/api/process-tasks/{step1['task_id']}/complete", json={"comment": "业务域评审完成"}, headers=ctx["admin"])
    assert completed.status_code == 200, completed.text

    scored = _approve(client, ctx["admin"], r["id"])
    assert scored.status_code == 200, scored.text
    after_score = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]["process"]
    solution = next(st for st in after_score["steps"] if st["seq"] == after_score["current_step_seq"])
    assert "方案评估" in solution["name"] and solution["assignee_name"] == "产品Leader M16"

    client.patch(f"/api/requirements/{r['id']}", json={"solution_type": "二次开发", "dev_effort": 1}, headers=ctx["admin"])
    routed = client.post(f"/api/requirements/{r['id']}/to-dev", json={}, headers=ctx["admin"])
    assert routed.status_code == 200, routed.text
    after_route = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]["process"]
    implementation = next(st for st in after_route["steps"] if st["seq"] == after_route["current_step_seq"])
    assert "实现交付" in implementation["name"] and implementation["assignee_name"] == "开发Leader M16"


def test_route_project_and_auto_close_loop(client, ctx):
    """新购/≥20人天 → 转项目(指派PM+通知) → 项目创建关联 → 项目验收关闭 → 需求自动闭环。"""
    r = _register(client, ctx["admin"], ctx["domain"], "ERP新购需求")
    _approve(client, ctx["admin"], r["id"])
    # ≥阈值(20) 判转项目
    client.patch(f"/api/requirements/{r['id']}", json={"solution_type": "二次开发", "dev_effort": 20}, headers=ctx["admin"])
    assert client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]["route"] == "转项目管理"
    # 新购同样判转项目
    client.patch(f"/api/requirements/{r['id']}", json={"solution_type": "新购系统", "dev_effort": 5}, headers=ctx["admin"])
    assert client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]["route"] == "转项目管理"

    # 转项目：指派 PM → 需求进实现中；流程「实现交付」任务指派 PM（而非按开发角色解析）
    resp = client.post(f"/api/requirements/{r['id']}/to-project", json={"pm_id": ctx["pm"]}, headers=ctx["admin"])
    assert resp.json()["data"]["status"] == "implementing", resp.text
    proc = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]["process"]
    step3 = next(st for st in proc["steps"] if "实现交付" in st["name"])
    assert step3["assignee_name"] == "项目经理M16"

    # PM 创建项目并关联需求
    p = client.post("/api/projects", json={
        "name": "ERP 系统建设（M16）", "pm": ctx["pm"],
        "planned_start": "2026-08-01", "planned_end": "2026-12-31",
        "requirement_id": r["id"],
    }, headers=ctx["admin"]).json()["data"]
    detail = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]
    assert detail["project_id"] == p["id"]

    # 项目关闭 → 不直接关需求，提醒 PM 回需求完成「实现交付」（M16.5）
    for to in ("active", "completed", "closed"):
        fields = {"reason": "验收通过，正式关闭"} if to == "closed" else {}
        resp = client.post(f"/api/projects/{p['id']}/transition", json={"to": to, "fields": fields}, headers=ctx["admin"])
        assert resp.json()["success"], resp.text
    detail = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]
    assert detail["status"] == "implementing"  # 未自动关闭，等待业务验收

    # PM 完成「实现交付」步骤 → 「验收与闭环」任务指派业务域负责人
    proc = detail["process"]
    cur = next(st for st in proc["steps"] if st["seq"] == proc["current_step_seq"])
    assert "实现交付" in cur["name"]
    resp = client.post(f"/api/process-tasks/{cur['task_id']}/complete",
                       json={"comment": "项目交付完成，系统已上线"}, headers=ctx["admin"])
    assert resp.json()["success"], resp.text
    proc = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]["process"]
    acc = next(st for st in proc["steps"] if "验收" in st["name"])
    assert proc["current_step_seq"] == acc["seq"] and acc["assignee_name"] == "服务线负责人M16"

    # 业务域负责人完成「验收与闭环」→ 需求自动关闭并通知
    resp = client.post(f"/api/process-tasks/{acc['task_id']}/complete",
                       json={"comment": "业务部门验收通过"}, headers=ctx["admin"])
    assert resp.json()["success"], resp.text
    detail = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]
    assert detail["status"] == "closed" and "闭环" in detail["closure_note"]


def test_threshold_configurable(client, ctx):
    """阈值可配：调低到 5 后，8 人天二开也判转项目。"""
    client.put("/api/requirements/scoring-config", json={"effort_threshold": 5}, headers=ctx["admin"])
    r = _register(client, ctx["admin"], ctx["domain"], "阈值验证需求")
    _approve(client, ctx["admin"], r["id"])
    client.patch(f"/api/requirements/{r['id']}", json={"solution_type": "二次开发", "dev_effort": 8}, headers=ctx["admin"])
    assert client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]["route"] == "转项目管理"
    client.put("/api/requirements/scoring-config", json={"effort_threshold": 20}, headers=ctx["admin"])


def test_sr_flow_requester_step_assigns_submitter(client, admin_headers, ctx):
    """M16.8：流程步骤 default_role=requester → 指派单据提交人本人（用户改配置后的引擎语义）。"""
    # 把 sr_flow 第 3 步主责改为 requester（模拟用户配置）
    defs = client.get("/api/admin/process-definitions", headers=admin_headers).json()["data"]
    sr = next(d for d in defs if d["code"].startswith("sr_flow") and d["active"])
    steps = [{k: st[k] for k in ("seq", "name", "default_role", "cc_roles", "autonomy_level", "sla_hours", "description")}
             for st in sr["steps"]]
    steps[-1]["default_role"] = "requester"
    r = client.patch(f"/api/admin/process-definitions/{sr['id']}", json={"steps": steps}, headers=admin_headers)
    assert r.json()["success"], r.text

    # 业务用户提交服务请求 → 推进到最后一步 → 任务指派提交人本人
    m = client.post("/api/members", json={"name": "业务申请人M168"}, headers=admin_headers).json()["data"]
    client.post("/api/admin/users", json={"username": "req_m168", "password": "pass123",
                                          "roles": ["requester"], "person_id": m["id"]}, headers=admin_headers)
    tk = client.post("/api/auth/login", json={"username": "req_m168", "password": "pass123"}).json()["data"]["token"]
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    t = client.post("/api/tickets", json={
        "title": "M168确认指派验证", "ticket_type": "service_request", "priority": "P3",
        "description": "d", "service_item_id": item,
    }, headers={"Authorization": f"Bearer {tk}"}).json()["data"]

    detail = client.get(f"/api/tickets/{t['id']}", headers=admin_headers).json()["data"]
    proc = detail["process"]
    # 完成前两步
    for _ in range(2):
        cur = next(st for st in proc["steps"] if st["seq"] == proc["current_step_seq"])
        client.post(f"/api/process-tasks/{cur['task_id']}/complete", json={"comment": "完成"}, headers=admin_headers)
        proc = client.get(f"/api/tickets/{t['id']}", headers=admin_headers).json()["data"]["process"]
    last = next(st for st in proc["steps"] if st["seq"] == proc["current_step_seq"])
    assert last["assignee_name"] == "业务申请人M168"  # 指派提交人本人而非任意业务用户
