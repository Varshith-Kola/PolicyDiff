"""APScheduler-based periodic policy checking.

The scheduler runs a single job at a fixed base interval (e.g. every hour).
Each run calls ``check_all_policies()`` which respects per-policy
``next_check_at`` timestamps, so policies with different intervals are
handled correctly without needing individual APScheduler jobs.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Base tick interval — the scheduler wakes up this often and checks
# which policies are due.  Individual policy intervals are honoured
# via the ``next_check_at`` column (see pipeline.check_all_policies).
BASE_TICK_HOURS = 1


def start_scheduler(check_callback, interval_hours: int = BASE_TICK_HOURS):
    """Start the background scheduler for periodic policy checks.

    ``check_callback`` should be an async callable (no arguments) that
    invokes ``check_all_policies()``.
    """
    scheduler.add_job(
        check_callback,
        trigger=IntervalTrigger(hours=interval_hours),
        id="policy_check",
        name="Periodic Policy Check",
        replace_existing=True,
        max_instances=1,  # Prevent overlapping runs
    )
    scheduler.start()
    logger.info(
        f"Scheduler started — base tick every {interval_hours}h "
        f"(per-policy intervals honoured via next_check_at)"
    )


def stop_scheduler():
    """Shut down the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
