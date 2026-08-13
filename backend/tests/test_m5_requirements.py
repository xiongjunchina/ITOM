"""M5：需求四阶段/阶段门/任务分解/验收清单/转出闭环。"""
from io import BytesIO

import pytest
from openpyxl import load_workbook


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
    req_p, req = member_and_user("业务数字化经理小赵", "req10", ["bdo"])

    domain = client.post(
        "/api/admin/business-domains",
        json={"code": "retail10", "name": "零售业务线", "owner_id": bp_p},
        headers=admin_headers,
    ).json()["data"]
    return {"bp_p": bp_p, "bp": bp, "pdm_p": pdm_p, "pdm": pdm, "dev_p": dev_p, "dev": dev,
            "req_p": req_p, "req": req, "domain": domain["id"]}


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


def test_bdo_scope(client, ctx):
    mine = _register(client, ctx["req"], ctx["domain"], title="业务用户的需求")
    listing = client.get("/api/requirements", headers=ctx["req"]).json()["data"]
    assert all(row["requester_name"] == "业务数字化经理小赵" for row in listing)
    other = _register(client, ctx["bp"], ctx["domain"], title="BP代提需求")
    assert client.get(f"/api/requirements/{other['id']}", headers=ctx["req"]).status_code == 403


def test_requirement_draft_attachments_bind_atomically(client, ctx, monkeypatch, tmp_path):
    """需求补充信息的附件在提交前不可读取，提交时随需求在同一事务中绑定。"""
    monkeypatch.setattr("app.core.config.settings.upload_dir", str(tmp_path))
    upload = client.post(
        "/api/attachments/requirement-drafts",
        files={"file": ("需求截图.png", b"requirement-png", "image/png")},
        headers=ctx["req"],
    )
    assert upload.status_code == 200, upload.text
    draft = upload.json()["data"]

    hidden = client.get(
        f"/api/attachments?entity_type=requirement_draft&entity_id={draft['id']}", headers=ctx["req"],
    )
    assert hidden.status_code == 403
    assert client.get(f"/api/attachments/{draft['id']}/download", headers=ctx["req"]).status_code == 403
    bypass = client.post(
        f"/api/attachments?entity_type=requirement_draft&entity_id={draft['id']}",
        files={"file": ("bypass.exe", b"binary", "application/octet-stream")},
        headers=ctx["req"],
    )
    assert bypass.status_code == 403

    requirement = _register(
        client,
        ctx["req"],
        ctx["domain"],
        title="带补充附件的需求",
        remarks="补充上下文与影响范围",
        attachment_ids=[draft["id"]],
    )
    detail = client.get(f"/api/requirements/{requirement['id']}", headers=ctx["req"]).json()["data"]
    assert detail["remarks"] == "补充上下文与影响范围"
    attachments = client.get(
        f"/api/attachments?entity_type=requirement&entity_id={requirement['id']}", headers=ctx["req"],
    )
    assert attachments.status_code == 200, attachments.text
    assert attachments.json()["total"] == 1
    bound = attachments.json()["data"][0]
    assert bound["id"] == draft["id"] and bound["filename"] == "需求截图.png"
    download = client.get(f"/api/attachments/{bound['id']}/download", headers=ctx["req"])
    assert download.status_code == 200 and download.content == b"requirement-png"


