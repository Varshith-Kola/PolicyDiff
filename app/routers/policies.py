"""Policy CRUD API routes.

All routes are synchronous ``def`` (not ``async def``) so that SQLAlchemy
calls don't block the event loop — FastAPI runs ``def`` routes in a thread pool.

N+1 query problem fixed: ``_policies_with_stats`` uses a single aggregating
query instead of 3 queries per policy.
"""

import asyncio
import logging
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_auth, get_user_id
from app.middleware.rate_limit import rate_limit
from app.models import Policy, Snapshot, Diff
from app.schemas import PolicyCreate, PolicyUpdate, PolicyResponse
from app.services.wayback import seed_from_wayback

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/policies", tags=["policies"])


def _policies_with_stats(db: Session, policy_filter=None, owner_id: int = None):
    """Fetch policies with computed stats in a single query to eliminate N+1.

    Returns a list of dicts ready for PolicyResponse serialisation.
    When owner_id is set, only returns policies owned by that user.
    """
    base = db.query(Policy)
    if owner_id is not None:
        base = base.filter(Policy.owner_id == owner_id)
    if policy_filter is not None:
        base = base.filter(policy_filter)
    policies = base.order_by(Policy.created_at.desc()).all()
    if not policies:
        return []

    policy_ids = [p.id for p in policies]

    # Aggregate snapshot counts and last captured_at in one query
    snap_rows = (
        db.query(
            Snapshot.policy_id,
            func.count(Snapshot.id).label("cnt"),
            func.max(Snapshot.captured_at).label("last_cap"),
        )
        .filter(Snapshot.policy_id.in_(policy_ids))
        .group_by(Snapshot.policy_id)
        .all()
    )
    snap_map = {r[0]: {"count": r[1], "last_checked": r[2]} for r in snap_rows}

    # Aggregate last diff date per policy
    diff_rows = (
        db.query(
            Diff.policy_id,
            func.max(Diff.created_at).label("last_change"),
        )
        .filter(Diff.policy_id.in_(policy_ids))
        .group_by(Diff.policy_id)
        .all()
    )
    diff_map = {r[0]: r[1] for r in diff_rows}

    results = []
    for p in policies:
        s = snap_map.get(p.id, {"count": 0, "last_checked": None})
        results.append({
            "id": p.id,
            "name": p.name,
            "company": p.company,
            "url": p.url,
            "policy_type": p.policy_type,
            "is_active": p.is_active,
            "check_interval_hours": p.check_interval_hours,
            "seed_status": p.seed_status or "none",
            "created_at": p.created_at,
            "updated_at": p.updated_at,
            "snapshot_count": s["count"],
            "last_checked": s["last_checked"],
            "last_change": diff_map.get(p.id),
        })
    return results


def _single_policy_response(policy: Policy, db: Session) -> dict:
    """Build a PolicyResponse dict for a single policy (used after create/update)."""
    rows = _policies_with_stats(db, Policy.id == policy.id)
    return rows[0] if rows else {}


def _get_owned_policy(db: Session, policy_id: int, identity: str) -> Policy:
    """Fetch a policy by ID, enforcing ownership for Google OAuth users.

    API-key users can access any policy. Google OAuth users can only
    access policies they own.
    """
    user_id = get_user_id(identity)
    query = db.query(Policy).filter(Policy.id == policy_id)
    if user_id is not None:
        query = query.filter(Policy.owner_id == user_id)
    policy = query.first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return policy


def _run_wayback_seed(policy_id: int):
    """Run the async wayback seeder in a fresh event loop (BackgroundTasks thread)."""
    asyncio.run(seed_from_wayback(policy_id))


@router.get("", response_model=List[PolicyResponse])
def list_policies(
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """List policies owned by the current user (or all if API-key auth)."""
    user_id = get_user_id(identity)
    return _policies_with_stats(db, owner_id=user_id)


@router.post("", response_model=PolicyResponse, status_code=201)
def create_policy(
    data: PolicyCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """Add a new policy to monitor.

    URL is validated for SSRF safety by the schema validator.
    Automatically kicks off Wayback Machine historical seeding in the background.
    """
    rate_limit(request, "create_policy", max_requests=10, window_seconds=60)

    user_id = get_user_id(identity)
    # Check for duplicate URL only within this user's policies
    dup_filter = Policy.url == data.url
    if user_id is not None:
        dup_filter = (Policy.url == data.url) & (Policy.owner_id == user_id)
    existing = db.query(Policy).filter(dup_filter).first()
    if existing:
        raise HTTPException(status_code=409, detail="This URL is already being monitored")

    policy = Policy(**data.model_dump(), owner_id=user_id)
    db.add(policy)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This URL is already being monitored")
    db.refresh(policy)

    background_tasks.add_task(_run_wayback_seed, policy.id)
    logger.info(f"Wayback seeding queued for policy #{policy.id} ({policy.url})")

    return _single_policy_response(policy, db)


@router.get("/{policy_id}", response_model=PolicyResponse)
def get_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """Get a single policy by ID (must be owned by current user)."""
    policy = _get_owned_policy(db, policy_id, identity)
    return _single_policy_response(policy, db)


@router.put("/{policy_id}", response_model=PolicyResponse)
def update_policy(
    policy_id: int,
    data: PolicyUpdate,
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """Update a policy (must be owned by current user)."""
    policy = _get_owned_policy(db, policy_id, identity)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(policy, key, value)

    db.commit()
    db.refresh(policy)
    return _single_policy_response(policy, db)


@router.delete("/{policy_id}", status_code=204)
def delete_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """Delete a policy and all its snapshots/diffs (must be owned by current user)."""
    policy = _get_owned_policy(db, policy_id, identity)

    db.delete(policy)
    db.commit()


@router.post("/{policy_id}/seed-wayback")
def seed_wayback(
    policy_id: int,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """Manually trigger Wayback Machine seeding for a policy."""
    rate_limit(request, "seed_wayback", max_requests=10, window_seconds=120)

    policy = _get_owned_policy(db, policy_id, identity)

    if policy.seed_status == "seeding":
        raise HTTPException(status_code=409, detail="Seeding is already in progress")

    background_tasks.add_task(_run_wayback_seed, policy_id)
    logger.info(f"Manual Wayback seeding queued for policy #{policy_id}")

    return {
        "policy_id": policy_id,
        "status": "queued",
        "message": "Wayback Machine seeding has been queued",
    }
