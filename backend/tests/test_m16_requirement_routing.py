"""M16：需求评审分流全链路——二开(<阈值)→开发实现；新购/≥阈值→转项目→项目关闭自动闭环。"""
import pytest


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    def member(name):
        return client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]["id"]

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
    """二次开发 + 人天<20 → route=需求开发实现，正常任务分解排期。"""
    r = _register(client, ctx["admin"], ctx["domain"], "小改造需求")
    _approve(client, ctx["admin"], r["id"])
    client.patch(f"/api/requirements/{r['id']}",
                 json={"solution_type": "二次开发", "dev_effort": 8, "owner": ctx["dev"]},
                 headers=ctx["admin"])
    row = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]
    assert row["route"] == "需求开发实现"
    # 转项目动作被拒（不满足条件）
    resp = client.post(f"/api/requirements/{r['id']}/to-project", json={"pm_id": ctx["pm"]}, headers=ctx["admin"])
    assert resp.json()["error"]["code"] == "ROUTE_NOT_PROJECT"
    # 正常进实现
    resp = client.post(f"/api/requirements/{r['id']}/transition", json={"to": "implementing", "fields": {}}, headers=ctx["admin"])
    assert resp.json()["data"]["status"] == "implementing"


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

    # 转项目：指派 PM → 需求进实现中；PM 收到通知
    resp = client.post(f"/api/requirements/{r['id']}/to-project", json={"pm_id": ctx["pm"]}, headers=ctx["admin"])
    assert resp.json()["data"]["status"] == "implementing", resp.text

    # PM 创建项目并关联需求
    p = client.post("/api/projects", json={
        "name": "ERP 系统建设（M16）", "pm": ctx["pm"],
        "planned_start": "2026-08-01", "planned_end": "2026-12-31",
        "requirement_id": r["id"],
    }, headers=ctx["admin"]).json()["data"]
    detail = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]
    assert detail["project_id"] == p["id"]

    # 项目 关闭 → 需求自动闭环
    for to in ("active", "completed", "closed"):
        fields = {"reason": "验收通过，正式关闭"} if to == "closed" else {}
        resp = client.post(f"/api/projects/{p['id']}/transition", json={"to": to, "fields": fields}, headers=ctx["admin"])
        assert resp.json()["success"], resp.text
    detail = client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]
    assert detail["status"] == "closed" and "自动闭环" in detail["closure_note"]


def test_threshold_configurable(client, ctx):
    """阈值可配：调低到 5 后，8 人天二开也判转项目。"""
    client.put("/api/requirements/scoring-config", json={"effort_threshold": 5}, headers=ctx["admin"])
    r = _register(client, ctx["admin"], ctx["domain"], "阈值验证需求")
    _approve(client, ctx["admin"], r["id"])
    client.patch(f"/api/requirements/{r['id']}", json={"solution_type": "二次开发", "dev_effort": 8}, headers=ctx["admin"])
    assert client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).json()["data"]["route"] == "转项目管理"
    client.put("/api/requirements/scoring-config", json={"effort_threshold": 20}, headers=ctx["admin"])
