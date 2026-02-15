"""Snapshot API routes.

All routes use synchronous ``def`` to avoid blocking the event loop with DB calls.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_auth, get_user_id
from app.models import Policy, Snapshot
from app.schemas import SnapshotResponse, SnapshotDetail, SeedSnapshotRequest
from app.services.scraper import compute_hash

router = APIRouter(prefix="/api/policies/{policy_id}/snapshots", tags=["snapshots"])


@router.get("", response_model=List[SnapshotResponse])
def list_snapshots(
    policy_id: int,
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """List all snapshots for a policy, newest first."""
    user_id = get_user_id(identity)
    q = db.query(Policy).filter(Policy.id == policy_id)
    if user_id is not None:
        q = q.filter(Policy.owner_id == user_id)
    policy = q.first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    snapshots = (
        db.query(Snapshot)
        .filter(Snapshot.policy_id == policy_id)
        .order_by(Snapshot.captured_at.desc())
        .all()
    )
    return snapshots


@router.get("/{snapshot_id}", response_model=SnapshotDetail)
def get_snapshot(
    policy_id: int,
    snapshot_id: int,
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """Get a snapshot with full content."""
    snapshot = (
        db.query(Snapshot)
        .filter(Snapshot.id == snapshot_id, Snapshot.policy_id == policy_id)
        .first()
    )
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snapshot


@router.post("/seed", response_model=SnapshotResponse, status_code=201)
def seed_snapshot(
    policy_id: int,
    data: SeedSnapshotRequest,
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """Seed a historical snapshot manually.

    Includes idempotency check: if content with the same hash already exists
    for this policy, returns 409 instead of creating a duplicate.
    """
    user_id = get_user_id(identity)
    q = db.query(Policy).filter(Policy.id == policy_id)
    if user_id is not None:
        q = q.filter(Policy.owner_id == user_id)
    policy = q.first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    content_hash = compute_hash(data.content)

    # Idempotency: check for duplicate content
    existing = (
        db.query(Snapshot)
        .filter(Snapshot.policy_id == policy_id, Snapshot.content_hash == content_hash)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Snapshot with identical content already exists")

    snapshot = Snapshot(
        policy_id=policy_id,
        content_text=data.content,
        content_hash=content_hash,
        content_length=len(data.content),
        is_seed=True,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot
