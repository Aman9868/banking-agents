"""End-to-end request correlation and distributed tracing middleware."""

import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import structlog

logger = structlog.get_logger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware that injects and propagates X-Correlation-ID across all requests."""

    async def dispatch(self, request: Request, call_next):
        # 1. Read existing correlation ID from incoming request or generate a new UUID
        correlation_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID")
        if not correlation_id:
            correlation_id = f"corr-{uuid.uuid4().hex[:12]}"

        # 2. Bind correlation ID into structlog contextvars for consistent logging
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        # 3. Process request
        response: Response = await call_next(request)

        # 4. Attach correlation ID to outgoing response headers
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Request-ID"] = correlation_id

        # 5. Clear contextvars after request completes
        structlog.contextvars.unbind_contextvars("correlation_id")

        return response

