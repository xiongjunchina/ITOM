"""M10：需求六维加权评分 + 四象限 + 评估门 + 评分配置 + 批量导入。"""
import io

import pytest
from openpyxl import load_workbook

from app.db import SessionLocal
from app.models import Requirement


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    def member_and_user(name, username, roles):
        m = client.post("/api/members", json={"name": name}, headers=admin_headers).json()["data"]
        client.post("/api/admin/users",
                    json={"username": username, "password": "pass123", "roles": roles, "person_id": m["id"]},
                    headers=admin_headers)
        token = client.post("/api/auth/login", json={"username": username, "password": "pass123"}).json()["data"]["token"]
        return m["id"], {"Authorization": f"Bearer {token}"}

    pdm_p, pdm = member_and_user("产品M10", "pdm_m10", ["it_pdm"])
    domain = client.post("/api/admin/business-domains",
                         json={"code": "dig10", "name": "数字化业务线", "owner_id": None},
                         headers=admin_headers).json()["data"]
    return {"pdm": pdm, "pdm_p": pdm_p, "admin": admin_headers, "domain": domain["id"]}


def _register(client, headers, domain, **kw):
    payload = {"title": "多平台ERP中台", "req_type": "功能", "business_domain_id": domain,
               "description": "支撑多平台运营的中台", **kw}
    return client.post("/api/requirements", json=payload, headers=headers).json()["data"]


def test_score_weighted_total_and_quadrant(client, ctx):
    r = _register(client, ctx["pdm"], ctx["domain"])
    rid = r["id"]
    client.post(f"/api/requirements/{rid}/transition", json={"to": "evaluating", "fields": {}}, headers=ctx["admin"])

    # 六维评分 → 加权总分 3.8，象限=战略下注
    resp = client.post(f"/api/requirements/{rid}/score", json={
        "d1_strategy": 5, "d2_value": 5, "d3_tech": 3, "d4_org": 3, "d5_risk": 3, "d6_speed": 3,
        "decision": "通过", "comment": "战略基建",
    }, headers=ctx["admin"])
    data = resp.json()["data"]
    assert data["weighted_total"] == 3.8, resp.text
    assert data["quadrant"] == "战略下注"
    assert data["decision"] == "通过"

    # 列表/详情回填
    detail = client.get(f"/api/requirements/{rid}", headers=ctx["admin"]).json()["data"]
    assert detail["d1_strategy"] == 5 and detail["weighted_total"] == 3.8
    assert len(detail["scores"]) == 1 and detail["scores"][0]["is_consensus"] is True


