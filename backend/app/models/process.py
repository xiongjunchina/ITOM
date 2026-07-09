"""流程域模型（docs/04 §5，M2 最小版）。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GlidBase, JsonCol


class ProcessDefinition(GlidBase):
    __tablename__ = "process_definition"

    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    entity_type: Mapped[str] = mapped_column(String(32), comment="ticket/requirement/project…")
    trigger_condition: Mapped[dict | None] = mapped_column(JsonCol, comment='如 {"ticket_type":"change"}')
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text)

    steps: Mapped[list["ProcessStep"]] = relationship(order_by="ProcessStep.seq")


class ProcessStep(GlidBase):
    __tablename__ = "process_step"

    definition_id: Mapped[str] = mapped_column(ForeignKey("process_definition.id"))
    seq: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(128))
    default_role: Mapped[str | None] = mapped_column(String(32), comment="it_bp/it_pdm/it_pm/it_dev/it_ops/is_mgr/manager")
    autonomy_level: Mapped[str] = mapped_column(String(4), default="L4", comment="L1-L4")
    sla_hours: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(Text)


class ProcessInstance(GlidBase):
    __tablename__ = "process_instance"

    definition_id: Mapped[str] = mapped_column(ForeignKey("process_definition.id"))
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(26), index=True)
    status: Mapped[str] = mapped_column(String(16), default="进行中", comment="进行中/已完成/已终止")
    current_step_seq: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    definition: Mapped[ProcessDefinition] = relationship()
    tasks: Mapped[list["ProcessTask"]] = relationship(order_by="ProcessTask.created_at")


class ProcessTask(GlidBase):
    __tablename__ = "process_task"

    instance_id: Mapped[str] = mapped_column(ForeignKey("process_instance.id"))
    step_id: Mapped[str] = mapped_column(ForeignKey("process_step.id"))
    assignee: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="待处理", comment="待处理/已完成/已跳过")
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, comment="按步骤 SLA")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    comment: Mapped[str | None] = mapped_column(Text)

    step: Mapped[ProcessStep] = relationship()
