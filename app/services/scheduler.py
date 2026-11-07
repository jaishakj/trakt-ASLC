"""Background scheduler for periodic Trakt sync and RSS checking.

Uses APScheduler to periodically poll Trakt and record job status.
Prevents concurrent execution using job locking.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.models.user import User, Integration
from app.sync.engine import SyncEngine

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
_sync_lock = asyncio.Lock()

last_job_run: Optional[datetime] = None
last_job_status: str = "never_run"
last_job_error: Optional[str] = None


async def run_scheduled_sync():
    """Periodic job executed every SYNC_INTERVAL_MINUTES."""
    global last_job_run, last_job_status, last_job_error

    if _sync_lock.locked():
        logger.warning("Scheduled sync skipped: previous run is still in progress")
        return

    async with _sync_lock:
        last_job_run = datetime.now(timezone.utc)
        logger.info("Starting scheduled Trakt synchronization job...")
        try:
            async with AsyncSessionLocal() as session:
                # Find all users with active Trakt integrations
                stmt = select(Integration.user_id).where(
                    Integration.provider == "trakt",
                    Integration.access_token.isnot(None),
                )
                res = await session.execute(stmt)
                user_ids = res.scalars().all()

                if not user_ids:
                    logger.info("No connected Trakt users found for scheduled sync.")
                    last_job_status = "idle"
                    return

                engine = SyncEngine(session)
                for u_id in user_ids:
                    logger.info(f"Synchronizing Trakt for user_id={u_id}")
                    summary = await engine.execute_sync(u_id, dry_run=False, write_to_trakt=True)
                    logger.info(
                        f"User {u_id} sync completed: {summary.new_watch_events} new watches, "
                        f"{summary.rating_updates} rating updates, {summary.conflicts} conflicts."
                    )

            last_job_status = "success"
            last_job_error = None
        except Exception as exc:
            logger.error(f"Scheduled sync encountered an error: {exc}", exc_info=True)
            last_job_status = "failed"
            last_job_error = str(exc)


def start_scheduler():
    """Start the APScheduler background loop."""
    if not scheduler.running:
        scheduler.add_job(
            run_scheduled_sync,
            "interval",
            minutes=settings.SYNC_INTERVAL_MINUTES,
            id="trakt_sync_job",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        scheduler.start()
        logger.info(f"APScheduler started with interval={settings.SYNC_INTERVAL_MINUTES} minutes.")


def shutdown_scheduler():
    """Gracefully shutdown scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")
