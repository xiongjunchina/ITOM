"""M5：需求四阶段/阶段门/任务分解/验收清单/转出闭环。"""
import pytest


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    def member_and_user(name, username, roles):
        m = client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]
        client.post(
            "/api/admin/users",
            json={"username": username, "password": "pass123", "roles": roles, "person_id": m["id"]},
            headers=admin_headers,
        )
        token = client.post("/api/auth/login", json={"username": username, "password": "pass123"}).json()["data"]["token"]
        return m["id"], {"Authorization": f"Bearer {token}"}

    bp_p, bp = member_and_user("BP小美", "bp10", ["it_bp"])
    pdm_p, pdm = member_and_user("产品老王", "pdm10", ["it_pdm"])
    dev_p, dev = member_and_user("开发小陈", "dev10", ["it_dev"])
    _, req = member_and_user("业务小赵", "req10", ["requester"])

    domain = client.post(
        "/api/admin/business-domains",
        json={"code": "retail10", "name": "零售业务线", "owner_id": bp_p},
        headers=admin_headers,
    ).json()["data"]
    return {"bp_p": bp_p, "bp": bp, "pdm_p": pdm_p, "pdm": pdm, "dev_p": dev_p, "dev": dev,
            "req": req, "domain": domain["id"]}


def _register(client, headers, domain, **kw):
    payload = {"title": "门店报表需求", "req_type": "数据", "business_domain_id": domain,
               "description": "门店需要日报表", **kw}
    r = client.post("/api/requirements", json=payload, headers=headers)
    assert r.json()["success"], r.text
    return r.json()["data"]


def test_register_enters_review_and_assigns_domain_owner(client, ctx):
    """M16：登记即进入评审（evaluating），评审任务自动指派业务域负责人并通知。"""
    r = _register(client, ctx["req"], ctx["domain"])
    assert r["requirement_code"].startswith("RQ-") and r["status"] == "evaluating"
    assert r["business_domain_name"] == "零售业务线"

    detail = client.get(f"/api/requirements/{r['id']}", headers=ctx["pdm"]).json()["data"]
    assert detail["process"]["definition_name"] == "需求交付流程"
    step1 = detail["process"]["steps"][0]
    assert "需求评审" in step1["name"] and step1["assignee_name"] == "BP小美"

    notif = client.get("/api/notifications", headers=ctx["bp"]).json()["data"]
    assert any("需求评审指派" in n["title"] for n in notif)


def test_requester_scope(client, ctx):
    mine = _register(client, ctx["req"], ctx["domain"], title="业务用户的需求")
    listing = client.get("/api/requirements", headers=ctx["req"]).json()["data"]
    assert all(row["requester_name"] == "业务小赵" for row in listing)
    other = _register(client, ctx["bp"], ctx["domain"], title="BP代提需求")
    assert client.get(f"/api/requirements/{other['id']}", headers=ctx["req"]).status_code == 403


