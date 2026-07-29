"""M11：飞书集成——配置端点 / IT 子树组织同步(mock HTTP) / OAuth 扫码登录全链路 / 模拟入口守卫。"""
import json

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
    stats = client.post("/api/admin/org-sync", json={"source": "feishu", "sync": True}, headers=admin_headers).json()["data"]
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
        "email": "zhang.dev@example.com",
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


def test_helpdesk_config_mask_and_enable_guard(client, admin_headers):
    # 服务台凭据只允许写入，不在 GET 回传明文；启用时必须同时具备 ID + Token。
    r = client.put("/api/admin/feishu-config", json={"helpdesk_enabled": True}, headers=admin_headers)
    assert r.status_code == 400 and r.json()["error"]["code"] == "FEISHU_HELPDESK_CONFIG_INCOMPLETE"
    r = client.put("/api/admin/feishu-config", json={
        "helpdesk_id": "7667139085051383050",
        "helpdesk_token": "helpdesk-secret",
        "helpdesk_enabled": True,
        "helpdesk_event_verification_token": "event-secret",
    }, headers=admin_headers)
    assert r.status_code == 200
    cfg = client.get("/api/admin/feishu-config", headers=admin_headers).json()["data"]
    assert cfg["helpdesk_enabled"] is True
    assert cfg["has_helpdesk_token"] is True
    assert cfg["helpdesk_token_masked"] == "********"
    assert "helpdesk-secret" not in str(cfg) and "event-secret" not in str(cfg)


def test_helpdesk_event_subscription_is_explicit_and_status_is_visible(client, admin_headers, monkeypatch):
    """服务台凭据保存不等于事件已订阅，管理员显式订阅后才显示成功。"""
    from app.services.feishu import FeishuClient

    client.put("/api/admin/feishu-config", json={
        "app_id": "cli_test_app", "app_secret": "s3cret-value",
        "helpdesk_id": "hd-subscribe", "helpdesk_token": "token-subscribe", "helpdesk_enabled": True,
    }, headers=admin_headers)
    calls = {}

    def fake_subscribe(self, helpdesk_id, helpdesk_token):
        calls.update(helpdesk_id=helpdesk_id, helpdesk_token=helpdesk_token)

    monkeypatch.setattr(FeishuClient, "subscribe_helpdesk_events", fake_subscribe)
    result = client.post("/api/admin/feishu-config/subscribe-helpdesk-events", headers=admin_headers)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["subscribed"] is True
    assert calls == {"helpdesk_id": "hd-subscribe", "helpdesk_token": "token-subscribe"}
    cfg = client.get("/api/admin/feishu-config", headers=admin_headers).json()["data"]
    assert cfg["helpdesk_event_subscription_status"] == "subscribed"
    assert cfg["helpdesk_event_subscription_error"] is None


def test_helpdesk_subscription_client_uses_service_desk_header(monkeypatch):
    """订阅必须携带双重凭证，并按飞书线上格式提交 type/subtype 事件对象。"""
    from app.services.feishu import FeishuClient

    captured = {}

    class Response:
        def json(self):
            return {"code": 0, "msg": "success", "data": {}}

    monkeypatch.setattr(FeishuClient, "tenant_access_token", lambda self: "tenant-token")

    def fake_post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr("app.services.feishu.httpx.post", fake_post)
    FeishuClient("https://open.feishu.cn", "app", "secret").subscribe_helpdesk_events("hd-1", "token-1")
    assert captured["url"].endswith("/open-apis/helpdesk/v1/events/subscribe")
    assert captured["headers"]["Authorization"] == "Bearer tenant-token"
    assert captured["headers"]["X-Lark-Helpdesk-Authorization"] == "aGQtMTp0b2tlbi0x"
    assert captured["json"] == {"events": [
        {"type": "helpdesk.ticket", "subtype": "ticket.created_v1"},
        {"type": "helpdesk.ticket", "subtype": "ticket.updated_v1"},
        {"type": "helpdesk.ticket_message", "subtype": "ticket_message.created_v1"},
    ]}


def test_helpdesk_subscription_error_includes_field_violation(monkeypatch):
    """字段校验失败时保留飞书 field_violations，避免只显示笼统错误。"""
    from app.core.errors import AppError
    from app.services.feishu import FeishuClient

    class Response:
        def json(self):
            return {
                "code": 99992402,
                "msg": "field validation failed",
                "error": {
                    "log_id": "log-subscribe-1",
                    "field_violations": [{"field": "events", "description": "events is required"}],
                },
            }

    monkeypatch.setattr(FeishuClient, "tenant_access_token", lambda self: "tenant-token")
    monkeypatch.setattr("app.services.feishu.httpx.post", lambda *args, **kwargs: Response())
    with pytest.raises(AppError) as exc_info:
        FeishuClient("https://open.feishu.cn", "app", "secret").subscribe_helpdesk_events("hd-1", "token-1")
    assert "events: events is required" in exc_info.value.message
    assert "log_id=log-subscribe-1" in exc_info.value.message


