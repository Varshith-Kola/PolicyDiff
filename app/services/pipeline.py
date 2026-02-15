"""Core pipeline: scrape -> diff -> analyze -> notify.

Each concurrent policy check gets its own database session to prevent
session corruption when multiple coroutines run in parallel.
"""

import asyncio
import json
import logging
from datetime import timedelta
from typing import List

from sqlalchemy.orm import Session

from app.database import get_scoped_session
from app.models import Policy, Snapshot, Diff
from app.services.scraper import scrape_policy, compute_hash
from app.services.differ import compute_full_diff
from app.services.analyzer import analyze_diff
from app.services.notifier import send_alert
from app.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)

# Maximum concurrent policy checks (limits HTTP + LLM parallelism)
MAX_CONCURRENT_CHECKS = 5


async def check_policy(policy_id: int, policy_url: str, policy_name: str,
                        policy_company: str, policy_type: str) -> dict:
    """Run the full pipeline for a single policy.

    Uses its own database session to prevent cross-coroutine interference.
    Accepts primitive values instead of ORM objects so the caller's session
    is not shared.

    Returns a status dict.
    """
    with get_scoped_session() as db:
        try:
            # Step 1: Scrape
            text, content_hash, discovered_links = await scrape_policy(policy_url)

            # Step 2: Check if content has changed
            latest = (
                db.query(Snapshot)
                .filter(Snapshot.policy_id == policy_id)
                .order_by(Snapshot.captured_at.desc())
                .first()
            )

            if latest and latest.content_hash == content_hash:
                # Update next_check_at even on unchanged
                _update_next_check(db, policy_id)
                logger.info(f"No changes detected for {policy_name}")
                return {
                    "policy_id": policy_id,
                    "status": "unchanged",
                    "message": f"No changes detected for {policy_name}",
                }

            # Step 3: Idempotency — check if snapshot with same hash already exists
            existing_snap = (
                db.query(Snapshot)
                .filter(Snapshot.policy_id == policy_id, Snapshot.content_hash == content_hash)
                .first()
            )
            if existing_snap:
                logger.info(f"Duplicate snapshot detected for {policy_name} (hash collision)")
                return {
                    "policy_id": policy_id,
                    "status": "unchanged",
                    "message": f"Content already captured for {policy_name}",
                }

            # Step 4: Save new snapshot
            links_json = json.dumps(discovered_links) if discovered_links else None
            new_snapshot = Snapshot(
                policy_id=policy_id,
                content_text=text,
                content_hash=content_hash,
                content_length=len(text),
                discovered_links=links_json,
            )
            db.add(new_snapshot)
            db.flush()

            if not latest:
                _update_next_check(db, policy_id)
                db.commit()
                logger.info(f"First snapshot captured for {policy_name}")

                # Notify followers that the policy is now being tracked
                await send_alert(
                    policy_name=policy_name,
                    company=policy_company,
                    severity="informational",
                    summary=f"First snapshot captured for {policy_name} ({len(text)} chars). Future changes will be tracked and compared.",
                    key_changes='["Initial policy snapshot captured"]',
                    recommendation="No action needed — the policy is now being monitored.",
                    diff_id=0,
                    policy_id=policy_id,
                )

                return {
                    "policy_id": policy_id,
                    "status": "first_snapshot",
                    "message": f"First snapshot captured for {policy_name} ({len(text)} chars)",
                }

            # Step 5: Idempotency — check if diff already exists for this snapshot pair
            existing_diff = (
                db.query(Diff)
                .filter(
                    Diff.old_snapshot_id == latest.id,
                    Diff.new_snapshot_id == new_snapshot.id,
                )
                .first()
            )
            if existing_diff:
                db.commit()
                return {
                    "policy_id": policy_id,
                    "status": "changed",
                    "message": "Change already recorded",
                    "diff_id": existing_diff.id,
                }

            # Step 6: Compute diff
            diff_data = compute_full_diff(latest.content_text, text)

            # Step 7: Analyze with LLM
            analysis = await analyze_diff(
                policy_name=policy_name,
                company=policy_company,
                policy_type=policy_type,
                diff_text=diff_data["diff_text"],
                clauses_added=diff_data["clauses_added"],
                clauses_removed=diff_data["clauses_removed"],
                clauses_modified=diff_data["clauses_modified"],
            )

            # Step 8: Save diff record
            diff_record = Diff(
                policy_id=policy_id,
                old_snapshot_id=latest.id,
                new_snapshot_id=new_snapshot.id,
                diff_html=diff_data["diff_html"],
                diff_text=diff_data["diff_text"],
                clauses_added=diff_data["clauses_added"],
                clauses_removed=diff_data["clauses_removed"],
                clauses_modified=diff_data["clauses_modified"],
                summary=analysis.get("summary"),
                severity=analysis.get("severity", "informational"),
                severity_score=analysis.get("severity_score", 0.0),
                key_changes=analysis.get("key_changes"),
                recommendation=analysis.get("recommendation"),
            )
            db.add(diff_record)
            db.flush()

            # Step 9: Send notifications — track success/failure accurately
            alert_ok = await send_alert(
                policy_name=policy_name,
                company=policy_company,
                severity=diff_record.severity,
                summary=diff_record.summary or "",
                key_changes=diff_record.key_changes or "[]",
                recommendation=diff_record.recommendation or "",
                diff_id=diff_record.id,
                policy_id=policy_id,
            )
            diff_record.email_sent = alert_ok
            if alert_ok:
                diff_record.email_sent_at = utcnow()

            _update_next_check(db, policy_id)
            db.commit()

            logger.info(
                f"Change detected for {policy_name}: severity={diff_record.severity}, "
                f"diff_id={diff_record.id}, notified={alert_ok}"
            )

            return {
                "policy_id": policy_id,
                "status": "changed",
                "message": f"Change detected: {analysis.get('summary', 'See diff for details')}",
                "diff_id": diff_record.id,
            }

        except Exception as e:
            db.rollback()
            logger.error(f"Pipeline error for {policy_name}: {e}", exc_info=True)
            return {
                "policy_id": policy_id,
                "status": "error",
                "message": str(e),
            }


