"""Silent printing — sends a file to the OS default printer without dialogs."""

import logging
import platform
import subprocess
from pathlib import Path
from typing import Optional

from hw_controller.config import PRINT_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class PrinterError(Exception):
    """Raised when a print job fails."""
    code = "PRINTER_ERROR"


class PrinterController:
    """
    Cross-platform silent printing.

    Windows:  PowerShell `Start-Process -Verb Print`
    macOS:    `lpr`
    Linux:    `lp`
    """

    def __init__(self, timeout: int = PRINT_TIMEOUT_SECONDS):
        self._timeout = timeout

    def print_file(
        self,
        file_path: Path,
        copies: int = 1,
        printer_name: Optional[str] = None,
    ) -> dict:
        """Print a file silently, bypassing all dialogs.

        Args:
            file_path: Absolute path to the image/PDF to print.
            copies: Number of copies to print.
            printer_name: Optional specific printer. Uses OS default if None.

        Returns:
            dict with "status", "file", and "copies".

        Raises:
            PrinterError: on any failure (file missing, timeout, OS error).
        """
        if not file_path.exists():
            raise PrinterError(f"File not found: {file_path}")

        system = platform.system()

        try:
            if system == "Windows":
                self._print_windows(file_path, copies, printer_name)
            elif system == "Darwin":
                self._print_macos(file_path, copies, printer_name)
            elif system == "Linux":
                self._print_linux(file_path, copies, printer_name)
            else:
                raise PrinterError(f"Unsupported OS: {system}")

            logger.info("Printed %d copies of %s", copies, file_path.name)
            return {"status": "printed", "file": str(file_path), "copies": copies}

        except subprocess.TimeoutExpired as e:
            raise PrinterError(f"Print command timed out after {self._timeout}s") from e
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="replace") if e.stderr else str(e)
            raise PrinterError(f"Print failed: {stderr}") from e

    # ── Platform-specific implementations ───────────────────────────

    def _print_windows(
        self, file_path: Path, copies: int, printer_name: Optional[str]
    ) -> None:
        for _ in range(copies):
            cmd = (
                f'Start-Process -FilePath "{file_path}" '
                f'-Verb Print -WindowStyle Hidden'
            )
            if printer_name:
                # Use rundll32 for named printer
                cmd = (
                    f'rundll32 printui.dll,PrintUIEntry /y /n "{printer_name}"; '
                    f'Start-Process -FilePath "{file_path}" '
                    f'-Verb Print -WindowStyle Hidden'
                )
            subprocess.run(
                ["powershell", "-Command", cmd],
                check=True,
                capture_output=True,
                timeout=self._timeout,
            )

    def _print_macos(
        self, file_path: Path, copies: int, printer_name: Optional[str]
    ) -> None:
        cmd = ["lpr"]
        if printer_name:
            cmd += ["-P", printer_name]
        cmd += ["-#", str(copies), str(file_path)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=self._timeout)

    def _print_linux(
        self, file_path: Path, copies: int, printer_name: Optional[str]
    ) -> None:
        cmd = ["lp"]
        if printer_name:
            cmd += ["-d", printer_name]
        cmd += ["-n", str(copies), str(file_path)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=self._timeout)

    # ── Utility ─────────────────────────────────────────────────────

    @staticmethod
    def list_printers() -> list[str]:
        """Return a list of available printer names (best-effort)."""
        system = platform.system()
        try:
            if system == "Windows":
                result = subprocess.run(
                    ["powershell", "-Command",
                     "Get-Printer | Select-Object -ExpandProperty Name"],
                    capture_output=True, text=True, timeout=10,
                )
                return [p.strip() for p in result.stdout.splitlines() if p.strip()]
            elif system in ("Darwin", "Linux"):
                result = subprocess.run(
                    ["lpstat", "-p"],
                    capture_output=True, text=True, timeout=10,
                )
                printers = []
                for line in result.stdout.splitlines():
                    if line.startswith("printer"):
                        parts = line.split()
                        if len(parts) >= 2:
                            printers.append(parts[1])
                return printers
        except Exception as e:
            logger.warning("Failed to list printers: %s", e)
        return []
