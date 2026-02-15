"""Diff API routes.

All routes use synchronous ``def`` to avoid blocking the event loop.
Includes search/filter support via query parameters.
"""

import csv
import io
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_auth, get_user_id
from app.models import Policy, Diff
from app.schemas import DiffResponse, DiffDetail

router = APIRouter(prefix="/api", tags=["diffs"])


@router.get("/policies/{policy_id}/diffs", response_model=List[DiffResponse])
def list_diffs(
    policy_id: int,
    severity: Optional[str] = Query(None, description="Filter by severity"),
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """List all diffs for a policy, newest first. Optionally filter by severity."""
    user_id = get_user_id(identity)
    q = db.query(Policy).filter(Policy.id == policy_id)
    if user_id is not None:
        q = q.filter(Policy.owner_id == user_id)
    policy = q.first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    query = db.query(Diff).filter(Diff.policy_id == policy_id)
    if severity:
        query = query.filter(Diff.severity == severity)
    diffs = query.order_by(Diff.created_at.desc()).all()
    return diffs


@router.get("/diffs/{diff_id}", response_model=DiffDetail)
def get_diff(
    diff_id: int,
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """Get a single diff with full details including HTML diff."""
    user_id = get_user_id(identity)
    diff = db.query(Diff).filter(Diff.id == diff_id).first()
    if not diff:
        raise HTTPException(status_code=404, detail="Diff not found")
    # Verify ownership
    if user_id is not None:
        policy = db.query(Policy).filter(Policy.id == diff.policy_id, Policy.owner_id == user_id).first()
        if not policy:
            raise HTTPException(status_code=404, detail="Diff not found")
    return diff


@router.get("/diffs", response_model=List[DiffResponse])
def list_all_diffs(
    limit: int = Query(50, ge=1, le=200),
    severity: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="Search in summaries"),
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """List recent diffs across all policies with optional filters."""
    user_id = get_user_id(identity)
    query = db.query(Diff)
    if user_id is not None:
        owned_ids = [p.id for p in db.query(Policy.id).filter(Policy.owner_id == user_id).all()]
        query = query.filter(Diff.policy_id.in_(owned_ids)) if owned_ids else query.filter(False)
    if severity:
        query = query.filter(Diff.severity == severity)
    if search:
        query = query.filter(Diff.summary.ilike(f"%{search}%"))
    diffs = query.order_by(Diff.created_at.desc()).limit(limit).all()
    return diffs


@router.get("/export/diffs")
def export_diffs(
    format: str = Query("csv", pattern="^(csv|json)$"),
    policy_id: Optional[int] = Query(None),
    severity: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    identity: str = Depends(require_auth),
):
    """Export diffs as CSV or JSON for compliance reporting."""
    user_id = get_user_id(identity)
    query = db.query(Diff)
    if user_id is not None:
        owned_ids = [p.id for p in db.query(Policy.id).filter(Policy.owner_id == user_id).all()]
        query = query.filter(Diff.policy_id.in_(owned_ids)) if owned_ids else query.filter(False)
    if policy_id:
        query = query.filter(Diff.policy_id == policy_id)
    if severity:
        query = query.filter(Diff.severity == severity)
    diffs = query.order_by(Diff.created_at.desc()).all()

    if format == "json":
        data = [
            {
                "id": d.id,
                "policy_id": d.policy_id,
                "severity": d.severity,
                "severity_score": d.severity_score,
                "summary": d.summary,
                "recommendation": d.recommendation,
                "key_changes": json.loads(d.key_changes) if d.key_changes else [],
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "email_sent": d.email_sent,
            }
            for d in diffs
        ]
        return data

    # CSV export
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "policy_id", "severity", "severity_score", "summary",
                     "recommendation", "created_at", "email_sent"])
    for d in diffs:
        writer.writerow([
            d.id, d.policy_id, d.severity, d.severity_score,
            d.summary, d.recommendation,
            d.created_at.isoformat() if d.created_at else "",
            d.email_sent,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=policydiff_export.csv"},
    )
