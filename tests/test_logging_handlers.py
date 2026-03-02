from __future__ import annotations

import logging

from context_aware_translation import SafeRotatingFileHandler


def test_safe_rotating_file_handler_ignores_missing_parent(tmp_path):
    log_file = tmp_path / "removed" / "logs" / "app.log"
    handler = SafeRotatingFileHandler(
        filename=str(log_file),
        maxBytes=1024,
        backupCount=1,
        encoding="utf-8",
        delay=True,
    )
    logger = logging.getLogger("cat.test.safe_handler.missing_parent")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        logger.info("hello")
        assert not log_file.exists()
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_safe_rotating_file_handler_writes_when_parent_exists(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"
    handler = SafeRotatingFileHandler(
        filename=str(log_file),
        maxBytes=1024,
        backupCount=1,
        encoding="utf-8",
    )
    logger = logging.getLogger("cat.test.safe_handler.normal")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        logger.info("world")
        handler.flush()
        assert log_file.exists()
        assert "world" in log_file.read_text(encoding="utf-8")
    finally:
        logger.removeHandler(handler)
        handler.close()