def test_stage_gate_and_full_lifecycle(client, ctx, admin_headers):
    r = _register(client, ctx["bp"], ctx["domain"], title="全流程需求")
    rid = r["id"]
    # M16：登记即 evaluating；评分立项自动流转 analyzing
    resp = client.post(f"/api/requirements/{rid}/score", json={
        "d1_strategy": 4, "d2_value": 4, "d3_tech": 4, "d4_org": 4, "d5_risk": 2, "d6_speed": 4,
        "decision": "通过",
    }, headers=ctx["pdm"])
    assert resp.json()["data"]["status"] == "analyzing", resp.text

    # 未完成分析（缺 owner）不能进实现
    resp = client.post(f"/api/requirements/{rid}/transition", json={"to": "implementing", "fields": {}}, headers=admin_headers)
    assert resp.json()["error"]["code"] == "STAGE_FIELD_REQUIRED"

    client.patch(f"/api/requirements/{rid}", json={
        "moscow": "M", "owner": ctx["pdm_p"], "solution": "BI 报表方案",
        "acceptance_criteria": [{"text": "报表口径与财务一致", "checked": False},
                                {"text": "T+1 出数", "checked": False}],
    }, headers=ctx["pdm"])
    resp = client.post(f"/api/requirements/{rid}/transition", json={"to": "implementing", "fields": {}}, headers=admin_headers)
    assert resp.json()["data"]["status"] == "implementing"

    # 任务分解 + 负责人自更新状态
    t1 = client.post(f"/api/requirements/{rid}/tasks", json={"name": "建模", "assignee": ctx["dev_p"]}, headers=ctx["pdm"]).json()["data"]
    client.post(f"/api/requirements/{rid}/tasks", json={"name": "报表开发", "assignee": ctx["dev_p"]}, headers=ctx["pdm"])
    r1 = client.patch(f"/api/requirements/tasks/{t1['id']}", json={"status": "已完成"}, headers=ctx["dev"])
    assert r1.json()["success"], r1.text
    r2 = client.patch(f"/api/requirements/tasks/{t1['id']}", json={"name": "改名"}, headers=ctx["dev"])
    assert r2.status_code == 403  # 负责人只能改状态

    detail = client.get(f"/api/requirements/{rid}", headers=ctx["pdm"]).json()["data"]
    assert detail["task_total"] == 2 and detail["task_done"] == 1 and detail["progress"] == 50.0

    # 验收未全勾不能关闭
    resp = client.post(f"/api/requirements/{rid}/transition", json={"to": "closed", "fields": {}}, headers=admin_headers)
    assert resp.json()["error"]["code"] == "ACCEPTANCE_PENDING"

    client.patch(f"/api/requirements/{rid}", json={
        "acceptance_criteria": [{"text": "报表口径与财务一致", "checked": True},
                                {"text": "T+1 出数", "checked": True}],
    }, headers=ctx["pdm"])
    resp = client.post(f"/api/requirements/{rid}/transition", json={"to": "closed", "fields": {}}, headers=admin_headers)
    assert resp.json()["data"]["status"] == "closed"
    detail = client.get(f"/api/requirements/{rid}", headers=ctx["pdm"]).json()["data"]
    assert detail["lead_days"] is not None


def test_handover_problem_and_knowledge(client, ctx):
    r = _register(client, ctx["bp"], ctx["domain"], title="带遗留的需求")
    rid = r["id"]
    client.patch(f"/api/requirements/{rid}", json={"solution": "上线方案A"}, headers=ctx["pdm"])

    p = client.post(f"/api/requirements/{rid}/to-problem",
                    json={"description": "性能未达标，需持续优化"}, headers=ctx["pdm"]).json()["data"]
    assert p["problem_code"].startswith("PB-")
    k = client.post(f"/api/requirements/{rid}/to-knowledge", headers=ctx["pdm"]).json()["data"]
    assert k["article_code"].startswith("KB-")

    detail = client.get(f"/api/requirements/{rid}", headers=ctx["pdm"]).json()["data"]
    assert len(detail["handover"]["problems"]) == 1 and len(detail["handover"]["articles"]) == 1

    article = client.get(f"/api/knowledge/{k['article_id']}", headers=ctx["pdm"]).json()["data"]
    assert "经验沉淀" in article["title"] and "上线方案A" in article["content"]


def test_on_hold_and_cancel(client, ctx, admin_headers):
    r = _register(client, ctx["bp"], ctx["domain"], title="搁置需求")
    client.post(f"/api/requirements/{r['id']}/transition", json={"to": "on_hold", "fields": {}}, headers=admin_headers)
    resp = client.post(f"/api/requirements/{r['id']}/transition", json={"to": "cancelled", "fields": {}}, headers=admin_headers)
    assert resp.json()["data"]["status"] == "cancelled"


def test_dashboard_requirement_section(client, ctx, admin_headers):
    dash = client.get("/api/dashboard", headers=ctx["pdm"]).json()["data"]
    assert dash["requirement"]["by_stage"]["closed"] >= 1
    assert dash["requirement"]["avg_lead_days"] is not None
