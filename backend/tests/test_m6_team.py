"""M6 团队管理：建言积分 / 专项活动发放与上限 / 自动事件积分 / 培训 / 人效框架 / 流程监控 / 示例只读。"""
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

    dev_pid, dev_h = member_and_user("积分开发", "pt_dev", ["it_dev"])
    tm_pid, tm_h = member_and_user("积分组长", "pt_tm", ["it_tm"])
    cio_pid, cio_h = member_and_user("积分总监", "pt_cio", ["cio"])
    return {"dev_pid": dev_pid, "dev_h": dev_h, "tm_pid": tm_pid, "tm_h": tm_h,
            "cio_pid": cio_pid, "cio_h": cio_h, "member_and_user": member_and_user}


def my_points(client, headers):
    return client.get("/api/points/mine", headers=headers).json()["data"]


# ---------- 建言献策 ----------

def test_idea_submit_like_adopt_points(client, admin_headers, ctx):
    """提交+2 → 他人点赞+1 → 采纳+20；自赞/重复赞被拒。"""
    r = client.post("/api/ideas", json={"title": "值班机器人提醒", "content": "接入告警自动@值班人"}, headers=ctx["dev_h"])
    assert r.json()["success"], r.text
    idea = r.json()["data"]
    assert idea["idea_code"].startswith("ID-")
    assert my_points(client, ctx["dev_h"])["total"] == 2  # idea_submit

    # 自己点赞被拒
    r = client.post(f"/api/ideas/{idea['id']}/like", headers=ctx["dev_h"])
    assert r.json()["error"]["code"] == "SELF_LIKE"
    # 组长点赞 → 提出人 +1
    assert client.post(f"/api/ideas/{idea['id']}/like", headers=ctx["tm_h"]).json()["success"]
    r = client.post(f"/api/ideas/{idea['id']}/like", headers=ctx["tm_h"])
    assert r.json()["error"]["code"] == "DUPLICATE"
    assert my_points(client, ctx["dev_h"])["total"] == 3

    # it_tm 有 ideas.edit → 可采纳；采纳 +20
    r = client.patch(f"/api/ideas/{idea['id']}/status", json={"status": "adopted"}, headers=ctx["tm_h"])
    assert r.json()["success"], r.text
    assert my_points(client, ctx["dev_h"])["total"] == 23

    rows = client.get("/api/ideas", headers=ctx["dev_h"]).json()["data"]
    mine = next(x for x in rows if x["id"] == idea["id"])
    assert mine["status"] == "adopted" and mine["like_count"] == 1


def test_idea_requires_only_two_fields(client, ctx):
    r = client.post("/api/ideas", json={"title": "短"}, headers=ctx["dev_h"])
    assert r.status_code == 422  # content 必填，且仅 2 字段即可提交（上一用例已证）


# ---------- 专项活动 ----------

@pytest.fixture(scope="module")
def campaign(client, ctx):
    body = {
        "name": "季度文档冲刺", "description": "补齐运维文档",
        "period_label": "2026-H2", "start_date": "2026-07-01", "end_date": "2026-09-30",
        "performance_ratio": 0.2,
        "tasks": [
            {"name": "完成一篇 SOP", "points": 10, "max_times": 2},
            {"name": "评审他人文档", "points": 5, "max_times": 0},
        ],
    }
    r = client.post("/api/campaigns", json=body, headers=ctx["tm_h"])
    assert r.json()["success"], r.text
    return r.json()["data"]


def test_campaign_visibility_by_status(client, ctx, campaign):
    """草稿仅管理者可见；上架后全员可见。"""
    names = [c["name"] for c in client.get("/api/campaigns", headers=ctx["dev_h"]).json()["data"]]
    assert "季度文档冲刺" not in names  # draft 对普通成员隐藏
    r = client.post(f"/api/campaigns/{campaign['id']}/status", json={"status": "active"}, headers=ctx["tm_h"])
    assert r.json()["success"]
    rows = client.get("/api/campaigns", headers=ctx["dev_h"]).json()["data"]
    mine = next(c for c in rows if c["name"] == "季度文档冲刺")
    assert mine["status"] == "active" and len(mine["tasks"]) == 2


