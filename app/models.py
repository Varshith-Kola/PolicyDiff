"""SQLAlchemy database models.

All datetime columns use UTC-aware defaults via ``app.utils.datetime_helpers.utcnow``.
"""

from sqlalchemy import (
    Column,
    Index,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Boolean,
    Float,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.datetime_helpers import utcnow


class User(Base):
    """A registered user (via Google OAuth)."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    google_id = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(320), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    picture_url = Column(String(2048), nullable=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    gdpr_consent_at = Column(DateTime(timezone=True), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    followed_policies = relationship(
        "UserPageFollow", back_populates="user", cascade="all, delete-orphan"
    )
    email_preferences = relationship(
        "EmailPreference", back_populates="user", cascade="all, delete-orphan",
        uselist=False,
    )


class UserPageFollow(Base):
    """Association between a user and a policy they follow."""

    __tablename__ = "user_page_follows"
    __table_args__ = (
        UniqueConstraint("user_id", "policy_id", name="uq_user_policy_follow"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    policy_id = Column(Integer, ForeignKey("policies.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    user = relationship("User", back_populates="followed_policies")
    policy = relationship("Policy", back_populates="followers")


class EmailPreference(Base):
    """Per-user email notification preferences."""

    __tablename__ = "email_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    email_enabled = Column(Boolean, default=True)
    frequency = Column(
        String(20), default="immediate"
    )  # immediate | daily | weekly
    severity_threshold = Column(
        String(20), default="informational"
    )  # informational | concerning | action-needed
    unsubscribed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    user = relationship("User", back_populates="email_preferences")


class Policy(Base):
    """A monitored policy/ToS page."""

    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("url", "owner_id", name="uq_policy_url_owner"),
    )

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    company = Column(String(255), nullable=False)
    url = Column(String(2048), nullable=False)
    policy_type = Column(
        String(50), default="privacy_policy"
    )  # privacy_policy | terms_of_service
    is_active = Column(Boolean, default=True, index=True)
    check_interval_hours = Column(Integer, default=24)
    next_check_at = Column(DateTime(timezone=True), nullable=True)  # Per-policy scheduling
    seed_status = Column(
        String(20), default="none"
    )  # none | seeding | seeded | seed_failed
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    snapshots = relationship(
        "Snapshot", back_populates="policy", cascade="all, delete-orphan",
        order_by="desc(Snapshot.captured_at)"
    )
    owner = relationship("User", foreign_keys=[owner_id])
    followers = relationship(
        "UserPageFollow", back_populates="policy", cascade="all, delete-orphan"
    )

    @property
    def latest_snapshot(self):
        return self.snapshots[0] if self.snapshots else None

    @property
    def snapshot_count(self):
        return len(self.snapshots)


class Snapshot(Base):
    """A point-in-time capture of a policy page."""

    __tablename__ = "snapshots"
    __table_args__ = (
        Index("ix_snapshots_policy_captured", "policy_id", "captured_at"),
        Index("ix_snapshots_content_hash", "content_hash"),
    )

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("policies.id"), nullable=False, index=True)
    content_text = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    content_length = Column(Integer, default=0)
    discovered_links = Column(Text, nullable=True)  # JSON array
    captured_at = Column(DateTime(timezone=True), default=utcnow)
    is_seed = Column(Boolean, default=False)

    # Relationships
    policy = relationship("Policy", back_populates="snapshots")
    diffs_as_new = relationship(
        "Diff",
        foreign_keys="Diff.new_snapshot_id",
        back_populates="new_snapshot",
        cascade="all, delete-orphan",
    )
    diffs_as_old = relationship(
        "Diff",
        foreign_keys="Diff.old_snapshot_id",
        back_populates="old_snapshot",
        cascade="all, delete-orphan",
    )


class Diff(Base):
    """A computed diff between two snapshots, with LLM analysis."""

    __tablename__ = "diffs"
    __table_args__ = (
        UniqueConstraint("old_snapshot_id", "new_snapshot_id", name="uq_diff_snapshots"),
        Index("ix_diffs_policy_created", "policy_id", "created_at"),
        Index("ix_diffs_severity", "severity"),
    )

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("policies.id"), nullable=False, index=True)
    old_snapshot_id = Column(Integer, ForeignKey("snapshots.id"), nullable=False)
    new_snapshot_id = Column(Integer, ForeignKey("snapshots.id"), nullable=False)

    # Raw diff data
    diff_html = Column(Text)
    diff_text = Column(Text)

    # Clause-level changes
    clauses_added = Column(Text)  # JSON
    clauses_removed = Column(Text)  # JSON
    clauses_modified = Column(Text)  # JSON

    # LLM analysis
    summary = Column(Text)
    severity = Column(
        String(20), default="informational"
    )  # informational | concerning | action-needed
    severity_score = Column(Float, default=0.0)  # 0.0 - 1.0
    key_changes = Column(Text)  # JSON
    recommendation = Column(Text)

    # Notification tracking
    email_sent = Column(Boolean, default=False)
    webhook_sent = Column(Boolean, default=False)
    email_sent_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    old_snapshot = relationship("Snapshot", foreign_keys=[old_snapshot_id], back_populates="diffs_as_old")
    new_snapshot = relationship("Snapshot", foreign_keys=[new_snapshot_id], back_populates="diffs_as_new")
    policy = relationship("Policy")
