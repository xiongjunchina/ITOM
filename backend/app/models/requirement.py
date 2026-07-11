"""需求域模型（docs/04 §4，PRD §7）：轻量协同四阶段，2 表。"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GlidBase, JsonCol


class Requirement(GlidBase):
    __tablename__ = "requirement"

    requirement_code: Mapped[str] = mapped_column(String(32), unique=True)
    # 登记（4 必填 + 来源可选）
    title: Mapped[str] = mapped_column(String(200))
    req_type: Mapped[str] = mapped_column(String(16), comment="业务/功能/数据/集成/合规")
    business_domain_id: Mapped[str] = mapped_column(ForeignKey("business_domain.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(32), comment="需求来源(字典)")
    requester: Mapped[str | None] = mapped_column(String(26), comment="提出人 auth_user.id")
    requester_name: Mapped[str | None] = mapped_column(String(64))
    # 分析阶段
    moscow: Mapped[str | None] = mapped_column(String(2), comment="M/S/C/W")
    owner: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), comment="负责人")
    target_date: Mapped[date | None] = mapped_column(Date, comment="排期目标日期")
    solution: Mapped[str | None] = mapped_column(Text, comment="解决方案")
    acceptance_criteria: Mapped[list | None] = mapped_column(JsonCol, default=list, comment="[{text, checked}]")
    # 实现阶段
    project_id: Mapped[str | None] = mapped_column(ForeignKey("project.id"), index=True)
    # 派生/打点
    status: Mapped[str] = mapped_column(String(32), default="registered", index=True)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime)
    analyzing_at: Mapped[datetime | None] = mapped_column(DateTime)
    implementing_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    closure_note: Mapped[str | None] = mapped_column(Text, comment="关闭说明/遗留说明")
    parent_requirement_id: Mapped[str | None] = mapped_column(ForeignKey("requirement.id"))
    remarks: Mapped[str | None] = mapped_column(Text)


class RequirementTask(GlidBase):
    __tablename__ = "requirement_task"

    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirement.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    assignee: Mapped[str] = mapped_column(ForeignKey("org_member.id"))
    plan_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="待处理", comment="待处理/进行中/已完成")
    done_at: Mapped[datetime | None] = mapped_column(DateTime)
