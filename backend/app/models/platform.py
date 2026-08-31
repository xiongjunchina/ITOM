"""平台产品运营 P0 增量模型。

ServiceItem 与 Requirement 继续是服务和需求的唯一主记录；本文件仅保存
可选管理档案、版本化容量计划和正式承诺。
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import GlidBase, JsonCol


class PlatformServiceProfile(GlidBase):
    __tablename__ = "platform_service_profile"
    __table_args__ = (
        UniqueConstraint("service_item_id", name="uq_platform_service_profile_item"),
        CheckConstraint(
            "lifecycle IN ('candidate','pilot','active','retiring','retired')",
            name="ck_platform_service_profile_lifecycle",
        ),
    )

    service_item_id: Mapped[str] = mapped_column(ForeignKey("service_item.id"), index=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), index=True)
    lifecycle: Mapped[str] = mapped_column(String(16), default="candidate", index=True)
    value_proposition: Mapped[str | None] = mapped_column(Text)
    management_scope: Mapped[dict | None] = mapped_column(JsonCol, default=dict)
    enabled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    created_by: Mapped[str] = mapped_column(ForeignKey("auth_user.id"))
    updated_by: Mapped[str] = mapped_column(ForeignKey("auth_user.id"))


class PlatformDemandProfile(GlidBase):
    __tablename__ = "platform_demand_profile"
    __table_args__ = (
        UniqueConstraint("requirement_id", name="uq_platform_demand_profile_requirement"),
        CheckConstraint(
            "demand_class IN ('business','product','technology','reliability','compliance')",
            name="ck_platform_demand_profile_class",
        ),
        CheckConstraint(
            "capacity_class IN ('small','medium','large','expedite')",
            name="ck_platform_demand_profile_capacity_class",
        ),
    )

    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirement.id"), index=True)
    service_item_id: Mapped[str] = mapped_column(ForeignKey("service_item.id"), index=True)
    business_domain_id: Mapped[str] = mapped_column(ForeignKey("business_domain.id"), index=True)
    demand_class: Mapped[str] = mapped_column(String(24), index=True)
    expected_outcome: Mapped[str] = mapped_column(Text)
    target_quarter: Mapped[str] = mapped_column(String(7), index=True, comment="YYYY-Q1..Q4")
    capacity_class: Mapped[str] = mapped_column(String(16), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("auth_user.id"))
    updated_by: Mapped[str] = mapped_column(ForeignKey("auth_user.id"))


class PlatformCapacityPlan(GlidBase):
    __tablename__ = "platform_capacity_plan"
    __table_args__ = (
        UniqueConstraint("service_item_id", "period", "version", name="uq_platform_capacity_plan_version"),
        UniqueConstraint("created_by", "idempotency_key", name="uq_platform_capacity_plan_idempotency"),
        CheckConstraint(
            "status IN ('draft','review','approved','superseded')",
            name="ck_platform_capacity_plan_status",
        ),
        CheckConstraint(
            "gross_days >= 0 AND planned_unavailable_days >= 0 AND bau_reserve_days >= 0 "
            "AND risk_buffer_days >= 0 AND net_days >= 0",
            name="ck_platform_capacity_plan_nonnegative",
        ),
    )

    service_item_id: Mapped[str] = mapped_column(ForeignKey("service_item.id"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True, comment="YYYY-Q1..Q4")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    gross_days: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    planned_unavailable_days: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    bau_reserve_days: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    risk_buffer_days: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    net_days: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("auth_user.id"), index=True)
    updated_by: Mapped[str] = mapped_column(ForeignKey("auth_user.id"))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("auth_user.id"))
    approval_reason: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_digest: Mapped[str] = mapped_column(String(64))
    previous_version_id: Mapped[str | None] = mapped_column(ForeignKey("platform_capacity_plan.id"))


class PlatformCapacityCommitment(GlidBase):
    __tablename__ = "platform_capacity_commitment"
    __table_args__ = (
        UniqueConstraint("created_by", "idempotency_key", name="uq_platform_commitment_idempotency"),
        CheckConstraint(
            "commitment_type IN ('demand','roadmap','reliability','enablement')",
            name="ck_platform_commitment_type",
        ),
        CheckConstraint(
            "lifecycle_stage IN ('demand','build','run')",
            name="ck_platform_commitment_lifecycle",
        ),
        CheckConstraint(
            "investment_intent IN ('run','grow','transform')",
            name="ck_platform_commitment_intent",
        ),
        CheckConstraint(
            "status IN ('planned','active','completed','cancelled')",
            name="ck_platform_commitment_status",
        ),
        CheckConstraint(
            "subject_type IN ('requirement','roadmap','reliability','enablement')",
            name="ck_platform_commitment_subject_type",
        ),
        CheckConstraint("capacity_days > 0", name="ck_platform_commitment_positive_days"),
    )

    plan_id: Mapped[str] = mapped_column(ForeignKey("platform_capacity_plan.id"), index=True)
    subject_type: Mapped[str] = mapped_column(String(24), index=True)
    subject_id: Mapped[str | None] = mapped_column(String(26), index=True)
    title: Mapped[str] = mapped_column(String(200))
    commitment_type: Mapped[str] = mapped_column(String(24), index=True)
    capacity_days: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    lifecycle_stage: Mapped[str] = mapped_column(String(16))
    investment_intent: Mapped[str] = mapped_column(String(16))
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"))
    status: Mapped[str] = mapped_column(String(16), default="planned", index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("auth_user.id"))
    updated_by: Mapped[str] = mapped_column(ForeignKey("auth_user.id"))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_digest: Mapped[str] = mapped_column(String(64))
    over_capacity_reason: Mapped[str | None] = mapped_column(Text)
    over_capacity_approved_by: Mapped[str | None] = mapped_column(ForeignKey("auth_user.id"))
    over_capacity_approved_at: Mapped[datetime | None] = mapped_column(DateTime)
