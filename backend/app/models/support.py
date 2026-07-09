"""支撑域模型（docs/04 §1）+ 岗位表（人员主数据依赖）。"""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GlidBase, JsonCol


class Position(GlidBase):
    __tablename__ = "position"

    name: Mapped[str] = mapped_column(String(64))
    duties: Mapped[str | None] = mapped_column(Text, comment="分工职责")
    headcount: Mapped[int] = mapped_column(Integer, default=0, comment="编制数")


class OrgMember(GlidBase):
    __tablename__ = "org_member"

    name: Mapped[str] = mapped_column(String(64))
    dept: Mapped[str | None] = mapped_column(String(64))
    team: Mapped[str | None] = mapped_column(String(64))
    position_id: Mapped[str | None] = mapped_column(ForeignKey("position.id"))
    status: Mapped[str] = mapped_column(String(16), default="在岗", comment="在岗/离职")
    hire_date: Mapped[date | None] = mapped_column(Date)
    email: Mapped[str | None] = mapped_column(String(128))
    feishu_user_id: Mapped[str | None] = mapped_column(String(64), comment="飞书集成预留")
    skills: Mapped[list | None] = mapped_column(JsonCol, default=list)
    remarks: Mapped[str | None] = mapped_column(Text)

    position: Mapped[Position | None] = relationship()


class AuthUser(GlidBase):
    __tablename__ = "auth_user"

    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    person_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"))
    roles: Mapped[list] = mapped_column(JsonCol, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    person: Mapped[OrgMember | None] = relationship()


class WorkflowStatus(GlidBase):
    __tablename__ = "workflow_status"

    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    is_initial: Mapped[bool] = mapped_column(Boolean, default=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class WorkflowTransition(GlidBase):
    __tablename__ = "workflow_transition"

    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    from_code: Mapped[str] = mapped_column(String(32))
    to_code: Mapped[str] = mapped_column(String(32))
    allowed_roles: Mapped[list | None] = mapped_column(JsonCol, default=list, comment="空=不限角色")


class MasterData(GlidBase):
    __tablename__ = "master_data"

    category: Mapped[str] = mapped_column(String(64), index=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditLog(GlidBase):
    __tablename__ = "audit_log"

    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(26), index=True)
    action: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str | None] = mapped_column(String(26), comment="auth_user.id")
    actor_name: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[dict | None] = mapped_column(JsonCol)


class NotificationOutbox(GlidBase):
    __tablename__ = "notification_outbox"

    event_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(26))
    payload: Mapped[dict | None] = mapped_column(JsonCol)
    channel: Mapped[str] = mapped_column(String(16), default="in_app", comment="in_app/feishu…")
    status: Mapped[str] = mapped_column(String(16), default="pending", comment="pending/sent/failed")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class InAppNotification(GlidBase):
    __tablename__ = "in_app_notification"

    recipient: Mapped[str] = mapped_column(ForeignKey("org_member.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(200), comment="前端路由")
    read_at: Mapped[datetime | None] = mapped_column(DateTime)


class Attachment(GlidBase):
    __tablename__ = "attachment"

    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(26), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[str | None] = mapped_column(String(26))
