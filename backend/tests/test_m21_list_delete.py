"""M21：各清单实体删除（软删+级联+引用拦截）——delete 权限默认仅 admin。"""
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

    _, ops_h = member_and_user("运维M21", "m21_ops", ["it_ops"])
    return {"admin": admin_headers, "ops_h": ops_h}


def test_problem_delete_unlinks_ticket(client, ctx):
    item = client.get("/api/service-items", headers=ctx["admin"]).json()["data"][0]["id"]
    t = client.post("/api/tickets", json={"title": "升级源单", "ticket_type": "incident", "priority": "P3",
                                          "description": "d", "service_item_id": item}, headers=ctx["admin"]).json()["data"]
    client.post(f"/api/tickets/{t['id']}/transition", json={"to": "processing", "fields": {}}, headers=ctx["admin"])
    p = client.post(f"/api/tickets/{t['id']}/escalate-problem", headers=ctx["admin"]).json()["data"]
    # it_ops 无 problems.delete → 403
    assert client.delete(f"/api/problems/{p['problem_id']}", headers=ctx["ops_h"]).status_code == 403
    r = client.delete(f"/api/problems/{p['problem_id']}", headers=ctx["admin"])
    assert r.json()["success"] and r.json()["data"]["tickets_unlinked"] == 1
    # 解除关联后可再次升级（不再报 ALREADY_ESCALATED）
    again = client.post(f"/api/tickets/{t['id']}/escalate-problem", headers=ctx["admin"])
    assert again.json()["success"], again.text
    client.delete(f"/api/problems/{again.json()['data']['problem_id']}", headers=ctx["admin"])


def test_knowledge_delete(client, ctx):
    a = client.post("/api/knowledge", json={"title": "M21测试文章", "content": "正文", "category": "faq"},
                    headers=ctx["admin"]).json()["data"]
    assert client.delete(f"/api/knowledge/{a['id']}", headers=ctx["ops_h"]).status_code == 403
    assert client.delete(f"/api/knowledge/{a['id']}", headers=ctx["admin"]).json()["success"]
    assert client.get(f"/api/knowledge/{a['id']}", headers=ctx["admin"]).status_code == 404


def test_requirement_delete_cascades(client, ctx):
    domain = client.get("/api/admin/business-domains", headers=ctx["admin"]).json()["data"][0]["id"]
    r = client.post("/api/requirements", json={"title": "M21删除级联需求", "req_type": "功能",
                                               "business_domain_id": domain, "description": "d"},
                    headers=ctx["admin"]).json()["data"]
    resp = client.delete(f"/api/requirements/{r['id']}", headers=ctx["admin"])
    assert resp.json()["success"] and resp.json()["data"]["process_instances"] >= 1
    assert client.get(f"/api/requirements/{r['id']}", headers=ctx["admin"]).status_code == 404


def test_vendor_blocked_then_contract_then_vendor(client, ctx):
    v = client.post("/api/vendors", json={"name": "M21供应商"}, headers=ctx["admin"]).json()["data"]
    c = client.post("/api/contracts", json={"name": "M21合同", "vendor_id": v["id"],
                                            "start_date": "2026-01-01", "end_date": "2026-12-31"},
                    headers=ctx["admin"]).json()["data"]
    r = client.delete(f"/api/vendors/{v['id']}", headers=ctx["admin"])
    assert r.json()["error"]["code"] == "VENDOR_IN_USE"  # 有合同先拒
    assert client.delete(f"/api/contracts/{c['id']}", headers=ctx["ops_h"]).status_code == 403
    assert client.delete(f"/api/contracts/{c['id']}", headers=ctx["admin"]).json()["success"]
    assert client.delete(f"/api/vendors/{v['id']}", headers=ctx["admin"]).json()["success"]


def test_ci_delete_cascades_relations(client, ctx):
    owner = client.post("/api/members", json={"name": "CI管理员M21"}, headers=ctx["admin"]).json()["data"]["id"]
    a = client.post("/api/cis", json={"name": "应用A-M21", "category": "application", "owner": owner, "product_manager_id": owner}, headers=ctx["admin"]).json()["data"]
    b = client.post("/api/cis", json={"name": "库B-M21", "category": "database", "owner": owner}, headers=ctx["admin"]).json()["data"]
    client.post("/api/ci-relationships", json={"source_ci_id": a["id"], "target_ci_id": b["id"], "relation_type": "依赖"},
                headers=ctx["admin"])
    r = client.delete(f"/api/cis/{a['id']}", headers=ctx["admin"])
    assert r.json()["success"] and r.json()["data"]["relations"] == 1
    rows = client.get("/api/cis?page_size=200", headers=ctx["admin"]).json()["data"]
    assert all(x["id"] != a["id"] for x in rows)


