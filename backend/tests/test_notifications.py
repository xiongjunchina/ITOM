from datetime import datetime

from app.db import SessionLocal
from app.events import notifier
from app.models import (
    AilyIntegrationConfig,
    AuthUser,
    ExternalIdentity,
    InAppNotification,
    NotificationOutbox,
)
from app.services.aily import deliver_aily_outbox_row
from app.services.feishu import FeishuClient
from app.services.secrets_store import encrypt_secret


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


def test_generic_notification_is_queued_to_feishu_and_deduplicated(client, admin_headers, monkeypatch):
    admin = client.get("/api/auth/me", headers=admin_headers).json()["data"]
    tenant_id = "tenant-generic-notification"
    subject_id = "ou_generic_notification_admin"

    db = SessionLocal()
    try:
        user = db.get(AuthUser, admin["id"])
        config = db.query(AilyIntegrationConfig).filter(
            AilyIntegrationConfig.is_deleted.is_(False)
        ).first()
        if not config:
            config = AilyIntegrationConfig()
            db.add(config)
        config.enabled = True
        config.message_enabled = True
        config.bot_app_id = "cli_generic_notification"
        config.bot_app_secret_encrypted = encrypt_secret("generic-notification-secret")
        config.allowed_tenant_ids = [tenant_id]
        config.public_base_url = "https://itom.example.test"
        db.add(ExternalIdentity(
            provider="feishu",
            tenant_id=tenant_id,
            app_id="agent-generic-notification",
            subject_type="open_id",
            subject_id=subject_id,
            auth_user_id=user.id,
            status="active",
        ))
        db.commit()
    finally:
        db.close()

    event = {
        "event_type": "requirement.task_assigned",
        "entity_type": "requirement",
        "entity_id": "rq-generic-notification",
        "title": "新的需求开发任务",
        "content": "请在今天完成任务排期。",
        "link": "/requirements/rq-generic-notification",
    }
    with SessionLocal() as db:
        notifier.notify(db, recipients=[admin["id"]], **event)
        db.commit()
        rows = db.query(NotificationOutbox).filter(
            NotificationOutbox.channel == "feishu_aily",
            NotificationOutbox.event_type == event["event_type"],
            NotificationOutbox.entity_id == event["entity_id"],
        ).all()
        assert len(rows) == 1
        row_id = rows[0].id
        assert rows[0].status == "pending"
        assert rows[0].recipient_type == "open_id"
        assert rows[0].recipient_id == subject_id
        assert "新的需求开发任务" in rows[0].payload["text"]
        assert "https://itom.example.test/requirements/rq-generic-notification" in rows[0].payload["text"]
        assert db.query(InAppNotification).filter(
            InAppNotification.recipient == admin["id"],
            InAppNotification.title == event["title"],
        ).count() == 1

    with SessionLocal() as db:
        notifier.notify(db, recipients=[admin["id"]], **event)
        db.commit()
        assert db.query(NotificationOutbox).filter(
            NotificationOutbox.channel == "feishu_aily",
            NotificationOutbox.event_type == event["event_type"],
            NotificationOutbox.entity_id == event["entity_id"],
        ).count() == 1

    calls = []
    monkeypatch.setattr(
        FeishuClient,
        "send_app_text",
        lambda self, recipient_id, recipient_type, text: calls.append(
            (recipient_id, recipient_type, text)
        ) or "om_generic_notification",
    )
    with SessionLocal() as db:
        row = db.get(NotificationOutbox, row_id)
        deliver_aily_outbox_row(db, row)
        db.commit()
        assert row.status == "sent"
        assert row.provider_message_id == "om_generic_notification"
    assert calls and calls[0][0:2] == (subject_id, "open_id")

    with SessionLocal() as db:
        notifier.notify(
            db,
            event_type="ticket.resolved",
            entity_type="ticket",
            entity_id="tk-generic-resolution-card",
            recipients=[admin["id"]],
            title="服务请求已解决",
            content="该通知由专用交互卡片发送。",
        )
        db.commit()
        assert db.query(NotificationOutbox).filter(
            NotificationOutbox.channel == "feishu_aily",
            NotificationOutbox.event_type == "ticket.resolved",
            NotificationOutbox.entity_id == "tk-generic-resolution-card",
        ).count() == 0
