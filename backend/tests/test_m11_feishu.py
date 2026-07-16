"""M11：飞书集成——配置端点 / IT 子树组织同步(mock HTTP) / OAuth 扫码登录全链路 / 模拟入口守卫。"""
import pytest

from app.services.feishu import FeishuClient


@pytest.fixture(scope="module")
def cfg_ready(client, admin_headers):
    """写入并启用飞书配置（IT 根部门 od-root）。"""
    r = client.put("/api/admin/feishu-config", json={
        "app_id": "cli_test_app", "app_secret": "s3cret-value", "sync_scope": "od-root", "enabled": True,
    }, headers=admin_headers)
    assert r.json()["success"], r.text
    return r.json()["data"]


def test_config_crud_and_mask(client, admin_headers):
    # 默认空配置
    cfg = client.get("/api/admin/feishu-config", headers=admin_headers).json()["data"]
    assert cfg["enabled"] is False and cfg["has_secret"] is False

    # 未配 secret 前不可启用
    r = client.put("/api/admin/feishu-config", json={"enabled": True}, headers=admin_headers)
    assert r.json()["error"]["code"] == "FEISHU_CONFIG_INCOMPLETE"

    # 写入后 GET 掩码，不回传明文
    client.put("/api/admin/feishu-config",
               json={"app_id": "cli_x", "app_secret": "super-secret-123"}, headers=admin_headers)
    cfg = client.get("/api/admin/feishu-config", headers=admin_headers).json()["data"]
    assert cfg["has_secret"] and "super-secret-123" not in str(cfg)
    assert cfg["app_secret_masked"].startswith("supe")

    # secret 留空更新其它字段 → 不清空
    client.put("/api/admin/feishu-config", json={"sync_scope": "od-root"}, headers=admin_headers)
    cfg = client.get("/api/admin/feishu-config", headers=admin_headers).json()["data"]
    assert cfg["has_secret"] is True and cfg["sync_scope"] == "od-root"


FAKE_DEPTS = [  # od-root 的子孙
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
    monkeypatch.setattr(FeishuClient, "get_department",
                        lambda self, token, dep: {"name": "信息技术部", "order": 0})
    monkeypatch.setattr(FeishuClient, "list_child_departments",
                        lambda self, token, root: list(FAKE_DEPTS))
    monkeypatch.setattr(FeishuClient, "list_department_users",
                        lambda self, token, dep: list(FAKE_USERS.get(dep, [])))


def test_org_sync_it_subtree(client, admin_headers, cfg_ready, mock_feishu):
    stats = client.post("/api/admin/org-sync", json={"source": "feishu"}, headers=admin_headers).json()["data"]
    assert stats["dept_created"] == 3 and stats["member_created"] == 3

    org = client.get("/api/admin/org-tree", headers=admin_headers).json()["data"]
    assert "feishu" in org["sync_sources"]
    by_name = {d["name"]: d for d in org["departments"]}
    assert {"信息技术部", "开发组", "运维组"} <= set(by_name)
    assert by_name["开发组"]["parent_id"] == by_name["信息技术部"]["id"]
    dev_members = {m["name"] for m in by_name["开发组"]["members"]}
    assert "张开发" in dev_members

    # 同步统计回写配置
    cfg = client.get("/api/admin/feishu-config", headers=admin_headers).json()["data"]
    assert cfg["last_sync_at"] and cfg["last_sync_stats"]["member_created"] == 3


def test_scan_simulator_disabled_when_enabled(client, admin_headers, cfg_ready):
    r = client.post("/api/auth/feishu/scan", json={"external_id": "ou_fake", "display_name": "伪造者"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "SIMULATOR_DISABLED"


def test_oauth_login_full_chain(client, admin_headers, cfg_ready, mock_feishu, monkeypatch):
    # ① 登录页取授权地址
    url = client.get("/api/auth/feishu/authorize-url",
                     params={"redirect_uri": "http://localhost:8180/login/feishu-callback"}).json()["data"]["url"]
    assert "authen/v1/authorize" in url and "cli_test_app" in url
    from urllib.parse import parse_qs, urlparse

    state = parse_qs(urlparse(url).query)["state"][0]

    # ② 扫码回调：飞书身份是已同步的张开发（ou_dev1）→ 落开通请求，进过渡页
    monkeypatch.setattr(FeishuClient, "oauth_user_info", lambda self, code: {
        "open_id": "ou_dev1", "name": "张开发", "mobile": "13800000002", "avatar_url": "http://a/x.png",
    })
    data = client.post("/api/auth/feishu/callback", json={"code": "code-abc", "state": state}).json()["data"]
    assert data["status"] == "pending" and data["pending_token"]
    pending_token = data["pending_token"]

    # 坏 state 拒绝
    bad = client.post("/api/auth/feishu/callback", json={"code": "code-abc", "state": "forged"})
    assert bad.status_code == 401

    # ③ 管理员在审批列表看到请求，且自动匹配到同步人员
    reqs = client.get("/api/auth/onboarding/requests", headers=admin_headers).json()["data"]
    mine = next(x for x in reqs if x["external_id"] == "ou_dev1")
    assert mine["matched_person_name"] == "张开发" and mine["matched_person_id"]

    # ④ 过渡页轮询：pending
    st = client.get("/api/auth/onboarding/status",
                    headers={"Authorization": f"Bearer {pending_token}"}).json()["data"]
    assert st["status"] == "pending"

    # ⑤ 管理员开通：用户名/角色/默认语言 en + 关联人员
    ok = client.post(f"/api/auth/onboarding/requests/{mine['id']}/approve", json={
        "username": "zhang.dev", "roles": ["it_dev"], "language": "en", "person_id": mine["matched_person_id"],
    }, headers=admin_headers).json()["data"]
    assert ok["username"] == "zhang.dev"

    # ⑥ 过渡页拿到正式令牌进系统，默认语言 en
    st = client.get("/api/auth/onboarding/status",
                    headers={"Authorization": f"Bearer {pending_token}"}).json()["data"]
    assert st["status"] == "approved" and st["token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {st['token']}"}).json()["data"]
    assert me["user"]["preferences"]["language"] == "en" if "user" in me else me["preferences"]["language"] == "en"

    # ⑦ 再次扫码 → 直接登录
    data2 = client.post("/api/auth/feishu/callback", json={"code": "code-2", "state": state}).json()["data"]
    assert data2["status"] == "active" and data2["token"]


def test_config_admin_only(client, admin_headers):
    # 造一个非 admin 用户验证 403
    client.post("/api/admin/users", json={"username": "plain_m11", "password": "pass123", "roles": ["it_dev"]},
                headers=admin_headers)
    tk = client.post("/api/auth/login", json={"username": "plain_m11", "password": "pass123"}).json()["data"]["token"]
    h = {"Authorization": f"Bearer {tk}"}
    assert client.get("/api/admin/feishu-config", headers=h).status_code == 403
    assert client.put("/api/admin/feishu-config", json={"app_id": "x"}, headers=h).status_code == 403