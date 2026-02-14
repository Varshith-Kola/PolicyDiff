"""Policy CRUD API routes."""

import asyncio
import logging
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Policy, Snapshot, Diff
from app.schemas import PolicyCreate, PolicyUpdate, PolicyResponse
from app.services.wayback import seed_from_wayback

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/policies", tags=["policies"])


def _policy_to_response(policy: Policy, db: Session) -> dict:
    """Convert a Policy ORM object to response dict with computed fields."""
    latest_snapshot = (
        db.query(Snapshot)
        .filter(Snapshot.policy_id == policy.id)
        .order_by(Snapshot.captured_at.desc())
        .first()
    )
    latest_diff = (
        db.query(Diff)
        .filter(Diff.policy_id == policy.id)
        .order_by(Diff.created_at.desc())
        .first()
    )
    snapshot_count = db.query(Snapshot).filter(Snapshot.policy_id == policy.id).count()

    return {
        "id": policy.id,
        "name": policy.name,
        "company": policy.company,
        "url": policy.url,
        "policy_type": policy.policy_type,
        "is_active": policy.is_active,
        "check_interval_hours": policy.check_interval_hours,
        "seed_status": policy.seed_status or "none",
        "created_at": policy.created_at,
        "updated_at": policy.updated_at,
        "snapshot_count": snapshot_count,
        "last_checked": latest_snapshot.captured_at if latest_snapshot else None,
        "last_change": latest_diff.created_at if latest_diff else None,
    }


def _run_wayback_seed(policy_id: int):
    """Wrapper to run the async wayback seeder inside a BackgroundTasks callback."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(seed_from_wayback(policy_id))
    finally:
        loop.close()


@router.get("", response_model=List[PolicyResponse])
def list_policies(db: Session = Depends(get_db)):
    """List all monitored policies."""
    policies = db.query(Policy).order_by(Policy.created_at.desc()).all()
    return [_policy_to_response(p, db) for p in policies]


@router.post("", response_model=PolicyResponse, status_code=201)
def create_policy(
    data: PolicyCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Add a new policy to monitor.

    Automatically kicks off Wayback Machine historical seeding in the background.
    """
    # Check for duplicate URL
    existing = db.query(Policy).filter(Policy.url == data.url).first()
    if existing:
        raise HTTPException(status_code=409, detail="This URL is already being monitored")

    policy = Policy(**data.model_dump())
    db.add(policy)
    db.commit()
    db.refresh(policy)

    # Kick off Wayback seeding in the background
    background_tasks.add_task(_run_wayback_seed, policy.id)
    logger.info(f"Wayback seeding queued for policy #{policy.id} ({policy.url})")

    return _policy_to_response(policy, db)


@router.get("/{policy_id}", response_model=PolicyResponse)
def get_policy(policy_id: int, db: Session = Depends(get_db)):
    """Get a single policy by ID."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return _policy_to_response(policy, db)


@router.put("/{policy_id}", response_model=PolicyResponse)
def update_policy(policy_id: int, data: PolicyUpdate, db: Session = Depends(get_db)):
    """Update a policy."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(policy, key, value)

    db.commit()
    db.refresh(policy)
    return _policy_to_response(policy, db)


@router.delete("/{policy_id}", status_code=204)
def delete_policy(policy_id: int, db: Session = Depends(get_db)):
    """Delete a policy and all its snapshots/diffs."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    db.delete(policy)
    db.commit()


@router.post("/{policy_id}/seed-wayback")
async def seed_wayback(
    policy_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Manually trigger Wayback Machine seeding for a policy."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    if policy.seed_status == "seeding":
        raise HTTPException(status_code=409, detail="Seeding is already in progress")

    background_tasks.add_task(_run_wayback_seed, policy_id)
    logger.info(f"Manual Wayback seeding queued for policy #{policy_id}")

    return {
        "policy_id": policy_id,
        "status": "queued",
        "message": "Wayback Machine seeding has been queued",
    }