def test_stage_gate_and_full_lifecycle(client, ctx, admin_headers):
    r = _register(client, ctx["bp"], ctx["domain"], title="全流程需求")
    rid = r["id"]
    # M16：登记即 evaluating；评分立项自动流转 analyzing
    resp = client.post(f"/api/requirements/{rid}/score", json={
        "d1_strategy": 4, "d2_value": 4, "d3_tech": 4, "d4_org": 4, "d5_risk": 2, "d6_speed": 4,
        "decision": "通过",
    }, headers=ctx["bp"])
    assert resp.json()["data"]["status"] == "analyzing", resp.text

    # 未完成分析（缺 owner）不能进实现
    resp = client.post(f"/api/requirements/{rid}/transition", json={"to": "implementing", "fields": {}}, headers=admin_headers)
    assert resp.json()["error"]["code"] == "STAGE_FIELD_REQUIRED"

    client.patch(f"/api/requirements/{rid}", json={
        "moscow": "M", "owner": ctx["pdm_p"], "solution": "BI 报表方案",
        "acceptance_criteria": [{"text": "报表口径与财务一致", "checked": False},
                                {"text": "T+1 出数", "checked": False}],
    }, headers=admin_headers)
    resp = client.post(f"/api/requirements/{rid}/transition", json={"to": "implementing", "fields": {}}, headers=admin_headers)
    assert resp.json()["data"]["status"] == "implementing"

    # 任务分解 + IT 开发人员可维护实现中需求上的所有开发任务
    t1 = client.post(f"/api/requirements/{rid}/tasks", json={"name": "建模", "assignee": ctx["dev_p"]}, headers=ctx["pdm"]).json()["data"]
    client.post(f"/api/requirements/{rid}/tasks", json={"name": "报表开发", "assignee": ctx["dev_p"]}, headers=ctx["pdm"])
    active_tasks = client.get("/api/requirements/tasks/active", headers=ctx["pdm"]).json()["data"]
    registered = next(task for task in active_tasks if task["id"] == t1["id"])
    assert registered["registrar"] == ctx["bp_p"]
    assert registered["registrar_name"] == "BP小美"
    r1 = client.patch(f"/api/requirements/tasks/{t1['id']}", json={"status": "已完成"}, headers=ctx["dev"])
    assert r1.json()["success"], r1.text
    r_effort = client.patch(f"/api/requirements/tasks/{t1['id']}", json={"actual_effort": 1.5}, headers=ctx["dev"])
    assert r_effort.json()["success"], r_effort.text
    r2 = client.patch(f"/api/requirements/tasks/{t1['id']}", json={"name": "改名"}, headers=ctx["dev"])
    assert r2.status_code == 200, r2.text

    # 进行中的开发任务仅系统管理员可删除；其他状态由有开发任务维护权的 IT 人员删除。
    running = client.post(
        f"/api/requirements/{rid}/tasks", json={"name": "进行中任务", "assignee": ctx["dev_p"]}, headers=ctx["pdm"],
    ).json()["data"]
    assert client.patch(
        f"/api/requirements/tasks/{running['id']}", json={"status": "进行中"}, headers=ctx["dev"],
    ).status_code == 200
    assert client.delete(f"/api/requirements/tasks/{running['id']}", headers=ctx["dev"]).status_code == 403
    assert client.delete(f"/api/requirements/tasks/{running['id']}", headers=admin_headers).status_code == 200

    deletable = client.post(
        f"/api/requirements/{rid}/tasks", json={"name": "待删除任务", "assignee": ctx["dev_p"]}, headers=ctx["pdm"],
    ).json()["data"]
    assert client.delete(f"/api/requirements/tasks/{deletable['id']}", headers=ctx["dev"]).status_code == 200

    detail = client.get(f"/api/requirements/{rid}", headers=ctx["pdm"]).json()["data"]
    assert detail["task_total"] == 2 and detail["task_done"] == 1 and detail["progress"] == 50.0

    # 验收未全勾不能关闭
    resp = client.post(f"/api/requirements/{rid}/transition", json={"to": "closed", "fields": {}}, headers=admin_headers)
    assert resp.json()["error"]["code"] == "ACCEPTANCE_PENDING"

    client.patch(f"/api/requirements/{rid}", json={
        "acceptance_criteria": [{"text": "报表口径与财务一致", "checked": True},
                                {"text": "T+1 出数", "checked": True}],
    }, headers=admin_headers)
    resp = client.post(f"/api/requirements/{rid}/transition", json={"to": "closed", "fields": {}}, headers=admin_headers)
    assert resp.json()["data"]["status"] == "closed"
    detail = client.get(f"/api/requirements/{rid}", headers=ctx["pdm"]).json()["data"]
    assert detail["lead_days"] is not None


