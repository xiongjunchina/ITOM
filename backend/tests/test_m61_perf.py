"""M6.1：人效计分方案 CRUD 与自动计算 / 人员删除 / 权限收紧 / Dashboard 分型统计。"""
import pytest


@pytest.fixture(scope="module")
def ctx(client, admin_headers):
    def member_and_user(name, username, roles, position_id=None):
        body = {"name": name}
        if position_id:
            body["position_id"] = position_id
        m = client.post("/api/members", json=body, headers=admin_headers).json()["data"]
        client.post(
            "/api/admin/users",
            json={"username": username, "password": "pass123", "roles": roles, "person_id": m["id"]},
            headers=admin_headers,
        )
        token = client.post("/api/auth/login", json={"username": username, "password": "pass123"}).json()["data"]["token"]
        return m["id"], {"Authorization": f"Bearer {token}"}

    pos_ops = client.post("/api/positions", json={"name": "运维专员", "headcount": 2}, headers=admin_headers).json()["data"]
    ops_pid, ops_h = member_and_user("绩效运维", "pf_ops", ["it_ops"], position_id=pos_ops["id"])
    cio_pid, cio_h = member_and_user("绩效总监", "pf_cio", ["cio"])
    dev_pid, dev_h = member_and_user("绩效开发", "pf_dev", ["it_dev"])
    return {"pos_ops": pos_ops["id"], "ops_pid": ops_pid, "ops_h": ops_h,
            "cio_pid": cio_pid, "cio_h": cio_h, "dev_pid": dev_pid, "dev_h": dev_h,
            "member_and_user": member_and_user}


# ---------- 计分方案 ----------

def test_seeded_schemes_and_dimensions(client, ctx):
    dims = client.get("/api/perf/dimensions", headers=ctx["cio_h"]).json()["data"]
    assert {d["code"] for d in dims} == {
        "ticket_service", "change_compliance", "project_delivery", "requirement_delivery",
        "domain_satisfaction", "knowledge_contrib", "activity_points",
    }
    schemes = client.get("/api/perf/schemes", headers=ctx["cio_h"]).json()["data"]
    names = [s["name"] for s in schemes]
    assert "默认方案（兜底）" in names and "运维序列（参考模板）" in names
    default = next(s for s in schemes if s["is_default"])
    assert default["weight_total"] == 100
    # it_dev 无 performance 权限
    assert client.get("/api/perf/schemes", headers=ctx["dev_h"]).status_code == 403


def test_scheme_crud_and_validation(client, ctx):
    body = {
        "name": "运维专员方案", "position_ids": [ctx["pos_ops"]],
        "dimensions": [{"code": "ticket_service", "weight": 60}, {"code": "change_compliance", "weight": 40}],
    }
    r = client.post("/api/perf/schemes", json=body, headers=ctx["cio_h"])
    assert r.json()["success"], r.text
    sid = r.json()["data"]["id"]

    # 同岗位不能命中两个启用方案
    r = client.post("/api/perf/schemes", json={**body, "name": "冲突方案"}, headers=ctx["cio_h"])
    assert r.json()["error"]["code"] == "POSITION_CONFLICT"
    # 维度校验
    r = client.post("/api/perf/schemes", json={**body, "position_ids": [], "name": "坏维度",
                                               "dimensions": [{"code": "nope", "weight": 10}]}, headers=ctx["cio_h"])
    assert r.json()["error"]["code"] == "INVALID_DIMENSION"
    r = client.post("/api/perf/schemes", json={**body, "position_ids": [], "name": "重复维度",
                                               "dimensions": [{"code": "ticket_service", "weight": 10},
                                                              {"code": "ticket_service", "weight": 20}]}, headers=ctx["cio_h"])
    assert r.json()["error"]["code"] == "DUPLICATE_DIMENSION"

    # 编辑：权重调整
    body["dimensions"] = [{"code": "ticket_service", "weight": 50}, {"code": "change_compliance", "weight": 30},
                          {"code": "activity_points", "weight": 20}]
    r = client.patch(f"/api/perf/schemes/{sid}", json=body, headers=ctx["cio_h"])
    assert r.json()["data"]["weight_total"] == 100
    # it_dev 不能改
    assert client.patch(f"/api/perf/schemes/{sid}", json=body, headers=ctx["dev_h"]).status_code == 403


