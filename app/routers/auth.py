"""Authentication API routes.

Provides endpoints for API key validation and bearer token exchange.
When API_KEY is not configured, all endpoints return appropriate messages.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from app.config import get_settings
from app.schemas import AuthLoginRequest, AuthLoginResponse
from app.utils.security import generate_bearer_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=AuthLoginResponse)
def login(data: AuthLoginRequest):
    """Exchange an API key for a bearer token.

    The bearer token is valid for 24 hours and can be used in the
    Authorization header for subsequent requests.
    """
    settings = get_settings()

    if not settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Authentication is not configured. Set API_KEY in your environment.",
        )

    if data.api_key != settings.api_key:
        logger.warning("Failed login attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    token = generate_bearer_token(user_id=1, secret=settings.secret_key, expires_hours=24)
    logger.info("Bearer token issued")
    return AuthLoginResponse(token=token)


@router.get("/status")
def auth_status():
    """Check whether authentication is enabled and which methods are available."""
    settings = get_settings()
    api_key_enabled = bool(settings.api_key)
    google_enabled = bool(settings.google_client_id and settings.google_client_secret)
    any_auth = api_key_enabled or google_enabled

    return {
        "auth_enabled": any_auth,
        "api_key_enabled": api_key_enabled,
        "google_enabled": google_enabled,
        "message": (
            "Authentication is enabled."
            if any_auth
            else "Authentication is disabled. Set API_KEY or GOOGLE_CLIENT_ID in .env to enable."
        ),
    }
