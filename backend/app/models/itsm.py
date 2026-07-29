"""ITSM 域模型 M2 部分（docs/04 §2.1-2.3, 2.8）。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GlidBase, JsonCol


class ServiceCatalog(GlidBase):
    __tablename__ = "service_catalog"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    tier: Mapped[str] = mapped_column(String(16), default="silver", comment="gold/silver/bronze")
    description: Mapped[str | None] = mapped_column(Text)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="上架", comment="上架/下架")


class ServiceItem(GlidBase):
    __tablename__ = "service_item"

    item_code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    catalog_id: Mapped[str] = mapped_column(ForeignKey("service_catalog.id"))
    service_type: Mapped[str | None] = mapped_column(String(32))
    owner: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"))
    description: Mapped[str | None] = mapped_column(Text)
    sla_response_hours: Mapped[float | None] = mapped_column(Float, comment="覆盖 SLA 策略，可空")
    sla_resolution_hours: Mapped[float | None] = mapped_column(Float)
    target_audience: Mapped[str | None] = mapped_column(String(128))
    target_audience_mode: Mapped[str] = mapped_column(String(16), default="all", comment="all/custom")
    target_audience_refs: Mapped[list | None] = mapped_column(
        JsonCol, default=list, comment="服务对象引用 [{type: department|member, id}]"
    )
    status: Mapped[str] = mapped_column(String(16), default="上架")

    catalog: Mapped[ServiceCatalog] = relationship()


class SlaPolicy(GlidBase):
    __tablename__ = "sla_policy"

    priority: Mapped[str] = mapped_column(String(8), unique=True, comment="P1-P4")
    response_minutes: Mapped[int] = mapped_column(Integer)
    resolution_hours: Mapped[float] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SlaPriorityDefinition(GlidBase):
    """P1-P4 优先级定义（M29）：按流程类型分别定义。seed ITIL/ServiceNow 风格初稿，管理员可编辑适配企业实际。"""

    __tablename__ = "sla_priority_definition"
    __table_args__ = (UniqueConstraint("flow_type", "priority"),)

    flow_type: Mapped[str] = mapped_column(String(32), comment="service_request/incident/change/problem")
    priority: Mapped[str] = mapped_column(String(8), comment="P1-P4")
    definition: Mapped[str] = mapped_column(Text, comment="级别定义")
    examples: Mapped[str | None] = mapped_column(Text, comment="典型示例")


class Ticket(GlidBase):
    __tablename__ = "ticket"
    __table_args__ = (Index("ix_ticket_type_status", "ticket_type", "status"),)

    ticket_code: Mapped[str] = mapped_column(String(32), unique=True)
    # 创建必填
    title: Mapped[str] = mapped_column(String(200))
    ticket_type: Mapped[str] = mapped_column(String(32), comment="incident/service_request/change")
    priority: Mapped[str] = mapped_column(String(8), index=True, comment="P1-P4")
    description: Mapped[str] = mapped_column(Text)
    service_item_id: Mapped[str] = mapped_column(ForeignKey("service_item.id"), index=True)
    # 服务请求表单兼容字段；历史工单允许为空
    service_category: Mapped[str | None] = mapped_column(String(128))
    other_info: Mapped[str | None] = mapped_column(Text)
    # 创建可选
    assignee: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), index=True)
    ci_id: Mapped[str | None] = mapped_column(String(26), comment="M3 接 CMDB 外键")
    remarks: Mapped[str | None] = mapped_column(Text)
    # 变更条件字段（仅 change）
    change_type: Mapped[str | None] = mapped_column(String(16), comment="标准/普通/紧急")
    risk_level: Mapped[str | None] = mapped_column(String(16), comment="高/中/低")
    change_reason: Mapped[str | None] = mapped_column(Text)
    rollback_plan: Mapped[str | None] = mapped_column(Text)
    planned_start_at: Mapped[datetime | None] = mapped_column(DateTime)
    planned_end_at: Mapped[datetime | None] = mapped_column(DateTime)
    implementation_plan: Mapped[str | None] = mapped_column(Text)
    # 阶段字段
    solution: Mapped[str | None] = mapped_column(Text, comment="解决时必填")
    root_cause: Mapped[str | None] = mapped_column(Text)
    closure_code: Mapped[str | None] = mapped_column(String(32), comment="关闭时必填")
    satisfaction: Mapped[int | None] = mapped_column(Integer, comment="1-5 星")
    # 审批 [计]
    approved_by: Mapped[str | None] = mapped_column(String(26))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    approval_comment: Mapped[str | None] = mapped_column(Text)
    # 派生 [计]
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    submitter: Mapped[str | None] = mapped_column(String(26), comment="auth_user.id")
    submitter_name: Mapped[str | None] = mapped_column(String(64))
    submitter_dept: Mapped[str | None] = mapped_column(String(64))
    service_line: Mapped[str | None] = mapped_column(String(64), comment="服务项带出")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    paused_minutes: Mapped[float] = mapped_column(Float, default=0, comment="挂起累计，SLA 扣除")
    paused_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0)
    first_time_fix: Mapped[bool | None] = mapped_column(Boolean)
    sla_response_min: Mapped[float | None] = mapped_column(Float)
    sla_resolution_hours: Mapped[float | None] = mapped_column(Float)
    actual_response_min: Mapped[float | None] = mapped_column(Float)
    actual_resolution_hours: Mapped[float | None] = mapped_column(Float)
    sla_response_met: Mapped[bool | None] = mapped_column(Boolean)
    sla_resolution_met: Mapped[bool | None] = mapped_column(Boolean)
    sla_warned: Mapped[bool] = mapped_column(Boolean, default=False, comment="临期升级已通知")
    # 关联
    problem_id: Mapped[str | None] = mapped_column(String(26), comment="M3 接问题外键")
    requirement_id: Mapped[str | None] = mapped_column(String(26), comment="M5 接需求外键")

    service_item: Mapped[ServiceItem] = relationship()
