import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.core.models import User
from app.modules.attachments.router import router as attachments_router
from app.modules.exam.router import router as exam_router
from app.modules.finance.entitlements import router as entitlement_router
from app.modules.finance.router import router as finance_router
from app.modules.iam.router import Db, require_permission, router
from app.modules.sprint1.router import router as sprint1_router
from app.modules.teaching.router import router as teaching_router

Admin = Annotated[User, Depends(require_permission("system.admin"))]

app = FastAPI(docs_url=None if get_settings().app_env == "production" else "/api/docs")
app.include_router(router)
app.include_router(sprint1_router)
app.include_router(attachments_router)
app.include_router(exam_router)
app.include_router(teaching_router)
app.include_router(finance_router)
app.include_router(entitlement_router)


@app.middleware("http")
async def correlation_id(request: Request, call_next):  # noqa: ANN001
    request.state.correlation_id = str(uuid.uuid4())
    if (
        request.method not in {"GET", "HEAD", "OPTIONS"}
        and request.url.path.startswith("/api/")
        and request.url.path != "/api/auth/login"
    ):
        csrf_cookie = request.cookies.get("csrf_token")
        csrf_header = request.headers.get("X-CSRF-Token")
        if not csrf_cookie or csrf_cookie != csrf_header:
            return JSONResponse(status_code=403, content={"code": "CSRF_INVALID"})
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = request.state.correlation_id
    return response


@app.get("/api/health/live")
def live() -> dict:
    return {"status": "ok"}


@app.get("/api/health/ready")
def ready(db: Db) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/api/admin/ping")
def admin_ping(_user: Admin) -> dict:
    return {"status": "ok"}


@app.exception_handler(500)
async def internal_error(_request: Request, _error: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"code": "INTERNAL_ERROR"})


@app.exception_handler(OperationalError)
async def database_error(_request: Request, error: OperationalError) -> JSONResponse:
    if "database is locked" in str(error).lower():
        return JSONResponse(
            status_code=503,
            content={"code": "DATABASE_BUSY", "message": "数据库正忙，请稍后重试。"},
        )
    return JSONResponse(status_code=500, content={"code": "DATABASE_ERROR"})
