"""Pydantic schemas for API request/response validation.

All schemas use strict field types and validators to prevent invalid data
from reaching the database or service layer.
"""

from enum import Enum
from typing import Annotated, Optional, List

from pydantic import BaseModel, Field, field_validator, AfterValidator
from datetime import datetime, timezone


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC).

    SQLite returns naive datetimes even with timezone=True columns.
    Without this, JSON serializes as '2026-02-12T00:49:12' (no offset),
    and browsers interpret that as local time instead of UTC.
    With this fix, output is '2026-02-12T00:49:12+00:00' which JavaScript
    correctly interprets as UTC and converts to the user's local timezone.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# Use this instead of `datetime` for all response fields
UTCDatetime = Annotated[datetime, AfterValidator(_ensure_utc)]


# ---- Enums for strong typing ----

class PolicyType(str, Enum):
    privacy_policy = "privacy_policy"
    terms_of_service = "terms_of_service"


class Severity(str, Enum):
    informational = "informational"
    concerning = "concerning"
    action_needed = "action-needed"


class SeedStatus(str, Enum):
    none = "none"
    seeding = "seeding"
    seeded = "seeded"
    seed_failed = "seed_failed"


# ---- Auth Schemas ----

class AuthLoginRequest(BaseModel):
    api_key: str = Field(..., min_length=1, description="API key for authentication")


class AuthLoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"


# ---- User / OAuth Schemas ----

class UserResponse(BaseModel):
    id: int
    email: str
    name: Optional[str] = None
    picture_url: Optional[str] = None
    is_active: bool
    gdpr_consent_at: Optional[UTCDatetime] = None
    created_at: UTCDatetime
    followed_policy_ids: List[int] = []
    email_preferences: Optional["EmailPreferenceResponse"] = None

    model_config = {"from_attributes": True}


class EmailPreferenceResponse(BaseModel):
    email_enabled: bool = True
    frequency: str = "immediate"
    severity_threshold: str = "informational"
    unsubscribed_at: Optional[UTCDatetime] = None

    model_config = {"from_attributes": True}


class EmailPreferenceUpdate(BaseModel):
    email_enabled: Optional[bool] = None
    frequency: Optional[str] = Field(None, pattern="^(immediate|daily|weekly)$")
    severity_threshold: Optional[str] = Field(
        None, pattern="^(informational|concerning|action-needed)$"
    )


class FollowRequest(BaseModel):
    policy_id: int


class GDPRExportResponse(BaseModel):
    user: "UserResponse"
    followed_policies: List["PolicyResponse"] = []
    email_preferences: Optional[EmailPreferenceResponse] = None
    exported_at: UTCDatetime


# ---- Policy Schemas ----

class PolicyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    company: str = Field(..., min_length=1, max_length=255)
    url: str = Field(..., min_length=10, max_length=2048)
    policy_type: PolicyType = PolicyType.privacy_policy
    check_interval_hours: int = Field(default=24, ge=1, le=720)

    @field_validator("url")
    @classmethod
    def validate_url_format(cls, v: str) -> str:
        from app.utils.url_validator import validate_policy_url
        is_valid, error = validate_policy_url(v)
        if not is_valid:
            raise ValueError(error)
        return v.strip()


class PolicyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    company: Optional[str] = Field(None, min_length=1, max_length=255)
    url: Optional[str] = Field(None, min_length=10, max_length=2048)
    policy_type: Optional[PolicyType] = None
    is_active: Optional[bool] = None
    check_interval_hours: Optional[int] = Field(None, ge=1, le=720)

    @field_validator("url")
    @classmethod
    def validate_url_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        from app.utils.url_validator import validate_policy_url
        is_valid, error = validate_policy_url(v)
        if not is_valid:
            raise ValueError(error)
        return v.strip()


class PolicyResponse(BaseModel):
    id: int
    name: str
    company: str
    url: str
    policy_type: str
    is_active: bool
    check_interval_hours: int
    seed_status: str = "none"
    created_at: UTCDatetime
    updated_at: UTCDatetime
    snapshot_count: int
    last_checked: Optional[UTCDatetime] = None
    last_change: Optional[UTCDatetime] = None

    model_config = {"from_attributes": True}


# ---- Snapshot Schemas ----

class SnapshotResponse(BaseModel):
    id: int
    policy_id: int
    content_hash: str
    content_length: int
    discovered_links: Optional[str] = None
    captured_at: UTCDatetime
    is_seed: bool

    model_config = {"from_attributes": True}


class SnapshotDetail(SnapshotResponse):
    content_text: str


class SeedSnapshotRequest(BaseModel):
    content: str = Field(..., min_length=50, description="Policy text content")


# ---- Diff Schemas ----

class DiffResponse(BaseModel):
    id: int
    policy_id: int
    old_snapshot_id: int
    new_snapshot_id: int
    summary: Optional[str] = None
    severity: str
    severity_score: float
    key_changes: Optional[str] = None
    recommendation: Optional[str] = None
    created_at: UTCDatetime
    email_sent: bool

    model_config = {"from_attributes": True}


class DiffDetail(DiffResponse):
    diff_html: Optional[str] = None
    diff_text: Optional[str] = None
    clauses_added: Optional[str] = None
    clauses_removed: Optional[str] = None
    clauses_modified: Optional[str] = None


# ---- Dashboard Schemas ----

class DashboardStats(BaseModel):
    total_policies: int
    active_policies: int
    total_snapshots: int
    total_changes: int
    action_needed_count: int
    concerning_count: int
    recent_changes: List[DiffResponse]


class CheckNowResponse(BaseModel):
    policy_id: int
    status: str  # "changed" | "unchanged" | "error" | "first_snapshot"
    message: str
    diff_id: Optional[int] = None


class TimelineEntry(BaseModel):
    date: UTCDatetime
    event_type: str  # "snapshot" | "change"
    summary: Optional[str] = None
    severity: Optional[str] = None
    snapshot_id: Optional[int] = None
    diff_id: Optional[int] = None


# ---- Export Schemas ----

class ExportRequest(BaseModel):
    format: str = Field("csv", pattern="^(csv|json)$")
    policy_id: Optional[int] = None
    severity: Optional[Severity] = None
