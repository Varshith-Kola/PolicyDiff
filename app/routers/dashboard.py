"""Dashboard and action API routes.

check_now and check_all are ``async def`` because they call the async pipeline.
However, they do NOT pass their own DB session to the pipeline — instead,
``check_policy_from_orm`` / ``check_all_policies`` create independent sessions.

All read-only routes are ``def`` (sync) so FastAPI runs them in a thread pool,
preventing sync DB calls from blocking the event loop.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.middleware.auth import require_auth, get_user_id
from app.middleware.rate_limit import rate_limit
from app.models import Policy, Snapshot, Diff
from app.schemas import (
    DashboardStats,
    DiffResponse,
    CheckNowResponse,
    TimelineEntry,
)
from app.services.pipeline import check_policy_from_orm, check_all_policies
from app.services.notifier import send_alert

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard/stats", response_model=DashboardStats)
def get_dashboard_stats(
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """Get aggregated dashboard statistics scoped to the current user's policies."""
    user_id = get_user_id(identity)

    # Use subquery to avoid fetching all policy objects into Python
    policy_id_q = db.query(Policy.id)
    if user_id is not None:
        policy_id_q = policy_id_q.filter(Policy.owner_id == user_id)
    policy_id_subq = policy_id_q.subquery()

    total_policies = db.query(func.count(Policy.id)).filter(Policy.id.in_(db.query(policy_id_subq))).scalar()
    active_policies = db.query(func.count(Policy.id)).filter(
        Policy.id.in_(db.query(policy_id_subq)), Policy.is_active == True
    ).scalar()

    total_snapshots = db.query(func.count(Snapshot.id)).filter(Snapshot.policy_id.in_(db.query(policy_id_subq))).scalar()
    total_changes = db.query(func.count(Diff.id)).filter(Diff.policy_id.in_(db.query(policy_id_subq))).scalar()
    action_needed = db.query(func.count(Diff.id)).filter(Diff.policy_id.in_(db.query(policy_id_subq)), Diff.severity == "action-needed").scalar()
    concerning = db.query(func.count(Diff.id)).filter(Diff.policy_id.in_(db.query(policy_id_subq)), Diff.severity == "concerning").scalar()
    recent_diffs = db.query(Diff).filter(Diff.policy_id.in_(db.query(policy_id_subq))).order_by(Diff.created_at.desc()).limit(10).all()

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
async def check_now(
    policy_id: int,
    request: Request,
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """Manually trigger an immediate check for a specific policy.

    The pipeline runs with its own DB session — the request session is only
    used to look up the policy.
    """
    rate_limit(request, "check_policy", max_requests=30, window_seconds=60)

    user_id = get_user_id(identity)
    query = db.query(Policy).filter(Policy.id == policy_id)
    if user_id is not None:
        query = query.filter(Policy.owner_id == user_id)
    policy = query.first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    result = await check_policy_from_orm(policy)

    return CheckNowResponse(
        policy_id=policy_id,
        status=result["status"],
        message=result["message"],
        diff_id=result.get("diff_id"),
    )


@router.post("/check-all")
async def check_all(
    request: Request,
    identity: str = Depends(require_auth),
):
    """Manually trigger a check for all active policies owned by the current user.

    Each policy is checked with its own session via check_all_policies().
    No request-scoped DB session is needed.
    """
    rate_limit(request, "check_all", max_requests=10, window_seconds=120)

    user_id = get_user_id(identity)
    results = await check_all_policies(owner_id=user_id)
    return {"results": results, "total": len(results)}


@router.get("/policies/{policy_id}/timeline", response_model=List[TimelineEntry])
def get_timeline(
    policy_id: int,
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """Get a timeline of events for a policy."""
    user_id = get_user_id(identity)
    query = db.query(Policy).filter(Policy.id == policy_id)
    if user_id is not None:
        query = query.filter(Policy.owner_id == user_id)
    policy = query.first()
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
                + (" [historical]" if s.is_seed else " [live]"),
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

    entries.sort(key=lambda e: e.date, reverse=True)
    return entries


@router.post("/test-notification")
async def test_notification(
    request: Request,
    _auth: str = Depends(require_auth),
):
    """Send a test notification via all configured channels (email + webhook).

    Useful for verifying SMTP and webhook configuration without waiting
    for an actual policy change.
    """
    rate_limit(request, "test_notification", max_requests=3, window_seconds=60)

    ok = await send_alert(
        policy_name="Test Policy — Example Privacy Policy",
        company="PolicyDiff",
        severity="informational",
        summary=(
            "This is a test notification from PolicyDiff. "
            "If you're reading this, your notification pipeline is working correctly!"
        ),
        key_changes='["Email delivery verified", "Webhook delivery verified"]',
        recommendation="No action needed — this was a test.",
        diff_id=0,
    )

    if ok:
        return {"status": "sent", "message": "Test notification sent successfully. Check your inbox/webhook."}
    return {"status": "not_configured", "message": "No notification channels are configured. Set SMTP or WEBHOOK_URL in .env."}
