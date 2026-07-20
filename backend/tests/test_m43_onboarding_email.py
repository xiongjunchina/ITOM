"""M43/M44：审批生成 12 位加密初始密码，管理员按需查看和发送。"""
from app.db import SessionLocal
from app.models import AuthUser, LoginRequest
from app.core.security import verify_password


def test_approval_stores_revealable_12_char_password_without_sending(client, admin_headers, monkeypatch):
    sent: list = []
    monkeypatch.setattr("app.services.email.send_initial_password_email", lambda *args: sent.append(args))
    person = client.post("/api/members", headers=admin_headers, json={
        "name": "邮件开通用户", "email": "m44@example.com",
    }).json()["data"]
    client.post("/api/auth/feishu/scan", json={
        "external_id": "ou_m44", "display_name": "邮件开通用户", "email": "m44@example.com",
    })
    with SessionLocal() as db:
        request_id = db.query(LoginRequest).filter(LoginRequest.external_id == "ou_m44").first().id
    response = client.post(f"/api/auth/onboarding/requests/{request_id}/approve", headers=admin_headers, json={
        "username": "m44.user", "roles": ["requester"], "language": "zh", "person_id": person["id"],
    })
    assert response.status_code == 200 and sent == []
    user_id = response.json()["data"]["id"]

    revealed = client.get(f"/api/admin/users/{user_id}/initial-password", headers=admin_headers).json()["data"]["password"]
    assert len(revealed) == 12
    with SessionLocal() as db:
        user = db.get(AuthUser, user_id)
        assert user.initial_password_ciphertext and revealed not in user.initial_password_ciphertext
        assert verify_password(revealed, user.password_hash)

    emailed = client.post(f"/api/admin/users/{user_id}/initial-password/email", headers=admin_headers)
    assert emailed.status_code == 200
    assert len(sent) == 1 and sent[0][1] == "m44@example.com" and sent[0][-1] == revealed


def test_password_change_clears_revealable_initial_password(client, admin_headers):
    users = client.get("/api/admin/users?q=m44.user", headers=admin_headers).json()["data"]
    user_id = users[0]["id"]
    initial = client.get(f"/api/admin/users/{user_id}/initial-password", headers=admin_headers).json()["data"]["password"]
    token = client.post("/api/auth/login", json={"username": "m44.user", "password": initial}).json()["data"]["token"]
    assert client.post("/api/auth/me/password", headers={"Authorization": f"Bearer {token}"}, json={
        "current_password": initial, "new_password": "changed123",
    }).status_code == 200
    assert client.get(f"/api/admin/users/{user_id}/initial-password", headers=admin_headers).json()["error"]["code"] == "NO_INITIAL_PASSWORD"


def test_approval_no_longer_requires_email(client, admin_headers):
    client.post("/api/auth/feishu/scan", json={"external_id": "ou_m44_no_email", "display_name": "无邮箱用户"})
    with SessionLocal() as db:
        request_id = db.query(LoginRequest).filter(LoginRequest.external_id == "ou_m44_no_email").first().id
    response = client.post(f"/api/auth/onboarding/requests/{request_id}/approve", headers=admin_headers, json={
        "username": "m44.noemail", "roles": ["requester"], "language": "zh",
    })
    assert response.status_code == 200
