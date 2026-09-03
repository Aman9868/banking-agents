"""Main FastAPI Application for Enterprise AI Banking Agent."""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from apps.api.config import settings
from apps.api.routes.chat import router as chat_router
from apps.api.routes.admin import router as admin_router
from apps.api.routes.health import router as health_router
from security.headers import SecurityHeadersMiddleware
from security.tracing import CorrelationIdMiddleware
from gateway.rate_limit.limiter import RateLimitMiddleware
from database.init_db import init_database, seed_mock_data
import structlog

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context for startup and shutdown procedures."""
    logger.info("Starting Banking Agent API", environment=settings.ENVIRONMENT)
    try:
        await init_database()
        await seed_mock_data()
        logger.info("Database initialized and verified.")
    except Exception as exc:
        logger.error("Database initialization warning during startup", error=str(exc))
    yield
    logger.info("Shutting down Banking Agent API")


app = FastAPI(
    title="AI Banking Agent — Enterprise Operating Layer",
    description="Conversational enterprise banking orchestration with LangGraph, deterministic policy engines, and role-based tool gateways.",
    version="1.0.0",
    lifespan=lifespan
)

# Mandatory Web Security Middleware
app.add_middleware(SecurityHeadersMiddleware)

# Production Request Correlation and Distributed Tracing
app.add_middleware(CorrelationIdMiddleware)

# Redis Sliding-Window Rate Limiter
app.add_middleware(RateLimitMiddleware, requests_per_minute=120)

# CORS Policy - strictly scoped
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# Global Exception Handler (Never leak stack traces or internal DB details to client)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled server exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal system error occurred. Please contact customer support."}
    )


# Register Routers
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(admin_router)

# Mount ChatGPT-Style Frontend UI
import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    @app.api_route("/chat", methods=["GET", "HEAD"], include_in_schema=False)
    async def serve_chat_ui():
        index_file = os.path.join(static_dir, "index.html")
        return FileResponse(index_file)


