"""Request/response logging middleware for observability."""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("policydiff.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every HTTP request with method, path, status code, and latency."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Skip logging for static assets to reduce noise
        path = request.url.path
        if path.startswith("/static/"):
            return response

        logger.info(
            "%s %s %d %.1fms",
            request.method,
            path,
            response.status_code,
            elapsed_ms,
        )
        return response
