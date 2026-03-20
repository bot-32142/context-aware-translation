from __future__ import annotations

import threading
from pathlib import Path

_SQLITE_FILE_LOCKS: dict[str, threading.RLock] = {}
_SQLITE_FILE_LOCKS_GUARD = threading.Lock()


def get_sqlite_file_lock(sqlite_path: Path) -> threading.RLock:
    key = str(Path(sqlite_path).resolve())
    with _SQLITE_FILE_LOCKS_GUARD:
        lock = _SQLITE_FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _SQLITE_FILE_LOCKS[key] = lock
        return lock
