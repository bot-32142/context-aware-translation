"""Prevent system sleep while long-running operations are active."""

import ctypes
import logging
import platform
import subprocess
import threading

logger = logging.getLogger(__name__)

_SYSTEM = platform.system()


class SleepInhibitor:
    """Reference-counted system sleep inhibitor.

    Prevents idle sleep while at least one holder has acquired the inhibitor.

    - **macOS**: spawns a ``caffeinate -i`` subprocess.
    - **Windows**: calls ``SetThreadExecutionState`` via ctypes.
    - **Linux**: spawns ``systemd-inhibit sleep cat`` subprocess.

    Thread-safe: multiple workers can acquire/release from different threads.
    """

    _lock = threading.Lock()
    _count = 0
    _process: subprocess.Popen | None = None  # macOS / Linux

    @classmethod
    def acquire(cls) -> None:
        """Increment the hold count; start inhibition if this is the first."""
        if not cls._is_supported():
            return
        with cls._lock:
            cls._count += 1
            if cls._count == 1:
                cls._start()
            elif _SYSTEM != "Windows" and cls._process is not None and cls._process.poll() is not None:
                logger.warning("Sleep inhibitor process died unexpectedly, restarting")
                cls._start()

    @classmethod
    def release(cls) -> None:
        """Decrement the hold count; stop inhibition if this is the last."""
        if not cls._is_supported():
            return
        with cls._lock:
            if cls._count <= 0:
                logger.warning("SleepInhibitor.release() called without matching acquire()")
                cls._count = 0
                return
            cls._count -= 1
            if cls._count == 0:
                cls._stop()

    @classmethod
    def _start(cls) -> None:
        """Start platform-specific sleep inhibition."""
        if _SYSTEM == "Darwin":
            cls._start_subprocess(["caffeinate", "-i"])
        elif _SYSTEM == "Linux":
            cls._start_subprocess(
                [
                    "systemd-inhibit",
                    "--what=idle",
                    "--who=context-aware-translation",
                    "--why=Background operation in progress",
                    "cat",
                ]
            )
        elif _SYSTEM == "Windows":
            cls._start_windows()

    @classmethod
    def _stop(cls) -> None:
        """Stop platform-specific sleep inhibition."""
        if _SYSTEM == "Windows":
            cls._stop_windows()
        else:
            cls._stop_subprocess()

    @classmethod
    def _start_subprocess(cls, cmd: list[str]) -> None:
        """Spawn a subprocess that holds a sleep inhibition lock."""
        try:
            cls._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("Sleep prevention started (pid %d)", cls._process.pid)
        except FileNotFoundError:
            logger.warning("%s not found — sleep prevention unavailable", cmd[0])
            cls._process = None

    @classmethod
    def _stop_subprocess(cls) -> None:
        """Terminate the sleep inhibitor subprocess."""
        if cls._process is not None:
            if cls._process.stdin:
                cls._process.stdin.close()
            cls._process.terminate()
            cls._process.wait()
            logger.info("Sleep prevention stopped")
            cls._process = None

    @classmethod
    def _start_windows(cls) -> None:
        """Use SetThreadExecutionState to prevent idle sleep on Windows."""
        try:
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(  # type: ignore[attr-defined]
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            )
            logger.info("Sleep prevention started (Windows)")
        except AttributeError:
            logger.warning("SetThreadExecutionState not available — sleep prevention unavailable")

    @classmethod
    def _stop_windows(cls) -> None:
        """Reset execution state to allow sleep on Windows."""
        try:
            ES_CONTINUOUS = 0x80000000
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)  # type: ignore[attr-defined]
            logger.info("Sleep prevention stopped (Windows)")
        except AttributeError:
            pass

    @classmethod
    def is_active(cls) -> bool:
        """Return True if sleep prevention is currently active."""
        if _SYSTEM == "Windows":
            return cls._count > 0
        return cls._process is not None and cls._process.poll() is None

    @classmethod
    def _is_supported(cls) -> bool:
        """Return True if this platform supports sleep inhibition."""
        return _SYSTEM in ("Darwin", "Linux", "Windows")
