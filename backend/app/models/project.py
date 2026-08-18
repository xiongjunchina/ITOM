"""项目域模型（docs/04 §3，PRD §6）：6 表，派生数据（进度/健康度/SPI/实际成本）全部计算不落库。"""
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GlidBase, JsonCol


class Portfolio(GlidBase):
    """项目组合治理主体；存量 ``project.portfolio_id`` 继续作为主要组合兼容字段。"""

    __tablename__ = "portfolio"

    name: Mapped[str] = mapped_column(String(128), unique=True)
    portfolio_code: Mapped[str | None] = mapped_column(String(32), unique=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"))
    year: Mapped[str | None] = mapped_column(String(8), comment="年度，如 2026")
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    planning_start: Mapped[date | None] = mapped_column(Date)
    planning_end: Mapped[date | None] = mapped_column(Date)
    budget_limit_10k: Mapped[float | None] = mapped_column(Float)
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


class PortfolioObjective(GlidBase):
    """组合战略目标；项目通过 ``PortfolioProject.objective_contributions`` 贡献多个目标。"""

    __tablename__ = "portfolio_objective"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "objective_code", name="uq_portfolio_objective_code"),
        CheckConstraint("weight >= 0 AND weight <= 100", name="ck_portfolio_objective_weight"),
    )

    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolio.id"), index=True)
    objective_code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    metric_name: Mapped[str | None] = mapped_column(String(128))
    target_value: Mapped[float | None] = mapped_column(Float)
    current_value: Mapped[float | None] = mapped_column(Float)
    weight: Mapped[int] = mapped_column(Integer, default=0)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(24), default="active")


class PortfolioProject(GlidBase):
    """组合成员治理记录；首期一个项目只允许一个活动主要组合。"""

    __tablename__ = "portfolio_project"
    __table_args__ = (
        Index(
            "uq_portfolio_project_active_project",
            "project_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
            sqlite_where=text("is_deleted = 0"),
        ),
        Index(
            "uq_portfolio_project_active_pair",
            "portfolio_id",
            "project_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
            sqlite_where=text("is_deleted = 0"),
        ),
        Index(
            "uq_portfolio_project_active_priority",
            "portfolio_id",
            "priority_rank",
            unique=True,
            postgresql_where=text("is_deleted = false AND priority_rank IS NOT NULL"),
            sqlite_where=text("is_deleted = 0 AND priority_rank IS NOT NULL"),
        ),
    )
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolio.id"), index=True)
    # 活动成员唯一性由 PostgreSQL partial unique index 保证。不能使用普通 UNIQUE，
    # 否则软删除后项目无法迁入其他组合或重新加入原组合。
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    governance_status: Mapped[str] = mapped_column(String(24), default="candidate", index=True)
    system_score: Mapped[float | None] = mapped_column(Float)
    priority_rank: Mapped[int | None] = mapped_column(Integer)
    proposal_reason: Mapped[str | None] = mapped_column(Text)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    objective_contributions: Mapped[list | None] = mapped_column(
        JsonCol, default=list, comment="[{objective_id, weight, note}]"
    )
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("auth_user.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class PortfolioScoringRule(GlidBase):
    """组合评分维度；权重和证据要求可配置，历史基线保存快照。"""

    __tablename__ = "portfolio_scoring_rule"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "dimension_code", name="uq_portfolio_scoring_rule_code"),
        CheckConstraint("weight >= 0 AND weight <= 100", name="ck_portfolio_scoring_rule_weight"),
    )

    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolio.id"), index=True)
    dimension_code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[int] = mapped_column(Integer)
    evidence_required: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class PortfolioProjectScore(GlidBase):
    """某项目在某维度上的最新治理评分；历史值由治理动作和基线保留。"""

    __tablename__ = "portfolio_project_score"
    __table_args__ = (
        UniqueConstraint("portfolio_project_id", "rule_id", name="uq_portfolio_project_score_rule"),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_portfolio_project_score_value"),
    )

    portfolio_project_id: Mapped[str] = mapped_column(ForeignKey("portfolio_project.id"), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("portfolio_scoring_rule.id"))
    score: Mapped[float] = mapped_column(Float)
    evidence: Mapped[str | None] = mapped_column(Text)
    scored_by: Mapped[str] = mapped_column(ForeignKey("auth_user.id"))
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ProjectDependency(GlidBase):
    """跨项目依赖；WBS 内部依赖仍由 ``wbs_task.predecessor_ids`` 管理。"""

    __tablename__ = "project_dependency"
    __table_args__ = (
        UniqueConstraint(
            "predecessor_project_id", "successor_project_id", "dependency_type",
            name="uq_project_dependency_active_pair",
        ),
        CheckConstraint(
            "predecessor_project_id <> successor_project_id",
            name="ck_project_dependency_not_self",
        ),
    )

    predecessor_project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    successor_project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    dependency_type: Mapped[str] = mapped_column(String(32), default="finish_to_start")
    deliverable: Mapped[str] = mapped_column(String(300))
    due_date: Mapped[date | None] = mapped_column(Date)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"))
    impact: Mapped[str] = mapped_column(String(8), default="medium")
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    description: Mapped[str | None] = mapped_column(Text)


class ProjectResourceCommitment(GlidBase):
    """项目对人员的显式资源承诺；仅告警超配，不自动重排项目。"""

    __tablename__ = "project_resource_commitment"
    __table_args__ = (
        CheckConstraint("allocation_percent >= 1 AND allocation_percent <= 100", name="ck_resource_allocation_percent"),
        CheckConstraint("end_date >= start_date", name="ck_resource_commitment_dates"),
    )

    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("org_member.id"), index=True)
    role_name: Mapped[str | None] = mapped_column(String(96))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    allocation_percent: Mapped[int] = mapped_column(Integer)
    planned_person_days: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)


class PortfolioGovernanceAction(GlidBase):
    """只增治理动作，记录评分、排序、准入、暂停、恢复、终止和基线发布。"""

    __tablename__ = "portfolio_governance_action"

    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolio.id"), index=True)
    portfolio_project_id: Mapped[str | None] = mapped_column(ForeignKey("portfolio_project.id"), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    before_value: Mapped[dict | None] = mapped_column(JsonCol)
    after_value: Mapped[dict | None] = mapped_column(JsonCol)
    actor_id: Mapped[str] = mapped_column(ForeignKey("auth_user.id"))
    effective_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class PortfolioBaseline(GlidBase):
    """不可变组合发布快照；新发布创建递增版本。"""

    __tablename__ = "portfolio_baseline"
    __table_args__ = (UniqueConstraint("portfolio_id", "version", name="uq_portfolio_baseline_version"),)

    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolio.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JsonCol)
    published_by: Mapped[str] = mapped_column(ForeignKey("auth_user.id"))
    published_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
