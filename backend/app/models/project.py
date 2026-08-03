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
    # Project manager and creator are different responsibilities.  The latter is
    # needed for the first-node upstream correction window.
    created_by: Mapped[str | None] = mapped_column(String(26), comment="创建人 auth_user.id")
    pm: Mapped[str] = mapped_column(ForeignKey("org_member.id"), comment="项目经理")
    status: Mapped[str] = mapped_column(String(32), default="planning", index=True)
    planned_start: Mapped[date] = mapped_column(Date)
    planned_end: Mapped[date] = mapped_column(Date)
    actual_start: Mapped[date | None] = mapped_column(Date, comment="[计] 转进行中打点")
    actual_end: Mapped[date | None] = mapped_column(Date, comment="[计] 转已完成打点")
    portfolio_id: Mapped[str | None] = mapped_column(ForeignKey("portfolio.id"), index=True)
    service_item_id: Mapped[str | None] = mapped_column(ForeignKey("service_item.id"))
    budget_10k: Mapped[float | None] = mapped_column(Float, comment="预算(万元)")
    # 章程结构化字段（M13）：概述页分段展示，与章程模板章节一一对应
    background: Mapped[str | None] = mapped_column(Text, comment="项目背景（章程§1）")
    goals: Mapped[str | None] = mapped_column(Text, comment="项目目标（章程§3）")
    scope_in: Mapped[str | None] = mapped_column(Text, comment="范围-做什么（章程§4.1）")
    scope_out: Mapped[str | None] = mapped_column(Text, comment="范围-不做什么（章程§4.2）")
    resource_note: Mapped[str | None] = mapped_column(Text, comment="预算与资源说明（章程§6，金额在 budget_10k）")
    org_members: Mapped[list | None] = mapped_column(JsonCol, comment="主要成员 [{name,role,duty}]（章程§2）")
    stakeholders: Mapped[list | None] = mapped_column(JsonCol, comment="关键干系人 [{name,role,duty}]（章程§2）")
    description: Mapped[str | None] = mapped_column(Text, comment="[兼容] 其他说明/历史描述")
    latest_update: Mapped[str | None] = mapped_column(Text, comment="最新动态一句话")

    portfolio: Mapped[Portfolio | None] = relationship()


class WbsTask(GlidBase):
    __tablename__ = "wbs_task"

    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    parent_task_id: Mapped[str | None] = mapped_column(ForeignKey("wbs_task.id"))
    wbs_code: Mapped[str] = mapped_column(String(32), comment="[计] 层级编号 1/1.1/1.2.1，树位置自动生成")
    stage: Mapped[str | None] = mapped_column(String(64), comment="阶段，如 1.立项/2.选型")
    name: Mapped[str] = mapped_column(String(200), comment="任务名称(交付物)：名词性交付物命名")
    wbs_dict: Mapped[str | None] = mapped_column(Text, comment="WBS 词典说明（含/不含），厘清工作包边界")
    deliverable: Mapped[str | None] = mapped_column(String(500), comment="交付物/验收标准(DoD)")
    assignee: Mapped[str] = mapped_column(ForeignKey("org_member.id"), comment="责任人（唯一）")
    is_milestone: Mapped[bool] = mapped_column(default=False, comment="里程碑=是 的行汇总入里程碑跟踪")
    start_date: Mapped[date] = mapped_column(Date, comment="计划开始")
    end_date: Mapped[date] = mapped_column(Date, comment="计划结束")
    actual_start: Mapped[date | None] = mapped_column(Date, comment="实际开始")
    actual_end: Mapped[date | None] = mapped_column(Date, comment="实际结束")
    progress: Mapped[int] = mapped_column(Integer, default=0, comment="完成度%，0-100 的整数")
    # 进度偏差(天)=实际结束-计划结束、状态=据完成度与计划结束日判定，均在序列化时计算，不落库
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    remarks: Mapped[str | None] = mapped_column(Text, comment="备注")
    description: Mapped[str | None] = mapped_column(Text, comment="[兼容旧字段]")
    predecessor_ids: Mapped[list | None] = mapped_column(JsonCol, default=list, comment="前置任务 id 列表（前端按 WBS 号展示）")
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
