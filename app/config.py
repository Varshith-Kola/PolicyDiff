"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database
    database_url: str = "sqlite:///./data/policydiff.db"

    # OpenAI
    openai_api_key: Optional[str] = None

    # Email / SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    alert_from_email: Optional[str] = None
    alert_to_email: Optional[str] = None

    # Webhook (Slack, Discord, or generic URL)
    webhook_url: Optional[str] = None

    # Scheduling
    check_interval_hours: int = 24

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
