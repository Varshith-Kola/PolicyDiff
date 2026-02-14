"""Wayback Machine auto-seeding service.

Queries the Wayback Machine CDX API to find historical snapshots of a policy
URL, fetches each archived page, extracts text using the same pipeline as the
live scraper, and stores them as seed snapshots.  Then computes diffs between
consecutive snapshots so the user sees a populated timeline immediately.
"""

import asyncio
import datetime
import json
import logging
from typing import List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Policy, Snapshot, Diff
from app.services.scraper import extract_policy_text, compute_hash
from app.services.differ import compute_full_diff
from app.services.analyzer import analyze_diff

logger = logging.getLogger(__name__)

CDX_API = "https://web.archive.org/cdx/search/cdx"
WAYBACK_BASE = "https://web.archive.org/web"

# Maximum historical snapshots to seed
MAX_SNAPSHOTS = 5


async def _query_cdx(url: str, limit: int = MAX_SNAPSHOTS) -> List[dict]:
    """Query the Wayback Machine CDX API for archived snapshots of a URL.

    Returns a list of dicts with keys: timestamp, original, statuscode, digest.
    Results are the most recent *distinct* captures (deduplicated by digest).
    """
    params = {
        "url": url,
        "output": "json",
        "fl": "timestamp,original,statuscode,digest",
        "filter": "statuscode:200",
        "collapse": "digest",       # deduplicate by content digest
        "limit": limit * 2,         # fetch extra in case some fail
        "sort": "reverse",          # newest first
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(CDX_API, params=params)
            resp.raise_for_status()

        rows = resp.json()
        if not rows or len(rows) < 2:
            # First row is the header
            return []

        header = rows[0]
        results = []
        for row in rows[1:]:
            entry = dict(zip(header, row))
            results.append(entry)

        logger.info(f"[wayback] CDX returned {len(results)} unique snapshots for {url}")
        return results[:limit]

    except Exception as e:
        logger.error(f"[wayback] CDX API query failed for {url}: {type(e).__name__}: {e!r}")
        return []


async def _fetch_wayback_page(timestamp: str, original_url: str) -> Optional[str]:
    """Fetch an archived page from the Wayback Machine and return raw HTML."""
    wayback_url = f"{WAYBACK_BASE}/{timestamp}id_/{original_url}"
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": "PolicyDiff/1.0 (privacy-policy-monitor)",
                "Accept-Encoding": "gzip, deflate",
            },
        ) as client:
            resp = await client.get(wayback_url)
            resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.warning(f"[wayback] failed to fetch {wayback_url}: {e}")
        return None


def _timestamp_to_datetime(ts: str) -> datetime.datetime:
    """Convert a Wayback timestamp like '20240315120000' to datetime."""
    return datetime.datetime.strptime(ts[:14], "%Y%m%d%H%M%S")


