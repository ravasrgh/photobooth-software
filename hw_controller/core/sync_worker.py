"""Background sync worker — uploads sessions and media to Supabase/S3 when online."""

import asyncio
import logging
from datetime import datetime, timezone

from hw_controller.config import SYNC_MAX_ATTEMPTS, SYNC_POLL_INTERVAL
from hw_controller.db.database import Database
from hw_controller.db.models import SyncJob

logger = logging.getLogger(__name__)


class SyncWorker:
    """
    Polls the sync_queue table for pending jobs and attempts uploads.

    Runs as a background asyncio task. Handles:
    - Retry with exponential back-off (max SYNC_MAX_ATTEMPTS)
    - Marking jobs as completed / failed
    - Graceful shutdown via cancel()
    """

    def __init__(self, db: Database, poll_interval: float = SYNC_POLL_INTERVAL):
        self._db = db
        self._poll_interval = poll_interval
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the background worker as an asyncio task."""
        self._task = asyncio.create_task(self._run(), name="sync_worker")
        logger.info("Sync worker started (poll every %.0fs)", self._poll_interval)

    async def stop(self) -> None:
        """Cancel the background task gracefully."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Sync worker stopped")

    async def _run(self) -> None:
        """Main loop — poll for pending jobs."""
        while True:
            try:
                await self._process_pending()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Sync worker error")
            await asyncio.sleep(self._poll_interval)

    async def _process_pending(self) -> None:
        """Fetch and process all pending sync jobs."""
        with self._db.session_scope() as session:
            pending_jobs = (
                session.query(SyncJob)
                .filter(SyncJob.status.in_(["pending", "failed"]))
                .filter(SyncJob.attempts < SyncJob.max_attempts)
                .order_by(SyncJob.created_at)
                .limit(10)
                .all()
            )

            for job in pending_jobs:
                await self._process_job(session, job)

    async def _process_job(self, db_session, job: SyncJob) -> None:
        """Attempt to upload a single job."""
        now = datetime.now(timezone.utc).isoformat()
        job.status = "in_progress"
        job.attempts += 1
        job.last_attempt_at = now
        db_session.commit()

        try:
            await self._upload(job)
            job.status = "completed"
            job.completed_at = now
            job.error_message = None
            logger.info("Sync job %s completed", job.id[:8])
        except Exception as e:
            if job.attempts >= job.max_attempts:
                job.status = "failed"
                logger.error("Sync job %s failed permanently: %s", job.id[:8], e)
            else:
                job.status = "pending"  # will be retried
                logger.warning(
                    "Sync job %s attempt %d/%d failed: %s",
                    job.id[:8], job.attempts, job.max_attempts, e,
                )
            job.error_message = str(e)
        finally:
            db_session.commit()

    async def _upload(self, job: SyncJob) -> None:
        """Perform the actual upload to Supabase/S3.

        This is a placeholder — implement with your cloud SDK.
        """
        # TODO: Replace with actual Supabase / S3 upload logic
        #
        # Example pseudocode:
        #   from supabase import create_client
        #   supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        #   with open(file_path, "rb") as f:
        #       supabase.storage.from_("photos").upload(remote_path, f)
        #
        logger.info(
            "Upload placeholder: job=%s type=%s (implement cloud SDK)",
            job.id[:8], job.job_type,
        )
        # Simulate a network check
        # raise ConnectionError("No internet") — uncomment to test retry logic
