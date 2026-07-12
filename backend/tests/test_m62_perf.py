"""M6.2：维度核定 + 加减分事项 / 招聘需求字段 / 用户偏好 / Dashboard 四板块 / requester 数据范围。"""
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

    dev_pid, dev_h = member_and_user("核定开发", "ov_dev", ["it_dev"])
    tm_pid, tm_h = member_and_user("核定组长", "ov_tm", ["it_tm"])
    bm_pid, bm_h = member_and_user("核定BM", "ov_bm", ["it_bm"])
    return {"dev_pid": dev_pid, "dev_h": dev_h, "tm_pid": tm_pid, "tm_h": tm_h,
            "bm_pid": bm_pid, "bm_h": bm_h, "member_and_user": member_and_user}


def perf_row(client, headers, name, period="2026-Q3"):
    data = client.get(f"/api/team/performance?period={period}", headers=headers).json()["data"]
    return next(r for r in data["rows"] if r["person_name"] == name)


# ---------- 维度核定（系统值只是初始参考） ----------

def test_override_and_clear(client, ctx):
    """it_tm/it_bm 均可核定；核定值参与总分；清除后回到参考值。"""
    row = perf_row(client, ctx["tm_h"], "核定开发")
    assert row["dims"]["knowledge_contrib"]["score"] == 0  # 公共维度参考值 0

    r = client.put("/api/perf/overrides", json={
        "period": "2026-Q3", "person_id": ctx["dev_pid"], "dimension_code": "knowledge_contrib", "score": 88,
    }, headers=ctx["tm_h"])
    assert r.json()["success"], r.text
    row = perf_row(client, ctx["bm_h"], "核定开发")  # it_bm 也能看
    dim = row["dims"]["knowledge_contrib"]
    assert dim["score"] == 0 and dim["override"] == 88 and dim["effective"] == 88

    # 无数据维度核定后也计入权重
    r = client.put("/api/perf/overrides", json={
        "period": "2026-Q3", "person_id": ctx["dev_pid"], "dimension_code": "ticket_service", "score": 70,
    }, headers=ctx["bm_h"])
    assert r.json()["success"]
    row = perf_row(client, ctx["tm_h"], "核定开发")
    assert row["dims"]["ticket_service"]["effective"] == 70

    # 清除核定 → 回参考值
    client.put("/api/perf/overrides", json={
        "period": "2026-Q3", "person_id": ctx["dev_pid"], "dimension_code": "ticket_service", "score": None,
    }, headers=ctx["tm_h"])
    row = perf_row(client, ctx["tm_h"], "核定开发")
    assert row["dims"]["ticket_service"]["override"] is None
    # 普通成员无权核定
    r = client.put("/api/perf/overrides", json={
        "period": "2026-Q3", "person_id": ctx["dev_pid"], "dimension_code": "knowledge_contrib", "score": 100,
    }, headers=ctx["dev_h"])
    assert r.status_code == 403


def test_adjustments_bonus_penalty(client, ctx):
    """加分/扣分事项：必填说明；计入总分 = 基础分 + 加分 − 扣分。"""
    r = client.post("/api/perf/adjustments", json={
        "period": "2026-Q3", "person_id": ctx["dev_pid"], "kind": "bonus", "points": 6,
        "reason": "重保期间通宵处理故障，特殊贡献",
    }, headers=ctx["tm_h"])
    assert r.json()["success"], r.text
    r = client.post("/api/perf/adjustments", json={
        "period": "2026-Q3", "person_id": ctx["dev_pid"], "kind": "penalty", "points": 2,
        "reason": "违规直连生产库",
    }, headers=ctx["tm_h"])
    adj_id = r.json()["data"]["id"]

    row = perf_row(client, ctx["tm_h"], "核定开发")
    assert row["bonus"] == 6 and row["penalty"] == 2
    assert {a["reason"] for a in row["adjustments"]} == {"重保期间通宵处理故障，特殊贡献", "违规直连生产库"}
    assert row["total"] == round((row["base_score"] or 0) + 6 - 2, 1)

    # 说明必填（min_length=2）
    r = client.post("/api/perf/adjustments", json={
        "period": "2026-Q3", "person_id": ctx["dev_pid"], "kind": "bonus", "points": 1, "reason": "x",
    }, headers=ctx["tm_h"])
    assert r.status_code == 422

    # 删除事项
    assert client.delete(f"/api/perf/adjustments/{adj_id}", headers=ctx["tm_h"]).json()["success"]
    row = perf_row(client, ctx["tm_h"], "核定开发")
    assert row["penalty"] == 0