def test_award_max_times_and_ledger(client, ctx, campaign):
    """按任务发放；超上限拦截；台账 period=活动考核期；折算分=积分×系数。"""
    task_sop = next(t for t in campaign["tasks"] if t["name"] == "完成一篇 SOP")
    aw = {"person_id": ctx["dev_pid"], "task_id": task_sop["id"], "times": 2}
    r = client.post(f"/api/campaigns/{campaign['id']}/awards", json=aw, headers=ctx["tm_h"])
    assert r.json()["data"]["awarded"] == 20
    r = client.post(f"/api/campaigns/{campaign['id']}/awards",
                    json={**aw, "times": 1}, headers=ctx["tm_h"])
    assert r.json()["error"]["code"] == "MAX_TIMES"

    # max_times=0 不限次
    task_review = next(t for t in campaign["tasks"] if t["name"] == "评审他人文档")
    for _ in range(3):
        assert client.post(f"/api/campaigns/{campaign['id']}/awards",
                           json={"person_id": ctx["dev_pid"], "task_id": task_review["id"]},
                           headers=ctx["tm_h"]).json()["success"]

    detail = client.get(f"/api/campaigns/{campaign['id']}", headers=ctx["dev_h"]).json()["data"]
    assert detail["my_points"] == 35 and detail["my_performance"] == 7.0  # 35×0.2
    assert detail["leaderboard"][0]["points"] == 35
    assert detail["can_manage"] is False  # it_dev 无 ideas.edit

    board = client.get("/api/points/leaderboard?period=2026-H2", headers=ctx["dev_h"]).json()["data"]["board"]
    assert any(b["person_name"] == "积分开发" for b in board)


def test_award_requires_active_and_perm(client, ctx, campaign):
    task = campaign["tasks"][0]
    # 普通成员无发放权限
    r = client.post(f"/api/campaigns/{campaign['id']}/awards",
                    json={"person_id": ctx["dev_pid"], "task_id": task["id"]}, headers=ctx["dev_h"])
    assert r.status_code == 403
    # 下架后不能发放
    client.post(f"/api/campaigns/{campaign['id']}/status", json={"status": "offline"}, headers=ctx["tm_h"])
    r = client.post(f"/api/campaigns/{campaign['id']}/awards",
                    json={"person_id": ctx["tm_pid"], "task_id": task["id"]}, headers=ctx["tm_h"])
    assert r.json()["error"]["code"] == "NOT_ACTIVE"
    client.post(f"/api/campaigns/{campaign['id']}/status", json={"status": "active"}, headers=ctx["tm_h"])


def test_campaign_edit_locked_after_awards(client, ctx, campaign):
    """已有发放记录后：任务只增不删（保护台账引用）。"""
    body = {
        "name": "季度文档冲刺", "period_label": "2026-H2",
        "start_date": "2026-07-01", "end_date": "2026-09-30", "performance_ratio": 0.2,
        "tasks": [{"name": "全新任务", "points": 8, "max_times": 1}],
    }
    r = client.patch(f"/api/campaigns/{campaign['id']}", json=body, headers=ctx["tm_h"])
    data = r.json()["data"]
    names = [t["name"] for t in data["tasks"]]
    assert "完成一篇 SOP" in names and "全新任务" in names  # 原任务保留，新任务追加


def test_example_campaign_seeded_and_readonly(client, admin_headers, ctx):
    """示例活动置顶上架、含 4 个激励任务；不可编辑/发放/下架。"""
    rows = client.get("/api/campaigns", headers=ctx["dev_h"]).json()["data"]
    demo = rows[0]
    assert demo["is_example"] and "团建活动方案策划" in demo["name"] and demo["status"] == "active"
    assert len(demo["tasks"]) == 4
    detail = client.get(f"/api/campaigns/{demo['id']}", headers=admin_headers).json()["data"]
    assert detail["can_manage"] is False
    for call in (
        lambda: client.post(f"/api/campaigns/{demo['id']}/status", json={"status": "offline"}, headers=admin_headers),
        lambda: client.post(f"/api/campaigns/{demo['id']}/awards",
                            json={"person_id": ctx["dev_pid"], "task_id": demo["tasks"][0]["id"]}, headers=admin_headers),
    ):
        assert call().json()["error"]["code"] == "EXAMPLE_READONLY"
    # 示例建言同样只读
    ideas = client.get("/api/ideas", headers=ctx["dev_h"]).json()["data"]
    assert ideas[0]["is_example"] and ideas[0]["idea_code"] == "ID-DEMO-001"
    r = client.post(f"/api/ideas/{ideas[0]['id']}/like", headers=ctx["dev_h"])
    assert r.json()["error"]["code"] == "EXAMPLE_READONLY"


