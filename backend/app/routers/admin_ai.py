"""Administrator-only WA0 AI governance API."""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_perm
from app.models import AuthUser
from app.schemas.common import ok
from app.services import assistant_config


router = APIRouter(prefix="/api/admin/ai", tags=["admin-ai"])


class ProviderCreateIn(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=128)
    provider_type: Literal["openai_compatible"] = "openai_compatible"
    api_base_url: str = Field(min_length=1, max_length=300)
    api_key: str | None = Field(default=None, max_length=8192)
    model: str = Field(min_length=1, max_length=128)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_output_tokens: int = Field(default=2048, ge=1, le=65536)
    temperature: float | None = Field(default=None, ge=0, le=2)
    is_primary: bool = False
    fallback_provider_id: str | None = None
    enabled: bool = False

    @field_validator("name", "model")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class ProviderUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    provider_type: Literal["openai_compatible"] | None = None
    api_base_url: str | None = Field(default=None, min_length=1, max_length=300)
    api_key: str | None = Field(default=None, max_length=8192)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    max_output_tokens: int | None = Field(default=None, ge=1, le=65536)
    temperature: float | None = Field(default=None, ge=0, le=2)
    is_primary: bool | None = None
    fallback_provider_id: str | None = None
    enabled: bool | None = None

    @field_validator("name", "model")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class ProfileDraftUpdateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    expected_updated_at: datetime
    name: str | None = Field(default=None, min_length=1, max_length=128)
    default_provider_id: str | None = None
    retention_days: int | None = Field(default=None, ge=0, le=90)
    enabled: bool | None = None
    system_prompt_zh: str | None = Field(default=None, max_length=20000)
    system_prompt_en: str | None = Field(default=None, max_length=20000)
    enabled_capabilities: list[str] | None = Field(default=None, max_length=256)
    knowledge_scope: list[str] | None = Field(default=None, max_length=64)
    max_risk_level: str | None = Field(default=None, pattern=r"^L[1-4]$")


class ProfilePublishIn(BaseModel):
    expected_draft_updated_at: datetime


class ProfileRollbackIn(BaseModel):
    version: int = Field(ge=1)
    expected_latest_version: int = Field(ge=1)


@router.get("/providers")
def list_providers(db: Session = Depends(get_db), _: AuthUser = Depends(require_perm("admin_ai", "view"))):
    return ok(assistant_config.list_providers(db))


@router.post("/providers")
def create_provider(
    body: ProviderCreateIn,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("admin_ai", "edit")),
):
    return ok(assistant_config.create_provider(db, body.model_dump(), actor))


@router.patch("/providers/{provider_id}")
def update_provider(
    provider_id: str,
    body: ProviderUpdateIn,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("admin_ai", "edit")),
):
    return ok(assistant_config.update_provider(db, provider_id, body.model_dump(exclude_unset=True), actor))


@router.delete("/providers/{provider_id}")
def delete_provider(
    provider_id: str,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("admin_ai", "delete")),
):
    return ok(assistant_config.delete_provider(db, provider_id, actor))


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: str,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("admin_ai", "edit")),
):
    return ok(await assistant_config.probe_provider(db, provider_id, actor))


@router.get("/profiles/{code}/draft")
def get_profile_draft(
    code: str,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("admin_ai", "view")),
):
    return ok(assistant_config.get_profile_draft(db, code, actor))


@router.patch("/profiles/{code}/draft")
def update_profile_draft(
    code: str,
    body: ProfileDraftUpdateIn,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("admin_ai", "edit")),
):
    values = body.model_dump(exclude_unset=True, exclude={"expected_updated_at"})
    return ok(assistant_config.update_profile_draft(db, code, values, body.expected_updated_at, actor))


@router.post("/profiles/{code}/publish")
def publish_profile(
    code: str,
    body: ProfilePublishIn,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("admin_ai", "edit")),
):
    return ok(assistant_config.publish_profile(db, code, body.expected_draft_updated_at, actor))


@router.post("/profiles/{code}/rollback")
def rollback_profile(
    code: str,
    body: ProfileRollbackIn,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_perm("admin_ai", "edit")),
):
    return ok(assistant_config.rollback_profile(db, code, body.version, body.expected_latest_version, actor))


@router.get("/health")
def health(db: Session = Depends(get_db), _: AuthUser = Depends(require_perm("admin_ai", "view"))):
    return ok(assistant_config.health_summary(db))


@router.get("/usage")
def usage(
    days: int = Query(default=30, ge=1, le=90),
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_perm("admin_ai", "view")),
):
    return ok(assistant_config.usage_summary(db, days=days))


@router.get("/action-audits")
def action_audits(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status: str | None = Query(default=None, max_length=16),
    capability_code: str | None = Query(default=None, max_length=96),
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_perm("admin_ai", "view")),
):
    rows, total = assistant_config.action_audits(
        db,
        page=page,
        page_size=page_size,
        status=status,
        capability_code=capability_code,
    )
    return ok(rows, total=total, page=page)