def test_detail_exposes_persisted_scores_without_history_and_rejects_with_reason(client, ctx):
    """历史/导入需求即使缺评分历史行，也必须能回填六维评分并选择驳回。"""
    r = _register(client, ctx["pdm"], ctx["domain"], title="历史主表评分需求")
    rid = r["id"]
    with SessionLocal() as db:
        requirement = db.get(Requirement, rid)
        requirement.score_d1_strategy = 5
        requirement.score_d2_value = 4
        requirement.score_d3_tech = 4
        requirement.score_d4_org = 3
        requirement.score_d5_risk = 2
        requirement.score_d6_speed = 4
        db.commit()

    detail = client.get(f"/api/requirements/{rid}", headers=ctx["admin"]).json()["data"]
    assert detail["scores"] == []
    assert [detail[key] for key in ("d1_strategy", "d2_value", "d3_tech", "d4_org", "d5_risk", "d6_speed")] == [5, 4, 4, 3, 2, 4]
    assert detail["weighted_total"] == 4.1 and detail["quadrant"] == "战略下注"

    rejected = client.post(
        f"/api/requirements/{rid}/score",
        json={"decision": "驳回", "comment": "当前业务优先级已调整，停止投入实施"},
        headers=ctx["admin"],
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["status"] == "cancelled"


def test_eval_gate_quadrant_and_auto_flow(client, ctx):
    """M16 评估门：未评分不可立项；重评象限仅 搁置/驳回（驳回必填理由）；决议即自动流转。"""
    r = _register(client, ctx["pdm"], ctx["domain"], title="低优先需求")
    rid = r["id"]
    assert r["status"] == "evaluating"  # M16：登记即进评审

    # 未评分就立项 → 拦截
    resp = client.post(f"/api/requirements/{rid}/score", json={"decision": "通过"}, headers=ctx["admin"])
    assert resp.json()["error"]["code"] == "EVAL_INCOMPLETE"

    # 低分落「重新评估」象限 → 立项被象限约束拦截
    resp = client.post(f"/api/requirements/{rid}/score", json={
        "d1_strategy": 2, "d2_value": 2, "d3_tech": 3, "d4_org": 3, "d5_risk": 3, "d6_speed": 2,
        "decision": "通过",
    }, headers=ctx["admin"])
    assert resp.json()["error"]["code"] == "QUADRANT_REJECTED"

    # 驳回必填理由
    resp = client.post(f"/api/requirements/{rid}/score", json={"decision": "驳回"}, headers=ctx["admin"])
    assert resp.json()["error"]["code"] == "REASON_REQUIRED"

    # 搁置 → 自动流转 on_hold（补充后可重新评审）
    resp = client.post(f"/api/requirements/{rid}/score", json={"decision": "搁置", "comment": "价值论证不足，请补充预期收益"}, headers=ctx["admin"])
    assert resp.json()["data"]["status"] == "on_hold"

    # 重新进入评审 → 提分至非重评象限 → 立项自动流转 analyzing
    client.post(f"/api/requirements/{rid}/transition", json={"to": "evaluating", "fields": {}}, headers=ctx["admin"])
    resp = client.post(f"/api/requirements/{rid}/score", json={
        "d1_strategy": 4, "d2_value": 4, "d3_tech": 4, "d4_org": 3, "d5_risk": 2, "d6_speed": 4,
        "decision": "通过",
    }, headers=ctx["admin"])
    data = resp.json()["data"]
    assert data["status"] == "analyzing" and data["flowed_to"] == "analyzing"


def test_reject_closes_with_reason(client, ctx):
    """M16：重评象限驳回（带理由）→ 需求关闭并记录理由。"""
    r = _register(client, ctx["pdm"], ctx["domain"], title="被驳回需求")
    rid = r["id"]
    resp = client.post(f"/api/requirements/{rid}/score", json={
        "d1_strategy": 1, "d2_value": 2, "d3_tech": 3, "d4_org": 3, "d5_risk": 4, "d6_speed": 2,
        "decision": "驳回", "comment": "与年度战略无关且价值不可量化",
    }, headers=ctx["admin"])
    assert resp.json()["data"]["status"] == "cancelled", resp.text
    detail = client.get(f"/api/requirements/{rid}", headers=ctx["admin"]).json()["data"]
    assert "评审驳回" in detail["closure_note"] and "价值不可量化" in detail["closure_note"]


def test_scoring_config_admin_only(client, ctx):
    cfg = client.get("/api/requirements/scoring-config", headers=ctx["admin"]).json()["data"]
    assert cfg["weights"]["d1"] == 0.2 and cfg["thresholds"]["total"] == 3.5

    # 非管理员不可改
    resp = client.put("/api/requirements/scoring-config", json={"thresholds": {"total": 4.0, "strategic": 4, "viable": 3}}, headers=ctx["pdm"])
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # 权重和不为 1 → 拒绝
    resp = client.put("/api/requirements/scoring-config",
                      json={"weights": {"d1": 0.5, "d2": 0.2, "d3": 0.2, "d4": 0.1, "d5": 0.1, "d6": 0.2}},
                      headers=ctx["admin"])
    assert resp.json()["error"]["code"] == "INVALID_WEIGHTS"

    # admin 改阈值成功
    resp = client.put("/api/requirements/scoring-config",
                      json={"thresholds": {"total": 3.8, "strategic": 4, "viable": 3}}, headers=ctx["admin"])
    assert resp.json()["success"]


def test_template_download_and_import(client, ctx):
    # 下载模板
    tpl = client.get("/api/requirements/template", headers=ctx["admin"])
    assert tpl.status_code == 200 and "spreadsheetml" in tpl.headers["content-type"]

    # 填充模板：一行已评分（进评估）、一行未评分（进登记）、一行业务域错误
    wb = load_workbook(io.BytesIO(tpl.content))
    ws = wb["需求登记"]
    ws.append(["海外仓WMS", "功能", "数字化业务线", "库存效率中台", None, "供应链", "李强",
               None, "补货精度提升", "库存周转", 5, 5, 4, 3, 2, 4, "通过", 20, 60])
    ws.append(["达人库", "业务", "数字化业务线", "达人资源库", None, "DTC", "王磊",
               None, None, None, None, None, None, None, None, None, None, None, None])
    ws.append(["坏行", "功能", "不存在的业务线", "描述", None, None, None,
               None, None, None, None, None, None, None, None, None, None, None, None])
    buf = io.BytesIO()
    wb.save(buf)

    resp = client.post("/api/requirements/import",
                       files={"file": ("req.xlsx", buf.getvalue(),
                                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                       headers=ctx["admin"])
    data = resp.json()["data"]
    assert data["imported"] == 2, resp.text
    assert len(data["errors"]) == 1 and "不存在" in data["errors"][0]["error"]

    # 已评分行落到评估中，且总分/象限计算正确
    listing = client.get("/api/requirements?q=海外仓", headers=ctx["admin"]).json()["data"]
    wms = next(x for x in listing if x["title"] == "海外仓WMS")
    assert wms["status"] == "evaluating" and wms["decision"] == "通过"
    # 5,5,4,3,2,4 → 0.2*5+0.2*5+0.2*4+0.1*3+0.1*(6-2)+0.2*4 = 1+1+0.8+0.3+0.4+0.8 = 4.3
    assert wms["weighted_total"] == 4.3 and wms["quadrant"] == "战略下注"


def test_active_tasks_board(client, ctx):
    """需求走到实现阶段，任务(含描述/工天)出现在实现任务清单。"""
    r = _register(client, ctx["pdm"], ctx["domain"], title="任务看板需求")
    rid = r["id"]
    client.post(f"/api/requirements/{rid}/transition", json={"to": "evaluating", "fields": {}}, headers=ctx["admin"])
    client.post(f"/api/requirements/{rid}/score", json={
        "d1_strategy": 5, "d2_value": 5, "d3_tech": 4, "d4_org": 4, "d5_risk": 2, "d6_speed": 5, "decision": "通过",
    }, headers=ctx["admin"])
    client.post(f"/api/requirements/{rid}/transition", json={"to": "analyzing", "fields": {}}, headers=ctx["admin"])
    client.patch(f"/api/requirements/{rid}", json={"owner": ctx["pdm_p"], "solution": "MVP"}, headers=ctx["admin"])
    resp = client.post(f"/api/requirements/{rid}/transition", json={"to": "implementing", "fields": {}}, headers=ctx["admin"])
    assert resp.json()["data"]["status"] == "implementing", resp.text

    client.post(f"/api/requirements/{rid}/tasks", json={
        "name": "接口开发", "description": "对接海外仓API", "assignee": ctx["pdm_p"], "plan_effort": 5,
    }, headers=ctx["admin"])

    rows = client.get("/api/requirements/tasks/active", headers=ctx["admin"]).json()["data"]
    mine = next(x for x in rows if x["requirement_id"] == rid)
    assert mine["description"] == "对接海外仓API" and mine["plan_effort"] == 5
    assert mine["requirement_code"] == r["requirement_code"] and mine["requirement_status"] == "implementing"
    assert mine["name"] == "接口开发"
