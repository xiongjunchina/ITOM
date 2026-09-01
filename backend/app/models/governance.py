"""治理记录模型：P0 仅记录线下 DMC/授权决策，不实现在线投票。"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import GlidBase, JsonCol


class DmcDecisionRecord(GlidBase):
    """DMC 或授权层级的人工决议快照，可关联需求或项目。"""

    __tablename__ = "dmc_decision_record"

    entity_type: Mapped[str] = mapped_column(String(32), comment="关联对象类型：requirement/project")
    entity_id: Mapped[str] = mapped_column(String(26), index=True, comment="关联对象 GLID")
    decision_level: Mapped[str] = mapped_column(
        String(16), comment="digital_leader/eason/dmc"
    )
    decision: Mapped[str] = mapped_column(
        String(16), comment="approved/conditional/hold/rejected"
    )
    amount_cny: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), comment="决策涉及外部金额（人民币元）")
    budget_source: Mapped[str | None] = mapped_column(String(64), comment="预算来源/科目")
    conditions: Mapped[str | None] = mapped_column(Text, comment="附带条件")
    decision_date: Mapped[date | None] = mapped_column(Date)
    meeting_reference: Mapped[str | None] = mapped_column(String(200), comment="会议编号或决议引用")
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), comment="决议跟进责任人")
    deadline: Mapped[date | None] = mapped_column(Date)
    check_at: Mapped[date | None] = mapped_column(Date, comment="复核日期")
    recorded_by: Mapped[str | None] = mapped_column(String(26), comment="记录人 auth_user.id")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    evidence_refs: Mapped[list | None] = mapped_column(JsonCol, comment="证据附件/链接引用（不存密钥）")
    note: Mapped[str | None] = mapped_column(Text)
