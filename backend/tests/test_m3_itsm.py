"""M3：CMDB / 问题 / 供应商 / 合同 / 知识库。"""
from datetime import date, timedelta

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

    ops_person, ops = member_and_user("运维甲", "mops1", ["it_ops"])
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    return {"ops_person": ops_person, "ops": ops, "item": item, "mu": member_and_user}


# ---------- 问题 ----------

def test_problem_lifecycle(client, ctx):
    r = client.post(
        "/api/problems",
        json={"title": "数据库连接池频繁耗尽", "description": "近一周 3 次", "priority": "P2", "owner": ctx["ops_person"]},
        headers=ctx["ops"],
    )
    p = r.json()["data"]
    assert p["problem_code"].startswith("PB-")

    detail = client.get(f"/api/problems/{p['id']}", headers=ctx["ops"]).json()["data"]
    assert detail["process"]["definition_name"] == "问题分析流程"

    # 转已知错误缺根因被拒
    r = client.post(f"/api/problems/{p['id']}/transition", json={"to": "analyzing", "fields": {}}, headers=ctx["ops"])
    assert r.json()["success"]
    r = client.post(f"/api/problems/{p['id']}/transition", json={"to": "known_error", "fields": {}}, headers=ctx["ops"])
    assert r.json()["error"]["code"] == "STAGE_FIELD_REQUIRED"

    r = client.post(
        f"/api/problems/{p['id']}/transition",
        json={"to": "known_error", "fields": {"root_cause": "连接泄漏：ORM session 未关闭", "workaround": "定时重启连接池"}},
        headers=ctx["ops"],
    )
    assert r.json()["data"]["status"] == "known_error"
    client.post(f"/api/problems/{p['id']}/transition", json={"to": "resolved", "fields": {}}, headers=ctx["ops"])
    r = client.post(f"/api/problems/{p['id']}/transition", json={"to": "closed", "fields": {}}, headers=ctx["ops"])
    assert r.json()["data"]["status"] == "closed"


def test_ticket_escalate_to_problem(client, ctx):
    t = client.post(
        "/api/tickets",
        json={"title": "邮件系统再次宕机", "ticket_type": "incident", "priority": "P2",
              "description": "本月第三次", "service_item_id": ctx["item"], "assignee": ctx["ops_person"]},
        headers=ctx["ops"],
    ).json()["data"]

    r = client.post(f"/api/tickets/{t['id']}/escalate-problem", headers=ctx["ops"])
    assert r.json()["success"], r.text
    problem_id = r.json()["data"]["problem_id"]

    detail = client.get(f"/api/problems/{problem_id}", headers=ctx["ops"]).json()["data"]
    assert detail["source_ticket_id"] == t["id"]
    assert any(lt["id"] == t["id"] for lt in detail["linked_tickets"])
    assert "由工单" in detail["description"]

    # 重复升级被拒
    r = client.post(f"/api/tickets/{t['id']}/escalate-problem", headers=ctx["ops"])
    assert r.json()["error"]["code"] == "ALREADY_ESCALATED"

    # 再关联一张同根因工单
    t2 = client.post(
        "/api/tickets",
        json={"title": "邮件又挂了", "ticket_type": "incident", "priority": "P3",
              "description": "d", "service_item_id": ctx["item"]},
        headers=ctx["ops"],
    ).json()["data"]
    r = client.post(f"/api/problems/{problem_id}/link-ticket", json={"ticket_id": t2["id"]}, headers=ctx["ops"])
    assert r.json()["success"]
    detail = client.get(f"/api/problems/{problem_id}", headers=ctx["ops"]).json()["data"]
    assert detail["linked_ticket_count"] == 2


# ---------- CMDB ----------

