"""内嵌 FastMCP Server、Aily JWT 中间件和 P0 身份诊断工具。"""
from contextlib import asynccontextmanager
import hashlib
import json
from time import perf_counter

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from app.core.errors import AppError
from app.core.glid import new_glid
from app.db import SessionLocal
from app.mcp.context import current_aily_principal, require_aily_principal
from app.mcp.identity import resolve_aily_principal, validate_aily_request_source
from app.mcp.tools import BUSINESS_TOOLS
from app.models import AuthUser, McpToolCall


def get_current_user_context() -> dict:
    """验证 Aily 身份已映射到活动 ITOM 账号；不返回任何内部或外部标识 ID。"""
    started = perf_counter()
    principal = require_aily_principal()
    call_id = new_glid()
    request_digest = hashlib.sha256(b"{}").hexdigest()
    external_subject = (
        f"{principal.subject_type}:sha256:"
        f"{hashlib.sha256(principal.subject_id.encode()).hexdigest()}"
    )
    with SessionLocal() as db:
        user = db.get(AuthUser, principal.auth_user_id)
        if not user or not user.is_active or user.is_deleted:
            result_code = "AILY_ITOM_ACCOUNT_DISABLED"
            db.add(McpToolCall(
                call_id=call_id,
                tool_name="get_current_user_context",
                tenant_id=principal.tenant_id,
                agent_id=principal.agent_id,
                external_subject=external_subject,
                auth_user_id=principal.auth_user_id,
                session_ref_hash=principal.session_ref_hash,
                request_digest=request_digest,
                result_code=result_code,
                duration_ms=int((perf_counter() - started) * 1000),
            ))
            db.commit()
            raise AppError(result_code, "映射的 ITOM 账号不存在或已停用", 403)
        result = {
            "success": True,
            "phase": "P0",
            "identity_verified": True,
            "account_status": "active",
            "account_name": user.person.name if user.person else user.username,
            "message": "当前 Aily 用户已映射到活动 ITOM 账号。",
        }
        db.add(McpToolCall(
            call_id=call_id,
            tool_name="get_current_user_context",
            tenant_id=principal.tenant_id,
            agent_id=principal.agent_id,
            external_subject=external_subject,
            auth_user_id=principal.auth_user_id,
            session_ref_hash=principal.session_ref_hash,
            request_digest=request_digest,
            result_code="OK",
            duration_ms=int((perf_counter() - started) * 1000),
        ))
        db.commit()
        return result


class AilyMcpAuthMiddleware:
    """纯 ASGI 中间件，区分协议发现与真实工具调用。

    Aily 在首次保存自定义 MCP 后才展示 JWT 验签密钥，因此注册校验期间的
    initialize/list 请求只校验启用状态与 Origin。任何 tools/call 仍必须通过
    JWT、租户/Agent 白名单、外部身份映射和 ITOM 账号状态校验。
    """

    DISCOVERY_METHODS = frozenset({
        "initialize",
        "notifications/initialized",
        "ping",
        "tools/list",
        "resources/list",
        "resources/templates/list",
        "prompts/list",
    })

    def __init__(self, app):
        self.app = app

    @staticmethod
    async def _capture_body(receive):
        messages = []
        body = bytearray()
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.request":
                body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                break

        async def replay_receive():
            if messages:
                return messages.pop(0)
            return await receive()

        return bytes(body), replay_receive

    @classmethod
    def _is_discovery_request(cls, http_method: str, body: bytes) -> bool:
        if http_method in {"GET", "DELETE"}:
            return True
        if http_method != "POST" or not body:
            return False
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        requests = payload if isinstance(payload, list) else [payload]
        return bool(requests) and all(
            isinstance(item, dict) and item.get("method") in cls.DISCOVERY_METHODS
            for item in requests
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        replay_receive = receive
        body = b""
        if scope.get("method") == "POST":
            body, replay_receive = await self._capture_body(receive)
        discovery_request = self._is_discovery_request(scope.get("method", ""), body)
        headers = Headers(scope=scope)
        principal = None
        try:
            with SessionLocal() as db:
                if discovery_request:
                    validate_aily_request_source(db, origin=headers.get("origin"))
                else:
                    principal = resolve_aily_principal(
                        db,
                        token=headers.get("x-aily-jwt", ""),
                        origin=headers.get("origin"),
                        session_ref=headers.get("mcp-session-id"),
                    )
        except AppError as exc:
            response = JSONResponse(
                status_code=exc.status_code,
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32001, "message": exc.message, "data": {"code": exc.code}},
                },
            )
            await response(scope, receive, send)
            return
        if principal is None:
            await self.app(scope, replay_receive, send)
            return
        token = current_aily_principal.set(principal)
        try:
            await self.app(scope, replay_receive, send)
        finally:
            current_aily_principal.reset(token)


def build_mcp_server() -> FastMCP:
    """创建一次性的 FastMCP 协议实例；官方会话管理器不允许退出后复用。"""
    server = FastMCP(
        name="ITOM Aily MCP",
        instructions=(
            "ITOM 是服务目录、表单、权限、流程和业务状态的唯一依据。"
            "当前开放服务项检索、真实表单、服务请求提交、IT 需求登记、本人单据查询，"
            "以及服务请求解决确认、重开和评价闭环。"
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        # 动态 Origin 白名单由下层 Aily 身份中间件从数据库读取；SDK 的静态
        # localhost Host 白名单无法覆盖每次变化的 ngrok 公网域名。
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    server.tool()(get_current_user_context)
    for tool in BUSINESS_TOOLS:
        server.tool()(tool)
    return server


class AilyMcpRuntime:
    """可随 FastAPI 生命周期重建的 MCP ASGI 代理。

    生产进程通常只启动一次；测试和开发热重载会重复进入 lifespan，因此每次
    都创建新的 FastMCP 会话管理器，避免复用已关闭的 task group。
    """

    def __init__(self):
        self.server: FastMCP | None = None
        self.asgi_app = None

    @asynccontextmanager
    async def run(self):
        self.server = build_mcp_server()
        self.asgi_app = AilyMcpAuthMiddleware(self.server.streamable_http_app())
        try:
            async with self.server.session_manager.run():
                yield
        finally:
            self.asgi_app = None
            self.server = None

    async def __call__(self, scope, receive, send):
        if self.asgi_app is None:
            response = JSONResponse(
                status_code=503,
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32002, "message": "MCP runtime is not ready"},
                },
            )
            await response(scope, receive, send)
            return
        await self.asgi_app(scope, receive, send)


mcp_runtime = AilyMcpRuntime()