# ---------- 招聘需求字段 ----------

def test_hiring_level_and_qualification(client, admin_headers):
    pos = client.post("/api/positions", json={"name": "SRE", "headcount": 1}, headers=admin_headers).json()["data"]
    # 任职资格必填（M6.3）
    r = client.post("/api/hiring-needs", json={"position_id": pos["id"], "level": "高级"}, headers=admin_headers)
    assert r.status_code == 422
    r = client.post("/api/hiring-needs", json={
        "position_id": pos["id"], "level": "高级", "headcount": 1,
        "qualification": "5 年以上大型系统运维经验；精通 K8s 与可观测体系；有故障指挥经验",
    }, headers=admin_headers)
    assert r.json()["success"], r.text
    rows = client.get("/api/hiring-needs", headers=admin_headers).json()["data"]
    row = next(x for x in rows if x["position_name"] == "SRE")
    assert row["level"] == "高级" and "K8s" in row["qualification"]
    # 级别枚举校验
    r = client.post("/api/hiring-needs", json={"position_id": pos["id"], "level": "special"}, headers=admin_headers)
    assert r.status_code == 422


# ---------- 用户偏好（总览 widget） ----------

def test_dashboard_preferences(client, ctx):
    me = client.get("/api/auth/me", headers=ctx["dev_h"]).json()["data"]
    assert me["preferences"] == {}
    r = client.patch("/api/auth/me/preferences",
                     json={"dashboard_widgets": ["itsm_service_request", "itsm_incident", "team"]},
                     headers=ctx["dev_h"])
    assert r.json()["data"]["preferences"]["dashboard_widgets"] == ["itsm_service_request", "itsm_incident", "team"]
    # 团队总览 widget 偏好独立保存（M6.3），且不覆盖已有键
    r = client.patch("/api/auth/me/preferences",
                     json={"team_overview_widgets": ["workload", "stats"]}, headers=ctx["dev_h"])
    prefs = r.json()["data"]["preferences"]
    assert prefs["team_overview_widgets"] == ["workload", "stats"]
    assert prefs["dashboard_widgets"] == ["itsm_service_request", "itsm_incident", "team"]
    me = client.get("/api/auth/me", headers=ctx["dev_h"]).json()["data"]
    assert me["preferences"]["dashboard_widgets"] == ["itsm_service_request", "itsm_incident", "team"]


# ---------- Dashboard 四板块 ----------

def test_dashboard_itsm_blocks(client, admin_headers):
    d = client.get("/api/dashboard", headers=admin_headers).json()["data"]
    blocks = d["service"]["itsm_blocks"]
    assert set(blocks) == {"service_request", "change", "incident", "problem"}
    assert {"open", "month_resolved", "sla_rate"} <= set(blocks["service_request"])
    assert {"pending_approval", "implementing", "success_rate"} <= set(blocks["change"])
    assert {"open", "sla_warned", "month_resolved"} <= set(blocks["incident"])
    assert {"open", "known_errors", "close_rate"} <= set(blocks["problem"])


# ---------- requester 数据范围核查（④） ----------

