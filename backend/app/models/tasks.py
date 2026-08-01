"""任务管理域模型：Bug 修复与非项目级委派任务。

需求开发任务继续使用 :class:`RequirementTask`，本模块不复用 ITIL
``Problem``，避免改变现有问题管理单据的字段和流程语义。
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import GlidBase


class Bug(GlidBase):
    """开发团队登记的缺陷单，流程由 Bug 专用流程定义驱动。"""

    __tablename__ = "bug"

    bug_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(8), default="P2", index=True)
    status: Mapped[str] = mapped_column(String(32), default="registered", index=True)
    ci_id: Mapped[str | None] = mapped_column(ForeignKey("ci.id"), index=True)
    product_manager_id: Mapped[str | None] = mapped_column(
        ForeignKey("org_member.id"), comment="登记时从所属系统解析并快照的产品经理"
    )
    dev_leader_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"))
    reporter_id: Mapped[str | None] = mapped_column(String(26), comment="登记人 auth_user.id")
    source_type: Mapped[str | None] = mapped_column(String(32))
    source_id: Mapped[str | None] = mapped_column(String(26))
    reproduction: Mapped[str | None] = mapped_column(Text, comment="复现步骤/条件")
    expected_result: Mapped[str | None] = mapped_column(Text)
    actual_result: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(String(64))
    evidence: Mapped[str | None] = mapped_column(Text)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    verification_note: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)


class BugFixTask(GlidBase):
    """Bug 确认后由开发负责人拆出的开发、测试或辅助任务。"""

    __tablename__ = "bug_fix_task"

    bug_id: Mapped[str] = mapped_column(ForeignKey("bug.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    task_type: Mapped[str] = mapped_column(String(16), default="开发")
    description: Mapped[str | None] = mapped_column(Text)
    assignee: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), index=True)
    plan_start: Mapped[date | None] = mapped_column(Date)
    plan_date: Mapped[date | None] = mapped_column(Date)
    plan_effort: Mapped[float | None] = mapped_column(Float)
    actual_effort: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="登记", index=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime)
    completion_note: Mapped[str | None] = mapped_column(Text)


class WorkTask(GlidBase):
    """非项目级委派任务，支持来源关联但不强制外键到具体业务域。"""

    __tablename__ = "work_task"

    task_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(String(32), default="其他", index=True)
    source_type: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    source_id: Mapped[str | None] = mapped_column(String(26), index=True)
    registrar: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"))
    assignee: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), index=True)
    priority: Mapped[str] = mapped_column(String(8), default="P3")
    plan_start: Mapped[date | None] = mapped_column(Date)
    plan_date: Mapped[date | None] = mapped_column(Date)
    plan_effort: Mapped[float | None] = mapped_column(Float)
    actual_effort: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="登记", index=True)
    performance_bucket: Mapped[str] = mapped_column(
        String(24), default="role_result", comment="role_result/team_contribution"
    )
    pause_reason: Mapped[str | None] = mapped_column(Text)
    abort_reason: Mapped[str | None] = mapped_column(Text)
    completion_note: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
