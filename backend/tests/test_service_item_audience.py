"""服务项服务对象范围：全体员工或组织架构中的部门/员工。"""


def test_service_item_audience_scope_is_structured(client, admin_headers):
    department = client.post(
        "/api/admin/departments",
        json={"code": "AUDIENCE_DEPT", "name": "服务对象测试部门", "dept_type": "it"},
        headers=admin_headers,
    ).json()["data"]
    member = client.post(
        "/api/members",
        json={"name": "服务对象测试员工", "department_id": department["id"]},
        headers=admin_headers,
    ).json()["data"]
    catalog = client.post(
        "/api/catalogs", json={"name": "服务对象测试目录"}, headers=admin_headers
    ).json()["data"]

    item = client.post(
        "/api/service-items",
        json={
            "name": "自定义服务对象服务项",
            "catalog_id": catalog["id"],
            "target_audience_mode": "custom",
            "target_audience_refs": [
                {"type": "department", "id": department["id"]},
                {"type": "member", "id": member["id"]},
            ],
        },
        headers=admin_headers,
    )
    assert item.status_code == 200, item.text
    row = item.json()["data"]
    assert row["target_audience_mode"] == "custom"
    assert row["target_audience"] == "部门：服务对象测试部门；员工：服务对象测试员工"
    assert {tuple(ref.values()) for ref in row["target_audience_refs"]} == {
        ("department", department["id"]),
        ("member", member["id"]),
    }

    all_staff = client.patch(
        f"/api/service-items/{row['id']}",
        json={"target_audience_mode": "all", "target_audience_refs": []},
        headers=admin_headers,
    )
    assert all_staff.status_code == 200, all_staff.text
    assert all_staff.json()["data"]["target_audience"] == "全体员工"
    assert all_staff.json()["data"]["target_audience_refs"] == []

    invalid = client.post(
        "/api/service-items",
        json={
            "name": "空范围服务项",
            "catalog_id": catalog["id"],
            "target_audience_mode": "custom",
            "target_audience_refs": [],
        },
        headers=admin_headers,
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "AUDIENCE_REQUIRED"
