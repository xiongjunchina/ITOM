"""ITSM 域模型 M3 部分：CMDB / 问题 / 供应商 / 合同 / 知识（docs/04 §2.4-2.12）。"""
from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GlidBase, JsonCol


class Vendor(GlidBase):
    __tablename__ = "vendor"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    contact: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(128))
    service_scope: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[str | None] = mapped_column(String(8), comment="A/B/C/D")
    status: Mapped[str] = mapped_column(String(16), default="合作中", comment="合作中/已终止")
    remarks: Mapped[str | None] = mapped_column(Text)


class Contract(GlidBase):
    __tablename__ = "contract"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendor.id"))
    amount_10k: Mapped[float | None] = mapped_column(Float, comment="金额(万元)")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    owner: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"))
    remarks: Mapped[str | None] = mapped_column(Text)
    expiry_warned: Mapped[bool] = mapped_column(default=False, comment="到期预警已发")

    vendor: Mapped[Vendor] = relationship()
    # status 为计算属性：生效/临期/已过期（按日期实时推导，不落库）


class Ci(GlidBase):
    """配置项：合并原 9 张资产表，类别专属属性进 attrs JSONB。"""

    __tablename__ = "ci"

    ci_code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(32), index=True, comment="应用/服务器/云资源/网络/安全/协作/终端/基础设施/咨询")
    status: Mapped[str] = mapped_column(String(16), default="运行中", comment="运行中/维护中/已下线")
    owner: Mapped[str] = mapped_column(ForeignKey("org_member.id"))
    environment: Mapped[str | None] = mapped_column(String(16), comment="生产/测试/开发")
    business_owner: Mapped[str | None] = mapped_column(String(64))
    vendor_id: Mapped[str | None] = mapped_column(ForeignKey("vendor.id"))
    description: Mapped[str | None] = mapped_column(Text)
    launch_date: Mapped[date | None] = mapped_column(Date)
    attrs: Mapped[dict | None] = mapped_column(JsonCol, default=dict, comment="类别专属属性")
    remarks: Mapped[str | None] = mapped_column(Text)


class CiRelationship(GlidBase):
    __tablename__ = "ci_relationship"
    __table_args__ = (UniqueConstraint("source_ci_id", "target_ci_id", "relation_type"),)

    source_ci_id: Mapped[str] = mapped_column(ForeignKey("ci.id"), index=True)
    target_ci_id: Mapped[str] = mapped_column(ForeignKey("ci.id"), index=True)
    relation_type: Mapped[str] = mapped_column(String(16), comment="运行于/依赖/连接")


class Problem(GlidBase):
    __tablename__ = "problem"

    problem_code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(8), default="P3")
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    service_item_id: Mapped[str | None] = mapped_column(ForeignKey("service_item.id"))
    root_cause: Mapped[str | None] = mapped_column(Text, comment="转已知错误时必填")
    workaround: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(ForeignKey("org_member.id"))
    source_ticket_id: Mapped[str | None] = mapped_column(String(26), comment="工单升级来源")
    source_requirement_id: Mapped[str | None] = mapped_column(String(26), comment="需求遗留转入(M5)")


class ProblemTicket(GlidBase):
    __tablename__ = "problem_ticket"
    __table_args__ = (UniqueConstraint("problem_id", "ticket_id"),)

    problem_id: Mapped[str] = mapped_column(ForeignKey("problem.id"), index=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("ticket.id"), index=True)


class KnowledgeArticle(GlidBase):
    __tablename__ = "knowledge_article"

    article_code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, comment="Markdown 或净化后的 HTML")
    content_format: Mapped[str] = mapped_column(String(8), default="markdown", comment="markdown/html")
    tags: Mapped[list | None] = mapped_column(JsonCol, default=list)
    status: Mapped[str] = mapped_column(String(16), default="published", comment="draft/published")
    author: Mapped[str | None] = mapped_column(String(26), comment="auth_user.id")
    author_name: Mapped[str | None] = mapped_column(String(64))
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    helpful_count: Mapped[int] = mapped_column(Integer, default=0)
    linked_ticket_ids: Mapped[list | None] = mapped_column(JsonCol, default=list)
    source_requirement_id: Mapped[str | None] = mapped_column(String(26), comment="需求经验转入(M5)")


class KnowledgeVote(GlidBase):
    __tablename__ = "knowledge_vote"
    __table_args__ = (UniqueConstraint("article_id", "person"),)

    article_id: Mapped[str] = mapped_column(ForeignKey("knowledge_article.id"), index=True)
    person: Mapped[str] = mapped_column(String(26), comment="auth_user.id（requester 也可点有用）")
