"""Core pipeline: scrape -> diff -> analyze -> notify.

Improvements:
  - check_all_policies uses asyncio.gather with a semaphore for concurrent checking
  - scrape_policy now returns discovered_links which are stored on the snapshot
"""

import asyncio
import datetime
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Policy, Snapshot, Diff
from app.services.scraper import scrape_policy, compute_hash
from app.services.differ import compute_full_diff
from app.services.analyzer import analyze_diff
from app.services.notifier import send_alert

logger = logging.getLogger(__name__)

# Maximum concurrent policy checks (limits HTTP + LLM parallelism)
MAX_CONCURRENT_CHECKS = 5


async def check_policy(policy: Policy, db: Session) -> dict:
    """
    Run the full pipeline for a single policy:
    1. Scrape the page
    2. Compare with latest snapshot
    3. If changed: compute diff, analyze, notify

    Returns a status dict.
    """
    try:
        # Step 1: Scrape (now returns discovered_links too)
        text, content_hash, discovered_links = await scrape_policy(policy.url)

        # Step 2: Check if content has changed
        latest = (
            db.query(Snapshot)
            .filter(Snapshot.policy_id == policy.id)
            .order_by(Snapshot.captured_at.desc())
            .first()
        )

        if latest and latest.content_hash == content_hash:
            logger.info(f"No changes detected for {policy.name}")
            return {
                "policy_id": policy.id,
                "status": "unchanged",
                "message": f"No changes detected for {policy.name}",
            }

        # Step 3: Save new snapshot with discovered links
        links_json = json.dumps(discovered_links) if discovered_links else None
        new_snapshot = Snapshot(
            policy_id=policy.id,
            content_text=text,
            content_hash=content_hash,
            content_length=len(text),
            discovered_links=links_json,
        )
        db.add(new_snapshot)
        db.flush()

        if not latest:
            db.commit()
            logger.info(f"First snapshot captured for {policy.name}")
            return {
                "policy_id": policy.id,
                "status": "first_snapshot",
                "message": f"First snapshot captured for {policy.name} ({len(text)} chars)",
            }

        # Step 4: Compute diff
        diff_data = compute_full_diff(latest.content_text, text)

        # Step 5: Analyze with LLM
        analysis = await analyze_diff(
            policy_name=policy.name,
            company=policy.company,
            policy_type=policy.policy_type,
            diff_text=diff_data["diff_text"],
            clauses_added=diff_data["clauses_added"],
            clauses_removed=diff_data["clauses_removed"],
            clauses_modified=diff_data["clauses_modified"],
        )

        # Step 6: Save diff record
        diff_record = Diff(
            policy_id=policy.id,
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

        # Step 7: Send notifications (email + webhook)
        await send_alert(
            policy_name=policy.name,
            company=policy.company,
            severity=diff_record.severity,
            summary=diff_record.summary or "",
            key_changes=diff_record.key_changes or "[]",
            recommendation=diff_record.recommendation or "",
            diff_id=diff_record.id,
        )

        diff_record.email_sent = True
        diff_record.email_sent_at = datetime.datetime.utcnow()

        db.commit()

        logger.info(
            f"Change detected for {policy.name}: severity={diff_record.severity}, "
            f"diff_id={diff_record.id}"
        )

        return {
            "policy_id": policy.id,
            "status": "changed",
            "message": f"Change detected: {analysis.get('summary', 'See diff for details')}",
            "diff_id": diff_record.id,
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Pipeline error for {policy.name}: {e}")
        return {
            "policy_id": policy.id,
            "status": "error",
            "message": str(e),
        }


async def check_all_policies(db: Session):
    """Check all active policies concurrently with a semaphore.

    Uses asyncio.gather with a concurrency limit to avoid overwhelming
    target servers and the OpenAI API simultaneously.
    """
    policies = db.query(Policy).filter(Policy.is_active == True).all()
    logger.info(f"Starting scheduled check for {len(policies)} active policies")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)

    async def _check_with_semaphore(policy):
        async with semaphore:
            return await check_policy(policy, db)

    results = await asyncio.gather(
        *[_check_with_semaphore(p) for p in policies],
        return_exceptions=True,
    )

    # Normalize exceptions into error dicts
    final_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            final_results.append({
                "policy_id": policies[i].id,
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
