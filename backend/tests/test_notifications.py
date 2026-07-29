from datetime import datetime

from app.db import SessionLocal
from app.models import InAppNotification


def test_mark_all_notifications_read_is_scoped_to_current_user(client, admin_headers):
    admin = client.get("/api/auth/me", headers=admin_headers).json()["data"]
    db = SessionLocal()
    try:
        db.add_all([
            InAppNotification(recipient=admin["id"], title="批量已读测试1", content="未读"),
            InAppNotification(recipient=admin["id"], title="批量已读测试2", content="未读"),
            InAppNotification(recipient="another-recipient", title="不应被修改", content="仍未读"),
        ])
        db.commit()
    finally:
        db.close()

    response = client.post("/api/notifications/read-all", headers=admin_headers)
    assert response.json()["success"]
    assert response.json()["data"]["updated"] >= 2

    notifications = client.get("/api/notifications", headers=admin_headers).json()["data"]
    assert all(item["read_at"] for item in notifications)

    db = SessionLocal()
    try:
        other = db.query(InAppNotification).filter(InAppNotification.recipient == "another-recipient").one()
        assert other.read_at is None
    finally:
        db.close()


def test_clear_read_notifications_soft_deletes_only_read_rows(client, admin_headers):
    admin = client.get("/api/auth/me", headers=admin_headers).json()["data"]
    other_recipient = "another-recipient-clear-read"
    db = SessionLocal()
    try:
        db.add_all([
            InAppNotification(recipient=admin["id"], title="可清除", content="已读", read_at=datetime.now()),
            InAppNotification(recipient=admin["id"], title="应保留", content="未读"),
            InAppNotification(recipient=other_recipient, title="其他账号已读", content="不应清除", read_at=datetime.now()),
        ])
        db.commit()
    finally:
        db.close()

    response = client.post("/api/notifications/clear-read", headers=admin_headers)
    assert response.json()["success"]
    assert response.json()["data"]["deleted"] >= 1

    notifications = client.get("/api/notifications", headers=admin_headers).json()["data"]
    assert any(item["title"] == "应保留" and item["read_at"] is None for item in notifications)
    assert not any(item["title"] == "可清除" for item in notifications)

    db = SessionLocal()
    try:
        other = db.query(InAppNotification).filter(InAppNotification.recipient == other_recipient).one()
        assert other.is_deleted is False
    finally:
        db.close()