def test_performance_computation(client, admin_headers, ctx):
    """运维走岗位方案；工单维度按 SLA+满意度计；无数据维度自动归一。"""
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    t = client.post("/api/tickets", json={
        "title": "绩效计算工单", "ticket_type": "incident", "description": "x", "priority": "P4",
        "service_item_id": item, "assignee": ctx["ops_pid"],
    }, headers=admin_headers).json()["data"]
    client.post(f"/api/tickets/{t['id']}/transition", json={"to": "processing", "fields": {}}, headers=admin_headers)
    client.post(f"/api/tickets/{t['id']}/transition",
                json={"to": "resolved", "fields": {"solution": "done"}}, headers=admin_headers)
    client.post(f"/api/tickets/{t['id']}/transition",
                json={"to": "closed", "fields": {"closure_code": "已解决"}}, headers=admin_headers)
    client.post(f"/api/tickets/{t['id']}/satisfaction", json={"score": 4}, headers=admin_headers)

    perf = client.get("/api/team/performance", headers=ctx["cio_h"]).json()["data"]
    ops_row = next(r for r in perf["rows"] if r["person_name"] == "绩效运维")
    assert ops_row["scheme_name"] == "运维专员方案"
    ts = ops_row["dims"]["ticket_service"]
    # SLA 100×0.6 + 满意度 80×0.4 = 92
    assert ts["score"] == 92.0 and ts["weight"] == 50
    # 变更维度无数据 → None；活动积分公共维度有数值
    assert ops_row["dims"]["change_compliance"]["score"] is None
    assert ops_row["dims"]["activity_points"]["score"] is not None
    # 归一：total = (92×50 + 积分分×20) / 70
    ap = ops_row["dims"]["activity_points"]["score"]
    assert ops_row["total"] == round((92 * 50 + ap * 20) / 70, 1)
    # 开发没绑岗位 → 默认方案
    dev_row = next(r for r in perf["rows"] if r["person_name"] == "绩效开发")
    assert dev_row["scheme_name"] == "默认方案（兜底）"


# ---------- 人员删除 ----------

def test_member_delete_guards_and_cascade(client, admin_headers, ctx):
    # 名下有未完成工作 → 拦截
    pid, _h = ctx["member_and_user"]("待删除员工", "pf_del", ["it_dev"])
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    t = client.post("/api/tickets", json={
        "title": "占用工单", "ticket_type": "incident", "description": "x", "priority": "P4",
        "service_item_id": item, "assignee": pid,
    }, headers=admin_headers).json()["data"]
    r = client.delete(f"/api/members/{pid}", headers=admin_headers)
    assert r.json()["error"]["code"] == "MEMBER_HAS_OPEN_WORK"

    # 完结工作后可删，且绑定账号被停用
    client.post(f"/api/tickets/{t['id']}/transition", json={"to": "processing", "fields": {}}, headers=admin_headers)
    client.post(f"/api/tickets/{t['id']}/transition",
                json={"to": "resolved", "fields": {"solution": "done"}}, headers=admin_headers)
    client.post(f"/api/tickets/{t['id']}/transition",
                json={"to": "closed", "fields": {"closure_code": "已解决"}}, headers=admin_headers)
    r = client.delete(f"/api/members/{pid}", headers=admin_headers)
    assert r.json()["success"], r.text
    assert r.json()["data"]["accounts_disabled"] == ["pf_del"]
    r = client.post("/api/auth/login", json={"username": "pf_del", "password": "pass123"})
    assert not r.json().get("success")
    # 非 admin（it_tm 无 admin_members.delete）不能删
    tm_pid2, tm_h2 = ctx["member_and_user"]("临时组长", "pf_tm2", ["it_tm"])
    r = client.delete(f"/api/members/{tm_pid2}", headers=tm_h2)
    assert r.status_code == 403


def test_member_delete_synced_blocked(client, admin_headers):
    from app.db import SessionLocal
    from app.models import OrgMember
    db = SessionLocal()
    m = OrgMember(name="飞书同步员工", external_source="feishu")
    db.add(m)
    db.commit()
    mid = m.id
    db.close()
    r = client.delete(f"/api/members/{mid}", headers=admin_headers)
    assert r.json()["error"]["code"] == "SYNCED_READONLY"


# ---------- Dashboard 分型统计 ----------

def test_dashboard_by_type(client, admin_headers):
    d = client.get("/api/dashboard", headers=admin_headers).json()["data"]
    bt = d["service"]["by_type"]
    assert {"service_request_open", "incident_open", "change_pending_approval", "change_implementing"} <= set(bt)
