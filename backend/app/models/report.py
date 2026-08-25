"""统一报表中心模型。

实时指标不写预计算表；只有用户明确生成的正式报告保存可审计版本快照。
"""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import GlidBase, JsonCol


class ReportTemplate(GlidBase):
    __tablename__ = "report_template"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    domains: Mapped[list] = mapped_column(JsonCol, default=list)
    metric_codes: Mapped[list] = mapped_column(JsonCol, default=list)
    default_filters: Mapped[dict] = mapped_column(JsonCol, default=dict)
    default_period_type: Mapped[str] = mapped_column(String(16), default="month")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("auth_user.id"), index=True)


class ReportInstance(GlidBase):
    __tablename__ = "report_instance"

    template_id: Mapped[str] = mapped_column(ForeignKey("report_template.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    period_type: Mapped[str] = mapped_column(String(16), index=True)
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    filters: Mapped[dict] = mapped_column(JsonCol, default=dict)
    status: Mapped[str] = mapped_column(
        String(16), default="draft", index=True, comment="draft/review/approved/published/locked"
    )
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    published_version: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(ForeignKey("auth_user.id"), index=True)
    process_instance_id: Mapped[str | None] = mapped_column(ForeignKey("process_instance.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)


class ReportVersion(GlidBase):
    __tablename__ = "report_version"
    __table_args__ = (UniqueConstraint("report_instance_id", "version"),)

    report_instance_id: Mapped[str] = mapped_column(ForeignKey("report_instance.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    metric_snapshot: Mapped[dict] = mapped_column(JsonCol, default=dict)
    narrative: Mapped[dict] = mapped_column(JsonCol, default=dict)
    formula_versions: Mapped[dict] = mapped_column(JsonCol, default=dict)
    data_quality: Mapped[dict] = mapped_column(JsonCol, default=dict)
    checksum: Mapped[str] = mapped_column(String(64))
    generated_by: Mapped[str] = mapped_column(ForeignKey("auth_user.id"))
    generated_at: Mapped[datetime] = mapped_column(DateTime)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)


class ReportAudience(GlidBase):
    __tablename__ = "report_audience"
    __table_args__ = (UniqueConstraint("report_instance_id", "subject_type", "subject_id"),)

    report_instance_id: Mapped[str] = mapped_column(ForeignKey("report_instance.id"), index=True)
    subject_type: Mapped[str] = mapped_column(String(16), comment="user/role/group")
    subject_id: Mapped[str] = mapped_column(String(64), index=True)


class ReportGenerationJob(GlidBase):
    __tablename__ = "report_generation_job"
    __table_args__ = (UniqueConstraint("actor_id", "idempotency_key"),)

    report_instance_id: Mapped[str] = mapped_column(ForeignKey("report_instance.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("auth_user.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), index=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    version_id: Mapped[str | None] = mapped_column(ForeignKey("report_version.id"))
    error_code: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ReportSchedule(GlidBase):
    __tablename__ = "report_schedule"

    template_id: Mapped[str] = mapped_column(ForeignKey("report_template.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    period_type: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    audience: Mapped[list] = mapped_column(JsonCol, default=list)
    created_by: Mapped[str] = mapped_column(ForeignKey("auth_user.id"))
