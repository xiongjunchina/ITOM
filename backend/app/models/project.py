"""项目域模型（docs/04 §3，PRD §6）：6 表，派生数据（进度/健康度/SPI/实际成本）全部计算不落库。"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GlidBase, JsonCol


class Portfolio(GlidBase):
    """项目组合：仅作项目分组（PRD §6.5）。"""

    __tablename__ = "portfolio"

    name: Mapped[str] = mapped_column(String(128), unique=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"))
    year: Mapped[str | None] = mapped_column(String(8), comment="年度，如 2026")
    description: Mapped[str | None] = mapped_column(Text)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Project(GlidBase):
    __tablename__ = "project"

    project_code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    pm: Mapped[str] = mapped_column(ForeignKey("org_member.id"), comment="项目经理")
    status: Mapped[str] = mapped_column(String(32), default="planning", index=True)
    planned_start: Mapped[date] = mapped_column(Date)
    planned_end: Mapped[date] = mapped_column(Date)
    actual_start: Mapped[date | None] = mapped_column(Date, comment="[计] 转进行中打点")
    actual_end: Mapped[date | None] = mapped_column(Date, comment="[计] 转已完成打点")
    portfolio_id: Mapped[str | None] = mapped_column(ForeignKey("portfolio.id"), index=True)
    service_item_id: Mapped[str | None] = mapped_column(ForeignKey("service_item.id"))
    budget_10k: Mapped[float | None] = mapped_column(Float, comment="预算(万元)")
    description: Mapped[str | None] = mapped_column(Text)
    latest_update: Mapped[str | None] = mapped_column(Text, comment="最新动态一句话")

    portfolio: Mapped[Portfolio | None] = relationship()


class WbsTask(GlidBase):
    __tablename__ = "wbs_task"

    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    parent_task_id: Mapped[str | None] = mapped_column(ForeignKey("wbs_task.id"))
    wbs_code: Mapped[str] = mapped_column(String(32), comment="[计] 树位置自动生成，如 1.2.1")
    name: Mapped[str] = mapped_column(String(200))
    assignee: Mapped[str] = mapped_column(ForeignKey("org_member.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="未开始", comment="未开始/进行中/已完成")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    description: Mapped[str | None] = mapped_column(Text)
    deliverable: Mapped[str | None] = mapped_column(String(200))
    predecessor_ids: Mapped[list | None] = mapped_column(JsonCol, default=list, comment="前置任务 id 列表")
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Milestone(GlidBase):
    __tablename__ = "milestone"

    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    target_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    achieved_at: Mapped[date | None] = mapped_column(Date)
    overdue_warned: Mapped[bool] = mapped_column(default=False, comment="逾期告警已发")


class Risk(GlidBase):
    __tablename__ = "risk"

    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    probability: Mapped[str] = mapped_column(String(8), comment="高/中/低")
    impact: Mapped[str] = mapped_column(String(8), comment="高/中/低")
    mitigation: Mapped[str | None] = mapped_column(Text, comment="应对措施")
    status: Mapped[str] = mapped_column(String(16), default="开放", comment="开放/已关闭")


class CostEntry(GlidBase):
    __tablename__ = "cost_entry"

    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    entry_date: Mapped[date] = mapped_column(Date)
    amount_10k: Mapped[float] = mapped_column(Float, comment="金额(万元)")
    note: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[str | None] = mapped_column(String(26))
