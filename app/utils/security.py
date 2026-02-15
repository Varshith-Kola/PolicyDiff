"""Security utilities: API key management and JWT token generation.

Uses PyJWT (RFC 7519) for bearer tokens instead of hand-rolled HMAC.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

import jwt


def generate_api_key() -> str:
    """Generate a cryptographically secure API key."""
    return f"pd_{secrets.token_urlsafe(32)}"


def hash_api_key(key: str) -> str:
    """Hash an API key for safe storage using SHA-256."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify_api_key(plain_key: str, hashed_key: str) -> bool:
    """Constant-time comparison of a plain API key against its stored hash."""
    return hmac.compare_digest(hash_api_key(plain_key), hashed_key)


def generate_bearer_token(user_id: int, secret: str, expires_hours: int = 24) -> str:
    """Generate a JWT bearer token (RFC 7519).

    Claims:
      - sub: user ID
      - exp: expiry timestamp (UTC)
      - iat: issued-at timestamp (UTC)
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "exp": now + timedelta(hours=expires_hours),
        "iat": now,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_bearer_token(token: str, secret: str) -> Optional[int]:
    """Verify a JWT bearer token and return the user_id, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return int(payload["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        return None