# ---------- 自动事件积分（M6b） ----------

def test_ticket_resolution_awards_points(client, admin_headers, ctx):
    """工单 解决+5 / 关单 SLA 双达成+3 —— 事件订阅自动计分。"""
    pid, h = ctx["member_and_user"]("积分运维", "pt_ops", ["it_ops"])
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    r = client.post("/api/tickets", json={"title": "积分事件测试工单", "ticket_type": "incident",
                                          "description": "test", "priority": "P4", "service_item_id": item,
                                          "assignee": pid},
                    headers=admin_headers)
    assert r.json()["success"], r.text
    t = r.json()["data"]
    client.post(f"/api/tickets/{t['id']}/transition", json={"to": "processing", "fields": {}}, headers=admin_headers)
    r = client.post(f"/api/tickets/{t['id']}/transition",
                    json={"to": "resolved", "fields": {"solution": "done", "root_cause": "n/a"}}, headers=admin_headers)
    assert r.json()["success"], r.text
    pts = my_points(client, h)
    assert pts["total"] == 5 and pts["entries"][0]["source_type"] == "ticket_resolved"
    r = client.post(f"/api/tickets/{t['id']}/transition",
                    json={"to": "closed", "fields": {"closure_code": "已解决"}}, headers=admin_headers)
    assert r.json()["success"], r.text
    assert my_points(client, h)["total"] == 8  # +ticket_sla_met（P4 时限宽裕必达成）


def test_training_awards_points(client, admin_headers, ctx):
    """培训登记：主讲+15、参与+3；类型校验。"""
    r = client.post("/api/trainings", json={"activity_type": "野餐", "topic": "xx",
                                            "activity_date": "2026-07-10"}, headers=admin_headers)
    assert r.json()["error"]["code"] == "INVALID_TYPE"
    r = client.post("/api/trainings", json={
        "activity_type": "内部交叉培训", "topic": "PostgreSQL 调优分享", "activity_date": "2026-07-10",
        "host_id": ctx["tm_pid"], "participant_ids": [ctx["tm_pid"], ctx["dev_pid"]],
    }, headers=admin_headers)
    assert r.json()["success"], r.text
    tm_entries = my_points(client, ctx["tm_h"])["entries"]
    assert any(e["source_type"] == "training_host" and e["points"] == 15 for e in tm_entries)
    dev_entries = my_points(client, ctx["dev_h"])["entries"]
    assert any(e["source_type"] == "training_attend" and e["points"] == 3 for e in dev_entries)
    assert not any(e["source_type"] == "training_attend" for e in tm_entries)  # 主讲不重复计参与分


def test_point_rule_inactive_skips(client, admin_headers, ctx):
    """停用规则后不再计分（可配置开关）。"""
    from app.db import SessionLocal
    from app.models import PointRule
    db = SessionLocal()
    rule = db.query(PointRule).filter(PointRule.code == "idea_submit").first()
    rule.active = False
    db.commit()
    before = my_points(client, ctx["dev_h"])["total"]
    client.post("/api/ideas", json={"title": "停用规则验证", "content": "x"}, headers=ctx["dev_h"])
    assert my_points(client, ctx["dev_h"])["total"] == before
    rule = db.query(PointRule).filter(PointRule.code == "idea_submit").first()
    rule.active = True
    db.commit()
    db.close()


# ---------- 团队总览 / 人效 / 文化 / 招聘 ----------

