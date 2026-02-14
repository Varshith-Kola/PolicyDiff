"""Snapshot API routes."""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Policy, Snapshot
from app.schemas import SnapshotResponse, SnapshotDetail, SeedSnapshotRequest
from app.services.scraper import compute_hash

router = APIRouter(prefix="/api/policies/{policy_id}/snapshots", tags=["snapshots"])


@router.get("", response_model=List[SnapshotResponse])
def list_snapshots(policy_id: int, db: Session = Depends(get_db)):
    """List all snapshots for a policy, newest first."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
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
def get_snapshot(policy_id: int, snapshot_id: int, db: Session = Depends(get_db)):
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
    policy_id: int, data: SeedSnapshotRequest, db: Session = Depends(get_db)
):
    """
    Seed a historical snapshot manually.
    Useful for bootstrapping history from Wayback Machine, etc.
    """
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    content_hash = compute_hash(data.content)

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
