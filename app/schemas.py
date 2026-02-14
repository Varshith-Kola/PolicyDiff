"""Pydantic schemas for API request/response validation."""

from pydantic import BaseModel, HttpUrl
from typing import Optional, List
from datetime import datetime


# ---- Policy Schemas ----

class PolicyCreate(BaseModel):
    name: str
    company: str
    url: str
    policy_type: str = "privacy_policy"
    check_interval_hours: int = 24


class PolicyUpdate(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    url: Optional[str] = None
    policy_type: Optional[str] = None
    is_active: Optional[bool] = None
    check_interval_hours: Optional[int] = None


class PolicyResponse(BaseModel):
    id: int
    name: str
    company: str
    url: str
    policy_type: str
    is_active: bool
    check_interval_hours: int
    seed_status: str = "none"
    created_at: datetime
    updated_at: datetime
    snapshot_count: int
    last_checked: Optional[datetime] = None
    last_change: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---- Snapshot Schemas ----

class SnapshotResponse(BaseModel):
    id: int
    policy_id: int
    content_hash: str
    content_length: int
    discovered_links: Optional[str] = None
    captured_at: datetime
    is_seed: bool

    model_config = {"from_attributes": True}


class SnapshotDetail(SnapshotResponse):
    content_text: str


class SeedSnapshotRequest(BaseModel):
    content: str


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
    created_at: datetime
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
    date: datetime
    event_type: str  # "snapshot" | "change"
    summary: Optional[str] = None
    severity: Optional[str] = None
    snapshot_id: Optional[int] = None
    diff_id: Optional[int] = None
