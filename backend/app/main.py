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
    admin_rbac,
    admin_users,
    attachments,
    auth,
    dashboard,
    itsm_catalog,
    members,
    notifications,
    process,
    tickets,
)
from app.services import scheduler
from app.services.seed import run_seed
from app.services.seed_itsm import run_seed_itsm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        run_seed(db)
        run_seed_itsm(db)
    task = asyncio.create_task(scheduler.run_forever())
    yield
    task.cancel()


app = FastAPI(title="New_AOM API", version="0.2.5-m2.5", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")


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


for r in (auth, admin_users, admin_rbac, members, admin_misc, notifications, attachments, dashboard, itsm_catalog, tickets, process):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"success": True, "data": {"status": "ok", "version": app.version}}