def test_team_overview_and_performance(client, admin_headers, ctx):
    ov = client.get("/api/team/overview", headers=ctx["dev_h"]).json()["data"]
    assert ov["active_campaigns"] >= 2  # 示例 + 文档冲刺
    assert any(w["person_name"] == "积分运维" for w in ov["workload"]) or ov["onboard_count"] > 0
    assert any(b["person_name"] == "积分开发" for b in ov["points_board"])

    # 人效可见性（M6.2）：admin/cio/it_bm/it_tm（IT 管理岗）可见，普通成员 403
    assert client.get("/api/team/performance", headers=ctx["dev_h"]).status_code == 403
    assert client.get("/api/team/performance", headers=ctx["tm_h"]).status_code == 200
    perf = client.get("/api/team/performance?period=2026-H2", headers=ctx["cio_h"]).json()["data"]
    assert perf["rows"] and perf["dimensions"]
    dev_row = next(r for r in perf["rows"] if r["person_name"] == "积分开发")
    assert dev_row["scheme_name"] == "默认方案（兜底）"  # 未绑岗位走兜底方案
    assert dev_row["dims"]["activity_points"]["score"] is not None


def test_charter_and_hiring(client, admin_headers, ctx):
    assert client.put("/api/team-charter", json={"vision": "稳定高效"}, headers=ctx["dev_h"]).status_code == 403
    r = client.put("/api/team-charter", json={"vision": "稳定高效", "goals": "全年可用率 99.9%"}, headers=ctx["tm_h"])
    assert r.json()["success"]
    assert client.get("/api/team-charter", headers=ctx["dev_h"]).json()["data"]["vision"] == "稳定高效"

    # 岗位编制（M6.1 收紧）：it_tm/it_dev 均不可见，cio 可管
    assert client.get("/api/positions", headers=ctx["dev_h"]).status_code == 403
    assert client.get("/api/hiring-needs", headers=ctx["tm_h"]).status_code == 403
    pos = client.post("/api/positions", json={"name": "DBA", "headcount": 1}, headers=ctx["cio_h"]).json()["data"]
    r = client.post("/api/hiring-needs", json={"position_id": pos["id"], "headcount": 2}, headers=ctx["cio_h"])
    hid = r.json()["data"]["id"]
    client.patch(f"/api/hiring-needs/{hid}", json={"position_id": pos["id"], "headcount": 2,
                                                   "status": "面试中", "progress_note": "已约 3 人"},
                 headers=ctx["cio_h"])
    rows = client.get("/api/hiring-needs", headers=ctx["cio_h"]).json()["data"]
    assert rows[0]["status"] == "面试中" and rows[0]["position_name"] == "DBA"


# ---------- 流程监控 / Dashboard ----------

def test_process_monitor_list(client, admin_headers, ctx):
    """事件工单触发的流程实例出现在监控列表，含当前卡点。"""
    r = client.get("/api/process-instances", headers=ctx["tm_h"])
    assert r.json()["success"], r.text
    rows = r.json()["data"]
    assert rows and all({"definition_name", "status", "entity_type"} <= set(x) for x in rows)
    running = client.get("/api/process-instances?status=running", headers=ctx["tm_h"]).json()["data"]
    assert all(x["status"] == "running" for x in running)
    assert client.get("/api/process-instances", headers=ctx["dev_h"]).status_code == 403  # it_dev 无监控权限


def test_dashboard_team_section(client, admin_headers):
    d = client.get("/api/dashboard", headers=admin_headers).json()["data"]
    team = d["team"]
    assert set(team) == {"top_workload", "top_points", "trainings", "hirings"}
    assert team["trainings"] >= 1 and team["hirings"] >= 1
    assert any(p["name"] == "积分开发" for p in team["top_points"])


def test_point_rules_api(client, admin_headers, ctx):
    """积分规则可查看；管理者可调分值/停用。"""
    rows = client.get("/api/point-rules", headers=ctx["dev_h"]).json()["data"]
    assert {"idea_submit", "training_host", "ticket_resolved"} <= {r["code"] for r in rows}
    r = client.patch("/api/point-rules/idea_like", json={"points": 2, "active": True}, headers=ctx["dev_h"])
    assert r.status_code == 403
    r = client.patch("/api/point-rules/idea_like", json={"points": 2, "active": True}, headers=ctx["tm_h"])
    assert r.json()["data"]["points"] == 2
    client.patch("/api/point-rules/idea_like", json={"points": 1, "active": True}, headers=ctx["tm_h"])
