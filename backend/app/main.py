import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import AppError
from app.db import Base, SessionLocal, engine
from app.routers import (
    admin_misc,
    admin_org,
    admin_rbac,
    admin_users,
    attachments,
    auth,
    cmdb,
    dashboard,
    itsm_catalog,
    itsm_import,
    knowledge,
    members,
    notifications,
    problems,
    process,
    projects,
    perf,
    requirements,
    team_activities,
    team_mgmt,
    tickets,
    vendors_contracts,
    ui_branding,
    integrations,
)
from app.services import scheduler
from app.services.migrate import run_migrations
from app.services.seed import run_seed, run_seed_perf
from app.services.seed_examples import run_seed_examples, run_seed_team_examples
from app.services.seed_itsm import run_seed_itsm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        run_migrations(db)
        run_seed(db)
        run_seed_itsm(db)
        if os.getenv("SEED_EXAMPLES", "0") == "1":
            # 示例教学数据：默认不种（2026-07-12 用户要求干净系统）；演示/测试环境置 1 开启
            run_seed_examples(db)
            run_seed_team_examples(db)
        run_seed_perf(db)
    from app.services.points import register_subscribers

    register_subscribers()
    task = asyncio.create_task(scheduler.run_forever())
    yield
    task.cancel()


app = FastAPI(title="IT运营管理平台 API", version="0.9.0-m9", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    from app.core.i18n import localize_message

    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": {"code": exc.code, "message": localize_message(exc.message)}},
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    from app.core.i18n import get_lang

    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", []))
    prefix = "Invalid parameter" if get_lang() == "en" else "参数错误"
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {"code": "VALIDATION_ERROR", "message": f"{prefix}: {loc} {first.get('msg', '')}"},
        },
    )


MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
READONLY_EXEMPT_PREFIXES = ("/api/auth/login", "/api/notifications")  # 登录与已读回执放行


@app.middleware("http")
async def lang_middleware(request: Request, call_next):
    """按请求头 X-Lang 设置当前语言（zh/en，默认 zh），供 status_name/错误消息本地化。"""
    from app.core.i18n import set_lang

    set_lang(request.headers.get("x-lang", "zh"))
    return await call_next(request)


@app.middleware("http")
async def auditor_readonly_guard(request: Request, call_next):
    """auditor 只读边界：仅持有 auditor（含组授予）的用户禁止一切修改操作。"""
    path = request.url.path
    if (
        request.method in MUTATING_METHODS
        and path.startswith("/api")
        and not path.startswith(READONLY_EXEMPT_PREFIXES)
    ):
        authorization = request.headers.get("authorization", "")
        if authorization.startswith("Bearer "):
            from app.core.security import decode_token
            from app.models import AuthUser
            from app.services.rbac import effective_roles

            user_id = decode_token(authorization[7:])
            if user_id:
                with SessionLocal() as db:
                    user = db.get(AuthUser, user_id)
                    if user and user.is_active:
                        roles = effective_roles(db, user)
                        if roles and roles <= {"auditor"}:
                            return JSONResponse(
                                status_code=403,
                                content={"success": False, "error": {"code": "READ_ONLY", "message": "审计员为只读角色，不能执行修改操作"}},
                            )
    return await call_next(request)


for r in (auth, admin_users, admin_rbac, admin_org, members, admin_misc, notifications, attachments, dashboard,
          itsm_catalog, itsm_import, tickets, process, problems, cmdb, vendors_contracts, knowledge, perf, projects, requirements, team_activities, team_mgmt, ui_branding, integrations):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"success": True, "data": {"status": "ok", "version": app.version}}
