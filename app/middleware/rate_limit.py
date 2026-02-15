"""In-memory sliding-window rate limiter middleware.

Limits requests per client IP to prevent abuse of expensive operations
(scraping, LLM calls). Uses a simple token-bucket algorithm stored in memory.

For production multi-instance deployments, replace with Redis-backed limiting.
"""

import logging
import time
from collections import defaultdict
from typing import Dict, List, Tuple

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)


class RateLimiter:
    """In-memory sliding-window rate limiter.

    Tracks request timestamps per (client_ip, route_key) and enforces
    a configurable max_requests within window_seconds.
    """

    def __init__(self):
        # Key: (client_ip, route_key) -> list of timestamps
        self._requests: Dict[Tuple[str, str], List[float]] = defaultdict(list)

    def _cleanup(self, key: Tuple[str, str], window: float, now: float):
        """Remove timestamps older than the window."""
        timestamps = self._requests[key]
        cutoff = now - window
        self._requests[key] = [t for t in timestamps if t > cutoff]

    def check(
        self,
        client_ip: str,
        route_key: str,
        max_requests: int,
        window_seconds: float,
    ) -> bool:
        """Check if the request is allowed. Returns True if allowed."""
        now = time.monotonic()
        key = (client_ip, route_key)
        self._cleanup(key, window_seconds, now)

        if len(self._requests[key]) >= max_requests:
            return False

        self._requests[key].append(now)
        return True

    def remaining(
        self,
        client_ip: str,
        route_key: str,
        max_requests: int,
        window_seconds: float,
    ) -> int:
        """Return the number of remaining requests in the current window."""
        now = time.monotonic()
        key = (client_ip, route_key)
        self._cleanup(key, window_seconds, now)
        return max(0, max_requests - len(self._requests[key]))


# Singleton instance
_limiter = RateLimiter()


def get_client_ip(request: Request) -> str:
    """Extract the client IP from the request, respecting X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(
    request: Request,
    route_key: str,
    max_requests: int = 30,
    window_seconds: float = 60.0,
):
    """Enforce rate limiting. Raises 429 if exceeded.

    Usage in a route:
        rate_limit(request, "check_policy", max_requests=10, window_seconds=60)
    """
    client_ip = get_client_ip(request)
    if not _limiter.check(client_ip, route_key, max_requests, window_seconds):
        remaining = _limiter.remaining(client_ip, route_key, max_requests, window_seconds)
        logger.warning(
            f"Rate limit exceeded for {client_ip} on {route_key} "
            f"({max_requests}/{window_seconds}s)"
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {int(window_seconds)} seconds.",
            headers={
                "Retry-After": str(int(window_seconds)),
                "X-RateLimit-Limit": str(max_requests),
                "X-RateLimit-Remaining": str(remaining),
            },
        )
