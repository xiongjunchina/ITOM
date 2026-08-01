"""业务用户服务项可见范围与工单创建权限。"""


def _user_headers(client, admin_headers, member_id: str, username: str, roles: list[str] | None = None):
    client.post(
        "/api/admin/users",
        json={"username": username, "password": "pass123", "roles": roles or ["requester"], "person_id": member_id},
        headers=admin_headers,
    )
    token = client.post(
        "/api/auth/login", json={"username": username, "password": "pass123"}
    ).json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


def test_requester_service_item_audience_is_enforced(client, admin_headers):
    parent = client.post(
        "/api/admin/departments",
        json={"code": "AUDIENCE_PARENT", "name": "服务对象范围父部门", "dept_type": "business"},
        headers=admin_headers,
    ).json()["data"]
    child = client.post(
        "/api/admin/departments",
        json={
            "code": "AUDIENCE_CHILD",
            "name": "服务对象范围子部门",
            "parent_id": parent["id"],
            "dept_type": "business",
        },
        headers=admin_headers,
    ).json()["data"]
    in_scope = client.post(
        "/api/members",
        json={"name": "服务对象范围内用户", "department_id": child["id"]},
        headers=admin_headers,
    ).json()["data"]
    out_scope = client.post(
        "/api/members",
        json={"name": "服务对象范围外用户"},
        headers=admin_headers,
    ).json()["data"]
    bdo_out_scope = client.post(
        "/api/members",
        json={"name": "范围外业务数字化经理"},
        headers=admin_headers,
    ).json()["data"]
    in_headers = _user_headers(client, admin_headers, in_scope["id"], "audience_in_scope")
    out_headers = _user_headers(client, admin_headers, out_scope["id"], "audience_out_scope")
    bdo_headers = _user_headers(client, admin_headers, bdo_out_scope["id"], "audience_bdo_out_scope", ["bdo"])

    catalog = client.post(
        "/api/catalogs", json={"name": "范围控制测试目录"}, headers=admin_headers
    ).json()["data"]
    item = client.post(
        "/api/service-items",
        json={
            "name": "父部门范围服务项",
            "catalog_id": catalog["id"],
            "target_audience_mode": "custom",
            "target_audience_refs": [{"type": "department", "id": parent["id"]}],
        },
        headers=admin_headers,
    ).json()["data"]

    visible = client.get("/api/service-items", headers=in_headers)
    assert visible.status_code == 200, visible.text
    assert item["id"] in {row["id"] for row in visible.json()["data"]}

    hidden = client.get("/api/service-items", headers=out_headers)
    assert hidden.status_code == 200, hidden.text
    assert item["id"] not in {row["id"] for row in hidden.json()["data"]}
    # BDO 是业务用户子集，同样受服务对象范围控制，不能被当作 IT 内部人员放行。
    bdo_hidden = client.get("/api/service-items", headers=bdo_headers)
    assert bdo_hidden.status_code == 200, bdo_hidden.text
    assert item["id"] not in {row["id"] for row in bdo_hidden.json()["data"]}

    ticket_payload = {
        "title": "范围内用户申请服务",
        "ticket_type": "service_request",
        "priority": "P3",
        "description": "测试服务对象范围",
        "service_item_id": item["id"],
    }
    allowed = client.post("/api/tickets", json=ticket_payload, headers=in_headers)
    assert allowed.status_code == 200, allowed.text

    denied = client.post(
        "/api/tickets",
        json={**ticket_payload, "title": "范围外用户申请服务"},
        headers=out_headers,
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "SERVICE_ITEM_FORBIDDEN"

    bdo_denied = client.post(
        "/api/tickets",
        json={**ticket_payload, "title": "BDO 范围外服务申请"},
        headers=bdo_headers,
    )
    assert bdo_denied.status_code == 403
    assert bdo_denied.json()["error"]["code"] == "SERVICE_ITEM_FORBIDDEN"
