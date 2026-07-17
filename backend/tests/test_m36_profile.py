"""M36.2 个人中心：资料载荷 / 偏好（头像、个人说明）/ 自助改密（首设免验规则）。"""


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    return r


def test_profile_payload_and_preferences(client, admin_headers):
    res = client.get("/api/auth/me/profile", headers=admin_headers).json()
    assert res["success"]
    acc = res["data"]["account"]
    assert acc["username"] == "admin"
    assert acc["password_set"] is True  # 本地账号：口令视为已人为设定
    # 偏好：个人说明 + 头像（data URL）
    r = client.patch("/api/auth/me/preferences",
                     json={"bio": "系统管理员", "avatar": "data:image/jpeg;base64,/9j/4AAQ"},
                     headers=admin_headers)
    assert r.json()["success"]
    res = client.get("/api/auth/me/profile", headers=admin_headers).json()["data"]
    assert res["preferences"]["bio"] == "系统管理员"
    assert res["preferences"]["avatar"].startswith("data:image/jpeg")
    # 非法头像被拒
    r = client.patch("/api/auth/me/preferences", json={"avatar": "http://evil/x.png"}, headers=admin_headers)
    assert r.json()["error"]["code"] == "BAD_AVATAR"
    # 移除头像
    r = client.patch("/api/auth/me/preferences", json={"avatar": None}, headers=admin_headers)
    assert r.json()["success"]
    res = client.get("/api/auth/me/profile", headers=admin_headers).json()["data"]
    assert res["preferences"]["avatar"] is None


def test_local_user_change_password_requires_current(client, admin_headers):
    r = client.post("/api/admin/users", json={"username": "pwd_local", "password": "init1234", "roles": ["requester"]},
                    headers=admin_headers)
    assert r.json()["success"], r.text
    token = _login(client, "pwd_local", "init1234").json()["data"]["token"]
    h = {"Authorization": f"Bearer {token}"}
    # 缺当前密码 / 当前密码错误 → 拒绝
    r = client.post("/api/auth/me/password", json={"new_password": "abcd1234"}, headers=h)
    assert r.json()["error"]["code"] == "PASSWORD_WRONG"
    r = client.post("/api/auth/me/password", json={"current_password": "wrong999", "new_password": "abcd1234"}, headers=h)
    assert r.json()["error"]["code"] == "PASSWORD_WRONG"
    # 弱密码（纯数字）→ 拒绝
    r = client.post("/api/auth/me/password", json={"current_password": "init1234", "new_password": "12345678"}, headers=h)
    assert r.json()["error"]["code"] == "WEAK_PASSWORD"
    # 正确修改后新密码可登录、旧密码失效
    r = client.post("/api/auth/me/password", json={"current_password": "init1234", "new_password": "abcd1234"}, headers=h)
    assert r.json()["success"], r.text
    assert _login(client, "pwd_local", "abcd1234").status_code == 200
    assert _login(client, "pwd_local", "init1234").status_code == 401


def test_feishu_user_first_set_password_then_requires_current(client, admin_headers):
    # 模拟扫码 → 管理员开通（随机口令，password_set=False）
    r = client.post("/api/auth/feishu/scan", json={"external_id": "ou_pwd_test", "display_name": "密码测试员"})
    assert r.json()["success"], r.text
    reqs = client.get("/api/auth/onboarding/requests?status=pending", headers=admin_headers).json()["data"]
    req = next(x for x in reqs if x["external_id"] == "ou_pwd_test")
    r = client.post(f"/api/auth/onboarding/requests/{req['id']}/approve",
                    json={"username": "pwd_feishu", "roles": ["requester"], "language": "zh"}, headers=admin_headers)
    assert r.json()["success"], r.text
    # 再扫码直登拿 token
    r = client.post("/api/auth/feishu/scan", json={"external_id": "ou_pwd_test", "display_name": "密码测试员"})
    data = r.json()["data"]
    assert data["status"] == "active"
    h = {"Authorization": f"Bearer {data['token']}"}
    assert client.get("/api/auth/me/profile", headers=h).json()["data"]["account"]["password_set"] is False
    # 首次自设：免验当前密码
    r = client.post("/api/auth/me/password", json={"new_password": "feishu12"}, headers=h)
    assert r.json()["success"], r.text
    assert _login(client, "pwd_feishu", "feishu12").status_code == 200  # 账号密码登录已启用
    # 已自设过：再改必须验当前密码
    r = client.post("/api/auth/me/password", json={"new_password": "feishu34"}, headers=h)
    assert r.json()["error"]["code"] == "PASSWORD_WRONG"
    r = client.post("/api/auth/me/password", json={"current_password": "feishu12", "new_password": "feishu34"}, headers=h)
    assert r.json()["success"], r.text
    assert _login(client, "pwd_feishu", "feishu34").status_code == 200
