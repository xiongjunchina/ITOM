"""团队域模型 M6a：建言献策 + 专项活动 + 积分台账（docs/04 §6，PRD §9）。"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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
    note: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[str | None] = mapped_column(String(26))


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


class DevelopmentActivity(GlidBase):
    """培训发展活动（PRD §9.4）：登记即触发培训积分。"""

    __tablename__ = "development_activity"

    activity_type: Mapped[str] = mapped_column(String(32), comment="内部交叉培训/外部技术交流/新技术研究")
    topic: Mapped[str] = mapped_column(String(200))
    activity_date: Mapped[date] = mapped_column(Date)
    host_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), comment="主讲/组织人")
    participant_ids: Mapped[list | None] = mapped_column(JsonCol, default=list)
    output_link: Mapped[str | None] = mapped_column(String(500), comment="产出链接（课件/纪要/报告）")
    remarks: Mapped[str | None] = mapped_column(Text)


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