async def seed_from_wayback(policy_id: int) -> dict:
    """Main entry point: seed a policy's history from the Wayback Machine.

    This function is designed to run as a background task.  It creates its
    own DB session so it's independent of the request lifecycle.

    Returns a status dict.
    """
    db: Session = SessionLocal()
    try:
        policy = db.query(Policy).filter(Policy.id == policy_id).first()
        if not policy:
            logger.error(f"[wayback] policy {policy_id} not found")
            return {"status": "error", "message": "Policy not found"}

        # Mark as seeding
        policy.seed_status = "seeding"
        db.commit()

        logger.info(f"[wayback] starting seed for {policy.name} ({policy.url})")

        # Step 1: Query CDX for snapshots
        cdx_results = await _query_cdx(policy.url)

        if not cdx_results:
            policy.seed_status = "seed_failed"
            db.commit()
            logger.info(f"[wayback] no snapshots found for {policy.url}")
            return {"status": "no_snapshots", "message": "No Wayback Machine snapshots found"}

        # Collect existing content hashes to deduplicate
        existing_hashes = set(
            h[0] for h in db.query(Snapshot.content_hash)
            .filter(Snapshot.policy_id == policy_id)
            .all()
        )

        new_snapshots: List[Snapshot] = []

        # Step 2: Fetch and extract each snapshot
        for entry in cdx_results:
            ts = entry["timestamp"]
            original = entry.get("original", policy.url)

            html = await _fetch_wayback_page(ts, original)
            if not html:
                continue

            text = extract_policy_text(html, original)
            if len(text) < 100:
                logger.warning(f"[wayback] snapshot {ts} too short ({len(text)} chars), skipping")
                continue

            content_hash = compute_hash(text)

            # Deduplicate
            if content_hash in existing_hashes:
                logger.info(f"[wayback] snapshot {ts} is a duplicate (hash {content_hash[:12]}), skipping")
                continue
            existing_hashes.add(content_hash)

            captured_at = _timestamp_to_datetime(ts)

            snapshot = Snapshot(
                policy_id=policy_id,
                content_text=text,
                content_hash=content_hash,
                content_length=len(text),
                captured_at=captured_at,
                is_seed=True,
            )
            db.add(snapshot)
            db.flush()
            new_snapshots.append(snapshot)
            logger.info(
                f"[wayback] seeded snapshot {ts} ({len(text)} chars, "
                f"hash {content_hash[:12]})"
            )

            # Be polite to the Wayback Machine
            await asyncio.sleep(1.5)

        db.commit()

        if not new_snapshots:
            policy.seed_status = "seeded"
            db.commit()
            return {
                "status": "seeded",
                "message": "All Wayback snapshots were duplicates of existing ones",
                "snapshots_added": 0,
            }

        # Step 3: Compute diffs between consecutive snapshots
        all_snapshots = (
            db.query(Snapshot)
            .filter(Snapshot.policy_id == policy_id)
            .order_by(Snapshot.captured_at.asc())
            .all()
        )

        diffs_created = 0
        if len(all_snapshots) >= 2:
            for i in range(len(all_snapshots) - 1):
                old_snap = all_snapshots[i]
                new_snap = all_snapshots[i + 1]

                # Skip if diff already exists
                exists = (
                    db.query(Diff)
                    .filter(
                        Diff.old_snapshot_id == old_snap.id,
                        Diff.new_snapshot_id == new_snap.id,
                    )
                    .first()
                )
                if exists:
                    continue

                # Skip if content is identical
                if old_snap.content_hash == new_snap.content_hash:
                    continue

                try:
                    diff_data = compute_full_diff(old_snap.content_text, new_snap.content_text)

                    analysis = await analyze_diff(
                        policy_name=policy.name,
                        company=policy.company,
                        policy_type=policy.policy_type,
                        diff_text=diff_data["diff_text"],
                        clauses_added=diff_data["clauses_added"],
                        clauses_removed=diff_data["clauses_removed"],
                        clauses_modified=diff_data["clauses_modified"],
                    )

                    diff_record = Diff(
                        policy_id=policy_id,
                        old_snapshot_id=old_snap.id,
                        new_snapshot_id=new_snap.id,
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
                        created_at=new_snap.captured_at,  # date it to when the change happened
                    )
                    db.add(diff_record)
                    diffs_created += 1
                    logger.info(
                        f"[wayback] diff between snapshot {old_snap.id} -> {new_snap.id}: "
                        f"severity={analysis.get('severity')}"
                    )
                except Exception as e:
                    logger.warning(f"[wayback] failed to compute diff {old_snap.id}->{new_snap.id}: {e}")

        policy.seed_status = "seeded"
        db.commit()

        logger.info(
            f"[wayback] seeding complete for {policy.name}: "
            f"{len(new_snapshots)} snapshots added, {diffs_created} diffs computed"
        )

        return {
            "status": "seeded",
            "message": (
                f"Seeded {len(new_snapshots)} historical snapshots "
                f"and computed {diffs_created} diffs"
            ),
            "snapshots_added": len(new_snapshots),
            "diffs_created": diffs_created,
        }

    except Exception as e:
        db.rollback()
        logger.error(f"[wayback] seeding failed for policy {policy_id}: {e}")
        try:
            policy = db.query(Policy).filter(Policy.id == policy_id).first()
            if policy:
                policy.seed_status = "seed_failed"
                db.commit()
        except Exception:
            pass
        return {"status": "error", "message": str(e)}
    finally:
        db.close()
