from datetime import datetime

from pydantic import BaseModel, Field


class CatalogCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    tier: str = "silver"
    description: str | None = None
    sort: int = 0


class CatalogUpdate(BaseModel):
    name: str | None = None
    tier: str | None = None
    description: str | None = None
    sort: int | None = None
    status: str | None = None


class ServiceItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    catalog_id: str
    service_type: str | None = None
    owner: str | None = None
    description: str | None = None
    sla_response_hours: float | None = None
    sla_resolution_hours: float | None = None
    target_audience: str | None = None


class ServiceItemUpdate(BaseModel):
    name: str | None = None
    catalog_id: str | None = None
    service_type: str | None = None
    owner: str | None = None
    description: str | None = None
    sla_response_hours: float | None = None
    sla_resolution_hours: float | None = None
    target_audience: str | None = None
    status: str | None = None


class TicketCreate(BaseModel):
    # 5 必填（PRD §5.1）
    title: str = Field(min_length=2, max_length=200)
    ticket_type: str
    priority: str = "P3"
    description: str = Field(min_length=1)
    service_item_id: str
    # 可选
    assignee: str | None = None
    ci_id: str | None = None
    remarks: str | None = None
    # 变更条件字段
    change_type: str | None = None
    risk_level: str | None = None
    change_reason: str | None = None
    rollback_plan: str | None = None
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    implementation_plan: str | None = None


class TicketUpdate(BaseModel):
    title: str | None = None
    priority: str | None = None
    description: str | None = None
    assignee: str | None = None
    ci_id: str | None = None
    remarks: str | None = None
    root_cause: str | None = None
    change_type: str | None = None
    risk_level: str | None = None
    change_reason: str | None = None
    rollback_plan: str | None = None
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    implementation_plan: str | None = None


class TransitionIn(BaseModel):
    to: str
    fields: dict = {}


class SatisfactionIn(BaseModel):
    score: int = Field(ge=1, le=5)


class SlaPolicyIn(BaseModel):
    priority: str
    response_minutes: int = Field(gt=0)
    resolution_hours: float = Field(gt=0)
    active: bool = True
