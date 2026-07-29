"""P1 Aily MCP 业务工具；所有入口统一鉴权、审计和事务提交。"""

from dataclasses import dataclass
import hashlib
import logging
from time import perf_counter
from typing import Callable

from app.core.errors import AppError
from app.core.glid import new_glid
from app.db import SessionLocal
from app.mcp.context import require_aily_principal
from app.models import AuthUser, McpToolCall, Requirement, Ticket
from app.services import requirement_intake, service_request_intake
from app.services.mcp_intents import payload_digest
from app.services.permissions import has_perm


logger = logging.getLogger("aom.mcp.tools")


@dataclass
class ToolOutcome:
    data: dict
    entity_type: str | None = None
    entity_id: str | None = None


def _execute(tool_name: str, params: dict, handler: Callable) -> dict:
    started = perf_counter()
    principal = require_aily_principal()
    request_digest = payload_digest(params)
    external_subject = (
        f"{principal.subject_type}:sha256:"
        f"{hashlib.sha256(principal.subject_id.encode()).hexdigest()}"
    )
    result_code = "OK"
    outcome = ToolOutcome({})
    with SessionLocal() as db:
        try:
            user = db.get(AuthUser, principal.auth_user_id)
            if not user or not user.is_active or user.is_deleted:
                raise AppError("AILY_ITOM_ACCOUNT_DISABLED", "映射的 ITOM 账号不存在或已停用", 403)
            outcome = handler(db, user)
            result = {"success": True, **outcome.data}
        except AppError as exc:
            db.rollback()
            result_code = exc.code
            result = {
                "success": False,
                "error": {"code": exc.code, "message": exc.message},
            }
            outcome = ToolOutcome({})
        except Exception as exc:
            db.rollback()
            logger.error("MCP tool %s failed (%s)", tool_name, exc.__class__.__name__)
            result_code = "INTERNAL_ERROR"
            result = {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": "ITOM 处理失败，请稍后重试"},
            }
            outcome = ToolOutcome({})
        db.add(McpToolCall(
            call_id=new_glid(),
            tool_name=tool_name,
            tenant_id=principal.tenant_id,
            agent_id=principal.agent_id,
            external_subject=external_subject,
            auth_user_id=principal.auth_user_id,
            session_ref_hash=principal.session_ref_hash,
            request_digest=request_digest,
            result_code=result_code,
            entity_type=outcome.entity_type,
            entity_id=outcome.entity_id,
            duration_ms=int((perf_counter() - started) * 1000),
        ))
        db.commit()
        return result


def _require_perm(db, user, module: str, action: str) -> None:
    if not has_perm(db, user, module, action):
        raise AppError("FORBIDDEN", "当前账号无此操作权限", 403)


def search_service_items(query: str, limit: int = 5) -> dict:
    """按用户诉求实时检索当前账号可申请的 ITOM 服务项。"""
    params = {"query": query, "limit": limit}
    return _execute(
        "search_service_items",
        params,
        lambda db, user: ToolOutcome({"items": service_request_intake.search_items(db, user, query, limit)}),
    )


def get_service_item_form(service_item_id: str) -> dict:
    """返回指定服务项的已发布真实表单、SLA、流程和预计支持队列。"""
    return _execute(
        "get_service_item_form",
        {"service_item_id": service_item_id},
        lambda db, user: ToolOutcome(service_request_intake.item_form(db, user, service_item_id)),
    )


def prepare_service_request(service_item_id: str, answers: dict, idempotency_key: str) -> dict:
    """校验服务请求表单并生成最终预览；仅在字段齐全时返回短期确认凭证。"""
    def handler(db, user):
        _require_perm(db, user, "ticket_sr", "create")
        return ToolOutcome(service_request_intake.prepare_request(
            db, user, service_item_id, answers, idempotency_key
        ))

    return _execute(
        "prepare_service_request",
        {"service_item_id": service_item_id, "answers": answers, "idempotency_key": idempotency_key},
        handler,
    )


def submit_service_request(confirmation_token: str, idempotency_key: str) -> dict:
    """在用户确认预览后幂等创建 service_request；不能创建 IT 事件或变更。"""
    def handler(db, user):
        _require_perm(db, user, "ticket_sr", "create")
        result, ticket = service_request_intake.submit_request(
            db, user, confirmation_token, idempotency_key
        )
        return ToolOutcome(result, "ticket" if ticket else None, ticket.id if ticket else None)

    return _execute(
        "submit_service_request",
        {"confirmation_token": confirmation_token, "idempotency_key": idempotency_key},
        handler,
    )


