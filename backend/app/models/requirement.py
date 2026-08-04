"""需求域模型（docs/04 §4，PRD §7）：五阶段协同漏斗。

M10：MoSCoW 单字段升级为麦肯锡六维加权评分 + 四象限决策。
- Requirement：登记字段 + 评估结果（六维共识分/决议）+ 实现字段
- RequirementScore：评审官评分行（单人评分起步，多方共识留作增强）
- RequirementScoringConfig：权重/阈值/分档单行配置（系统管理可调，年度复审）
"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

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
    department: Mapped[str | None] = mapped_column(String(64), comment="渠道/所在部门")
    expected_date: Mapped[date | None] = mapped_column(Date, comment="期望完成时间(业务侧)")
    expected_effect: Mapped[str | None] = mapped_column(Text, comment="期望效果")
    business_value_note: Mapped[str | None] = mapped_column(Text, comment="运营价值(定性)")
    # 评估阶段：六维评分（共识终值，1-5；空=未评）+ 决议
    score_d1_strategy: Mapped[int | None] = mapped_column(Integer, comment="D1 战略对齐 1-5")
    score_d2_value: Mapped[int | None] = mapped_column(Integer, comment="D2 业务价值 1-5")
    score_d3_tech: Mapped[int | None] = mapped_column(Integer, comment="D3 技术可行性 1-5")
    score_d4_org: Mapped[int | None] = mapped_column(Integer, comment="D4 组织就绪度 1-5")
    score_d5_risk: Mapped[int | None] = mapped_column(Integer, comment="D5 风险等级 1-5(反向)")
    score_d6_speed: Mapped[int | None] = mapped_column(Integer, comment="D6 价值速度 1-5")
    decision: Mapped[str | None] = mapped_column(String(16), comment="最终决议：立项/搁置/驳回")
    solution_type: Mapped[str | None] = mapped_column(String(16), comment="方案类型（M16）：二次开发/新购系统")
    prd_effort: Mapped[float | None] = mapped_column(Float, comment="PRD 人天")
    dev_effort: Mapped[float | None] = mapped_column(Float, comment="开发人天")
    # 在实际执行“转开发实现/转项目管理”时冻结路径；不回填历史记录，避免评分阈值调整后改写既有流转事实。
    implementation_route: Mapped[str | None] = mapped_column(String(32), comment="实现路径快照：需求开发实现/转项目管理")
    # 分析阶段
    moscow: Mapped[str | None] = mapped_column(String(2), comment="M/S/C/W（辅助标签）")
    owner: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), comment="负责人")
    target_date: Mapped[date | None] = mapped_column(Date, comment="排期目标日期(内部)")
    solution: Mapped[str | None] = mapped_column(Text, comment="解决方案")
    acceptance_criteria: Mapped[list | None] = mapped_column(JsonCol, default=list, comment="[{text, checked}]")
    # 实现阶段
    project_id: Mapped[str | None] = mapped_column(ForeignKey("project.id"), index=True)
    # 派生/打点
    status: Mapped[str] = mapped_column(String(32), default="registered", index=True)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime)
    evaluating_at: Mapped[datetime | None] = mapped_column(DateTime)
    analyzing_at: Mapped[datetime | None] = mapped_column(DateTime)
    implementing_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    closure_note: Mapped[str | None] = mapped_column(Text, comment="关闭说明/遗留说明")
    parent_requirement_id: Mapped[str | None] = mapped_column(ForeignKey("requirement.id"))
    remarks: Mapped[str | None] = mapped_column(Text)


class RequirementScore(GlidBase):
    """评审官评分行。单人评分起步：一条 is_consensus=True 即为终值；
    多方评审时可存多条个人初评，共识行回填到 Requirement.score_d1-d6。"""
    __tablename__ = "requirement_score"

    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirement.id"), index=True)
    reviewer_id: Mapped[str | None] = mapped_column(String(26), comment="评审官 auth_user.id")
    reviewer_name: Mapped[str | None] = mapped_column(String(64))
    reviewer_role: Mapped[str | None] = mapped_column(String(32), comment="业务/技术/PMO/财务")
    role_weight: Mapped[float | None] = mapped_column(Float, comment="角色评分权重")
    d1_strategy: Mapped[int | None] = mapped_column(Integer)
    d2_value: Mapped[int | None] = mapped_column(Integer)
    d3_tech: Mapped[int | None] = mapped_column(Integer)
    d4_org: Mapped[int | None] = mapped_column(Integer)
    d5_risk: Mapped[int | None] = mapped_column(Integer)
    d6_speed: Mapped[int | None] = mapped_column(Integer)
    is_consensus: Mapped[bool] = mapped_column(default=False, comment="是否为最终共识值")
    comment: Mapped[str | None] = mapped_column(Text)


class RequirementScoringConfig(GlidBase):
    """需求评分规则单行配置（系统管理可调，年度复审）。"""
    __tablename__ = "requirement_scoring_config"

    weights: Mapped[dict | None] = mapped_column(
        JsonCol, comment="六维权重 {d1..d6}，风险按 (6-D5) 反向计入"
    )
    thresholds: Mapped[dict | None] = mapped_column(
        JsonCol, comment="四象限阈值 {total, strategic, viable}"
    )
    rubric: Mapped[dict | None] = mapped_column(
        JsonCol, comment="六维 1-5 分档说明 {d1:{5:..,4:..}, ...}"
    )
    role_weights: Mapped[dict | None] = mapped_column(
        JsonCol, comment="评审角色权重 {业务:0.4, 技术:0.3, PMO:0.2, 财务:0.1}"
    )
    effort_threshold: Mapped[float | None] = mapped_column(
        Float, comment="转项目人天阈值（M16）：二开人天≥阈值 或 新购系统 → 转项目管理；默认 20"
    )
    review_assignees: Mapped[dict | None] = mapped_column(
        JsonCol, comment="方案评估指派（M16）{pdm_leader: 人员id主责, dev_leader: 人员id知会}"
    )


class RequirementTask(GlidBase):
    __tablename__ = "requirement_task"

    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirement.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, comment="任务描述")
    assignee: Mapped[str] = mapped_column(ForeignKey("org_member.id"))
    plan_date: Mapped[date | None] = mapped_column(Date)
    plan_effort: Mapped[float | None] = mapped_column(Float, comment="计划工天")
    actual_effort: Mapped[float | None] = mapped_column(Float, comment="实际工天")
    status: Mapped[str] = mapped_column(String(16), default="待处理", comment="待处理/进行中/已完成")
    done_at: Mapped[datetime | None] = mapped_column(DateTime)
