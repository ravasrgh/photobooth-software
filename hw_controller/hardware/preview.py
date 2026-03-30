"""MJPEG preview streaming server for live camera viewfinder.

Serves a Motion-JPEG stream over HTTP so the Electron frontend can
display a live preview in an <img> tag:

    <img src="http://127.0.0.1:8080/preview" />

The stream runs at a configurable FPS (default 15) and quality (default 70).
When no camera is available, a placeholder frame is served instead.
"""

import asyncio
import io
import logging
import time
from typing import Optional

from aiohttp import web

logger = logging.getLogger(__name__)

# 1×1 grey JPEG placeholder (generated at module load)
_PLACEHOLDER_FRAME: bytes = b""

def _make_placeholder() -> bytes:
    """Generate a small 320×240 placeholder JPEG with 'No Camera' text."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (320, 240), color=(40, 40, 40))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
        except (OSError, IOError):
            font = ImageFont.load_default()
        draw.text((80, 105), "No Camera", fill=(180, 180, 180), font=font)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        return buf.getvalue()
    except ImportError:
        # Minimal valid 1×1 JPEG if Pillow unavailable
        import struct
        return (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
            b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
            b"\x1f\x1e\x1d\x1a\x1c\x1c $.\' ',#\x1c\x1c(7),01444\x1f\'9=82<.342"
            b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
            b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
            b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00T\xdb\x9e\xa7\x13\xff\xd9"
        )


class PreviewServer:
    """Async MJPEG preview server.

    Usage:
        server = PreviewServer(port=8080, fps=15, quality=70)
        await server.start(camera_controller)  # starts serving
        ...
        await server.stop()
    """

    BOUNDARY = b"--frame"

    def __init__(self, port: int = 8080, fps: int = 15, quality: int = 70):
        self._port = port
        self._fps = fps
        self._quality = quality
        self._camera = None
        self._runner: Optional[web.AppRunner] = None
        self._running = False
        self._placeholder = _make_placeholder()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}/preview"

    async def start(self, camera=None) -> None:
        """Start the preview HTTP server.

        Args:
            camera: A CameraController instance (or None for placeholder mode).
        """
        if self._running:
            logger.warning("Preview server already running")
            return

        self._camera = camera

        app = web.Application()
        app.router.add_get("/preview", self._handle_stream)
        app.router.add_get("/preview/snapshot", self._handle_snapshot)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", self._port)
        await site.start()
        self._running = True
        logger.info("Preview server started on port %d (%d FPS)", self._port, self._fps)

    async def stop(self) -> None:
        """Stop the preview server."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        self._running = False
        self._camera = None
        logger.info("Preview server stopped")

    def _grab_frame(self) -> bytes:
        """Get a single JPEG frame from the camera, or placeholder."""
        if self._camera is not None:
            try:
                return self._camera.capture_preview_frame(quality=self._quality)
            except Exception as e:
                logger.debug("Preview frame error: %s", e)
        return self._placeholder

    async def _handle_stream(self, request: web.Request) -> web.StreamResponse:
        """MJPEG multipart stream handler."""
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "multipart/x-mixed-replace; boundary=frame",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)

        interval = 1.0 / self._fps
        try:
            while True:
                start = time.monotonic()
                frame = await asyncio.to_thread(self._grab_frame)
                chunk = (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                    + frame + b"\r\n"
                )
                await response.write(chunk)

                elapsed = time.monotonic() - start
                sleep_time = max(0, interval - elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
        except (ConnectionResetError, asyncio.CancelledError):
            pass

        return response

    async def _handle_snapshot(self, request: web.Request) -> web.Response:
        """Single JPEG snapshot endpoint."""
        frame = await asyncio.to_thread(self._grab_frame)
        return web.Response(body=frame, content_type="image/jpeg")
