"""MCP 请求级身份上下文。"""
from contextvars import ContextVar
from dataclasses import dataclass

from app.core.errors import AppError


@dataclass(frozen=True)
class AilyPrincipal:
    auth_user_id: str
    tenant_id: str
    app_id: str
    agent_id: str
    subject_type: str
    subject_id: str
    session_ref_hash: str | None


current_aily_principal: ContextVar[AilyPrincipal | None] = ContextVar(
    "current_aily_principal",
    default=None,
)


def require_aily_principal() -> AilyPrincipal:
    principal = current_aily_principal.get()
    if principal is None:
        raise AppError("AILY_CONTEXT_MISSING", "Aily 身份上下文不存在", 401)
    return principal