def get_my_service_request(ticket_code: str) -> dict:
    """查询当前 Aily 用户本人提交的一张服务请求。"""
    def handler(db, user):
        _require_perm(db, user, "ticket_sr", "view")
        ticket = service_request_intake.own_ticket(db, user, ticket_code)
        return ToolOutcome({"ticket": service_request_intake.ticket_summary(ticket)}, "ticket", ticket.id)

    return _execute("get_my_service_request", {"ticket_code": ticket_code}, handler)


def list_my_service_requests(limit: int = 20) -> dict:
    """列出当前 Aily 用户本人最近提交的服务请求。"""
    def handler(db, user):
        _require_perm(db, user, "ticket_sr", "view")
        safe_limit = min(max(int(limit or 20), 1), 50)
        rows = (
            db.query(Ticket)
            .filter(
                Ticket.ticket_type == "service_request",
                Ticket.submitter == user.id,
                Ticket.is_deleted.is_(False),
            )
            .order_by(Ticket.submitted_at.desc())
            .limit(safe_limit)
            .all()
        )
        return ToolOutcome({"items": [service_request_intake.ticket_summary(row) for row in rows]})

    return _execute("list_my_service_requests", {"limit": limit}, handler)


def get_it_requirement_form() -> dict:
    """返回 ITOM 的 IT 需求登记字段和当前有效业务域。"""
    def handler(db, user):
        _require_perm(db, user, "requirements", "create")
        return ToolOutcome(requirement_intake.form_definition(db))

    return _execute("get_it_requirement_form", {}, handler)


def prepare_it_requirement(fields: dict, idempotency_key: str) -> dict:
    """校验 IT 需求登记字段并生成最终预览和短期确认凭证。"""
    def handler(db, user):
        _require_perm(db, user, "requirements", "create")
        return ToolOutcome(requirement_intake.prepare_requirement(db, user, fields, idempotency_key))

    return _execute(
        "prepare_it_requirement",
        {"fields": fields, "idempotency_key": idempotency_key},
        handler,
    )


def register_it_requirement(confirmation_token: str, idempotency_key: str) -> dict:
    """在用户确认后幂等登记 IT 需求并进入 ITOM 需求评估流程。"""
    def handler(db, user):
        _require_perm(db, user, "requirements", "create")
        result, requirement = requirement_intake.register_requirement(
            db, user, confirmation_token, idempotency_key
        )
        return ToolOutcome(
            result,
            "requirement" if requirement else None,
            requirement.id if requirement else None,
        )

    return _execute(
        "register_it_requirement",
        {"confirmation_token": confirmation_token, "idempotency_key": idempotency_key},
        handler,
    )


def get_my_it_requirement(requirement_code: str) -> dict:
    """查询当前 Aily 用户本人登记的一条 IT 需求。"""
    def handler(db, user):
        _require_perm(db, user, "requirements", "view")
        requirement = requirement_intake.own_requirement(db, user, requirement_code)
        return ToolOutcome(
            {"requirement": requirement_intake.requirement_summary(db, requirement)},
            "requirement",
            requirement.id,
        )

    return _execute("get_my_it_requirement", {"requirement_code": requirement_code}, handler)


def list_my_it_requirements(limit: int = 20) -> dict:
    """列出当前 Aily 用户本人最近登记的 IT 需求。"""
    def handler(db, user):
        _require_perm(db, user, "requirements", "view")
        safe_limit = min(max(int(limit or 20), 1), 50)
        rows = (
            db.query(Requirement)
            .filter(Requirement.requester == user.id, Requirement.is_deleted.is_(False))
            .order_by(Requirement.registered_at.desc())
            .limit(safe_limit)
            .all()
        )
        return ToolOutcome({"items": [requirement_intake.requirement_summary(db, row) for row in rows]})

    return _execute("list_my_it_requirements", {"limit": limit}, handler)


P1_TOOLS = (
    search_service_items,
    get_service_item_form,
    prepare_service_request,
    submit_service_request,
    get_my_service_request,
    list_my_service_requests,
    get_it_requirement_form,
    prepare_it_requirement,
    register_it_requirement,
    get_my_it_requirement,
    list_my_it_requirements,
)
