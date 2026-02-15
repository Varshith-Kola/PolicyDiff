"""Authentication middleware and FastAPI dependencies.

Supports three modes:
  1. Static API key (single-user, self-hosted) — set API_KEY in .env
  2. Bearer token (multi-user) — HMAC tokens from /api/auth/login
  3. Google OAuth (multi-user) — bearer tokens issued after Google sign-in

When neither API_KEY nor GOOGLE_CLIENT_ID is configured, auth is disabled.
Static files and health check are always public.
"""

import hmac
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

# Paths that never require authentication
PUBLIC_PATHS = frozenset({
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
})

PUBLIC_PREFIXES = (
    "/static/",
    "/api/auth/",
)


def _is_public_path(path: str) -> bool:
    """Check if a request path is public (no auth required)."""
    if path in PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def _auth_is_enabled() -> bool:
    """Check if any authentication method is configured."""
    settings = get_settings()
    return bool(settings.api_key or settings.google_client_id)


def _verify_bearer(token: str) -> Optional[str]:
    """Verify a bearer token and return the identity string."""
    settings = get_settings()

    # Direct API key match
    if settings.api_key and token == settings.api_key:
        return "api-key"

    # HMAC-based bearer token (issued by API key login or Google OAuth)
    from app.utils.security import verify_bearer_token
    user_id = verify_bearer_token(token, settings.secret_key)
    if user_id is not None:
        return f"user:{user_id}"

    return None


async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[str]:
    """FastAPI dependency that enforces authentication on API routes.

    Returns the authenticated identity string:
      - "api-key" for static API key auth
      - "user:<id>" for bearer token auth (API key login or Google OAuth)
      - None when auth is disabled

    Raises HTTP 401 when auth is enabled but credentials are invalid.
    """
    if not _auth_is_enabled():
        return None

    settings = get_settings()

    # Check for API key in X-API-Key header (timing-safe comparison)
    api_key_header = request.headers.get("x-api-key")
    if api_key_header and settings.api_key and hmac.compare_digest(api_key_header, settings.api_key):
        return "api-key"

    # Check for Bearer token
    if credentials and credentials.credentials:
        identity = _verify_bearer(credentials.credentials)
        if identity:
            return identity

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_user_id(identity: str | None) -> int | None:
    """Extract the numeric user ID from an auth identity string.

    Returns the user ID for 'user:<id>' identities, None otherwise
    (api-key users or auth disabled).
    """
    if identity and identity.startswith("user:"):
        try:
            return int(identity.split(":", 1)[1])
        except (ValueError, IndexError):
            return None
    return None


async def optional_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[str]:
    """Like require_auth but returns None instead of raising on failure."""
    if not _auth_is_enabled():
        return None
    try:
        return await require_auth(request, credentials)
    except HTTPException:
        return None