def test_ci_crud_and_impact(client, ctx, admin_headers):
    def mk_ci(name, category, attrs=None):
        r = client.post(
            "/api/cis",
            json={"name": name, "category": category, "owner": ctx["ops_person"],
                  "environment": "生产", "attrs": attrs or {}},
            headers=ctx["ops"],
        )
        assert r.json()["success"], r.text
        return r.json()["data"]

    app_ci = mk_ci("报表系统", "app", {"tech_stack": "Java/MySQL", "deploy_mode": "容器"})
    db_ci = mk_ci("MySQL 主库", "server", {"ip": "10.0.0.10"})
    net_ci = mk_ci("核心交换机", "network")

    assert app_ci["ci_code"].startswith("CI-")
    assert app_ci["attrs"]["tech_stack"] == "Java/MySQL"

    # 关系：报表系统 运行于 MySQL；MySQL 连接 交换机
    r = client.post("/api/ci-relationships", json={"source_ci_id": app_ci["id"], "target_ci_id": db_ci["id"], "relation_type": "运行于"}, headers=ctx["ops"])
    assert r.json()["success"]
    client.post("/api/ci-relationships", json={"source_ci_id": db_ci["id"], "target_ci_id": net_ci["id"], "relation_type": "连接"}, headers=ctx["ops"])

    # 自环与重复被拒
    r = client.post("/api/ci-relationships", json={"source_ci_id": app_ci["id"], "target_ci_id": app_ci["id"], "relation_type": "依赖"}, headers=ctx["ops"])
    assert r.json()["error"]["code"] == "INVALID_RELATION"
    r = client.post("/api/ci-relationships", json={"source_ci_id": app_ci["id"], "target_ci_id": db_ci["id"], "relation_type": "运行于"}, headers=ctx["ops"])
    assert r.json()["error"]["code"] == "DUPLICATE"

    # 影响分析：MySQL 的上游=交换机(我连接的)，下游=报表系统(运行于我)
    impact = client.get(f"/api/cis/{db_ci['id']}/impact", headers=ctx["ops"]).json()["data"]
    assert any(x["ci"]["name"] == "核心交换机" for x in impact["upstream"])
    assert any(x["ci"]["name"] == "报表系统" for x in impact["downstream"])

    # 关联工单出现在影响分析
    client.post(
        "/api/tickets",
        json={"title": "报表打不开", "ticket_type": "incident", "priority": "P3", "description": "d",
              "service_item_id": ctx["item"], "ci_id": db_ci["id"]},
        headers=ctx["ops"],
    )
    impact = client.get(f"/api/cis/{db_ci['id']}/impact", headers=ctx["ops"]).json()["data"]
    assert len(impact["tickets"]) == 1

    # requester 无权建 CI
    _, req = ctx["mu"]("报单员", "mreq1", ["requester"])
    r = client.post("/api/cis", json={"name": "x", "category": "app", "owner": ctx["ops_person"]}, headers=req)
    assert r.status_code == 403


# ---------- 供应商与合同 ----------

def test_vendor_contract_and_expiry(client, ctx, admin_headers):
    v = client.post(
        "/api/vendors",
        json={"name": "云服务商A", "contact": "王经理", "rating": "A", "service_scope": "云主机/数据库"},
        headers=ctx["ops"],
    ).json()["data"]
    assert v["code"].startswith("VD-")

    # 日期非法被拒
    r = client.post(
        "/api/contracts",
        json={"name": "云资源年度合同", "vendor_id": v["id"],
              "start_date": "2026-01-01", "end_date": "2025-01-01"},
        headers=ctx["ops"],
    )
    assert r.json()["error"]["code"] == "INVALID_DATES"

    # 临期合同（60 天后到期）
    end = (date.today() + timedelta(days=60)).isoformat()
    c = client.post(
        "/api/contracts",
        json={"name": "云资源年度合同", "vendor_id": v["id"], "amount_10k": 50,
              "start_date": "2026-01-01", "end_date": end, "owner": ctx["ops_person"]},
        headers=ctx["ops"],
    ).json()["data"]
    assert c["status"] == "临期" and 0 < c["days_to_expiry"] <= 90

    # 到期扫描发通知
    from app.services.scheduler import scan_contract_expiry

    scan_contract_expiry()
    notif = client.get("/api/notifications", headers=ctx["ops"]).json()["data"]
    assert any("合同临期" in n["title"] for n in notif)

    # 续签（改到期日）后状态回生效且预警重置
    new_end = (date.today() + timedelta(days=400)).isoformat()
    c2 = client.patch(f"/api/contracts/{c['id']}", json={"end_date": new_end}, headers=ctx["ops"]).json()["data"]
    assert c2["status"] == "生效"

    # Dashboard 告警包含临期合同（先造一个新的临期合同）
    client.post(
        "/api/contracts",
        json={"name": "网络维保合同", "vendor_id": v["id"],
              "start_date": "2026-01-01", "end_date": (date.today() + timedelta(days=30)).isoformat()},
        headers=ctx["ops"],
    )
    dash = client.get("/api/dashboard", headers=ctx["ops"]).json()["data"]
    assert any(a["type"] == "contract_expiring" for a in dash["alerts"])


