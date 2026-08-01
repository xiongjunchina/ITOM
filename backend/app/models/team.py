"""团队域模型 M6a：建言献策 + 专项活动 + 积分台账（docs/04 §6，PRD §9）。"""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GlidBase, JsonCol


class Idea(GlidBase):
    """建言献策：提交仅 2 字段（PRD §9.6）。"""

    __tablename__ = "idea"

    idea_code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    proposer: Mapped[str | None] = mapped_column(String(26), comment="auth_user.id")
    proposer_name: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="submitted", comment="submitted/adopted/implemented/declined")
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    adopted_at: Mapped[datetime | None] = mapped_column(DateTime)
    decline_reason: Mapped[str | None] = mapped_column(Text)


class IdeaLike(GlidBase):
    __tablename__ = "idea_like"
    __table_args__ = (UniqueConstraint("idea_id", "voter"),)

    idea_id: Mapped[str] = mapped_column(ForeignKey("idea.id"), index=True)
    voter: Mapped[str] = mapped_column(String(26), comment="auth_user.id")


class PointRule(GlidBase):
    """自动积分规则（可配置分值）；M6b 事件接入时扩展更多 code。"""

    __tablename__ = "point_rule"

    code: Mapped[str] = mapped_column(String(48), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    points: Mapped[float] = mapped_column(Float)
    contribution_bucket: Mapped[str] = mapped_column(
        String(24), default="team_contribution", comment="role_result/team_contribution"
    )
    contribution_dimension: Mapped[str | None] = mapped_column(String(48))
    target_points: Mapped[float | None] = mapped_column(Float, comment="团队贡献维度目标积分")
    active: Mapped[bool] = mapped_column(default=True)


class ActivityCampaign(GlidBase):
    """专项活动：管理员上架/下架的游戏化激励活动，积分按折算系数计入考核期绩效。"""

    __tablename__ = "activity_campaign"

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    period_label: Mapped[str] = mapped_column(String(32), comment="考核期，如 2026-H2 / 2026-Q3")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    performance_ratio: Mapped[float] = mapped_column(Float, default=1.0, comment="绩效折算系数：绩效分=活动积分×系数")
    status: Mapped[str] = mapped_column(String(16), default="draft", comment="draft/active(上架)/offline(下架)")
    created_by: Mapped[str | None] = mapped_column(String(26))

    tasks: Mapped[list["CampaignTask"]] = relationship(order_by="CampaignTask.sort")


class CampaignTask(GlidBase):
    """活动激励任务/贡献指标。"""

    __tablename__ = "campaign_task"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("activity_campaign.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, comment="贡献指标说明/达成标准")
    points: Mapped[float] = mapped_column(Float, comment="每次完成奖励积分")
    max_times: Mapped[int] = mapped_column(Integer, default=1, comment="每人可获奖次数上限，0=不限")
    sort: Mapped[int] = mapped_column(Integer, default=0)


class PointEntry(GlidBase):
    """积分台账（统一账本）：专项活动发放 + 自动事件积分（M6b）+ 手工调整，全部留痕。"""

    __tablename__ = "point_entry"

    person_id: Mapped[str] = mapped_column(ForeignKey("org_member.id"), index=True)
    points: Mapped[float] = mapped_column(Float)
    source_type: Mapped[str] = mapped_column(String(48), index=True, comment="campaign_award/idea_adopt/idea_like/manual/…")
    source_ref: Mapped[str | None] = mapped_column(String(26), comment="来源单据/任务 id")
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("activity_campaign.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("campaign_task.id"))
    period: Mapped[str | None] = mapped_column(String(32), index=True, comment="计入考核期")
    contribution_bucket: Mapped[str] = mapped_column(
        String(24), default="team_contribution", comment="role_result/team_contribution"
    )
    contribution_dimension: Mapped[str | None] = mapped_column(String(48))
    note: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[str | None] = mapped_column(String(26))


class LearningGrowthGoal(GlidBase):
    """员工在考核期内填写的学习成长目标及实际完成情况。

    每个目标保存当前完成比例与佐证；服务层会按同一人员/周期的目标平均进度
    折算为 learning_growth 团队贡献积分，并同步到 PointEntry，保持现有积分账本可追溯。
    """

    __tablename__ = "learning_growth_goal"

    period: Mapped[str] = mapped_column(String(32), index=True, comment="考核期，如 2026-Q3")
    person_id: Mapped[str] = mapped_column(ForeignKey("org_member.id"), index=True)
    goal: Mapped[str] = mapped_column(String(200), comment="学习成长目标")
    target_description: Mapped[str | None] = mapped_column(Text, comment="目标与验收标准")
    progress: Mapped[float] = mapped_column(Float, default=0, comment="实际完成比例 0-100")
    evidence: Mapped[str | None] = mapped_column(Text, comment="相关佐证")
    note: Mapped[str | None] = mapped_column(Text, comment="补充说明")
    points: Mapped[float] = mapped_column(Float, default=0, comment="按周期目标积分折算后的积分")


class PerfScheme(GlidBase):
    """人效计分方案（M6.1）：按岗位绑定「维度×权重」，全部用户可自定义。"""

    __tablename__ = "perf_scheme"

    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    position_ids: Mapped[list | None] = mapped_column(JsonCol, default=list, comment="适用岗位 id 列表")
    dimensions: Mapped[list | None] = mapped_column(JsonCol, default=list, comment='[{"code","weight"}]')
    is_default: Mapped[bool] = mapped_column(default=False, comment="未匹配岗位的兜底方案，全局唯一")
    active: Mapped[bool] = mapped_column(default=True)


class PerfAdjustment(GlidBase):
    """考核期加减分事项（M6.2）：特殊贡献加分 / 违规事件扣分，必填事项说明。"""

    __tablename__ = "perf_adjustment"

    period: Mapped[str] = mapped_column(String(32), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("org_member.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8), comment="bonus 加分 / penalty 扣分")
    points: Mapped[float] = mapped_column(Float, comment="正数；扣分在计算时取负")
    reason: Mapped[str] = mapped_column(String(200), comment="加减分事项说明（必填）")
    created_by: Mapped[str | None] = mapped_column(String(26))


class PerfOverride(GlidBase):
    """维度核定分（M6.2）：系统算出的是初始参考值，管理岗可核定覆盖。"""

    __tablename__ = "perf_override"
    __table_args__ = (UniqueConstraint("period", "person_id", "dimension_code"),)

    period: Mapped[str] = mapped_column(String(32), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("org_member.id"), index=True)
    dimension_code: Mapped[str] = mapped_column(String(48))
    score: Mapped[float] = mapped_column(Float, comment="核定分 0-100")
    created_by: Mapped[str | None] = mapped_column(String(26))


class PerformancePeriod(GlidBase):
    """矩阵角色绩效周期：状态和版本是发布隔离的边界。"""

    __tablename__ = "performance_period"
    __table_args__ = (UniqueConstraint("period_code", "version"),)

    period_code: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(
        String(24), default="draft",
        comment="draft/auto_scored/external_input/manager_review/cio_review/published/locked",
    )
    rule_snapshot: Mapped[dict | None] = mapped_column(JsonCol, default=dict)
    role_snapshot: Mapped[dict | None] = mapped_column(JsonCol, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str | None] = mapped_column(String(26))
    updated_by: Mapped[str | None] = mapped_column(String(26))


class PerformanceContributionConfig(GlidBase):
    """周期团队贡献与满意度组合规则；由 CIO/系统管理员维护。"""

    __tablename__ = "performance_contribution_config"

    weights: Mapped[dict | None] = mapped_column(JsonCol, default=dict, comment="团队贡献维度权重，合计 100")
    targets: Mapped[dict | None] = mapped_column(JsonCol, default=dict, comment="团队贡献维度目标积分")
    internal_satisfaction_weight: Mapped[float] = mapped_column(Float, default=50)
    external_satisfaction_weight: Mapped[float] = mapped_column(Float, default=50)
    updated_by: Mapped[str | None] = mapped_column(String(26))


class PerformanceRoleProfile(GlidBase):
    """矩阵角色档案；岗位权限角色与绩效角色故意分离。"""

    __tablename__ = "performance_role_profile"

    role_code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    line_type: Mapped[str] = mapped_column(String(16), comment="business/professional/platform")
    review_mode: Mapped[str] = mapped_column(String(24), default="manager_review", comment="manager_review/cio_direct")
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PerformanceRoleDimension(GlidBase):
    """角色评分维度和自动取数配置。"""

    __tablename__ = "performance_role_dimension"
    __table_args__ = (UniqueConstraint("profile_id", "dimension_code"),)

    profile_id: Mapped[str] = mapped_column(ForeignKey("performance_role_profile.id"), index=True)
    dimension_code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    weight: Mapped[float] = mapped_column(Float, default=0)
    source_config: Mapped[dict | None] = mapped_column(JsonCol, default=dict)
    evidence_required: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PerformanceRoleAssignment(GlidBase):
    """人员-角色-周期快照，承载评审范围和评审主体。"""

    __tablename__ = "performance_role_assignment"
    __table_args__ = (UniqueConstraint("period_id", "person_id", "role_code"),)

    period_id: Mapped[str] = mapped_column(ForeignKey("performance_period.id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("org_member.id"), index=True)
    role_code: Mapped[str] = mapped_column(String(64), index=True)
    line_type: Mapped[str] = mapped_column(String(16))
    business_domain_id: Mapped[str | None] = mapped_column(ForeignKey("business_domain.id"), index=True)
    professional_group_id: Mapped[str | None] = mapped_column(ForeignKey("user_group.id"), index=True)
    role_weight: Mapped[float] = mapped_column(Float, default=0)
    evaluator_ids: Mapped[list | None] = mapped_column(JsonCol, default=list)
    evaluator_weights: Mapped[dict | None] = mapped_column(JsonCol, default=dict, comment="评审人权重，合计 100")
    review_scope: Mapped[dict | None] = mapped_column(JsonCol, default=dict)
    review_mode: Mapped[str] = mapped_column(String(24), default="manager_review")
    snapshot_detail: Mapped[dict | None] = mapped_column(JsonCol, default=dict)


class PerformanceExternalInput(GlidBase):
    """系统外业务评价等原始事实；锁定后只能生成修订版本。"""

    __tablename__ = "performance_external_input"

    period_id: Mapped[str] = mapped_column(ForeignKey("performance_period.id"), index=True)
    metric_code: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(26), index=True)
    evaluator_name: Mapped[str] = mapped_column(String(128))
    evaluator_department: Mapped[str | None] = mapped_column(String(128))
    raw_score: Mapped[float] = mapped_column(Float)
    raw_scale: Mapped[float] = mapped_column(Float, default=100)
    normalized_score: Mapped[float | None] = mapped_column(Float)
    comment: Mapped[str | None] = mapped_column(Text)
    evidence_refs: Mapped[list | None] = mapped_column(JsonCol, default=list)
    inputter_id: Mapped[str | None] = mapped_column(String(26))
    status: Mapped[str] = mapped_column(String(16), default="draft", comment="draft/submitted/verified/locked")
    version: Mapped[int] = mapped_column(Integer, default=1)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)


class PerformanceScoreComponent(GlidBase):
    """单个角色维度的参考分、各阶段建议分和生效分。"""

    __tablename__ = "performance_score_component"
    __table_args__ = (UniqueConstraint("period_id", "assignment_id", "dimension_code"),)

    period_id: Mapped[str] = mapped_column(ForeignKey("performance_period.id"), index=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("performance_role_assignment.id"), index=True)
    dimension_code: Mapped[str] = mapped_column(String(64))
    system_score: Mapped[float | None] = mapped_column(Float)
    business_manager_score: Mapped[float | None] = mapped_column(Float)
    professional_manager_score: Mapped[float | None] = mapped_column(Float)
    cio_score: Mapped[float | None] = mapped_column(Float)
    manager_scores: Mapped[dict | None] = mapped_column(JsonCol, default=dict, comment="评审人独立评分")
    manager_reasons: Mapped[dict | None] = mapped_column(JsonCol, default=dict, comment="评审人独立说明")
    manager_evidence_refs: Mapped[dict | None] = mapped_column(JsonCol, default=dict, comment="评审人独立佐证")
    effective_score: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    evidence_refs: Mapped[list | None] = mapped_column(JsonCol, default=list)
    updated_by: Mapped[str | None] = mapped_column(String(26))


class PerformanceReviewAction(GlidBase):
    """评审动作追加记录，不覆盖历史。"""

    __tablename__ = "performance_review_action"

    period_id: Mapped[str] = mapped_column(ForeignKey("performance_period.id"), index=True)
    assignment_id: Mapped[str | None] = mapped_column(ForeignKey("performance_role_assignment.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(26), index=True)
    stage: Mapped[str] = mapped_column(String(24))
    action: Mapped[str] = mapped_column(String(32))
    before_value: Mapped[dict | None] = mapped_column(JsonCol, default=dict)
    after_value: Mapped[dict | None] = mapped_column(JsonCol, default=dict)
    reason: Mapped[str | None] = mapped_column(Text)
    evidence_refs: Mapped[list | None] = mapped_column(JsonCol, default=list)


class PerformanceScore(GlidBase):
    """已发布的绩效结果快照；员工接口只读取 published 周期。"""

    __tablename__ = "performance_score"
    __table_args__ = (UniqueConstraint("period_id", "person_id"),)

    period_id: Mapped[str] = mapped_column(ForeignKey("performance_period.id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("org_member.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    business_role_score: Mapped[float | None] = mapped_column(Float)
    professional_role_score: Mapped[float | None] = mapped_column(Float)
    team_contribution_score: Mapped[float] = mapped_column(Float, default=0)
    regular_score: Mapped[float | None] = mapped_column(Float)
    bonus: Mapped[float] = mapped_column(Float, default=0)
    penalty: Mapped[float] = mapped_column(Float, default=0)
    published_score: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict | None] = mapped_column(JsonCol, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


class DevelopmentActivity(GlidBase):
    """培训发展活动（PRD §9.4）：登记即触发培训积分并保留登记人。

    ``participant_ids`` 是积分对象的冻结快照；整部门勾选另存部门、名称与
    当时覆盖人员，供清单显示和审计，不能在组织变动后重新按当前组织推导。
    """

    __tablename__ = "development_activity"

    activity_type: Mapped[str] = mapped_column(String(32), comment="内部交叉培训/外部技术交流/新技术研究")
    topic: Mapped[str] = mapped_column(String(200))
    activity_date: Mapped[date] = mapped_column(Date)
    host_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), comment="主讲/组织人")
    participant_ids: Mapped[list | None] = mapped_column(JsonCol, default=list)
    participant_department_selections: Mapped[list | None] = mapped_column(
        JsonCol,
        default=list,
        comment="整部门参与快照：[{id,name,member_ids}]；人员快照仍以 participant_ids 为准",
    )
    output_link: Mapped[str | None] = mapped_column(String(500), comment="产出链接（课件/纪要/报告）")
    remarks: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(26), comment="登记人 auth_user.id；存量记录由审计日志回填")


class TeamCharter(GlidBase):
    """团队文化单页（PRD §9.5）：愿景/目标/行为准则，富文本单例。"""

    __tablename__ = "team_charter"

    vision: Mapped[str | None] = mapped_column(Text)
    goals: Mapped[str | None] = mapped_column(Text)
    principles: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(String(26))


class HiringNeed(GlidBase):
    """招聘需求与进度（PRD §9.3）。"""

    __tablename__ = "hiring_need"

    position_id: Mapped[str] = mapped_column(ForeignKey("position.id"))
    level: Mapped[str] = mapped_column(String(8), default="中级", comment="高级/中级/初级")
    headcount: Mapped[int] = mapped_column(Integer, default=1)
    qualification: Mapped[str | None] = mapped_column(Text, comment="任职资格要求")
    status: Mapped[str] = mapped_column(String(16), default="待招聘", comment="待招聘/面试中/已到岗/已取消")
    progress_note: Mapped[str | None] = mapped_column(String(200), comment="进度备注")
