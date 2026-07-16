"""M20：服务请求清单管理动作——admin（矩阵 delete/edit）可编辑、一键关闭、删除。"""
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

    _, ops_h = member_and_user("运维M20", "m20_ops", ["it_ops"])
    _, req_h = member_and_user("业务M20", "m20_req", ["requester"])
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    return {"admin": admin_headers, "ops_h": ops_h, "req_h": req_h, "item": item}


def _sr(client, ctx, title, headers=None):
    return client.post("/api/tickets", json={
        "title": title, "ticket_type": "service_request", "priority": "P4",
        "description": "d", "service_item_id": ctx["item"],
    }, headers=headers or ctx["admin"]).json()["data"]


def test_admin_edit_from_list(client, ctx):
    t = _sr(client, ctx, "编辑前标题")
    r = client.patch(f"/api/tickets/{t['id']}", json={"title": "编辑后标题", "priority": "P2"}, headers=ctx["admin"])
    assert r.json()["success"], r.text
    d = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]
    assert d["title"] == "编辑后标题" and d["priority"] == "P2"


def test_admin_quick_close_from_new(client, ctx):
    """new 状态一键关闭：沿状态机 new→resolved→closed 推进，理由入解决方案。"""
    t = _sr(client, ctx, "待关闭的测试单")
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "重复登记，作废关闭"}, headers=ctx["admin"])
    assert r.json()["success"], r.text
    assert r.json()["data"]["status"] == "closed"
    d = client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).json()["data"]
    assert d["solution"] == "重复登记，作废关闭" and "[关单说明]" in (d["remarks"] or "")
    # 终态再关 → 报错
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "再关一次试试"}, headers=ctx["admin"])
    assert r.json()["error"]["code"] == "TICKET_FINAL"
    # 理由太短 → 422
    t2 = _sr(client, ctx, "短理由校验")
    assert client.post(f"/api/tickets/{t2['id']}/close", json={"reason": "abc"}, headers=ctx["admin"]).status_code == 422


def test_requester_closes_own_sr(client, ctx):
    """M28：登记人可主动关闭自己的服务请求（理由必填、审计留痕）；他人单仍 403。"""
    t = _sr(client, ctx, "业务用户的单", headers=ctx["req_h"])
    r = client.post(f"/api/tickets/{t['id']}/close", json={"reason": "问题自行解决，撤回申请"}, headers=ctx["req_h"])
    assert r.json()["success"], r.text
    assert r.json()["data"]["status"] == "closed"
    # 他人的服务请求不可关（ops 的单，requester 连看都看不到 → 403）
    t2 = _sr(client, ctx, "他人的单")
    r = client.post(f"/api/tickets/{t2['id']}/close", json={"reason": "试图关他人单"}, headers=ctx["req_h"])
    assert r.status_code == 403


def test_delete_only_with_delete_perm(client, ctx):
    """删除按矩阵 delete（默认仅 admin）：it_ops 403；admin 软删并级联流程实例。"""
    t = _sr(client, ctx, "待删除的测试单")
    assert client.delete(f"/api/tickets/{t['id']}", headers=ctx["ops_h"]).status_code == 403

    r = client.delete(f"/api/tickets/{t['id']}", headers=ctx["admin"])
    assert r.json()["success"], r.text
    assert r.json()["data"]["process_instances"] >= 1  # 流程实例级联软删
    assert client.get(f"/api/tickets/{t['id']}", headers=ctx["admin"]).status_code == 404
    rows = client.get("/api/tickets?page_size=100", headers=ctx["admin"]).json()["data"]
    assert all(x["id"] != t["id"] for x in rows)