# ---------- 知识库 ----------

def test_knowledge_flow(client, ctx, admin_headers):
    _, dev = ctx["mu"]("开发乙", "mdev1", ["it_dev"])

    a = client.post(
        "/api/knowledge",
        json={"title": "MySQL 连接池调优指南", "content": "## 背景\n...", "tags": ["数据库", "性能"]},
        headers=ctx["ops"],
    ).json()["data"]
    assert a["article_code"].startswith("KB-") and a["status"] == "published"

    # 检索
    r = client.get("/api/knowledge?q=连接池", headers=dev).json()
    assert any(x["id"] == a["id"] for x in r["data"])

    # 浏览计数 + 投票（不能自投、不能重复）
    client.get(f"/api/knowledge/{a['id']}", headers=dev)
    r = client.post(f"/api/knowledge/{a['id']}/vote", headers=ctx["ops"])
    assert r.json()["error"]["code"] == "SELF_VOTE"
    r = client.post(f"/api/knowledge/{a['id']}/vote", headers=dev)
    assert r.json()["data"]["helpful_count"] == 1
    r = client.post(f"/api/knowledge/{a['id']}/vote", headers=dev)
    assert r.json()["error"]["code"] == "DUPLICATE"

    detail = client.get(f"/api/knowledge/{a['id']}", headers=dev).json()["data"]
    assert detail["view_count"] >= 2 and detail["voted"] is True


def test_ticket_to_knowledge_draft(client, ctx):
    t = client.post(
        "/api/tickets",
        json={"title": "VPN 证书过期处理", "ticket_type": "incident", "priority": "P3",
              "description": "证书到期导致无法拨入", "service_item_id": ctx["item"]},
        headers=ctx["ops"],
    ).json()["data"]
    client.post(f"/api/tickets/{t['id']}/transition", json={"to": "resolved", "fields": {"solution": "更换证书并设置到期提醒"}}, headers=ctx["ops"])

    r = client.post(f"/api/tickets/{t['id']}/to-knowledge", headers=ctx["ops"])
    article_id = r.json()["data"]["article_id"]
    detail = client.get(f"/api/knowledge/{article_id}", headers=ctx["ops"]).json()["data"]
    assert detail["status"] == "draft"
    assert "更换证书" in detail["content"]
    assert any(lt["id"] == t["id"] for lt in detail["linked_tickets"])

    # 草稿他人不可见
    _, other = ctx["mu"]("路人丙", "mother1", ["it_dev"])
    assert client.get(f"/api/knowledge/{article_id}", headers=other).status_code == 403
    listing = client.get("/api/knowledge", headers=other).json()["data"]
    assert all(x["id"] != article_id for x in listing)

    # 作者发布后全员可见
    client.patch(f"/api/knowledge/{article_id}", json={"status": "published"}, headers=ctx["ops"])
    assert client.get(f"/api/knowledge/{article_id}", headers=other).json()["data"]["title"]


def test_dashboard_problem_rate(client, ctx):
    dash = client.get("/api/dashboard", headers=ctx["ops"]).json()["data"]["service"]
    assert dash["problem_close_rate"] is not None
    assert dash["open_problems"] >= 1
