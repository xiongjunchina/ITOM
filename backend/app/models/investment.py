"""B-OPS 统一 IT 投入账本。

项目、需求与运维共用预算、费用、实际工时和分摊事实。账本只保存管理
口径的角色标准费率快照，不保存或推导个人薪酬。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import GlidBase


class InvestmentBudgetItem(GlidBase):
    __tablename__ = "investment_budget_item"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_investment_budget_source"),
    )

    lifecycle_stage: Mapped[str] = mapped_column(
        String(16), index=True, comment="demand/build/run"
    )
    investment_intent: Mapped[str] = mapped_column(
        String(16), default="run", comment="run/grow/transform"
    )
    subject_type: Mapped[str] = mapped_column(String(32), index=True)
    subject_id: Mapped[str | None] = mapped_column(String(26), index=True)
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    cost_nature: Mapped[str] = mapped_column(String(8), default="opex", comment="capex/opex")
    name: Mapped[str] = mapped_column(String(128))
    amount_cny: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    note: Mapped[str | None] = mapped_column(String(500))
    source_type: Mapped[str | None] = mapped_column(String(32), index=True)
    source_id: Mapped[str | None] = mapped_column(String(26), index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("auth_user.id"))


class InvestmentCostEntry(GlidBase):
    __tablename__ = "investment_cost_entry"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_investment_cost_source"),
    )

    lifecycle_stage: Mapped[str] = mapped_column(String(16), index=True)
    investment_intent: Mapped[str] = mapped_column(String(16), default="run", index=True)
    subject_type: Mapped[str] = mapped_column(String(32), index=True)
    subject_id: Mapped[str | None] = mapped_column(String(26), index=True)
    recognition_date: Mapped[date] = mapped_column(Date, index=True)
    amount_cny: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    cost_status: Mapped[str] = mapped_column(
        String(16), index=True, comment="committed/incurred/paid"
    )
    category: Mapped[str] = mapped_column(String(32), index=True)
    cost_nature: Mapped[str] = mapped_column(String(8), default="opex", comment="capex/opex")
    labor_nature: Mapped[str] = mapped_column(
        String(16), default="none", comment="none/internal/external/unclassified"
    )
    recurrence: Mapped[str] = mapped_column(
        String(16), default="one_time", comment="one_time/recurring"
    )
    activity_type: Mapped[str | None] = mapped_column(String(32), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("project.id"), index=True)
    requirement_id: Mapped[str | None] = mapped_column(ForeignKey("requirement.id"), index=True)
    service_item_id: Mapped[str | None] = mapped_column(ForeignKey("service_item.id"), index=True)
    ci_id: Mapped[str | None] = mapped_column(ForeignKey("ci.id"), index=True)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("ticket.id"), index=True)
    problem_id: Mapped[str | None] = mapped_column(ForeignKey("problem.id"), index=True)
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contract.id"), index=True)
    vendor_id: Mapped[str | None] = mapped_column(ForeignKey("vendor.id"), index=True)
    wbs_task_id: Mapped[str | None] = mapped_column(ForeignKey("wbs_task.id"), index=True)
    supplier_snapshot: Mapped[str | None] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(String(500))
    source_type: Mapped[str | None] = mapped_column(String(32), index=True)
    source_id: Mapped[str | None] = mapped_column(String(26), index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("auth_user.id"))


class InvestmentWorklog(GlidBase):
    __tablename__ = "investment_worklog"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_investment_worklog_source"),
    )

    lifecycle_stage: Mapped[str] = mapped_column(String(16), index=True)
    investment_intent: Mapped[str] = mapped_column(String(16), default="run", index=True)
    subject_type: Mapped[str] = mapped_column(String(32), index=True)
    subject_id: Mapped[str | None] = mapped_column(String(26), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("org_member.id"), index=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    effort_days: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    role_type: Mapped[str] = mapped_column(String(32), index=True)
    activity_type: Mapped[str] = mapped_column(String(32), index=True)
    standard_rate_cny_per_day: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("project.id"), index=True)
    requirement_id: Mapped[str | None] = mapped_column(ForeignKey("requirement.id"), index=True)
    service_item_id: Mapped[str | None] = mapped_column(ForeignKey("service_item.id"), index=True)
    ci_id: Mapped[str | None] = mapped_column(ForeignKey("ci.id"), index=True)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("ticket.id"), index=True)
    problem_id: Mapped[str | None] = mapped_column(ForeignKey("problem.id"), index=True)
    wbs_task_id: Mapped[str | None] = mapped_column(ForeignKey("wbs_task.id"), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(String(32), index=True)
    source_id: Mapped[str | None] = mapped_column(String(26), index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("auth_user.id"))


class InvestmentAllocation(GlidBase):
    __tablename__ = "investment_allocation"
    __table_args__ = (
        UniqueConstraint(
            "source_kind", "source_id", "target_type", "target_id",
            name="uq_investment_allocation_target",
        ),
    )

    source_kind: Mapped[str] = mapped_column(String(16), index=True, comment="budget/cost/worklog")
    source_id: Mapped[str] = mapped_column(String(26), index=True)
    target_type: Mapped[str] = mapped_column(String(32), index=True)
    target_id: Mapped[str] = mapped_column(String(26), index=True)
    percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    allocation_method: Mapped[str] = mapped_column(String(24), default="manual_percentage")
    note: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("auth_user.id"))
