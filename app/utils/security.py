"""Security utilities: API key management and token generation."""

import hashlib
import hmac
import secrets
import time
from typing import Optional


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
    """Generate a simple HMAC-based bearer token.

    Format: <user_id>:<expiry_timestamp>:<hmac_signature>
    """
    expires_at = int(time.time()) + (expires_hours * 3600)
    payload = f"{user_id}:{expires_at}"
    signature = hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{payload}:{signature}"


def verify_bearer_token(token: str, secret: str) -> Optional[int]:
    """Verify a bearer token and return the user_id, or None if invalid/expired."""
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return None
        user_id_str, expires_str, signature = parts
        user_id = int(user_id_str)
        expires_at = int(expires_str)

        # Check signature
        expected_payload = f"{user_id}:{expires_at}"
        expected_sig = hmac.new(
            secret.encode("utf-8"), expected_payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None

        # Check expiry
        if time.time() > expires_at:
            return None

        return user_id
    except (ValueError, IndexError):
        return None
