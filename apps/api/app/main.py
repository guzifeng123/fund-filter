from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.compliance import error_envelope
from app.core.config import settings
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.repositories.llm_observability import shutdown_default_llm_event_dispatcher
from app.routers import ai, backtests, dashboard, data, funds, portfolios, risk_assessments, settings as settings_router


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
        if not shutdown_default_llm_event_dispatcher(
            timeout_seconds=settings.llm_observability_shutdown_timeout_seconds
        ):
            logger.warning("llm_provider_event_dispatcher_shutdown_timed_out")


app = FastAPI(title="Fund Analysis API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router, prefix="/api", tags=["dashboard"])
app.include_router(data.router, prefix="/api", tags=["data"])
app.include_router(funds.router, prefix="/api/funds", tags=["funds"])
app.include_router(risk_assessments.router, prefix="/api/risk-assessments", tags=["risk"])
app.include_router(portfolios.router, prefix="/api/portfolios", tags=["portfolios"])
app.include_router(backtests.router, prefix="/api/backtests", tags=["backtests"])
app.include_router(ai.router, prefix="/api/ai", tags=["ai"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code", "HTTP_ERROR"))
        message = str(detail.get("message", "请求处理失败"))
        extra_detail = detail.get("detail")
    else:
        code = "HTTP_ERROR"
        message = str(detail)
        extra_detail = None
    return JSONResponse(
        status_code=exc.status_code,
        content=error_envelope(code=code, message=message, detail=extra_detail),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    detail = jsonable_encoder(
        exc.errors(),
        custom_encoder={BaseException: str},
    )
    return JSONResponse(
        status_code=422,
        content=error_envelope(
            code="VALIDATION_ERROR",
            message="请求参数不符合接口要求",
            detail=detail,
        ),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=error_envelope(
            code="INTERNAL_SERVER_ERROR",
            message="服务暂时不可用，请稍后重试",
            detail={"type": exc.__class__.__name__},
        ),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
