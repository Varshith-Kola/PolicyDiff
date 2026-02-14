"""Dashboard and action API routes."""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Policy, Snapshot, Diff
from app.schemas import (
    DashboardStats,
    DiffResponse,
    CheckNowResponse,
    TimelineEntry,
)
from app.services.pipeline import check_policy

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard/stats", response_model=DashboardStats)
def get_dashboard_stats(db: Session = Depends(get_db)):
    """Get aggregated dashboard statistics."""
    total_policies = db.query(Policy).count()
    active_policies = db.query(Policy).filter(Policy.is_active == True).count()
    total_snapshots = db.query(Snapshot).count()
    total_changes = db.query(Diff).count()
    action_needed = (
        db.query(Diff).filter(Diff.severity == "action-needed").count()
    )
    concerning = db.query(Diff).filter(Diff.severity == "concerning").count()

    recent_diffs = (
        db.query(Diff).order_by(Diff.created_at.desc()).limit(10).all()
    )

    return DashboardStats(
        total_policies=total_policies,
        active_policies=active_policies,
        total_snapshots=total_snapshots,
        total_changes=total_changes,
        action_needed_count=action_needed,
        concerning_count=concerning,
        recent_changes=[
            DiffResponse(
                id=d.id,
                policy_id=d.policy_id,
                old_snapshot_id=d.old_snapshot_id,
                new_snapshot_id=d.new_snapshot_id,
                summary=d.summary,
                severity=d.severity,
                severity_score=d.severity_score,
                key_changes=d.key_changes,
                recommendation=d.recommendation,
                created_at=d.created_at,
                email_sent=d.email_sent,
            )
            for d in recent_diffs
        ],
    )


@router.post("/policies/{policy_id}/check", response_model=CheckNowResponse)
async def check_now(policy_id: int, db: Session = Depends(get_db)):
    """Manually trigger an immediate check for a specific policy."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    result = await check_policy(policy, db)

    return CheckNowResponse(
        policy_id=policy_id,
        status=result["status"],
        message=result["message"],
        diff_id=result.get("diff_id"),
    )


@router.post("/check-all")
async def check_all(db: Session = Depends(get_db)):
    """Manually trigger a check for all active policies."""
    policies = db.query(Policy).filter(Policy.is_active == True).all()
    results = []
    for policy in policies:
        result = await check_policy(policy, db)
        results.append(result)
    return {"results": results, "total": len(results)}


@router.get("/policies/{policy_id}/timeline", response_model=List[TimelineEntry])
def get_timeline(policy_id: int, db: Session = Depends(get_db)):
    """Get a timeline of events for a policy."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    entries = []

    # Add snapshot events
    snapshots = (
        db.query(Snapshot)
        .filter(Snapshot.policy_id == policy_id)
        .order_by(Snapshot.captured_at.desc())
        .all()
    )
    for s in snapshots:
        entries.append(
            TimelineEntry(
                date=s.captured_at,
                event_type="snapshot",
                summary=f"Snapshot captured ({s.content_length} chars)"
                + (" [seeded]" if s.is_seed else ""),
                snapshot_id=s.id,
            )
        )

    # Add diff/change events
    diffs = (
        db.query(Diff)
        .filter(Diff.policy_id == policy_id)
        .order_by(Diff.created_at.desc())
        .all()
    )
    for d in diffs:
        entries.append(
            TimelineEntry(
                date=d.created_at,
                event_type="change",
                summary=d.summary,
                severity=d.severity,
                diff_id=d.id,
            )
        )

    # Sort by date descending
    entries.sort(key=lambda e: e.date, reverse=True)
    return entries
