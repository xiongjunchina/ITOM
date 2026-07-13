"""M7.2 后端 i18n：X-Lang 头本地化 status_name 与错误消息（默认 zh）。"""


def test_status_name_localized_by_header(client, admin_headers):
    # 示例工单 TK-DEMO-001 已解决 / 变更 TK-DEMO-002 已批准（SEED_EXAMPLES=1）
    zh = client.get("/api/tickets", headers=admin_headers).json()["data"]
    assert any(t["status_name"] == "已解决" for t in zh)

    en_headers = {**admin_headers, "X-Lang": "en"}
    en = client.get("/api/tickets", headers=en_headers).json()["data"]
    names = {t["ticket_code"]: t["status_name"] for t in en}
    assert names.get("TK-DEMO-001") == "Resolved"
    assert names.get("TK-DEMO-002") == "Approved"


def test_error_message_localized(client, admin_headers):
    en_headers = {**admin_headers, "X-Lang": "en"}
    # 不存在的工单 → 404
    r = client.get("/api/tickets/NOPE", headers=en_headers)
    assert r.json()["error"]["message"] == "Ticket not found"
    # 默认（无头）中文
    r = client.get("/api/tickets/NOPE", headers=admin_headers)
    assert r.json()["error"]["message"] == "工单不存在"


def test_login_error_localized(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "bad"},
                    headers={"X-Lang": "en"})
    assert r.json()["error"]["message"] == "Wrong username or password"
    r = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
    assert r.json()["error"]["message"] == "用户名或密码错误"


def test_project_requirement_status_localized(client, admin_headers):
    en_headers = {**admin_headers, "X-Lang": "en"}
    projects = client.get("/api/projects", headers=en_headers).json()["data"]
    if projects:  # 示例项目 PJ-DEMO-001
        assert projects[0]["status_name"] in {"Planning", "In progress", "Completed", "Closed", "Paused", "Cancelled"}
    reqs = client.get("/api/requirements", headers=en_headers).json()["data"]
    if reqs:
        assert reqs[0]["status_name"] in {"Registered", "Analyzing", "Implementing", "Closed", "On hold", "Cancelled"}
