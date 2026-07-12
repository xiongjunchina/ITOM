"""M7：飞书扫码登录 + 管理员开通审批 + 过渡页轮询 + 双向通知 + 语言字段。"""
import pytest


@pytest.fixture(scope="module")
def member(client, admin_headers):
    return client.post("/api/members", json={"name": "新员工张三"}, headers=admin_headers).json()["data"]


def scan(client, external_id="fs_zhangsan", name="张三"):
    return client.post("/api/auth/feishu/scan", json={"external_id": external_id, "display_name": name}).json()["data"]


# ---------- 扫码 → 待处理 ----------

def test_scan_creates_pending_request(client, admin_headers):
    d = scan(client)
    assert d["status"] == "pending" and d["pending_token"] and d["request_id"]

    # 重复扫码复用同一 pending 请求（不重复建）
    d2 = scan(client)
    assert d2["request_id"] == d["request_id"]

    # 管理员可见待处理请求 + 计数
    reqs = client.get("/api/auth/onboarding/requests", headers=admin_headers).json()["data"]
    assert any(r["id"] == d["request_id"] and r["status"] == "pending" for r in reqs)
    assert client.get("/api/auth/onboarding/pending-count", headers=admin_headers).json()["data"]["pending"] >= 1


def test_pending_token_is_not_a_session(client):
    """待开通令牌只能查开通状态，不能当正式会话用。"""
    d = scan(client, external_id="fs_probe", name="探针")
    h = {"Authorization": f"Bearer {d['pending_token']}"}
    assert client.get("/api/auth/onboarding/status", headers=h).json()["data"]["status"] == "pending"
    assert client.get("/api/auth/me", headers=h).status_code == 401  # 正式接口拒绝待开通令牌


def test_onboarding_requires_admin(client):
    _, staff_h = _make_user(client, "onb_dev", ["it_dev"])
    assert client.get("/api/auth/onboarding/requests", headers=staff_h).status_code == 403
    assert client.get("/api/auth/onboarding/pending-count", headers=staff_h).status_code == 403


# ---------- 开通 → 员工自动进入 ----------

def test_approve_then_employee_enters(client, admin_headers, member):
    d = scan(client, external_id="fs_join", name="李四")
    pending_h = {"Authorization": f"Bearer {d['pending_token']}"}
    assert client.get("/api/auth/onboarding/status", headers=pending_h).json()["data"]["status"] == "pending"

    r = client.post(
        f"/api/auth/onboarding/requests/{d['request_id']}/approve",
        json={"username": "lisi", "roles": ["it_ops"], "language": "en", "person_id": member["id"]},
        headers=admin_headers,
    )
    assert r.json()["success"], r.text

    # 员工过渡页轮询到 approved → 拿到正式令牌 + 语言
    st = client.get("/api/auth/onboarding/status", headers=pending_h).json()["data"]
    assert st["status"] == "approved" and st["token"]
    assert st["user"]["username"] == "lisi" and st["user"]["language"] == "en"
    assert "it_ops" in st["user"]["roles"]

    # 正式令牌可用
    real_h = {"Authorization": f"Bearer {st['token']}"}
    assert client.get("/api/auth/me", headers=real_h).json()["data"]["username"] == "lisi"

    # 开通后员工收到站内通知（已绑定人员）
    notes = client.get("/api/notifications", headers=real_h).json()["data"]
    assert any("已开通" in n["title"] for n in notes)

    # 已开通用户再次扫码 → 直接登录（active）
    d2 = scan(client, external_id="fs_join", name="李四")
    assert d2["status"] == "active" and d2["token"]
    assert d2["user"]["language"] == "en"

    # 请求已处理，不能重复开通
    r = client.post(
        f"/api/auth/onboarding/requests/{d['request_id']}/approve",
        json={"username": "lisi2"}, headers=admin_headers,
    )
    assert r.json()["error"]["code"] == "ALREADY_PROCESSED"

    # 计数减少（该请求已 approved）
    reqs = client.get("/api/auth/onboarding/requests?status=approved", headers=admin_headers).json()["data"]
    assert any(x["id"] == d["request_id"] for x in reqs)


def test_approve_guards(client, admin_headers):
    d = scan(client, external_id="fs_guard", name="王五")
    rid = d["request_id"]
    # admin 角色不可开通授予
    r = client.post(f"/api/auth/onboarding/requests/{rid}/approve",
                    json={"username": "wangwu", "roles": ["admin"]}, headers=admin_headers)
    assert r.json()["error"]["code"] == "ADMIN_NOT_GRANTABLE"
    # 未知角色
    r = client.post(f"/api/auth/onboarding/requests/{rid}/approve",
                    json={"username": "wangwu", "roles": ["nope"]}, headers=admin_headers)
    assert r.json()["error"]["code"] == "INVALID_ROLE"
    # 用户名占用
    r = client.post(f"/api/auth/onboarding/requests/{rid}/approve",
                    json={"username": "admin"}, headers=admin_headers)
    assert r.json()["error"]["code"] == "USERNAME_TAKEN"
    # 非法用户名
    assert client.post(f"/api/auth/onboarding/requests/{rid}/approve",
                       json={"username": "王五"}, headers=admin_headers).status_code == 422


# ---------- 驳回 ----------

def test_reject_flow(client, admin_headers):
    d = scan(client, external_id="fs_reject", name="赵六")
    pending_h = {"Authorization": f"Bearer {d['pending_token']}"}
    r = client.post(f"/api/auth/onboarding/requests/{d['request_id']}/reject",
                    json={"reason": "非本公司员工"}, headers=admin_headers)
    assert r.json()["success"], r.text
    st = client.get("/api/auth/onboarding/status", headers=pending_h).json()["data"]
    assert st["status"] == "rejected" and st["note"] == "非本公司员工"
    # 驳回后不能再开通
    assert client.post(f"/api/auth/onboarding/requests/{d['request_id']}/approve",
                       json={"username": "zhaoliu"}, headers=admin_headers).json()["error"]["code"] == "ALREADY_PROCESSED"


# ---------- 语言切换 ----------

def test_language_default_and_switch(client, admin_headers):
    _, h = _make_user(client, "lang_dev", ["it_dev"])
    assert client.get("/api/auth/me", headers=h).json()["data"]["language"] == "zh"  # 默认中文
    r = client.patch("/api/auth/me/preferences", json={"language": "en"}, headers=h)
    assert r.json()["data"]["preferences"]["language"] == "en"
    assert client.get("/api/auth/me", headers=h).json()["data"]["language"] == "en"
    # 非法语言被拒
    assert client.patch("/api/auth/me/preferences", json={"language": "fr"}, headers=h).status_code == 422


# ---------- helper ----------

def _make_user(client, username, roles):
    admin_tok = client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-pw"}).json()["data"]["token"]
    ah = {"Authorization": f"Bearer {admin_tok}"}
    m = client.post("/api/members", json={"name": username}, headers=ah).json()["data"]
    client.post("/api/admin/users",
                json={"username": username, "password": "pass123", "roles": roles, "person_id": m["id"]}, headers=ah)
    tok = client.post("/api/auth/login", json={"username": username, "password": "pass123"}).json()["data"]["token"]
    return m["id"], {"Authorization": f"Bearer {tok}"}
