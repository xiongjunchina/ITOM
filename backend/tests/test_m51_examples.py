"""M5.1：全模块示例数据 — 置顶/只读/教学链关联/组织数据可编辑。"""


def test_examples_seeded_and_pinned(client, admin_headers):
    # 各模块列表首行是示例
    for url, code_field, demo_code in (
        ("/api/tickets", "ticket_code", "TK-DEMO"),
        ("/api/problems", "problem_code", "PB-DEMO-001"),
        ("/api/knowledge", "article_code", "KB-DEMO-001"),
        ("/api/vendors", "code", "VD-DEMO"),
        ("/api/contracts", "code", "CT-DEMO"),
        ("/api/projects", "project_code", "PJ-DEMO-001"),
        ("/api/requirements", "requirement_code", "RQ-DEMO-001"),
    ):
        rows = client.get(url, headers=admin_headers).json()["data"]
        assert rows, url
        assert rows[0].get(code_field, "").startswith(demo_code.split("-0")[0]), f"{url} 首行应为示例"
        assert rows[0]["is_example"] is True, url


def test_example_readonly_everywhere(client, admin_headers):
    tickets = client.get("/api/tickets", headers=admin_headers).json()["data"]
    demo_ticket = next(t for t in tickets if t["ticket_code"] == "TK-DEMO-001")
    r = client.patch(f"/api/tickets/{demo_ticket['id']}", json={"title": "改示例"}, headers=admin_headers)
    assert r.json()["error"]["code"] == "EXAMPLE_READONLY"
    r = client.post(f"/api/tickets/{demo_ticket['id']}/transition", json={"to": "closed", "fields": {"closure_code": "resolved"}}, headers=admin_headers)
    assert r.json()["error"]["code"] == "EXAMPLE_READONLY"

    projects = client.get("/api/projects", headers=admin_headers).json()["data"]
    demo_project = next(p for p in projects if p["project_code"] == "PJ-DEMO-001")
    r = client.post(f"/api/projects/{demo_project['id']}/wbs", json={
        "name": "加任务", "assignee": "x", "start_date": "2026-07-01", "end_date": "2026-07-02",
    }, headers=admin_headers)
    assert r.json()["error"]["code"] == "EXAMPLE_READONLY"
    # 示例项目详情：无流转按钮、can_edit=false
    detail = client.get(f"/api/projects/{demo_project['id']}", headers=admin_headers).json()["data"]
    assert detail["allowed_transitions"] == [] and detail["can_edit"] is False

    reqs = client.get("/api/requirements", headers=admin_headers).json()["data"]
    demo_req = next(x for x in reqs if x["requirement_code"] == "RQ-DEMO-001")
    r = client.post(f"/api/requirements/{demo_req['id']}/to-knowledge", headers=admin_headers)
    assert r.json()["error"]["code"] == "EXAMPLE_READONLY"

    articles = client.get("/api/knowledge", headers=admin_headers).json()["data"]
    demo_kb = next(a for a in articles if a["article_code"] == "KB-DEMO-001")
    r = client.post(f"/api/knowledge/{demo_kb['id']}/vote", headers=admin_headers)
    assert r.json()["error"]["code"] == "EXAMPLE_READONLY"


def test_example_teaching_chain(client, admin_headers):
    """示例互相关联：需求挂项目、问题挂工单、合同挂供应商、WBS 有前置依赖。"""
    reqs = client.get("/api/requirements", headers=admin_headers).json()["data"]
    demo_req = next(x for x in reqs if x["requirement_code"] == "RQ-DEMO-001")
    detail = client.get(f"/api/requirements/{demo_req['id']}", headers=admin_headers).json()["data"]
    assert detail["project_name"] and len(detail["tasks"]) == 2
    assert any("填写指引" in c["text"] for c in detail["acceptance_criteria"])

    projects = client.get("/api/projects", headers=admin_headers).json()["data"]
    demo_project = next(p for p in projects if p["project_code"] == "PJ-DEMO-001")
    pdetail = client.get(f"/api/projects/{demo_project['id']}", headers=admin_headers).json()["data"]
    assert any(lr["requirement_code"] == "RQ-DEMO-001" for lr in pdetail["linked_requirements"])
    wbs = client.get(f"/api/projects/{demo_project['id']}/wbs", headers=admin_headers).json()["data"]
    assert any(w["predecessor_ids"] for w in wbs)  # 甘特依赖线数据

    problems = client.get("/api/problems", headers=admin_headers).json()["data"]
    demo_pb = next(p for p in problems if p["problem_code"] == "PB-DEMO-001")
    pb = client.get(f"/api/problems/{demo_pb['id']}", headers=admin_headers).json()["data"]
    assert "填写指引" in (pb.get("root_cause") or "")


def test_example_org_records_editable(client, admin_headers):
    """支撑组织数据可编辑（用户将改为真实的人和组织）。"""
    members = client.get("/api/members", headers=admin_headers).json()["data"]
    demo = next(m for m in members if m["name"] == "【示例】王小明")
    r = client.patch(f"/api/members/{demo['id']}", json={"name": "真实员工"}, headers=admin_headers)
    assert r.json()["success"], r.text
    # 改回去，保持幂等
    client.patch(f"/api/members/{demo['id']}", json={"name": "【示例】王小明"}, headers=admin_headers)

    domains = client.get("/api/admin/business-domains", headers=admin_headers).json()["data"]
    demo_d = next(d for d in domains if "【示例】" in d["name"])
    r = client.patch(f"/api/admin/business-domains/{demo_d['id']}", json={"name": "【示例】零售业务线", "description": "可编辑验证"}, headers=admin_headers)
    assert r.json()["success"], r.text
