"""平台产品运营 P0 API 输入模型。"""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


Quarter = str
ServiceLifecycle = Literal["candidate", "pilot", "active", "retiring", "retired"]
DemandClass = Literal["business", "product", "technology", "reliability", "compliance"]
CapacityClass = Literal["small", "medium", "large", "expedite"]


class PlatformServiceIn(BaseModel):
    service_item_id: str
    owner_id: str | None = None
    lifecycle: ServiceLifecycle = "candidate"
    value_proposition: str | None = Field(default=None, max_length=2000)
    management_scope: dict = Field(default_factory=dict)


class PlatformServiceUpdate(BaseModel):
    owner_id: str | None = None
    lifecycle: ServiceLifecycle | None = None
    value_proposition: str | None = Field(default=None, max_length=2000)
    management_scope: dict | None = None
    lifecycle_change_reason: str | None = Field(default=None, max_length=1000)


class PlatformDemandIn(BaseModel):
    requirement_id: str
    service_item_id: str
    business_domain_id: str
    demand_class: DemandClass
    expected_outcome: str = Field(min_length=1, max_length=4000)
    target_quarter: Quarter = Field(pattern=r"^\d{4}-Q[1-4]$")
    capacity_class: CapacityClass


class PlatformDemandUpdate(BaseModel):
    service_item_id: str | None = None
    business_domain_id: str | None = None
    demand_class: DemandClass | None = None
    expected_outcome: str | None = Field(default=None, min_length=1, max_length=4000)
    target_quarter: Quarter | None = Field(default=None, pattern=r"^\d{4}-Q[1-4]$")
    capacity_class: CapacityClass | None = None


class CapacityPlanIn(BaseModel):
    service_item_id: str
    period: Quarter = Field(pattern=r"^\d{4}-Q[1-4]$")
    gross_days: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    planned_unavailable_days: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    bau_reserve_days: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    risk_buffer_days: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_net_capacity(self):
        reserved = self.planned_unavailable_days + self.bau_reserve_days + self.risk_buffer_days
        if reserved > self.gross_days:
            raise ValueError("不可用、BAU 预留和风险缓冲之和不能超过总容量")
        return self


class CapacityPlanUpdate(BaseModel):
    gross_days: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    planned_unavailable_days: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    bau_reserve_days: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    risk_buffer_days: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    notes: str | None = Field(default=None, max_length=4000)


class CapacityCommitmentIn(BaseModel):
    subject_type: Literal["requirement", "roadmap", "reliability", "enablement"]
    subject_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    commitment_type: Literal["demand", "roadmap", "reliability", "enablement"]
    capacity_days: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    lifecycle_stage: Literal["demand", "build", "run"]
    investment_intent: Literal["run", "grow", "transform"]
    owner_id: str | None = None
    status: Literal["planned", "active", "completed", "cancelled"] = "planned"
    allow_overcommit: bool = False
    over_capacity_reason: str | None = Field(default=None, max_length=1000)


class CapacityApprovalIn(BaseModel):
    reason: str = Field(min_length=2, max_length=1000)


class CapacityRevisionIn(CapacityPlanIn):
    revision_reason: str = Field(min_length=2, max_length=1000)