def test_helpdesk_event_verification_accepts_unicode_token(client, admin_headers):
    """URL verification must still return JSON when a configured token is non-ASCII."""
    token = "事件令牌-测试"
    r = client.put("/api/admin/feishu-config", json={
        "helpdesk_event_verification_token": token,
    }, headers=admin_headers)
    assert r.status_code == 200, r.text

    verification = client.post("/api/integrations/feishu/helpdesk/events", json={
        "type": "url_verification", "token": token, "challenge": "unicode-challenge",
    })
    assert verification.status_code == 200, verification.text
    assert verification.json() == {"challenge": "unicode-challenge"}


def test_helpdesk_ticket_header_and_admin_probe(client, admin_headers, monkeypatch):
    from app.services.feishu import FeishuClient

    # 上游详情接口只收到 tenant token + base64(helpdesk_id:token)，不会泄漏配置到响应。
    client.put("/api/admin/feishu-config", json={
        "app_id": "cli_test_app", "app_secret": "s3cret-value",
        "helpdesk_id": "hd-1", "helpdesk_token": "token-1", "helpdesk_enabled": True,
    }, headers=admin_headers)
    monkeypatch.setattr(FeishuClient, "tenant_access_token", lambda self: "tenant-token")
    captured = {}

    class Response:
        def json(self):
            return {"code": 0, "data": {"ticket": {
                "ticket_id": "ticket-1", "title": "电脑中毒", "status": "open", "stage": "human",
                "guest": {"id": "ou_guest", "name": "员工"}, "fields": [{"name": "问题描述", "value": "无法打开文件"}],
            }}}

    def fake_get(url, headers, timeout):
        captured.update(url=url, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr("app.services.feishu.httpx.get", fake_get)
    r = client.post("/api/admin/feishu-config/test-helpdesk", json={"ticket_id": "ticket-1"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["title"] == "电脑中毒"
    assert captured["headers"]["Authorization"] == "Bearer tenant-token"
    assert captured["headers"]["X-Lark-Helpdesk-Authorization"] == "aGQtMTp0b2tlbi0x"
    assert "token-1" not in str(r.json())


def test_helpdesk_handoff_binds_identity_and_consumes_once(client, admin_headers, monkeypatch):
    import base64
    from app.db import SessionLocal
    from app.models import AuthUser

    client.put("/api/admin/feishu-config", json={
        "app_id": "cli_test_app", "app_secret": "s3cret-value",
        "helpdesk_id": "hd-1", "helpdesk_token": "token-1", "helpdesk_enabled": True,
    }, headers=admin_headers)
    db = SessionLocal()
    admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
    admin.external_id = "ou_guest"
    db.commit()
    db.close()

    from app.services.feishu import FeishuClient
    monkeypatch.setattr(FeishuClient, "get_helpdesk_ticket", lambda self, ticket_id, helpdesk_id, helpdesk_token: {
        "ticket_id": ticket_id, "title": "无法打开文档", "guest": {"id": "ou_guest", "name": "员工"},
        "agent": {"id": "ou_agent", "name": "客服"},
        "fields": [
            {"name": "紧急程度", "value": "紧急"},
            {"name": "服务类别", "value": "电脑与终端"},
            {"name": "问题描述", "value": "电脑中毒，无法打开文件"},
        ],
    })
    machine_header = base64.b64encode(b"hd-1:token-1").decode()
    r = client.post("/api/integrations/feishu/helpdesk/handoffs", json={
        "ticket_id": "ticket-1", "action": "service_request",
    }, headers={"X-Lark-Helpdesk-Authorization": machine_header})
    assert r.status_code == 200, r.text
    token = r.json()["data"]["handoff_token"]
    detail = client.get(f"/api/integrations/feishu/helpdesk/handoffs/{token}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    prefill = detail.json()["data"]["prefill"]
    assert prefill["priority"] == "P1"
    assert prefill["service_category"] == "电脑与终端"
    assert prefill["source"] == "feishu_helpdesk"
    assert "business_domain_id" not in prefill

    consumed = client.post(f"/api/integrations/feishu/helpdesk/handoffs/{token}/consume", json={
        "entity_type": "ticket", "entity_id": "01KZ0000000000000000000000",
    }, headers=admin_headers)
    assert consumed.status_code == 200
    again = client.get(f"/api/integrations/feishu/helpdesk/handoffs/{token}", headers=admin_headers)
    assert again.status_code == 200
    assert again.json()["data"] == {
        "status": "consumed",
        "action": "service_request",
        "ticket_id": "ticket-1",
        "consumed_entity_type": "ticket",
        "consumed_entity_id": "01KZ0000000000000000000000",
    }
    duplicate_consume = client.post(f"/api/integrations/feishu/helpdesk/handoffs/{token}/consume", json={
        "entity_type": "ticket", "entity_id": "01KZ0000000000000000000001",
    }, headers=admin_headers)
    assert duplicate_consume.status_code == 409
    assert duplicate_consume.json()["error"]["code"] == "FEISHU_HANDOFF_USED"


def test_helpdesk_dynamic_card_send_callback_and_idempotency(client, admin_headers, monkeypatch):
    """动态卡片必须把点击人 open_id 绑定到一次性交接，并拒绝重复/冒用操作。"""
    import base64
    from app.db import SessionLocal
    from app.models import AuthUser

    client.put("/api/admin/feishu-config", json={
        "app_id": "cli_test_app", "app_secret": "s3cret-value",
        "helpdesk_id": "hd-1", "helpdesk_token": "token-1", "helpdesk_enabled": True,
        "helpdesk_event_verification_token": "event-secret",
    }, headers=admin_headers)
    db = SessionLocal()
    admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
    admin.external_id = "ou_guest"
    db.commit()
    db.close()

    monkeypatch.setattr(FeishuClient, "get_helpdesk_ticket", lambda self, ticket_id, helpdesk_id, helpdesk_token: {
        "ticket_id": ticket_id, "title": "电脑中毒", "guest": {"id": "ou_guest", "name": "员工"},
        "fields": [{"name": "问题描述", "value": "无法打开文档"}],
    })
    sent = {}

    def fake_send(self, receive_id, receive_id_type, card):
        sent.update(receive_id=receive_id, receive_id_type=receive_id_type, card=card)
        return "om-card-1"

    monkeypatch.setattr(FeishuClient, "send_interactive_card", fake_send)
    machine_header = base64.b64encode(b"hd-1:token-1").decode()
    sent_response = client.post(
        "/api/integrations/feishu/helpdesk/cards",
        json={"ticket_id": "ticket-card-1"},
        headers={"X-Lark-Helpdesk-Authorization": machine_header},
    )
    assert sent_response.status_code == 200, sent_response.text
    assert sent_response.json()["data"]["message_id"] == "om-card-1"
    assert sent["receive_id"] == "ou_guest" and sent["receive_id_type"] == "open_id"
    values = [
        element["behaviors"][0]["value"]["action"]
        for element in sent["card"]["body"]["elements"][1:]
        if element.get("tag") == "button"
    ]
    assert values == ["create_service_request", "create_requirement"]
    assert all(element.get("tag") != "action" for element in sent["card"]["body"]["elements"])

    payload = {
        "schema": "2.0",
        "header": {"event_id": "evt-card-1", "event_type": "card.action.trigger", "token": "event-secret"},
        "event": {
            "operator": {"open_id": "ou_guest"},
            "context": {"open_message_id": "om-card-1"},
            "action": {"value": {"action": "create_service_request", "ticket_id": "ticket-card-1"}},
        },
    }
    callback = client.post("/api/integrations/feishu/helpdesk/card-callback", json=payload)
    assert callback.status_code == 200, callback.text
    assert callback.json()["toast"]["type"] == "success"
    response_card = callback.json()["card"]
    assert response_card["type"] == "raw"
    assert "/itsm/tickets?handoff=" in response_card["data"]["body"]["elements"][1]["behaviors"][0]["default_url"]

    verification = client.post("/api/integrations/feishu/helpdesk/card-callback", json={
        "type": "url_verification", "token": "event-secret", "challenge": "callback-challenge",
    })
    assert verification.status_code == 200 and verification.json() == {"challenge": "callback-challenge"}

    duplicate = client.post("/api/integrations/feishu/helpdesk/events", json=payload)
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "FEISHU_CARD_DUPLICATE"

    mismatch = {**payload, "header": {**payload["header"], "event_id": "evt-card-2"},
                "event": {**payload["event"], "operator": {"open_id": "ou_other"}}}
    rejected = client.post("/api/integrations/feishu/helpdesk/card-callback", json=mismatch)
    assert rejected.status_code == 403 and rejected.json()["error"]["code"] == "FEISHU_CARD_IDENTITY_MISMATCH"

    bad_token = {**payload, "header": {**payload["header"], "event_id": "evt-card-3", "token": "wrong"}}
    rejected = client.post("/api/integrations/feishu/helpdesk/card-callback", json=bad_token)
    assert rejected.status_code == 401 and rejected.json()["error"]["code"] == "FEISHU_EVENT_TOKEN_INVALID"

    # SDK-shaped card callbacks expose the token on event.token rather than header.token.
    event_token_payload = {**payload, "header": {**payload["header"], "event_id": "evt-card-4", "token": ""},
                           "event": {**payload["event"], "token": "event-secret"}}
    event_token_callback = client.post(
        "/api/integrations/feishu/helpdesk/card-callback", json=event_token_payload
    )
    assert event_token_callback.status_code == 200, event_token_callback.text


def test_helpdesk_customized_fields_map_to_ticket_prefill(client, admin_headers, monkeypatch):
    """真实 Helpdesk ticket-detail 字段使用 customized_fields/key_name/display_name。"""
    import base64
    from app.db import SessionLocal
    from app.models import AuthUser

    client.put("/api/admin/feishu-config", json={
        "app_id": "cli_test_app", "app_secret": "s3cret-value",
        "helpdesk_id": "hd-1", "helpdesk_token": "token-1", "helpdesk_enabled": True,
    }, headers=admin_headers)
    db = SessionLocal()
    admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
    admin.external_id = "ou_guest"
    db.commit()
    db.close()
    monkeypatch.setattr(FeishuClient, "get_helpdesk_ticket", lambda self, ticket_id, helpdesk_id, helpdesk_token: {
        "ticket_id": ticket_id,
        "guest": {"id": "ou_guest", "name": "员工"},
        "customized_fields": [
            {"key_name": "title", "display_name": "标题", "value": "电脑中毒"},
            {"key_name": "urgency", "display_name": "紧急程度", "value": "紧急"},
            {"key_name": "service_category", "display_name": "服务类别", "value": "电脑与终端"},
            {"key_name": "description", "display_name": "问题描述", "value": "无法打开文档"},
            {"key_name": "other_info", "display_name": "其他补充信息", "value": "已重启仍无法打开"},
        ],
    })
    machine_header = base64.b64encode(b"hd-1:token-1").decode()
    response = client.post("/api/integrations/feishu/helpdesk/handoffs", json={
        "ticket_id": "ticket-customized-fields", "action": "service_request",
    }, headers={"X-Lark-Helpdesk-Authorization": machine_header})
    assert response.status_code == 200, response.text
    token = response.json()["data"]["handoff_token"]
    detail = client.get(f"/api/integrations/feishu/helpdesk/handoffs/{token}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    prefill = detail.json()["data"]["prefill"]
    assert prefill["title"] == "电脑中毒"
    assert prefill["priority"] == "P1"
    assert prefill["service_category"] == "电脑与终端"
    assert prefill["description"] == "无法打开文档"
    assert prefill["other_info"] == "已重启仍无法打开"
    assert response.json()["data"]["entry_url"].startswith("http://testserver/itsm/tickets?handoff=")


def test_helpdesk_dropdown_option_uuid_resolves_to_display_name():
    """飞书下拉字段返回 tag UUID 时，交接快照应保存用户可读名称。"""
    from app.services.feishu_helpdesk import normalize_helpdesk_ticket

    option_id = "730e26c3-048c-4428-a169-ebbb4deb7d14"

    class FakeClient:
        def get_helpdesk_ticket_customized_fields(self, helpdesk_id, helpdesk_token):
            return [{
                "key_name": "service_category",
                "display_name": "服务类别",
                "field_type": "dropdown",
                "dropdown_options": {"children": [
                    {"tag": option_id, "display_name": "电脑与终端"},
                ]},
            }]

    snapshot = normalize_helpdesk_ticket(FakeClient(), {
        "guest": {"id": "ou_guest", "name": "员工"},
        "customized_fields": [{"key_name": "service_category", "display_name": "服务类别", "value": option_id}],
    }, "helpdesk-1", "token-1")
    assert snapshot["service_category"] == "电脑与终端"


def test_helpdesk_customized_field_api_reads_dropdown_options(monkeypatch):
    from app.services.feishu import FeishuClient

    monkeypatch.setattr(FeishuClient, "tenant_access_token", lambda self: "tenant-token")
    captured = {}

    class Response:
        def json(self):
            return {"code": 0, "data": {"items": [{
                "key_name": "service_category",
                "dropdown_options": {"children": [{"tag": "option-1", "display_name": "电脑与终端"}]},
            }]}}

    def fake_get(url, params, headers, timeout):
        captured.update(url=url, params=params, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr("app.services.feishu.httpx.get", fake_get)
    fields = FeishuClient("https://open.feishu.cn", "app", "secret").get_helpdesk_ticket_customized_fields(
        "hd-1", "token-1"
    )
    assert fields[0]["dropdown_options"]["children"][0]["display_name"] == "电脑与终端"
    assert captured["params"]["helpdesk_id"] == "hd-1"


def test_helpdesk_urgency_maps_to_matching_itom_level():
    from app.services.feishu_helpdesk import normalize_ticket

    def priority(value):
        return normalize_ticket({"customized_fields": [{
            "key_name": "urgency", "display_name": "紧急程度", "value": value,
        }]}).get("priority")

    assert priority("紧急") == "P1"
    assert priority("高") == "P2"
    assert priority("一般") == "P3"
    assert priority("低") == "P4"


def test_helpdesk_ticket_events_are_queued_idempotently(client, admin_headers):
    """事件回调只入队，重复 event_id 不会生成第二条同步任务。"""
    from app.db import SessionLocal
    from app.models import FeishuHelpdeskSyncEvent

    client.put("/api/admin/feishu-config", json={
        "app_id": "cli_test_app", "app_secret": "s3cret-value",
        "helpdesk_id": "hd-1", "helpdesk_token": "token-1", "helpdesk_enabled": True,
        "helpdesk_event_verification_token": "event-secret",
    }, headers=admin_headers)
    payload = {
        "header": {
            "event_id": "evt-ticket-created-1",
            "event_type": "helpdesk.ticket.created_v1",
            "token": "event-secret",
        },
        "event": {"ticket_id": "ticket-queued-1"},
    }
    first = client.post("/api/integrations/feishu/helpdesk/events", json=payload)
    second = client.post("/api/integrations/feishu/helpdesk/events", json=payload)
    assert first.status_code == 200 and first.json()["data"]["queued"] is True
    assert second.status_code == 200 and second.json()["data"]["queued"] is False
    db = SessionLocal()
    rows = db.query(FeishuHelpdeskSyncEvent).filter(FeishuHelpdeskSyncEvent.event_id == "evt-ticket-created-1").all()
    assert len(rows) == 1 and rows[0].ticket_id == "ticket-queued-1"
    db.close()


def test_helpdesk_sync_retry_survives_remote_failure(client, admin_headers, monkeypatch):
    """远端详情失败后，回滚不应让补偿扫描因 ORM 对象失效而中断。"""
    from datetime import datetime

    from app.db import SessionLocal
    from app.models import FeishuHelpdeskSyncEvent
    from app.services.feishu_helpdesk import queue_sync_event, scan_sync_events

    client.put("/api/admin/feishu-config", json={
        "app_id": "cli_test_app", "app_secret": "s3cret-value",
        "helpdesk_id": "hd-retry", "helpdesk_token": "token-retry", "helpdesk_enabled": True,
        "helpdesk_event_verification_token": "event-secret",
    }, headers=admin_headers)
    db = SessionLocal()
    row, created = queue_sync_event(db, {
        "header": {"event_id": "evt-retry-orm-1", "event_type": "helpdesk.ticket.created_v1"},
        "event": {"ticket_id": "ticket-retry-orm-1"},
    }, "helpdesk.ticket.created_v1")
    assert created is True
    db.close()

    def fail_process(*_args, **_kwargs):
        raise RuntimeError("simulated Feishu outage")

    monkeypatch.setattr("app.services.feishu_helpdesk.process_sync_event", fail_process)
    assert scan_sync_events() == 0

    db = SessionLocal()
    stored = db.query(FeishuHelpdeskSyncEvent).filter(
        FeishuHelpdeskSyncEvent.event_id == "evt-retry-orm-1"
    ).one()
    assert stored.status == "pending"
    assert stored.attempts == 1
    assert stored.last_error == "simulated Feishu outage"
    db.delete(stored)
    db.commit()
    db.close()


def test_helpdesk_rating_sync_updates_linked_ticket(client, admin_headers, monkeypatch):
    """飞书评价事件消费后，关联 ITSM 服务请求保存同一星级并回写确认消息。"""
    from app.db import SessionLocal
    from app.models import FeishuHelpdeskIntake, FeishuHelpdeskOutbox, FeishuHelpdeskSyncEvent, Ticket
    from app.services.feishu_helpdesk import queue_sync_event, scan_sync_events

    client.put("/api/admin/feishu-config", json={
        "app_id": "cli_test_app", "app_secret": "s3cret-value",
        "helpdesk_id": "hd-rating", "helpdesk_token": "token-rating", "helpdesk_enabled": True,
        "helpdesk_event_verification_token": "event-secret",
    }, headers=admin_headers)
    item = client.get("/api/service-items", headers=admin_headers).json()["data"][0]["id"]
    ticket = client.post("/api/tickets", json={
        "title": "飞书评价同步验证", "ticket_type": "service_request", "priority": "P4",
        "description": "rating", "service_item_id": item,
    }, headers=admin_headers).json()["data"]

    db = SessionLocal()
    db.add(FeishuHelpdeskIntake(
        helpdesk_id="hd-rating", ticket_id="feishu-rating-1", guest_open_id="ou-rating",
        classification="service_request", linked_entity_type="ticket", linked_entity_id=ticket["id"],
    ))
    db.commit()
    db.close()

    monkeypatch.setattr(FeishuClient, "tenant_access_token", lambda self: "tenant-rating")
    monkeypatch.setattr(FeishuClient, "get_helpdesk_ticket", lambda self, ticket_id, helpdesk_id, helpdesk_token: {
        "ticket_id": ticket_id, "status": "closed", "satisfaction": 5,
        "guest": {"id": "ou-rating", "name": "评价员工"},
    })
    db = SessionLocal()
    _, created = queue_sync_event(db, {
        # 飞书服务台没有独立 rated 事件；评价完成后由工单更新事件触发详情重读。
        "header": {"event_id": "evt-rating-1", "event_type": "helpdesk.ticket.updated_v1"},
        "event": {"ticket_id": "feishu-rating-1", "rating": 5},
    })
    assert created is True
    db.close()
    assert scan_sync_events() >= 1

    db = SessionLocal()
    linked = db.get(Ticket, ticket["id"])
    assert linked.status == "closed"
    assert linked.satisfaction == 5
    outbox = db.query(FeishuHelpdeskOutbox).filter(
        FeishuHelpdeskOutbox.ticket_id == "feishu-rating-1"
    ).all()
    assert any(row.payload.get("text") == "已记录你的服务评价，感谢反馈。" for row in outbox)
    for row in outbox:
        db.delete(row)
    intake = db.query(FeishuHelpdeskIntake).filter(
        FeishuHelpdeskIntake.ticket_id == "feishu-rating-1"
    ).one()
    event = db.query(FeishuHelpdeskSyncEvent).filter(
        FeishuHelpdeskSyncEvent.event_id == "evt-rating-1"
    ).one()
    db.delete(event)
    db.delete(intake)
    db.commit()
    db.close()

def test_helpdesk_progress_outbox_excludes_internal_events(client, admin_headers):
    """只回写用户可见阶段，内部事件不进入飞书 outbox。"""
    from app.db import SessionLocal
    from app.events.bus import publish
    from app.models import FeishuHelpdeskIntake, FeishuHelpdeskOutbox

    db = SessionLocal()
    linked_id = "01KYSYNCVISIBLE000000000000"
    intake = FeishuHelpdeskIntake(
        helpdesk_id="hd-visible", ticket_id="ticket-visible-1", guest_open_id="ou_guest",
        classification="service_request", linked_entity_type="ticket", linked_entity_id=linked_id,
    )
    db.add(intake)
    db.commit()
    publish(db, "ticket.assigned", "ticket", linked_id, {})
    publish(db, "ticket.user_confirmed", "ticket", linked_id, {})
    publish(db, "ticket.satisfaction_rated", "ticket", linked_id, {"score": 5})
    publish(db, "ticket.internal_note", "ticket", linked_id, {"note": "内部备注"})
    db.commit()
    rows = db.query(FeishuHelpdeskOutbox).filter(
        FeishuHelpdeskOutbox.ticket_id == "ticket-visible-1"
    ).order_by(FeishuHelpdeskOutbox.created_at).all()
    assert [row.payload.get("text") for row in rows] == [
        "ITOM 已分派受理人，正在安排处理。",
        "你已确认处理结果，工单正在关闭。",
        "已记录你的服务评价，感谢反馈。",
    ]
    for row in rows:
        db.delete(row)
    db.delete(intake)
    db.commit()
    db.close()


def test_helpdesk_agents_array_marks_ticket_as_human_service():
    """飞书详情使用 agents 数组时也应识别为已转人工并保留客服名称。"""
    from app.services.feishu_helpdesk import _is_human_service, normalize_ticket

    snapshot = normalize_ticket({
        "ticket_id": "ticket-agents-array-1",
        "status": 51,
        "guest": {"open_id": "ou_guest", "name": "员工甲"},
        "agents": [
            {"open_id": "ou_agent_1", "name": "客服甲"},
            {"open_id": "ou_agent_2", "name": "客服乙"},
        ],
    })

    assert snapshot["agent"] == {
        "open_id": "ou_agent_1",
        "name": "客服甲、客服乙",
    }
    assert _is_human_service(snapshot, {"event": {"status": 51, "stage": 2}}) is True


def test_helpdesk_numeric_close_solved_and_message_rating_are_normalized():
    """真实 Helpdesk 事件使用 numeric status/solve，评分只出现在消息文本。"""
    from app.services.feishu_helpdesk import _rating, _remote_closed, _remote_states, _remote_user_confirmed

    states = _remote_states({"event": {"object": {"status": 51, "solve": 2}}}, {})
    assert _remote_closed(states)
    assert _remote_user_confirmed(states)
    assert _rating({"event": {"text": "你的打分为: 😄 满意"}}, {}) == 5
    assert _rating({"event": {"text": "评价本次服务 [😄 满意][😐 一般][😞 不满意]"}}, {}) is None


def test_helpdesk_routing_prompt_prefers_post_and_falls_back_to_text(monkeypatch):
    """原服务台会话优先富文本，租户不支持时自动降级为完整 URL 文本。"""
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    monkeypatch.setattr(FeishuClient, "tenant_access_token", lambda self: "tenant-routing")

    def post_success(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return FakeResponse({"code": 0, "data": {"message_id": "msg-post-1"}})

    monkeypatch.setattr("app.services.feishu.httpx.post", post_success)
    feishu = FeishuClient("https://open.feishu.cn", "app", "secret")
    message_id, channel = feishu.send_helpdesk_routing_prompt(
        "ticket-routing-1", "hd-routing", "token-routing",
        "https://itom.example/feishu/helpdesk/entry?intake=one&action=service_request",
        "https://itom.example/feishu/helpdesk/entry?intake=one&action=requirement",
    )
    assert (message_id, channel) == ("msg-post-1", "helpdesk_post")
    assert calls[0][1]["msg_type"] == "post"
    rich_content = json.loads(calls[0][1]["content"])
    assert rich_content["post"]["zh_cn"]["content"][1][0]["tag"] == "a"

    calls.clear()

    def post_fallback(url, **kwargs):
        calls.append((url, kwargs["json"]))
        if len(calls) == 1:
            return FakeResponse({"code": 230099, "msg": "post unsupported"})
        return FakeResponse({"code": 0, "data": {"message_id": "msg-text-1"}})

    monkeypatch.setattr("app.services.feishu.httpx.post", post_fallback)
    message_id, channel = feishu.send_helpdesk_routing_prompt(
        "ticket-routing-2", "hd-routing", "token-routing",
        "https://itom.example/service", "https://itom.example/requirement",
    )
    assert (message_id, channel) == ("msg-text-1", "helpdesk_text")
    assert [item[1]["msg_type"] for item in calls] == ["post", "text"]
    assert "https://itom.example/service" in calls[1][1]["content"]


def test_helpdesk_stable_intake_entry_authenticates_before_issuing_token(
    client, admin_headers, monkeypatch,
):
    """稳定入口不含令牌；登录且重新核验 open_id 后才签发十分钟令牌。"""
    from urllib.parse import parse_qs, urlparse

    from app.db import SessionLocal
    from app.models import AuthUser, FeishuHelpdeskHandoff, FeishuHelpdeskIntake

    client.put("/api/admin/feishu-config", json={
        "app_id": "cli_test_app", "app_secret": "s3cret-value",
        "helpdesk_id": "hd-stable", "helpdesk_token": "token-stable", "helpdesk_enabled": True,
    }, headers=admin_headers)
    db = SessionLocal()
    admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
    admin.external_id = "ou_stable_guest"
    intake = FeishuHelpdeskIntake(
        helpdesk_id="hd-stable", ticket_id="ticket-stable-1",
        guest_open_id="ou_stable_guest", guest_name="稳定入口员工",
    )
    db.add(intake)
    db.commit()
    intake_id = intake.id
    db.close()

    monkeypatch.setattr(FeishuClient, "get_helpdesk_ticket", lambda *args, **kwargs: {
        "ticket_id": "ticket-stable-1",
        "guest": {"id": "ou_stable_guest", "name": "稳定入口员工"},
        "customized_fields": [
            {"display_name": "标题", "value": "稳定入口预填"},
            {"display_name": "问题描述", "value": "登录后再签发令牌"},
        ],
    })
    monkeypatch.setattr(FeishuClient, "get_helpdesk_ticket_customized_fields", lambda *args, **kwargs: [])

    first = client.post(
        f"/api/integrations/feishu/helpdesk/intakes/{intake_id}/handoff",
        json={"action": "service_request"}, headers=admin_headers,
    )
    assert first.status_code == 200, first.text
    first_url = first.json()["data"]["entry_url"]
    first_token = parse_qs(urlparse(first_url).query)["handoff"][0]
    assert "/itsm/tickets?handoff=" in first_url

    second = client.post(
        f"/api/integrations/feishu/helpdesk/intakes/{intake_id}/handoff",
        json={"action": "requirement"}, headers=admin_headers,
    )
    assert second.status_code == 200, second.text
    second_url = second.json()["data"]["entry_url"]
    assert "/requirements/overview?handoff=" in second_url
    assert first_token not in second_url

    db = SessionLocal()
    first_row = db.query(FeishuHelpdeskHandoff).filter(
        FeishuHelpdeskHandoff.token_hash.is_not(None),
        FeishuHelpdeskHandoff.ticket_id == "ticket-stable-1",
    ).order_by(FeishuHelpdeskHandoff.created_at).first()
    assert first_row.status == "expired"
    db.close()

    create_user = client.post("/api/admin/users", json={
        "username": "stable_other", "password": "pass123", "roles": ["it_dev"],
    }, headers=admin_headers)
    assert create_user.status_code in {200, 409}
    other_token = client.post(
        "/api/auth/login", json={"username": "stable_other", "password": "pass123"}
    ).json()["data"]["token"]
    rejected = client.post(
        f"/api/integrations/feishu/helpdesk/intakes/{intake_id}/handoff",
        json={"action": "service_request"}, headers={"Authorization": f"Bearer {other_token}"},
    )
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "FEISHU_HANDOFF_IDENTITY_MISMATCH"


def test_helpdesk_routing_prompt_outbox_tracks_channel_and_uses_im_fallback(
    client, admin_headers, monkeypatch,
):
    """outbox 审计原会话渠道，连续失败到第三次后才使用独立机器人卡片。"""
    from datetime import datetime

    from app.core.errors import AppError
    from app.db import SessionLocal
    from app.models import FeishuHelpdeskIntake, FeishuHelpdeskOutbox
    from app.services.feishu import FeishuClient
    from app.services.feishu_helpdesk import scan_outbox

    client.put("/api/admin/feishu-config", json={
        "app_id": "cli_test_app", "app_secret": "s3cret-value",
        "helpdesk_id": "hd-outbox", "helpdesk_token": "token-outbox", "helpdesk_enabled": True,
        "helpdesk_event_url": "https://itom.example/api/integrations/feishu/helpdesk/events",
    }, headers=admin_headers)
    db = SessionLocal()
    original = FeishuHelpdeskIntake(
        helpdesk_id="hd-outbox", ticket_id="ticket-routing-original",
        guest_open_id="ou_routing_original",
    )
    fallback = FeishuHelpdeskIntake(
        helpdesk_id="hd-outbox", ticket_id="ticket-routing-fallback",
        guest_open_id="ou_routing_fallback",
    )
    db.add_all([original, fallback])
    db.flush()
    db.add_all([
        FeishuHelpdeskOutbox(
            helpdesk_id="hd-outbox", ticket_id=original.ticket_id,
            kind="routing_prompt", dedupe_key="routing-original-test", payload={},
            next_attempt_at=datetime.now(),
        ),
        FeishuHelpdeskOutbox(
            helpdesk_id="hd-outbox", ticket_id=fallback.ticket_id,
            kind="routing_prompt", dedupe_key="routing-fallback-test", payload={}, attempts=2,
            next_attempt_at=datetime.now(),
        ),
    ])
    db.commit()
    db.close()

    def prompt(self, ticket_id, *args, **kwargs):
        if ticket_id == "ticket-routing-fallback":
            raise AppError("TEST_PROMPT_FAILURE", "模拟原会话连续失败", 502)
        return "msg-original", "helpdesk_post"

    monkeypatch.setattr(FeishuClient, "send_helpdesk_routing_prompt", prompt)
    monkeypatch.setattr(FeishuClient, "send_helpdesk_message", lambda *args, **kwargs: "msg-progress")
    monkeypatch.setattr(FeishuClient, "send_interactive_card", lambda *args, **kwargs: "msg-fallback")
    assert scan_outbox() >= 2

    db = SessionLocal()
    original = db.query(FeishuHelpdeskIntake).filter(
        FeishuHelpdeskIntake.ticket_id == "ticket-routing-original"
    ).one()
    fallback = db.query(FeishuHelpdeskIntake).filter(
        FeishuHelpdeskIntake.ticket_id == "ticket-routing-fallback"
    ).one()
    assert original.routing_prompt_channel == "helpdesk_post"
    assert original.routing_prompt_message_id == "msg-original"
    assert fallback.routing_prompt_channel == "im_card_fallback"
    assert fallback.routing_prompt_message_id == "msg-fallback"
    assert fallback.choice_card_sent_at is not None
    rows = db.query(FeishuHelpdeskOutbox).filter(
        FeishuHelpdeskOutbox.dedupe_key.in_(["routing-original-test", "routing-fallback-test"])
    ).all()
    for row in rows:
        db.delete(row)
    db.delete(original)
    db.delete(fallback)
    db.commit()
    db.close()


def test_helpdesk_public_progress_uses_im_text_when_helpdesk_scope_is_missing(
    client, admin_headers, monkeypatch,
):
    """缺少 helpdesk:all 时，用户可见进展立即走应用消息而非重试 8 次。"""
    from datetime import datetime

    from app.core.errors import AppError
    from app.db import SessionLocal
    from app.models import FeishuHelpdeskIntake, FeishuHelpdeskOutbox
    from app.services.feishu import FeishuClient
    from app.services.feishu_helpdesk import scan_outbox

    client.put("/api/admin/feishu-config", json={
        "app_id": "cli_test_app", "app_secret": "s3cret-value",
        "helpdesk_id": "hd-public-fallback", "helpdesk_token": "token-public-fallback",
        "helpdesk_enabled": True,
    }, headers=admin_headers)
    db = SessionLocal()
    intake = FeishuHelpdeskIntake(
        helpdesk_id="hd-public-fallback", ticket_id="ticket-public-fallback",
        guest_open_id="ou_public_fallback",
    )
    outbox = FeishuHelpdeskOutbox(
        helpdesk_id=intake.helpdesk_id, ticket_id=intake.ticket_id,
        kind="public_message", dedupe_key="public-fallback-test",
        payload={"text": "ITOM 已受理，正在处理中。"}, next_attempt_at=datetime.now(),
    )
    db.add_all([intake, outbox])
    db.commit()
    db.close()

    def denied(*args, **kwargs):
        raise AppError("FEISHU_HELPDESK_MESSAGE_ERROR", "飞书服务台消息发送失败 99991672：helpdesk:all", 502)

    captured = {}
    monkeypatch.setattr(FeishuClient, "send_helpdesk_message", denied)
    monkeypatch.setattr(
        FeishuClient,
        "send_app_text",
        lambda self, receive_id, receive_id_type, text: captured.update(
            receive_id=receive_id, receive_id_type=receive_id_type, text=text,
        ) or "msg-im-text",
    )
    # The shared test database may contain unrelated retry rows; assert this
    # outbox row was delivered in the same scan rather than assuming it is the
    # only pending row.
    assert scan_outbox() >= 1

    db = SessionLocal()
    row = db.query(FeishuHelpdeskOutbox).filter(
        FeishuHelpdeskOutbox.dedupe_key == "public-fallback-test",
    ).one()
    assert row.status == "sent"
    assert row.attempts == 1
    assert row.message_id == "msg-im-text"
    assert row.payload["delivery_channel"] == "im_text_fallback"
    assert captured == {
        "receive_id": "ou_public_fallback",
        "receive_id_type": "open_id",
        "text": "ITOM 已受理，正在处理中。",
    }
    db.delete(row)
    db.delete(db.query(FeishuHelpdeskIntake).filter(
        FeishuHelpdeskIntake.ticket_id == "ticket-public-fallback",
    ).one())
    db.commit()
    db.close()


def test_helpdesk_routing_permission_error_skips_second_helpdesk_request(monkeypatch):
    """缺少 helpdesk:all 时，分流入口不再先等待第二次文本接口超时。"""
    from app.core.errors import AppError
    from app.services.feishu import FeishuClient

    client = FeishuClient("https://open.feishu.cn", "cli_test_app", "secret")
    calls = []

    def denied(*args, **kwargs):
        calls.append("post")
        raise AppError("FEISHU_HELPDESK_MESSAGE_ERROR", "99991672 helpdesk:all", 502)

    def unexpected_text(*args, **kwargs):
        calls.append("text")
        raise AssertionError("permission failure must go straight to the app-bot fallback")

    monkeypatch.setattr(client, "_send_helpdesk_message_payload", denied)
    monkeypatch.setattr(client, "send_helpdesk_message", unexpected_text)
    with pytest.raises(AppError, match="helpdesk:all"):
        client.send_helpdesk_routing_prompt(
            "ticket-scope-error", "helpdesk", "token", "https://itom/tickets", "https://itom/requirements",
        )
    assert calls == ["post"]