def test_development_task_template_and_import(client, ctx, admin_headers):
    """开发任务模板可由 IT 成员下载；导入按行校验并保留失败明细。"""
    requirement = _register(client, ctx["bp"], ctx["domain"], title="批量导入开发任务")
    rid = requirement["id"]
    client.post(f"/api/requirements/{rid}/score", json={
        "d1_strategy": 4, "d2_value": 4, "d3_tech": 4, "d4_org": 4, "d5_risk": 2, "d6_speed": 4,
        "decision": "通过",
    }, headers=ctx["bp"])
    client.patch(f"/api/requirements/{rid}", json={
        "moscow": "M", "owner": ctx["pdm_p"], "solution": "批量任务导入方案",
    }, headers=admin_headers)
    assert client.post(
        f"/api/requirements/{rid}/transition", json={"to": "implementing", "fields": {}}, headers=admin_headers,
    ).status_code == 200

    # 普通项目关联不等于已冻结为“转项目管理”路径，仍允许关联需求开发任务。
    project = client.post("/api/projects", json={
        "name": "开发任务导入关联项目",
        "pm": ctx["pdm_p"],
        "planned_start": "2026-08-01",
        "planned_end": "2026-09-30",
        "requirement_id": rid,
    }, headers=admin_headers)
    assert project.status_code == 200, project.text
    linked = client.get(f"/api/requirements/{rid}", headers=ctx["pdm"]).json()["data"]
    assert linked["project_id"] == project.json()["data"]["id"]
    assert linked["implementation_route"] != "转项目管理"

    template = client.get("/api/requirements/tasks/template", headers=ctx["dev"])
    assert template.status_code == 200
    workbook = load_workbook(BytesIO(template.content))
    sheet = workbook["开发任务"]
    sheet.append(["", "暂未关联需求的任务", "后续再关联", "开发小陈", "2026-08-11", 1, 0, "待处理"])
    sheet.append([requirement["requirement_code"], "批量导入任务", "模板导入", "开发小陈", "2026-08-11", 2, 1, "待处理"])
    sheet.append(["RQ-NOT-FOUND", "无效关联", "", "开发小陈", "2026-08-11", 1, 0, "待处理"])
    content = BytesIO()
    workbook.save(content)
    result = client.post(
        "/api/requirements/tasks/import",
        files={"file": ("development-tasks.xlsx", content.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=ctx["dev"],
    )
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data["created"] == 2
    assert data["failed"] and data["failed"][0]["row"] == 5
    assert "不存在" in data["failed"][0]["error"]

    active = client.get("/api/requirements/tasks/active", headers=ctx["dev"])
    imported = next(row for row in active.json()["data"] if row["name"] == "批量导入任务")
    assert imported["can_edit"] is True and imported["can_delete"] is True
    unlinked = next(row for row in active.json()["data"] if row["name"] == "暂未关联需求的任务")
    assert unlinked["requirement_id"] is None
    assert client.get("/api/requirements/tasks/template", headers=ctx["req"]).status_code == 403


def test_requirement_owner_can_manage_multiple_tasks(client, ctx, admin_headers):
    """转开发后，需求负责人可登记多条任务并修改任务内容；普通任务负责人权限不被扩大。"""
    r = _register(client, ctx["pdm"], ctx["domain"], title="开发负责人任务维护")
    rid = r["id"]
    resp = client.post(f"/api/requirements/{rid}/score", json={
        "d1_strategy": 4, "d2_value": 4, "d3_tech": 4, "d4_org": 4, "d5_risk": 2, "d6_speed": 4,
        "decision": "通过",
    }, headers=ctx["bp"])
    assert resp.json()["data"]["status"] == "analyzing"
    client.patch(f"/api/requirements/{rid}", json={
        "moscow": "M", "owner": ctx["dev_p"], "solution": "开发实现方案",
    }, headers=admin_headers)
    resp = client.post(f"/api/requirements/{rid}/transition", json={"to": "implementing", "fields": {}}, headers=admin_headers)
    assert resp.json()["data"]["status"] == "implementing"

    detail = client.get(f"/api/requirements/{rid}", headers=ctx["dev"]).json()["data"]
    assert detail["can_manage_tasks"] is True
    first = client.post(f"/api/requirements/{rid}/tasks", json={
        "name": "接口开发", "assignee": ctx["dev_p"], "plan_effort": 2,
    }, headers=ctx["dev"])
    second = client.post(f"/api/requirements/{rid}/tasks", json={
        "name": "自测与联调", "assignee": ctx["dev_p"], "plan_effort": 1,
    }, headers=ctx["dev"])
    assert first.status_code == 200 and second.status_code == 200
    task_id = first.json()["data"]["id"]
    updated = client.patch(f"/api/requirements/tasks/{task_id}", json={
        "name": "接口开发（已调整）", "actual_effort": 2.5,
    }, headers=ctx["dev"])
    assert updated.status_code == 200, updated.text

    detail = client.get(f"/api/requirements/{rid}", headers=ctx["dev"]).json()["data"]
    assert detail["task_total"] == 2
    assert {task["name"] for task in detail["tasks"]} == {"接口开发（已调整）", "自测与联调"}


def test_handover_problem_and_knowledge(client, ctx, admin_headers):
    r = _register(client, ctx["bp"], ctx["domain"], title="带遗留的需求")
    rid = r["id"]
    # M92: the PDM has not completed the current review task on this record,
    # so only the system-level administrator may correct its route-sensitive
    # solution field before the workflow reaches that handler.
    client.patch(f"/api/requirements/{rid}", json={"solution": "上线方案A"}, headers=admin_headers)

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
