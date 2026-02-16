"""Session lifecycle orchestrator — ties state machine, camera, printer, and DB together."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hw_controller.config import DEFAULT_COUNTDOWN_SECONDS, DEFAULT_PHOTOS_PER_SESSION
from hw_controller.core.state_machine import BoothStateMachine, State, Trigger, InvalidTransitionError
from hw_controller.hardware.camera import CameraController, CameraError, CaptureResult
from hw_controller.hardware.printer import PrinterController, PrinterError
from hw_controller.db.database import Database
from hw_controller.db.models import Session as SessionModel, Media, SyncJob

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Orchestrates a complete photobooth session:

    1. start_session → creates DB record, moves to COUNTDOWN
    2. run_countdown → counts down, then fires capture
    3. capture → triggers camera, saves media to DB
    4. process → thumbnail generation (future: filters, overlays)
    5. review → user decides: next_photo / print / done
    6. print → sends to printer
    7. complete → finalises DB record, queues sync job
    """

    def __init__(
        self,
        state_machine: BoothStateMachine,
        camera: CameraController,
        printer: PrinterController,
        db: Database,
    ):
        self._sm = state_machine
        self._camera = camera
        self._printer = printer
        self._db = db

        # Active session state
        self._session_id: Optional[str] = None
        self._photo_index: int = 0
        self._photos_target: int = DEFAULT_PHOTOS_PER_SESSION
        self._countdown_seconds: int = DEFAULT_COUNTDOWN_SECONDS

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    @property
    def photo_index(self) -> int:
        return self._photo_index

    @property
    def photos_remaining(self) -> int:
        return max(0, self._photos_target - self._photo_index)

    # ── Session lifecycle ───────────────────────────────────────────

    async def start_session(
        self,
        event_name: Optional[str] = None,
        photos_per_session: Optional[int] = None,
        countdown_seconds: Optional[int] = None,
    ) -> dict:
        """Create a new session and transition to COUNTDOWN."""
        self._session_id = str(uuid.uuid4())
        self._photo_index = 0
        self._photos_target = photos_per_session or DEFAULT_PHOTOS_PER_SESSION
        self._countdown_seconds = countdown_seconds or DEFAULT_COUNTDOWN_SECONDS

        # Persist session
        session = SessionModel(
            id=self._session_id,
            event_name=event_name,
            status="active",
        )
        with self._db.session_scope() as db_session:
            db_session.add(session)

        await self._sm.fire(Trigger.SESSION_START, {
            "session_id": self._session_id,
            "photos_target": self._photos_target,
        })

        return {
            "session_id": self._session_id,
            "photos_target": self._photos_target,
            "countdown_seconds": self._countdown_seconds,
        }

    async def cancel_session(self) -> dict:
        """Cancel the current session and return to IDLE."""
        sid = self._session_id
        with self._db.session_scope() as db_session:
            session = db_session.query(SessionModel).get(sid)
            if session:
                session.status = "cancelled"
                session.completed_at = datetime.now(timezone.utc).isoformat()

        await self._sm.fire(Trigger.SESSION_CANCEL, {"session_id": sid})
        self._session_id = None
        return {"session_id": sid, "status": "cancelled"}

    # ── Countdown ───────────────────────────────────────────────────

    async def run_countdown(self, publish_tick=None) -> None:
        """Run the countdown timer. Calls publish_tick(remaining) each second."""
        for remaining in range(self._countdown_seconds, 0, -1):
            if publish_tick:
                await publish_tick(remaining)
            await asyncio.sleep(1)
        await self._sm.fire(Trigger.COUNTDOWN_DONE, {"session_id": self._session_id})

    # ── Capture ─────────────────────────────────────────────────────

    async def capture(self) -> dict:
        """Trigger camera capture and save media record."""
        self._photo_index += 1
        try:
            result: CaptureResult = await asyncio.to_thread(
                self._camera.trigger_capture,
                self._session_id,
                self._photo_index,
            )

            # Persist media
            media = Media(
                session_id=self._session_id,
                photo_index=self._photo_index,
                file_path=str(result.file_path),
                file_size_bytes=result.file_size_bytes,
                width=result.width,
                height=result.height,
            )
            with self._db.session_scope() as db_session:
                db_session.add(media)
                # Update session photo count
                session = db_session.query(SessionModel).get(self._session_id)
                if session:
                    session.photo_count = self._photo_index

            await self._sm.fire(Trigger.CAPTURE_DONE, {
                "session_id": self._session_id,
                **result.to_dict(),
            })

            return result.to_dict()

        except CameraError as e:
            await self._sm.fire(Trigger.CAPTURE_FAIL, {
                "session_id": self._session_id,
                "error_code": e.code,
                "error_message": str(e),
            })
            # Attempt reconnect in background
            asyncio.create_task(self._auto_reconnect())
            raise

    async def _auto_reconnect(self) -> None:
        """Background task to reconnect camera after failure."""
        success = await asyncio.to_thread(self._camera.attempt_reconnect)
        if success:
            await self._sm.fire(Trigger.ERROR_RESOLVED, {"reason": "camera_reconnected"})
        else:
            logger.error("Camera auto-reconnect failed — manual intervention needed")

    # ── Processing ──────────────────────────────────────────────────

    async def process_photo(self, file_path: str) -> dict:
        """Post-process a captured photo (thumbnail, future: filters).

        Currently generates a thumbnail via Pillow.
        """
        try:
            thumb_path = await asyncio.to_thread(self._generate_thumbnail, file_path)
            await self._sm.fire(Trigger.PROCESSING_DONE, {
                "session_id": self._session_id,
                "file_path": file_path,
                "thumbnail_path": str(thumb_path),
            })
            return {"file_path": file_path, "thumbnail_path": str(thumb_path)}
        except Exception as e:
            await self._sm.fire(Trigger.PROCESSING_FAIL, {
                "session_id": self._session_id,
                "error_message": str(e),
            })
            raise

    @staticmethod
    def _generate_thumbnail(file_path: str, size: tuple = (400, 300)) -> Path:
        """Create a thumbnail alongside the original file."""
        from PIL import Image

        src = Path(file_path)
        thumb = src.parent / f"{src.stem}_thumb{src.suffix}"
        with Image.open(src) as img:
            img.thumbnail(size)
            img.save(thumb, "JPEG", quality=85)
        return thumb

    # ── Print ───────────────────────────────────────────────────────

    async def print_photo(self, file_path: str, copies: int = 1) -> dict:
        """Send a photo to the printer."""
        try:
            result = await asyncio.to_thread(
                self._printer.print_file, Path(file_path), copies
            )
            # Mark as printed
            with self._db.session_scope() as db_session:
                media = db_session.query(Media).filter_by(file_path=file_path).first()
                if media:
                    media.printed = 1

            await self._sm.fire(Trigger.PRINT_DONE, {
                "session_id": self._session_id,
                **result,
            })
            return result
        except PrinterError as e:
            await self._sm.fire(Trigger.PRINT_FAIL, {
                "session_id": self._session_id,
                "error_code": e.code,
                "error_message": str(e),
            })
            raise

    # ── Complete / next ─────────────────────────────────────────────

    async def next_photo(self) -> dict:
        """Move to the next photo in the session (back to COUNTDOWN)."""
        await self._sm.fire(Trigger.NEXT_PHOTO, {
            "session_id": self._session_id,
            "photo_index": self._photo_index + 1,
            "photos_remaining": self.photos_remaining,
        })
        return {"photos_remaining": self.photos_remaining}

    async def complete_session(self) -> dict:
        """Finalise the session and queue for cloud sync."""
        sid = self._session_id

        with self._db.session_scope() as db_session:
            session = db_session.query(SessionModel).get(sid)
            if session:
                session.status = "completed"
                session.completed_at = datetime.now(timezone.utc).isoformat()

            # Queue sync job
            sync_job = SyncJob(
                media_id=None,
                job_type="upload_session",
                status="pending",
            )
            db_session.add(sync_job)

        await self._sm.fire(Trigger.SESSION_COMPLETE, {"session_id": sid})
        self._session_id = None
        return {"session_id": sid, "status": "completed"}
