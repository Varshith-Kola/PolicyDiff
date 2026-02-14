"""Diff API routes."""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Policy, Diff
from app.schemas import DiffResponse, DiffDetail

router = APIRouter(prefix="/api", tags=["diffs"])


@router.get("/policies/{policy_id}/diffs", response_model=List[DiffResponse])
def list_diffs(policy_id: int, db: Session = Depends(get_db)):
    """List all diffs for a policy, newest first."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    diffs = (
        db.query(Diff)
        .filter(Diff.policy_id == policy_id)
        .order_by(Diff.created_at.desc())
        .all()
    )
    return diffs


@router.get("/diffs/{diff_id}", response_model=DiffDetail)
def get_diff(diff_id: int, db: Session = Depends(get_db)):
    """Get a single diff with full details including HTML diff."""
    diff = db.query(Diff).filter(Diff.id == diff_id).first()
    if not diff:
        raise HTTPException(status_code=404, detail="Diff not found")
    return diff


@router.get("/diffs", response_model=List[DiffResponse])
def list_all_diffs(limit: int = 50, db: Session = Depends(get_db)):
    """List recent diffs across all policies."""
    diffs = (
        db.query(Diff)
        .order_by(Diff.created_at.desc())
        .limit(limit)
        .all()
    )
    return diffs
