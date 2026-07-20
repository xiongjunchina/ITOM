"""M37 个人设置：通知偏好、个人审计、飞书解绑与界面偏好。"""

from app.db import SessionLocal
from app.models import AuthUser
from app.services.audit import audit


def test_extended_preferences_and_personal_audit(client, admin_headers):
    r = client.patch("/api/auth/me/preferences", json={
        "notification_preferences": {"work": False, "workflow": True, "system": True},
        "theme": "dark", "density": "compact",
    }, headers=admin_headers)
    assert r.json()["success"], r.text
    profile = client.get("/api/auth/me/profile", headers=admin_headers).json()["data"]
    assert profile["preferences"]["theme"] == "dark"
    assert profile["preferences"]["density"] == "compact"
    assert profile["preferences"]["notification_preferences"]["work"] is False

    with SessionLocal() as db:
        admin = db.query(AuthUser).filter(AuthUser.username == "admin").first()
        audit(db, "test_entity", admin.id, "m37_test", admin, {"safe": True})
        db.commit()
    data = client.get("/api/auth/me/audit-logs", headers=admin_headers).json()
    assert data["success"]
    assert any(x["action"] == "m37_test" for x in data["data"])


def test_feishu_unbind_requires_local_password(client, admin_headers):
    with SessionLocal() as db:
        admin = db.query(AuthUser).filter(AuthUser.username == "admin").first()
        admin.external_id = "ou_admin_test"
        admin.auth_source = "feishu"
        db.commit()
    r = client.delete("/api/auth/me/feishu-binding", headers=admin_headers)
    assert r.json()["success"], r.text
    with SessionLocal() as db:
        admin = db.query(AuthUser).filter(AuthUser.username == "admin").first()
        assert admin.external_id is None
        assert admin.auth_source == "local"


def test_preference_validation(client, admin_headers):
    r = client.patch("/api/auth/me/preferences", json={"theme": "neon"}, headers=admin_headers)
    assert r.status_code == 422
