"""Wayback Machine auto-seeding service.

Queries the Wayback Machine CDX API to find historical snapshots of a policy
URL, fetches each archived page, extracts text using the same pipeline as the
live scraper, and stores them as seed snapshots.  Then computes diffs between
consecutive snapshots so the user sees a populated timeline immediately.

After historical seeding, a live fetch of the current page is performed so the
user always has the most up-to-date snapshot regardless of Wayback coverage.
"""

import asyncio
import json
import logging
from typing import List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

import httpx
from sqlalchemy.orm import Session

from app.database import get_scoped_session
from app.models import Policy, Snapshot, Diff
from app.services.scraper import extract_policy_text, scrape_policy, compute_hash
from app.services.differ import compute_full_diff
from app.services.analyzer import analyze_diff
from app.services.notifier import send_alert
from app.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)

CDX_API = "https://web.archive.org/cdx/search/cdx"
WAYBACK_BASE = "https://web.archive.org/web"

# Maximum historical snapshots to seed (most captures are content-identical
# after text extraction, so a small number is sufficient)
MAX_SNAPSHOTS = 3

# CDX query retry attempts
CDX_MAX_RETRIES = 2


def _url_variants(url: str) -> List[str]:
    """Generate URL variants for CDX lookup.

    The Wayback Machine indexes URLs in specific canonical forms.  A URL with
    query parameters may be indexed differently (or not at all) compared to
    the base path.  Try the original URL first, then stripped variants.
    """
    variants = [url]
    parsed = urlparse(url)

    # Variant 2: without query string
    if parsed.query:
        no_query = urlunparse(parsed._replace(query="", fragment=""))
        variants.append(no_query)

    # Variant 3: without trailing slash
    if parsed.path.endswith("/"):
        no_slash = urlunparse(parsed._replace(path=parsed.path.rstrip("/")))
        if no_slash not in variants:
            variants.append(no_slash)

    # Variant 4: wildcard prefix match (catches subpages)
    # Only if the URL has a deep path
    if parsed.path.count("/") >= 2:
        wildcard = url.rstrip("/") + "*"
        variants.append(wildcard)

    return variants