def test_requester_scope(client, admin_headers, ctx):
    """业务用户：能提工单/需求并跟踪自己的；看不到他人单据与 IT 内部模块。"""
    _pid, req_h = ctx["member_and_user"]("业务用户甲", "biz_a", ["requester"])

    # 他人工单不可见（示例工单 + ctx 用户的单都不属于他）
    rows = client.get("/api/tickets", headers=req_h).json()["data"]
    assert rows == []
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    t = client.post("/api/tickets", json={"title": "业务用户报障单", "ticket_type": "service_request",
                                          "description": "OA 打不开", "priority": "P3", "service_item_id": item},
                    headers=req_h).json()["data"]
    rows = client.get("/api/tickets", headers=req_h).json()["data"]
    assert [x["id"] for x in rows] == [t["id"]]  # 只看到自己的
    # 能查自己单据详情（进展跟踪）
    assert client.get(f"/api/tickets/{t['id']}", headers=req_h).json()["data"]["status"]

    # 需求：能提能看自己的（4 必填：标题/类型/业务域/描述）
    domain = client.get("/api/admin/business-domains", headers=admin_headers).json()["data"][0]["id"]
    r = client.post("/api/requirements", json={"title": "希望增加移动端审批", "req_type": "功能",
                                               "business_domain_id": domain, "description": "出差时审批不便"},
                    headers=req_h)
    assert r.json()["success"], r.text
    rows = client.get("/api/requirements", headers=req_h).json()["data"]
    assert len(rows) == 1 and rows[0]["title"] == "希望增加移动端审批"

    # IT 内部模块全部 403（接口层强制，不只菜单隐藏）
    for path in ("/api/problems", "/api/projects", "/api/portfolios", "/api/cis",
                 "/api/vendors", "/api/contracts", "/api/catalogs", "/api/sla/dashboard",
                 "/api/team/performance", "/api/process-instances", "/api/positions", "/api/hiring-needs",
                 "/api/campaigns", "/api/ideas", "/api/points/leaderboard",
                 "/api/trainings", "/api/team-charter", "/api/team/overview"):
        assert client.get(path, headers=req_h).status_code == 403, path
    # 但提单依赖的服务项列表可用（选择服务项）
    assert client.get("/api/service-items", headers=req_h).json()["success"]
    # 变更类工单创建被类型权限拦截？requester 可建 service_request；建变更单应被业务拒绝或允许？
    # 现行设计：类型不受矩阵限制，但页面入口仅服务请求；后端保持宽松（提交人只能跟踪自己的单）。
    # 团队总览对 requester 开放与否：team_overview 模块 requester 无 → 菜单隐藏；接口 get_current_user 放行。
    me = client.get("/api/auth/me", headers=req_h).json()["data"]
    perms = me["permissions"]
    assert set(perms) == {"dashboard", "tickets", "knowledge", "requirements"}
    assert perms["tickets"] == ["create", "view"] and perms["requirements"] == ["create", "view"]


# ---------- 季度考核制（M6.4）：Q1-Q3 单季 + 全年 All 聚合 ----------

def test_quarterly_periods_and_yearly_all(client, admin_headers, ctx):
    """全年考核 YYYY-All：积分聚合全年各周期打标；人效统计范围=全年。"""
    from app.db import SessionLocal
    from app.services.points import award

    db = SessionLocal()
    award(db, ctx["dev_pid"], 10, "manual", period="2026-Q1", note="Q1 积分")
    award(db, ctx["dev_pid"], 7, "manual", period="2026-Q3", note="Q3 积分")
    award(db, ctx["dev_pid"], 3, "manual", period="2026-All", note="Q4 期间积分（打标全年期）")
    db.commit()
    db.close()

    # 单季只统计本季
    q1 = client.get("/api/points/leaderboard?period=2026-Q1", headers=ctx["tm_h"]).json()["data"]["board"]
    assert next(b["points"] for b in q1 if b["person_name"] == "核定开发") == 10
    # 全年考核聚合 Q1+Q3+All 全部打标
    yr = client.get("/api/points/leaderboard?period=2026-All", headers=ctx["tm_h"]).json()["data"]["board"]
    assert next(b["points"] for b in yr if b["person_name"] == "核定开发") == 20

    # 人效：全年期合法，活动积分维度按全年聚合（相对分，有积分即 >0）
    perf = client.get("/api/team/performance?period=2026-All", headers=ctx["tm_h"]).json()["data"]
    dev_row = next(r for r in perf["rows"] if r["person_name"] == "核定开发")
    assert dev_row["dims"]["activity_points"]["score"] is not None
    # 非法格式被拒（H 制已废弃）
    assert client.get("/api/team/performance?period=2026-H2", headers=ctx["tm_h"]).json()["error"]["code"] == "INVALID_PERIOD"
    assert client.get("/api/team/performance?period=2026-Q4", headers=ctx["tm_h"]).json()["error"]["code"] == "INVALID_PERIOD"
