"""Application configuration loaded from environment variables.

Centralised settings with validation for all subsystems:
auth, database, LLM, email, webhooks, scheduling, and rate limiting.
"""

import secrets
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ---- Authentication ----
    api_key: Optional[str] = None  # Static API key; auth disabled when unset
    secret_key: str = secrets.token_urlsafe(32)  # For signing bearer tokens

    # ---- Google OAuth 2.0 ----
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # ---- Database ----
    database_url: str = "sqlite:///./data/policydiff.db"

    # ---- OpenAI / LLM ----
    openai_api_key: Optional[str] = None
    llm_max_concurrent: int = 3  # Max concurrent LLM calls (burst control)

    # ---- Email / SMTP ----
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    alert_from_email: Optional[str] = None
    alert_to_email: Optional[str] = None

    # ---- Webhook (Slack, Discord, or generic URL) ----
    webhook_url: Optional[str] = None

    # ---- Scheduling ----
    check_interval_hours: int = 24

    # ---- Rate Limiting ----
    rate_limit_requests: int = 60  # Max requests per window
    rate_limit_window: int = 60  # Window in seconds

    # ---- App ----
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = ""  # Comma-separated origins, empty = same-origin only
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    """Cached singleton accessor for application settings."""
    return Settings()


# Backward-compatible module-level alias
settings = get_settings()