async def _query_cdx_single(url: str, limit: int) -> List[dict]:
    """Single CDX API call for one URL variant.  Returns parsed results."""
    params = {
        "url": url,
        "output": "json",
        "fl": "timestamp,original,statuscode,digest",
        "filter": "statuscode:200",
        "collapse": "digest",       # deduplicate by content digest
        "limit": limit * 2,         # fetch extra in case some fail
        "sort": "reverse",          # newest first
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(CDX_API, params=params)
        resp.raise_for_status()

    rows = resp.json()
    if not rows or len(rows) < 2:
        return []

    header = rows[0]
    return [dict(zip(header, row)) for row in rows[1:]]


async def _query_cdx(url: str, limit: int = MAX_SNAPSHOTS) -> List[dict]:
    """Query the Wayback Machine CDX API with retries and URL variants.

    Tries the original URL first.  If no results, tries canonical variants
    (without query params, without trailing slash).  Each variant is retried
    up to CDX_MAX_RETRIES times on transient errors.
    """
    for variant in _url_variants(url):
        for attempt in range(1, CDX_MAX_RETRIES + 1):
            try:
                results = await _query_cdx_single(variant, limit)
                if results:
                    logger.info(
                        f"[wayback] CDX returned {len(results)} unique snapshots "
                        f"for {variant} (attempt {attempt})"
                    )
                    return results[:limit]
                break  # no results but no error — try next variant
            except Exception as e:
                logger.warning(
                    f"[wayback] CDX query attempt {attempt}/{CDX_MAX_RETRIES} "
                    f"failed for {variant}: {type(e).__name__}: {e}"
                )
                if attempt < CDX_MAX_RETRIES:
                    await asyncio.sleep(2 * attempt)

    logger.info(f"[wayback] no CDX results for any URL variant of {url}")
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


def _timestamp_to_datetime(ts: str):
    """Convert a Wayback timestamp like '20240315120000' to a UTC-aware datetime."""
    import datetime
    naive = datetime.datetime.strptime(ts[:14], "%Y%m%d%H%M%S")
    return naive.replace(tzinfo=datetime.timezone.utc)


async def _fetch_live_snapshot(
    db: Session, policy: Policy, policy_id: int, existing_hashes: set,
) -> Optional[Snapshot]:
    """Fetch the current live page and store it as a snapshot.

    This ensures the user always has the most up-to-date version of the policy,
    regardless of what the Wayback Machine has archived.  Uses the same scraper
    pipeline as "Check Now".
    """
    try:
        text, content_hash, discovered_links = await scrape_policy(policy.url)

        if content_hash in existing_hashes:
            logger.info(
                f"[wayback] live page is identical to an existing snapshot "
                f"(hash {content_hash[:12]}), skipping"
            )
            return None

        links_json = json.dumps(discovered_links) if discovered_links else None
        snapshot = Snapshot(
            policy_id=policy_id,
            content_text=text,
            content_hash=content_hash,
            content_length=len(text),
            discovered_links=links_json,
            captured_at=utcnow(),
            is_seed=False,  # This is a live fetch, not a Wayback seed
        )
        db.add(snapshot)
        db.flush()
        existing_hashes.add(content_hash)
        logger.info(
            f"[wayback] live snapshot captured ({len(text)} chars, "
            f"hash {content_hash[:12]})"
        )
        return snapshot
    except Exception as e:
        logger.warning(f"[wayback] live fetch failed for {policy.url}: {e}")
        return None


async def seed_from_wayback(policy_id: int) -> dict:
    """Main entry point: seed a policy's history from the Wayback Machine.

    This function is designed to run as a background task.  It creates its
    own DB session so it's independent of the request lifecycle.

    After importing historical Wayback snapshots, it also fetches the current
    live page so the user always has the most up-to-date version.

    Returns a status dict.
    """
    with get_scoped_session() as db:
        try:
            policy = db.query(Policy).filter(Policy.id == policy_id).first()
            if not policy:
                logger.error(f"[wayback] policy {policy_id} not found")
                return {"status": "error", "message": "Policy not found"}

            # Mark as seeding
            policy.seed_status = "seeding"
            db.commit()

            policy_url = policy.url
            policy_name = policy.name
            logger.info(f"[wayback] starting seed for {policy_name} ({policy_url})")

            # Collect existing content hashes to deduplicate
            existing_hashes = {
                h[0] for h in db.query(Snapshot.content_hash)
                .filter(Snapshot.policy_id == policy_id)
                .all()
            }

            # Step 1: Query CDX for historical snapshots
            cdx_results = await _query_cdx(policy_url)
            new_snapshots: List[Snapshot] = []

            if cdx_results:
                new_snapshots = await _fetch_and_store_snapshots(
                    db, policy, policy_id, cdx_results, existing_hashes
                )
                db.commit()
                logger.info(
                    f"[wayback] historical phase: {len(new_snapshots)} snapshots "
                    f"from {len(cdx_results)} CDX results"
                )
            else:
                logger.info(f"[wayback] no Wayback snapshots found for {policy_url}")

            # Step 2: Always fetch the CURRENT live page
            # This is the key fix — the user gets the latest version regardless
            # of Wayback Machine coverage
            live_snap = await _fetch_live_snapshot(
                db, policy, policy_id, existing_hashes
            )
            if live_snap:
                new_snapshots.append(live_snap)
            db.commit()

            if not new_snapshots:
                # No Wayback snapshots AND live fetch returned a duplicate
                policy.seed_status = "seeded"
                db.commit()
                return {
                    "status": "seeded",
                    "message": "Policy content is already up to date",
                    "snapshots_added": 0,
                }

            # Step 3: Compute diffs between consecutive snapshots
            diffs_created = await _compute_seeded_diffs(db, policy, policy_id)

            policy.seed_status = "seeded"
            db.commit()

            logger.info(
                f"[wayback] seeding complete for {policy_name}: "
                f"{len(new_snapshots)} snapshots added, {diffs_created} diffs computed"
            )

            # Notify followers about seeding results
            await _notify_seed_results(db, policy, policy_id, new_snapshots, diffs_created)

            return {
                "status": "seeded",
                "message": (
                    f"Seeded {len(new_snapshots)} snapshot(s) "
                    f"({len(new_snapshots) - (1 if live_snap else 0)} historical + "
                    f"{'1 live' if live_snap else '0 live'}) "
                    f"and computed {diffs_created} diffs"
                ),
                "snapshots_added": len(new_snapshots),
                "diffs_created": diffs_created,
            }

        except Exception as e:
            db.rollback()
            logger.error(f"[wayback] seeding failed for policy {policy_id}: {e}", exc_info=True)
            try:
                policy = db.query(Policy).filter(Policy.id == policy_id).first()
                if policy:
                    policy.seed_status = "seed_failed"
                    db.commit()
            except Exception:
                pass
            return {"status": "error", "message": str(e)}


async def _fetch_and_store_snapshots(
    db: Session, policy: Policy, policy_id: int,
    cdx_results: List[dict], existing_hashes: set,
) -> List[Snapshot]:
    """Fetch Wayback pages and store new snapshots. Returns list of new snapshots."""
    new_snapshots: List[Snapshot] = []

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

    return new_snapshots


async def _compute_seeded_diffs(db: Session, policy: Policy, policy_id: int) -> int:
    """Compute diffs between consecutive snapshots. Returns count of diffs created."""
    all_snapshots = (
        db.query(Snapshot)
        .filter(Snapshot.policy_id == policy_id)
        .order_by(Snapshot.captured_at.asc())
        .all()
    )

    diffs_created = 0
    if len(all_snapshots) < 2:
        return 0

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

    return diffs_created


async def _notify_seed_results(
    db: Session, policy: Policy, policy_id: int,
    new_snapshots: List[Snapshot], diffs_created: int,
):
    """Send notifications about seeding results."""
    if diffs_created > 0:
        latest_diff = (
            db.query(Diff)
            .filter(Diff.policy_id == policy_id)
            .order_by(Diff.created_at.desc())
            .first()
        )
        if latest_diff:
            alert_ok = await send_alert(
                policy_name=policy.name,
                company=policy.company,
                severity=latest_diff.severity,
                summary=latest_diff.summary or f"{diffs_created} historical change(s) seeded from Wayback Machine.",
                key_changes=latest_diff.key_changes or "[]",
                recommendation=latest_diff.recommendation or "Review the seeded timeline for historical changes.",
                diff_id=latest_diff.id,
                policy_id=policy_id,
            )
            latest_diff.email_sent = alert_ok
            if alert_ok:
                latest_diff.email_sent_at = utcnow()
            db.commit()
            logger.info(f"[wayback] notification sent for seeded diff #{latest_diff.id}: {alert_ok}")
    elif len(new_snapshots) > 0:
        await send_alert(
            policy_name=policy.name,
            company=policy.company,
            severity="informational",
            summary=f"Policy snapshot captured: {len(new_snapshots)} historical snapshot(s) seeded from Wayback Machine for {policy.name}.",
            key_changes=f'["Seeded {len(new_snapshots)} snapshot(s) from Wayback Machine"]',
            recommendation="No action needed — historical data has been imported. Future changes will be tracked and compared.",
            diff_id=0,
            policy_id=policy_id,
        )
        logger.info(f"[wayback] snapshot notification sent for policy {policy_id} ({len(new_snapshots)} snapshots, 0 diffs)")
