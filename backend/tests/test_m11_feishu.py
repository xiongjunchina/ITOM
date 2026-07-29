"""M11：飞书基础集成——配置、组织同步与 OAuth 登录；服务台能力已移除。"""
import pytest

from app.services.feishu import FeishuClient


@pytest.fixture(scope="module")
def cfg_ready(client, admin_headers):
    """写入并启用飞书配置（IT 根部门 od-root）。"""
    response = client.put("/api/admin/feishu-config", json={
        "app_id": "cli_test_app", "app_secret": "s3cret-value", "sync_scope": "od-root", "enabled": True,
    }, headers=admin_headers)
    assert response.json()["success"], response.text
    return response.json()["data"]


def test_config_crud_and_mask(client, admin_headers):
    cfg = client.get("/api/admin/feishu-config", headers=admin_headers).json()["data"]
    assert cfg["enabled"] is False and cfg["has_secret"] is False
    assert not any("helpdesk" in key for key in cfg)

    response = client.put("/api/admin/feishu-config", json={"enabled": True}, headers=admin_headers)
    assert response.json()["error"]["code"] == "FEISHU_CONFIG_INCOMPLETE"

    client.put("/api/admin/feishu-config", json={
        "app_id": "cli_x", "app_secret": "super-secret-123",
    }, headers=admin_headers)
    cfg = client.get("/api/admin/feishu-config", headers=admin_headers).json()["data"]
    assert cfg["has_secret"] and "super-secret-123" not in str(cfg)
    assert cfg["app_secret_masked"].startswith("supe")

    client.put("/api/admin/feishu-config", json={"sync_scope": "od-root"}, headers=admin_headers)
    cfg = client.get("/api/admin/feishu-config", headers=admin_headers).json()["data"]
    assert cfg["has_secret"] is True and cfg["sync_scope"] == "od-root"


FAKE_DEPTS = [
    {"open_department_id": "od-dev", "name": "开发组", "parent_department_id": "od-root", "order": 1},
    {"open_department_id": "od-ops", "name": "运维组", "parent_department_id": "od-root", "order": 2},
]
FAKE_USERS = {
    "od-root": [{"open_id": "ou_boss", "name": "IT总监", "en_name": "Boss", "gender": 1,
                 "employee_type": 1, "mobile": "13800000001", "email": "boss@x.com",
                 "status": {"is_resigned": False}}],
    "od-dev": [{"open_id": "ou_dev1", "name": "张开发", "gender": 2, "employee_type": 1,
                "leader_user_id": "ou_boss", "mobile": "13800000002",
                "status": {"is_resigned": False}}],
    "od-ops": [{"open_id": "ou_ops1", "name": "李运维", "employee_type": 3,
                "leader_user_id": "ou_boss", "status": {"is_resigned": False}}],
}


@pytest.fixture()
def mock_feishu(monkeypatch):
    monkeypatch.setattr(FeishuClient, "tenant_access_token", lambda self: "t-xxx")
    monkeypatch.setattr(FeishuClient, "get_department", lambda self, token, dep: {"name": "信息技术部", "order": 0})
    monkeypatch.setattr(FeishuClient, "list_child_departments", lambda self, token, root: list(FAKE_DEPTS))
    monkeypatch.setattr(FeishuClient, "list_department_users", lambda self, token, dep: list(FAKE_USERS.get(dep, [])))


def test_org_sync_it_subtree(client, admin_headers, cfg_ready, mock_feishu):
    stats = client.post("/api/admin/org-sync", json={"source": "feishu", "sync": True}, headers=admin_headers).json()["data"]
    assert stats["dept_created"] == 3 and stats["member_created"] == 3

    org = client.get("/api/admin/org-tree", headers=admin_headers).json()["data"]
    assert "feishu" in org["sync_sources"]
    by_name = {department["name"]: department for department in org["departments"]}
    assert {"信息技术部", "开发组", "运维组"} <= set(by_name)
    assert by_name["开发组"]["parent_id"] == by_name["信息技术部"]["id"]
    assert "张开发" in {member["name"] for member in by_name["开发组"]["members"]}

    cfg = client.get("/api/admin/feishu-config", headers=admin_headers).json()["data"]
    assert cfg["last_sync_at"] and cfg["last_sync_stats"]["member_created"] == 3


def test_scan_simulator_disabled_when_enabled(client, admin_headers, cfg_ready):
    response = client.post("/api/auth/feishu/scan", json={"external_id": "ou_fake", "display_name": "伪造者"})
    assert response.status_code == 403 and response.json()["error"]["code"] == "SIMULATOR_DISABLED"


def test_oauth_login_full_chain(client, admin_headers, cfg_ready, mock_feishu, monkeypatch):
    url = client.get("/api/auth/feishu/authorize-url", params={
        "redirect_uri": "http://localhost:8180/login/feishu-callback",
    }).json()["data"]["url"]
    assert "authen/v1/authorize" in url and "cli_test_app" in url
    from urllib.parse import parse_qs, urlparse

    state = parse_qs(urlparse(url).query)["state"][0]
    monkeypatch.setattr(FeishuClient, "oauth_user_info", lambda self, code: {
        "open_id": "ou_dev1", "name": "张开发", "mobile": "13800000002",
        "avatar_url": "http://a/x.png", "email": "zhang.dev@example.com",
    })
    data = client.post("/api/auth/feishu/callback", json={"code": "code-abc", "state": state}).json()["data"]
    assert data["status"] == "pending" and data["pending_token"]
    pending_token = data["pending_token"]

    bad = client.post("/api/auth/feishu/callback", json={"code": "code-abc", "state": "forged"})
    assert bad.status_code == 401

    requests = client.get("/api/auth/onboarding/requests", headers=admin_headers).json()["data"]
    mine = next(item for item in requests if item["external_id"] == "ou_dev1")
    assert mine["matched_person_name"] == "张开发" and mine["matched_person_id"]

    status = client.get("/api/auth/onboarding/status", headers={
        "Authorization": f"Bearer {pending_token}",
    }).json()["data"]
    assert status["status"] == "pending"

    approved = client.post(f"/api/auth/onboarding/requests/{mine['id']}/approve", json={
        "username": "zhang.dev", "roles": ["it_dev"], "language": "en", "person_id": mine["matched_person_id"],
    }, headers=admin_headers).json()["data"]
    assert approved["username"] == "zhang.dev"

    status = client.get("/api/auth/onboarding/status", headers={
        "Authorization": f"Bearer {pending_token}",
    }).json()["data"]
    assert status["status"] == "approved" and status["token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {status['token']}"}).json()["data"]
    assert me["user"]["preferences"]["language"] == "en" if "user" in me else me["preferences"]["language"] == "en"

    data_again = client.post("/api/auth/feishu/callback", json={"code": "code-2", "state": state}).json()["data"]
    assert data_again["status"] == "active" and data_again["token"]


def test_config_admin_only(client, admin_headers):
    client.post("/api/admin/users", json={
        "username": "plain_m11", "password": "pass123", "roles": ["it_dev"],
    }, headers=admin_headers)
    token = client.post("/api/auth/login", json={"username": "plain_m11", "password": "pass123"}).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/admin/feishu-config", headers=headers).status_code == 403
    assert client.put("/api/admin/feishu-config", json={"app_id": "x"}, headers=headers).status_code == 403


def test_removed_helpdesk_routes_are_not_mounted(client, admin_headers):
    assert client.get("/api/integrations/feishu/helpdesk/intakes", headers=admin_headers).status_code == 404
    assert client.post("/api/admin/feishu-config/test-helpdesk", headers=admin_headers).status_code == 404
