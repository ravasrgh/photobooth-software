"""DSLR Camera controller — wraps gphoto2 for capture + download."""

import logging
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Try to import gphoto2; allow graceful fallback for dev/testing
try:
    import gphoto2 as gp
except ImportError:
    gp = None  # type: ignore
    logger.warning("gphoto2 not installed — camera features are disabled")


@dataclass
class CaptureResult:
    """Result of a successful camera capture."""
    file_path: Path
    width: int
    height: int
    file_size_bytes: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "file_path": str(self.file_path),
            "width": self.width,
            "height": self.height,
            "file_size_bytes": self.file_size_bytes,
            "timestamp": self.timestamp,
        }


class CameraError(Exception):
    """Base for all camera errors."""
    code = "CAMERA_ERROR"


class CameraDisconnectedError(CameraError):
    """Raised when the camera is not connected or communication is lost."""
    code = "CAMERA_DISCONNECTED"


class CameraBusyError(CameraError):
    """Raised when the camera is busy processing a previous command."""
    code = "CAMERA_BUSY"


class CameraController:
    """
    Manages a single DSLR camera via libgphoto2.

    Provides connect/disconnect lifecycle, capture + download, and
    automatic reconnection when USB is interrupted.
    """

    def __init__(
        self,
        download_dir: Path,
        max_reconnect_attempts: int = 5,
        reconnect_interval: float = 2.0,
    ):
        self._camera = None
        self._context = None
        self._download_dir = download_dir
        self._connected = False
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_interval = reconnect_interval

    # ── Connection lifecycle ────────────────────────────────────────

    def connect(self) -> dict:
        """Detect and connect to the first available camera.

        Returns:
            dict with "status" and "summary" keys.

        Raises:
            CameraDisconnectedError: if no camera can be initialised.
            RuntimeError: if gphoto2 is not installed.
        """
        if gp is None:
            raise RuntimeError("gphoto2 is not installed")

        self._context = gp.Context()
        self._camera = gp.Camera()
        try:
            self._camera.init(self._context)
            self._connected = True
            summary = self._camera.get_summary(self._context)
            model_info = summary.text[:120]
            logger.info("Camera connected: %s", model_info)
            return {"status": "connected", "summary": model_info}
        except gp.GPhoto2Error as e:
            self._connected = False
            raise CameraDisconnectedError(f"Cannot init camera: {e}") from e

    def disconnect(self) -> None:
        """Gracefully release the camera."""
        if self._camera is not None:
            try:
                self._camera.exit(self._context)
            except Exception:
                pass
            finally:
                self._camera = None
                self._connected = False
                logger.info("Camera disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _ensure_connected(self) -> None:
        if not self._connected or self._camera is None:
            raise CameraDisconnectedError("Camera is not connected")

    # ── Capture ─────────────────────────────────────────────────────

    def trigger_capture(self, session_id: str, photo_index: int) -> CaptureResult:
        """Trigger the shutter, download the resulting image, and delete from SD.

        Args:
            session_id: Unique session identifier (used as subdirectory name).
            photo_index: 1-based index of the photo within the session.

        Returns:
            CaptureResult with the local file path and metadata.

        Raises:
            CameraDisconnectedError: on communication failure.
            CameraBusyError: if the camera is still processing.
        """
        self._ensure_connected()
        try:
            # 1. Capture
            file_path = self._camera.capture(gp.GP_CAPTURE_IMAGE, self._context)
            logger.info("Captured: %s/%s", file_path.folder, file_path.name)

            # 2. Download to local disk
            dest = self._download_dir / session_id
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / f"photo_{photo_index:03d}.jpg"

            camera_file = self._camera.file_get(
                file_path.folder,
                file_path.name,
                gp.GP_FILE_TYPE_NORMAL,
                self._context,
            )
            camera_file.save(str(target))

            # 3. Delete from camera SD to free space
            self._camera.file_delete(file_path.folder, file_path.name, self._context)

            file_size = target.stat().st_size

            # 4. Extract dimensions via Pillow if available
            width, height = 0, 0
            try:
                from PIL import Image

                with Image.open(target) as img:
                    width, height = img.size
            except Exception:
                pass

            result = CaptureResult(
                file_path=target,
                width=width,
                height=height,
                file_size_bytes=file_size,
            )
            logger.info(
                "Downloaded: %s (%dx%d, %d bytes)",
                target.name, width, height, file_size,
            )
            return result

        except gp.GPhoto2Error as e:
            error_code = getattr(e, "code", None)
            # GP_ERROR_CAMERA_BUSY = -110
            if error_code == -110:
                raise CameraBusyError(f"Camera busy: {e}") from e
            self._connected = False
            raise CameraDisconnectedError(f"Capture failed: {e}") from e

    # ── Preview frames ──────────────────────────────────────────────

    def capture_preview_frame(self, quality: int = 70) -> bytes:
        """Grab a single viewfinder JPEG frame for live preview streaming.

        Uses GP_CAPTURE_PREVIEW which reads the camera's live-view buffer
        without triggering the mechanical shutter.

        Args:
            quality: JPEG compression quality (1–100).

        Returns:
            Raw JPEG bytes.

        Raises:
            CameraDisconnectedError: if the camera is not connected.
        """
        self._ensure_connected()
        try:
            camera_file = self._camera.capture_preview(self._context)
            data = camera_file.get_data_and_size()
            return bytes(data)
        except gp.GPhoto2Error as e:
            raise CameraDisconnectedError(f"Preview capture failed: {e}") from e

    # ── Reconnection ────────────────────────────────────────────────

    def attempt_reconnect(self) -> bool:
        """Try to reconnect to the camera with retries.

        Returns:
            True if reconnection succeeded, False otherwise.
        """
        for attempt in range(1, self._max_reconnect_attempts + 1):
            logger.warning(
                "Reconnect attempt %d/%d",
                attempt,
                self._max_reconnect_attempts,
            )
            try:
                self.disconnect()
                self.connect()
                logger.info("Reconnect succeeded on attempt %d", attempt)
                return True
            except CameraDisconnectedError:
                time.sleep(self._reconnect_interval)
        logger.error("Reconnection failed after %d attempts", self._max_reconnect_attempts)
        return False
