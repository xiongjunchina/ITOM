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
    # Stable business key inside a process definition.  Names and sequence numbers
    # may be edited in a new version; performance/RACI mappings use this key.
    step_code: Mapped[str | None] = mapped_column(String(64), comment="版本内稳定节点编码")
    name: Mapped[str] = mapped_column(String(128))
    node_type: Mapped[str] = mapped_column(String(16), default="processing", comment="processing/approval")
    default_role: Mapped[str | None] = mapped_column(String(32), comment="处理人：角色码或 group:组码（产生任务，阻塞流程）")
    cc_roles: Mapped[list | None] = mapped_column(JsonCol, default=list, comment="知会人：角色码/group:组码列表（仅通知，不阻塞）")
    autonomy_level: Mapped[str] = mapped_column(String(4), default="L4", comment="L1-L4")
    sla_hours: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(Text)


class ProcessInstance(GlidBase):
    __tablename__ = "process_instance"

    definition_id: Mapped[str] = mapped_column(ForeignKey("process_definition.id"))
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(26), index=True)
    status: Mapped[str] = mapped_column(String(16), default="running", comment="running/completed（M24 统一英文 code，前端词表翻译）")
    current_step_seq: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    definition: Mapped[ProcessDefinition] = relationship()
    tasks: Mapped[list["ProcessTask"]] = relationship(order_by="ProcessTask.created_at")


class ProcessTask(GlidBase):
    __tablename__ = "process_task"

    instance_id: Mapped[str] = mapped_column(ForeignKey("process_instance.id"))
    step_id: Mapped[str] = mapped_column(ForeignKey("process_step.id"))
    definition_version: Mapped[int | None] = mapped_column(Integer, comment="任务生成时的流程版本")
    step_code_snapshot: Mapped[str | None] = mapped_column(String(64), comment="任务生成时的节点编码")
    raci_snapshot: Mapped[dict | None] = mapped_column(JsonCol, comment="任务生成时的 RACI 主责/知会快照")
    assignee: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="待处理", comment="待处理/已完成/已跳过")
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    # ``started_at`` is the assignment/SLA clock.  It is deliberately not reused
    # as a read receipt: an assignee can receive a task without opening it.
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime, comment="当前处理人首次实际查阅时间")
    viewed_by: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), comment="首次实际查阅人")
    # Only tasks created after the upstream-correction rule is released opt in.
    # Existing pending tasks remain safe and keep their historical semantics.
    upstream_correction_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="未查阅前是否允许上一节点更正"
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime, comment="按步骤 SLA")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_by: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"), comment="实际完成任务的人员")
    comment: Mapped[str | None] = mapped_column(Text)

    step: Mapped[ProcessStep] = relationship()
