"""M44 系统集成全局配置与密钥保护。"""
from app.db import SessionLocal
from app.models import SystemIntegrationConfig


def test_email_and_ldap_secrets_are_encrypted_and_masked(client, admin_headers):
    email = client.put("/api/admin/integrations/email", headers=admin_headers, json={
        "enabled": True, "host": "smtp.example.com", "port": 587,
        "username": "svc@example.com", "password": "smtp-secret",
        "from_email": "svc@example.com", "from_name": "ITOM", "use_tls": True,
    })
    assert email.status_code == 200 and email.json()["data"]["has_secret"] is True
    assert "password" not in email.json()["data"]

    ldap = client.put("/api/admin/integrations/ldap", headers=admin_headers, json={
        "enabled": True, "server_url": "ldap.example.com", "bind_dn": "cn=svc,dc=example,dc=com",
        "bind_password": "ldap-secret", "base_dn": "dc=example,dc=com",
        "user_dn_template": "{username}@example.com", "use_ssl": False,
    })
    assert ldap.status_code == 200 and ldap.json()["data"]["has_secret"] is True
    with SessionLocal() as db:
        row = db.query(SystemIntegrationConfig).first()
        assert "smtp-secret" not in str(row.email_config)
        assert "ldap-secret" not in str(row.ldap_config)


def test_ldap_login_fallback_for_existing_itom_user(client, admin_headers, monkeypatch):
    client.post("/api/admin/users", headers=admin_headers, json={
        "username": "ad.user", "password": "local123", "roles": ["requester"],
    })
    monkeypatch.setattr("app.services.ldap_auth.authenticate_ldap", lambda _db, username, password: username == "ad.user" and password == "domain-pass")
    response = client.post("/api/auth/login", json={"username": "ad.user", "password": "domain-pass"})
    assert response.status_code == 200
    assert response.json()["data"]["user"]["auth_source"] == "ad"
