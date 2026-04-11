"""FastAPI application entry point for the Workflow Automation Engine.

Creates the FastAPI app with CORS, rate limiting, auth middleware,
error handlers, and registers all API routers. Uses lifespan for
startup/shutdown hooks.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.executions import router as executions_router
from src.api.health import router as health_router
from src.api.middleware.auth import AuthMiddleware
from src.api.middleware.errors import (
    app_error_handler,
    http_exception_handler,
    unhandled_exception_handler,
)
from src.api.middleware.rate_limit import RateLimitMiddleware
from src.api.tenants import router as tenants_router
from src.api.webhooks import router as webhooks_router
from src.api.workflows import router as workflows_router
from src.config import settings
from src.db.postgres import dispose_engine
from src.db.redis import close_redis
from src.lib.logger import configure_logging, get_logger
from src.lib.utils import AppError

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler for startup and shutdown events.

    Startup: configure logging, initialize connections (future).
    Shutdown: close connections and clean up resources (future).
    """
    configure_logging()
    logger.info(
        "app_startup",
        env=settings.env,
        host=settings.host,
        port=settings.port,
    )
    yield
    logger.info("app_shutdown")
    await dispose_engine()
    await close_redis()


app = FastAPI(
    title="Workflow Automation Engine",
    description="Backend engine for executing multi-step DAG workflows.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — permissive in development, restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_development else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting — Redis sliding window counter, per-route limits
app.add_middleware(RateLimitMiddleware)

# Auth middleware — validates X-API-Key header on protected paths
app.add_middleware(AuthMiddleware)

# Wire error handlers into the app
app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]

# Register API routers
app.include_router(health_router)
app.include_router(tenants_router)
app.include_router(workflows_router)
app.include_router(executions_router)
app.include_router(webhooks_router)
