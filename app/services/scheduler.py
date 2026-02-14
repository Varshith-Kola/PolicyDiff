"""APScheduler-based periodic policy checking."""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def start_scheduler(check_callback, interval_hours: int = 24):
    """Start the background scheduler for periodic policy checks."""
    scheduler.add_job(
        check_callback,
        trigger=IntervalTrigger(hours=interval_hours),
        id="policy_check",
        name="Periodic Policy Check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started — checking policies every {interval_hours} hours")


def stop_scheduler():
    """Shut down the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
