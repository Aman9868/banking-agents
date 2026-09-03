"""HTTP Security Headers Middleware for Enterprise Banking API."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces strict OWASP-compliant security headers on all responses."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # Anti-sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Anti-clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Content Security Policy (allows Tailwind CDN and Lucide icons while restricting objects & frames)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self' https://cdn.tailwindcss.com https://unpkg.com; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
            "img-src 'self' data:; font-src 'self' data:; frame-ancestors 'none'; object-src 'none';"
        )

        # Disable browser caching for sensitive banking API responses
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"

        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions policy
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        return response

