def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_login_wrong_password(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "LOGIN_FAILED"


def test_login_and_me(client, admin_headers):
    resp = client.get("/api/auth/me", headers=admin_headers)
    body = resp.json()
    assert body["success"] and body["data"]["username"] == "admin"
    assert "admin" in body["data"]["roles"]


def test_unauthorized_without_token(client):
    assert client.get("/api/members").status_code == 401


def test_position_and_member_crud(client, admin_headers):
    resp = client.post(
        "/api/positions", json={"name": "运维工程师", "duties": "系统运维", "headcount": 2}, headers=admin_headers
    )
    pos_id = resp.json()["data"]["id"]

    resp = client.post(
        "/api/members",
        json={"name": "张三", "dept": "IT部", "position_id": pos_id, "skills": ["linux", "k8s"]},
        headers=admin_headers,
    )
    assert resp.json()["data"]["position_name"] == "运维工程师"
    member_id = resp.json()["data"]["id"]

    # 岗位缺口自动计算：编制 2 - 在岗 1 = 1
    resp = client.get("/api/positions", headers=admin_headers)
    row = next(p for p in resp.json()["data"] if p["id"] == pos_id)
    assert row["onboard"] == 1 and row["gap"] == 1

    resp = client.patch(f"/api/members/{member_id}", json={"team": "平台组"}, headers=admin_headers)
    assert resp.json()["data"]["team"] == "平台组"


def test_user_crud_and_rbac(client, admin_headers):
    # admin 建一个 requester 用户
    resp = client.post(
        "/api/admin/users",
        json={"username": "biz01", "password": "pass123", "roles": ["requester"]},
        headers=admin_headers,
    )
    assert resp.json()["success"], resp.text

    # requester 登录后无权写人员主数据、无权访问 admin 接口
    resp = client.post("/api/auth/login", json={"username": "biz01", "password": "pass123"})
    biz_headers = {"Authorization": f"Bearer {resp.json()['data']['token']}"}
    assert client.post("/api/members", json={"name": "李四"}, headers=biz_headers).status_code == 403
    assert client.get("/api/admin/users", headers=biz_headers).status_code == 403
    # 但可以读 dashboard
    assert client.get("/api/dashboard", headers=biz_headers).status_code == 200


def test_duplicate_username_rejected(client, admin_headers):
    resp = client.post(
        "/api/admin/users",
        json={"username": "biz01", "password": "pass123", "roles": ["requester"]},
        headers=admin_headers,
    )
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "USERNAME_TAKEN"


def test_invalid_role_rejected(client, admin_headers):
    resp = client.post(
        "/api/admin/users",
        json={"username": "x01", "password": "pass123", "roles": ["superman"]},
        headers=admin_headers,
    )
    assert resp.json()["error"]["code"] == "INVALID_ROLE"


def test_master_data_seeded_and_audit(client, admin_headers):
    resp = client.get("/api/admin/master-data?category=closure_code", headers=admin_headers)
    assert resp.json()["total"] == 5

    resp = client.get("/api/admin/audit-logs", headers=admin_headers)
    body = resp.json()
    assert body["total"] > 0  # 前面的 CRUD 已产生审计
    assert body["data"][0]["actor_name"]