def _update_next_check(db: Session, policy_id: int):
    """Update the next_check_at timestamp based on the policy's interval."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if policy:
        policy.next_check_at = utcnow() + timedelta(hours=policy.check_interval_hours)


async def check_policy_from_orm(policy: Policy) -> dict:
    """Convenience wrapper that extracts primitives from an ORM Policy object.

    Use this from request handlers where you have a live ORM object.
    The actual work happens in check_policy() with its own session.
    """
    return await check_policy(
        policy_id=policy.id,
        policy_url=policy.url,
        policy_name=policy.name,
        policy_company=policy.company,
        policy_type=policy.policy_type,
    )


async def check_all_policies(owner_id: int = None):
    """Check all active policies concurrently with independent sessions.

    Each policy check gets its own database session via check_policy().
    The policy list is fetched in a separate session that is closed before
    any concurrent work begins.

    If owner_id is provided, only policies owned by that user are checked.
    If owner_id is None, all active policies are checked (scheduler mode).
    """
    with get_scoped_session() as db:
        query = db.query(Policy).filter(Policy.is_active == True)
        if owner_id is not None:
            query = query.filter(Policy.owner_id == owner_id)
        policies = query.all()
        # Extract primitives before closing the session
        policy_data = [
            {
                "id": p.id,
                "url": p.url,
                "name": p.name,
                "company": p.company,
                "policy_type": p.policy_type,
                "next_check_at": p.next_check_at,
            }
            for p in policies
        ]

    # Filter to only policies that are due for a check
    now = utcnow()
    due_policies = [
        p for p in policy_data
        if p["next_check_at"] is None or p["next_check_at"] <= now
    ]

    if not due_policies:
        logger.info("No policies due for checking")
        return []

    logger.info(
        f"Starting scheduled check for {len(due_policies)} policies "
        f"(of {len(policy_data)} total active)"
    )

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)

    async def _check_with_semaphore(p: dict):
        async with semaphore:
            return await check_policy(
                policy_id=p["id"],
                policy_url=p["url"],
                policy_name=p["name"],
                policy_company=p["company"],
                policy_type=p["policy_type"],
            )

    results = await asyncio.gather(
        *[_check_with_semaphore(p) for p in due_policies],
        return_exceptions=True,
    )

    final_results: List[dict] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            final_results.append({
                "policy_id": due_policies[i]["id"],
                "status": "error",
                "message": str(result),
            })
        else:
            final_results.append(result)

    changes = [r for r in final_results if r["status"] == "changed"]
    errors = [r for r in final_results if r["status"] == "error"]
    logger.info(
        f"Scheduled check complete: {len(changes)} changes, {len(errors)} errors "
        f"(concurrent limit: {MAX_CONCURRENT_CHECKS})"
    )
    return final_results
