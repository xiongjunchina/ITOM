from datetime import datetime

from app.db import SessionLocal
from app.events import notifier
from app.models import (
    AilyIntegrationConfig,
    AuthUser,
    ExternalIdentity,
    FeishuConfig,
    InAppNotification,
    NotificationOutbox,
    OrgMember,
)
from app.services.aily import (
    deliver_aily_outbox_row,
    find_aily_identity,
    sync_aily_notification_identity,
)
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


def test_notification_waits_for_aily_identity_then_delivers(client, admin_headers, monkeypatch):
    """账号尚未映射时不静默丢弃；补齐映射后由原发件箱记录发送。"""
    user_id = None
    tenant_id = "tenant-pending-identity"
    subject_id = "on_pending_identity"
    with SessionLocal() as db:
        user = AuthUser(
            username="pending-aily-notification-user",
            password_hash="unused",
            auth_source="feishu",
            external_id="login-open-pending",
            roles=[],
        )
        db.add(user)
        db.flush()
        user_id = user.id
        config = db.query(AilyIntegrationConfig).filter(
            AilyIntegrationConfig.is_deleted.is_(False)
        ).first()
        config.enabled = True
        config.message_enabled = True
        config.bot_app_id = "cli_pending_identity"
        config.bot_app_secret_encrypted = encrypt_secret("pending-identity-secret")
        config.allowed_tenant_ids = [tenant_id]
        db.commit()

    event = {
        "event_type": "process.task_assigned",
        "entity_type": "ticket",
        "entity_id": "tk-pending-aily-identity",
        "title": "新的待办任务",
        "content": "请及时处理。",
        "link": "/tickets/tk-pending-aily-identity",
    }
    with SessionLocal() as db:
        notifier.notify(db, recipients=[user_id], **event)
        db.commit()
        row = db.query(NotificationOutbox).filter(
            NotificationOutbox.channel == "feishu_aily",
            NotificationOutbox.entity_id == event["entity_id"],
        ).one()
        row_id = row.id
        assert row.status == "pending"
        assert row.recipient_id is None
        assert row.last_error_redacted == "AILY_IDENTITY_NOT_MAPPED"
        assert row.payload["auth_user_id"] == user_id

    with SessionLocal() as db:
        row = db.get(NotificationOutbox, row_id)
        deliver_aily_outbox_row(db, row)
        db.commit()
        assert row.status == "pending"
        assert row.attempt_count == 0
        assert row.last_error_redacted == "AILY_IDENTITY_NOT_MAPPED"
        db.add(ExternalIdentity(
            provider="feishu",
            tenant_id=tenant_id,
            app_id="aily-agent-pending",
            subject_type="open_id",
            subject_id=subject_id,
            auth_user_id=user_id,
            status="active",
        ))
        db.commit()

    calls = []
    monkeypatch.setattr(
        FeishuClient,
        "send_app_text",
        lambda self, recipient_id, recipient_type, text: calls.append(
            (recipient_id, recipient_type, text)
        ) or "om_pending_identity",
    )
    with SessionLocal() as db:
        row = db.get(NotificationOutbox, row_id)
        deliver_aily_outbox_row(db, row)
        db.commit()
        assert row.status == "sent"
        assert row.recipient_type == "open_id"
        assert row.recipient_id == subject_id
    assert calls and calls[0][0:2] == (subject_id, "open_id")


def test_feishu_oauth_identity_auto_maps_notification_user_id_without_mcp_tenant_match(
    client,
    admin_headers,
):
    """OAuth 租户标识不与 MCP 入站白名单混用，优先保存跨应用 user_id。"""
    oauth_tenant_id = "oauth-tenant-auto-map"
    with SessionLocal() as db:
        admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
        config = db.query(AilyIntegrationConfig).filter(
            AilyIntegrationConfig.is_deleted.is_(False)
        ).first()
        config.enabled = True
        config.bot_app_id = "cli_auto_map"
        config.allowed_tenant_ids = ["aily-jwt-tenant-not-oauth-tenant"]
        result = sync_aily_notification_identity(
            db,
            user=admin,
            feishu_info={
                "tenant_key": oauth_tenant_id,
                "user_id": "u_auto_map",
                "union_id": "on_auto_map",
            },
        )
        db.commit()
        assert result == "mapped"
        row = db.query(ExternalIdentity).filter(
            ExternalIdentity.tenant_id == oauth_tenant_id,
            ExternalIdentity.app_id == "cli_auto_map",
            ExternalIdentity.subject_type == "user_id",
            ExternalIdentity.subject_id == "u_auto_map",
        ).one()
        assert row.auth_user_id == admin.id
        assert row.status == "active"
        resolved = find_aily_identity(db, auth_user_id=admin.id, cfg=config)
        assert resolved is not None
        assert resolved.id == row.id


def test_feishu_oauth_identity_auto_maps_union_id_when_user_id_is_unavailable(
    client,
    admin_headers,
):
    """缺少 user_id 时仍可使用同开发商应用间稳定的 union_id。"""
    with SessionLocal() as db:
        admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
        config = db.query(AilyIntegrationConfig).filter(
            AilyIntegrationConfig.is_deleted.is_(False)
        ).first()
        config.enabled = True
        config.bot_app_id = "cli_auto_map_union_fallback"
        config.allowed_tenant_ids = ["aily-jwt-tenant-unrelated"]
        result = sync_aily_notification_identity(
            db,
            user=admin,
            feishu_info={
                "tenant_key": "oauth-tenant-union-fallback",
                "union_id": "on_auto_map_fallback",
            },
        )
        db.commit()
        assert result == "mapped"
        row = db.query(ExternalIdentity).filter(
            ExternalIdentity.app_id == "cli_auto_map_union_fallback",
            ExternalIdentity.subject_type == "union_id",
            ExternalIdentity.subject_id == "on_auto_map_fallback",
        ).one()
        assert row.auth_user_id == admin.id
        resolved = find_aily_identity(db, auth_user_id=admin.id, cfg=config)
        assert resolved is not None
        assert resolved.id == row.id


