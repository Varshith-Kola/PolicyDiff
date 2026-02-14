"""SQLAlchemy database models."""

import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Boolean,
    Float,
)
from sqlalchemy.orm import relationship
from app.database import Base


class Policy(Base):
    """A monitored policy/ToS page."""

    __tablename__ = "policies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)  # e.g. "Google Privacy Policy"
    company = Column(String(255), nullable=False)  # e.g. "Google"
    url = Column(String(2048), nullable=False, unique=True)
    policy_type = Column(
        String(50), default="privacy_policy"
    )  # privacy_policy | terms_of_service
    is_active = Column(Boolean, default=True)
    check_interval_hours = Column(Integer, default=24)
    seed_status = Column(
        String(20), default="none"
    )  # none | seeding | seeded | seed_failed
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    snapshots = relationship(
        "Snapshot", back_populates="policy", cascade="all, delete-orphan",
        order_by="desc(Snapshot.captured_at)"
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

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("policies.id"), nullable=False, index=True)
    content_text = Column(Text, nullable=False)  # Extracted plain text
    content_hash = Column(String(64), nullable=False)  # SHA-256 of content
    content_length = Column(Integer, default=0)
    discovered_links = Column(Text, nullable=True)  # JSON array of related policy URLs found on page
    captured_at = Column(DateTime, default=datetime.datetime.utcnow)
    is_seed = Column(Boolean, default=False)  # Manually seeded snapshot

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

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("policies.id"), nullable=False, index=True)
    old_snapshot_id = Column(Integer, ForeignKey("snapshots.id"), nullable=False)
    new_snapshot_id = Column(Integer, ForeignKey("snapshots.id"), nullable=False)

    # Raw diff data
    diff_html = Column(Text)  # HTML-formatted side-by-side diff
    diff_text = Column(Text)  # Plain-text unified diff

    # Clause-level changes
    clauses_added = Column(Text)  # JSON array of added clauses
    clauses_removed = Column(Text)  # JSON array of removed clauses
    clauses_modified = Column(Text)  # JSON array of modified clauses

    # LLM analysis
    summary = Column(Text)  # Plain-language summary
    severity = Column(
        String(20), default="informational"
    )  # informational | concerning | action-needed
    severity_score = Column(Float, default=0.0)  # 0.0 - 1.0
    key_changes = Column(Text)  # JSON array of key change descriptions
    recommendation = Column(Text)  # What the user should do

    # Notification tracking
    email_sent = Column(Boolean, default=False)
    email_sent_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    old_snapshot = relationship("Snapshot", foreign_keys=[old_snapshot_id], back_populates="diffs_as_old")
    new_snapshot = relationship("Snapshot", foreign_keys=[new_snapshot_id], back_populates="diffs_as_new")
    policy = relationship("Policy")
