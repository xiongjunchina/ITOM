import asyncio
import logging
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
    requirements,
    team_activities,
    team_mgmt,
    tickets,
    vendors_contracts,
)
from app.services import scheduler
from app.services.migrate import run_migrations
from app.services.seed import run_seed
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
        run_seed_examples(db)
        run_seed_team_examples(db)
    from app.services.points import register_subscribers

    register_subscribers()
    task = asyncio.create_task(scheduler.run_forever())
    yield
    task.cancel()


app = FastAPI(title="New_AOM API", version="0.6.0-m6", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", []))
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {"code": "VALIDATION_ERROR", "message": f"参数错误: {loc} {first.get('msg', '')}"},
        },
    )


MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
READONLY_EXEMPT_PREFIXES = ("/api/auth/login", "/api/notifications")  # 登录与已读回执放行


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
          itsm_catalog, itsm_import, tickets, process, problems, cmdb, vendors_contracts, knowledge, projects, requirements, team_activities, team_mgmt):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"success": True, "data": {"status": "ok", "version": app.version}}