def test_feishu_oauth_auto_map_does_not_bypass_disabled_bot_identity(
    client,
    admin_headers,
):
    """管理员停用同租户/机器人映射后，标识类型变化也不能自动绕过。"""
    with SessionLocal() as db:
        admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
        config = db.query(AilyIntegrationConfig).filter(
            AilyIntegrationConfig.is_deleted.is_(False)
        ).first()
        config.enabled = True
        config.bot_app_id = "cli_disabled_auto_map"
        config.allowed_tenant_ids = ["aily-jwt-tenant-unrelated-disabled"]
        db.add(ExternalIdentity(
            provider="feishu",
            tenant_id="oauth-tenant-disabled",
            app_id=config.bot_app_id,
            subject_type="union_id",
            subject_id="on_disabled_auto_map",
            auth_user_id=admin.id,
            status="disabled",
        ))
        db.flush()

        result = sync_aily_notification_identity(
            db,
            user=admin,
            feishu_info={
                "tenant_key": "oauth-tenant-disabled",
                "user_id": "u_disabled_auto_map",
                "union_id": "on_disabled_auto_map",
            },
        )
        db.commit()
        assert result == "disabled"
        assert db.query(ExternalIdentity).filter(
            ExternalIdentity.app_id == config.bot_app_id,
            ExternalIdentity.subject_type == "user_id",
            ExternalIdentity.subject_id == "u_disabled_auto_map",
        ).count() == 0


def test_pending_notification_auto_maps_from_synced_org_after_verified_oauth_anchor(
    client,
    admin_headers,
    monkeypatch,
):
    """一个可信 OAuth 租户锚点建立后，其他同步员工无需逐人登录或手工绑定。"""
    tenant_id = "oauth-tenant-org-reconcile"
    bot_app_id = "cli_org_reconcile_bot"
    login_open_id = "ou_login_app_target"
    target_user_id = "u_org_reconcile_target"
    with SessionLocal() as db:
        admin = db.query(AuthUser).filter(AuthUser.username == "admin").one()
        config = db.query(AilyIntegrationConfig).filter(
            AilyIntegrationConfig.is_deleted.is_(False)
        ).first()
        config.enabled = True
        config.message_enabled = True
        config.bot_app_id = bot_app_id
        config.bot_app_secret_encrypted = encrypt_secret("org-reconcile-bot-secret")
        config.allowed_tenant_ids = ["unrelated-aily-jwt-tenant"]
        assert sync_aily_notification_identity(
            db,
            user=admin,
            feishu_info={
                "tenant_key": tenant_id,
                "user_id": "u_verified_anchor",
                "union_id": "on_verified_anchor",
            },
        ) == "mapped"

        feishu_config = db.query(FeishuConfig).filter(FeishuConfig.is_deleted.is_(False)).first()
        if not feishu_config:
            feishu_config = FeishuConfig()
            db.add(feishu_config)
        feishu_config.enabled = True
        feishu_config.app_id = "cli_login_org_app"
        feishu_config.app_secret = "login-org-secret"

        member = OrgMember(
            name="自动映射目标员工",
            status="在岗",
            external_source="feishu",
            external_id=login_open_id,
        )
        db.add(member)
        db.flush()
        target = AuthUser(
            username="org-reconcile-notification-user",
            password_hash="unused",
            auth_source="feishu",
            external_id=login_open_id,
            person_id=member.id,
            roles=[],
        )
        db.add(target)
        db.flush()
        row = NotificationOutbox(
            event_type="work_task.assigned",
            entity_type="work_task",
            entity_id="wt-org-reconcile",
            payload={"text": "您有新的委派任务", "auth_user_id": target.id},
            channel="feishu_aily",
            status="pending",
            idempotency_key="work-task-org-reconcile-target",
            attempt_count=0,
            last_error_redacted="AILY_IDENTITY_NOT_MAPPED",
        )
        db.add(row)
        db.commit()
        row_id = row.id
        target_auth_user_id = target.id

    lookups = []
    deliveries = []
    monkeypatch.setattr(FeishuClient, "tenant_access_token", lambda self: "tenant-token")
    monkeypatch.setattr(
        FeishuClient,
        "get_user",
        lambda self, token, subject, user_id_type="open_id": lookups.append(
            (token, subject, user_id_type)
        ) or {
            "user_id": target_user_id,
            "union_id": "on_org_reconcile_target",
        },
    )
    monkeypatch.setattr(
        FeishuClient,
        "send_app_text",
        lambda self, recipient_id, recipient_type, text: deliveries.append(
            (recipient_id, recipient_type, text)
        ) or "om_org_reconcile",
    )

    with SessionLocal() as db:
        row = db.get(NotificationOutbox, row_id)
        deliver_aily_outbox_row(db, row)
        db.commit()
        assert row.status == "sent"
        assert row.recipient_type == "user_id"
        assert row.recipient_id == target_user_id
        identity = db.query(ExternalIdentity).filter(
            ExternalIdentity.tenant_id == tenant_id,
            ExternalIdentity.app_id == bot_app_id,
            ExternalIdentity.subject_type == "user_id",
            ExternalIdentity.subject_id == target_user_id,
        ).one()
        assert identity.auth_user_id == target_auth_user_id
        assert identity.status == "active"

    assert lookups == [("tenant-token", login_open_id, "open_id")]
    assert deliveries and deliveries[0][0:2] == (target_user_id, "user_id")