def test_catalog_and_item_guards(client, ctx):
    cat = client.post("/api/catalogs", json={"name": "M21目录", "description": "d"}, headers=ctx["admin"]).json()["data"]
    item = client.post("/api/service-items", json={"name": "M21服务项", "catalog_id": cat["id"],
                                                   "service_type": "支持类", "status": "上架"},
                       headers=ctx["admin"]).json()["data"]
    # 目录下有服务项 → 拒
    assert client.delete(f"/api/catalogs/{cat['id']}", headers=ctx["admin"]).json()["error"]["code"] == "CATALOG_IN_USE"
    # 服务项被工单引用 → 拒
    t = client.post("/api/tickets", json={"title": "引用M21服务项", "ticket_type": "service_request", "priority": "P4",
                                          "description": "d", "service_item_id": item["id"]}, headers=ctx["admin"]).json()["data"]
    assert client.delete(f"/api/service-items/{item['id']}", headers=ctx["admin"]).json()["error"]["code"] == "ITEM_IN_USE"
    # 删工单 → 服务项可删 → 目录可删
    client.delete(f"/api/tickets/{t['id']}", headers=ctx["admin"])
    assert client.delete(f"/api/service-items/{item['id']}", headers=ctx["admin"]).json()["success"]
    assert client.delete(f"/api/catalogs/{cat['id']}", headers=ctx["admin"]).json()["success"]


def test_catalog_delete_cascades_service_items_without_deleting_history(client, ctx):
    cat = client.post("/api/catalogs", json={"name": "M21级联目录"}, headers=ctx["admin"]).json()["data"]
    item = client.post(
        "/api/service-items",
        json={"name": "M21级联服务项", "catalog_id": cat["id"], "service_type": "支持类"},
        headers=ctx["admin"],
    ).json()["data"]
    ticket = client.post(
        "/api/tickets",
        json={
            "title": "M21历史工单保留",
            "ticket_type": "service_request",
            "priority": "P4",
            "description": "目录删除后仍需保留历史引用",
            "service_item_id": item["id"],
        },
        headers=ctx["admin"],
    ).json()["data"]

    response = client.delete(f"/api/catalogs/{cat['id']}?cascade=true", headers=ctx["admin"])
    assert response.json()["success"]
    assert response.json()["data"]["items_deleted"] == 1
    assert all(row["id"] != cat["id"] for row in client.get("/api/catalogs", headers=ctx["admin"]).json()["data"])
    assert all(row["id"] != item["id"] for row in client.get("/api/service-items", headers=ctx["admin"]).json()["data"])
    assert client.get(f"/api/tickets/{ticket['id']}", headers=ctx["admin"]).status_code == 200


def test_service_item_search_status_filter_and_sort(client, ctx):
    cat = client.post("/api/catalogs", json={"name": "M21筛选目录"}, headers=ctx["admin"]).json()["data"]
    first = client.post(
        "/api/service-items",
        json={"name": "网络访问申请", "catalog_id": cat["id"], "service_type": "权限", "status": "上架"},
        headers=ctx["admin"],
    ).json()["data"]
    second = client.post(
        "/api/service-items",
        json={"name": "数据库账号回收", "catalog_id": cat["id"], "service_type": "权限"},
        headers=ctx["admin"],
    ).json()["data"]
    client.patch(f"/api/service-items/{second['id']}", json={"status": "下架"}, headers=ctx["admin"])

    catalog_row = next(
        row for row in client.get("/api/catalogs", headers=ctx["admin"]).json()["data"] if row["id"] == cat["id"]
    )
    assert catalog_row["published_item_count"] == 1
    assert catalog_row["unpublished_item_count"] == 1

    searched = client.get("/api/service-items?catalog_id=%s&q=数据库" % cat["id"], headers=ctx["admin"]).json()["data"]
    assert [row["id"] for row in searched] == [second["id"]]

    unpublished = client.get("/api/service-items?catalog_id=%s&status=下架" % cat["id"], headers=ctx["admin"]).json()["data"]
    assert [row["id"] for row in unpublished] == [second["id"]]

    descending = client.get(
        "/api/service-items?catalog_id=%s&sort_by=name&sort_dir=descend" % cat["id"],
        headers=ctx["admin"],
    ).json()["data"]
    assert [row["name"] for row in descending] == sorted([first["name"], second["name"]], reverse=True)


def test_portfolio_delete_requires_projects_to_be_migrated(client, ctx):
    pf = client.post("/api/portfolios", json={"name": "M21组合"}, headers=ctx["admin"]).json()["data"]
    m = client.post("/api/members", json={"name": "PM-M21"}, headers=ctx["admin"]).json()["data"]
    p = client.post("/api/projects", json={"name": "M21组合内项目", "pm": m["id"],
                                           "planned_start": "2026-08-01", "planned_end": "2026-09-30",
                                           "portfolio_id": pf["id"]}, headers=ctx["admin"]).json()["data"]
    r = client.delete(f"/api/portfolios/{pf['id']}", headers=ctx["admin"])
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "PORTFOLIO_NOT_EMPTY"
    d = client.get(f"/api/projects/{p['id']}", headers=ctx["admin"]).json()["data"]
    assert d["portfolio_id"] == pf["id"]
