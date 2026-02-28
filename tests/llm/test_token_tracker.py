"""Tests for TokenTracker singleton."""

import logging
import tempfile
import threading
import time
from pathlib import Path

import pytest

from context_aware_translation.llm.token_tracker import TokenLimitExceededError, TokenTracker
from context_aware_translation.storage.endpoint_profile import EndpointProfile
from context_aware_translation.storage.registry_db import RegistryDB


@pytest.fixture
def registry():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = RegistryDB(Path(tmpdir) / "test.db")
        yield db
        db.close()


@pytest.fixture(autouse=True)
def cleanup_tracker():
    """Ensure tracker is cleaned up after each test."""
    yield
    TokenTracker.shutdown()


def _insert_profile(
    registry,
    name="test",
    token_limit=None,
    tokens_used=0,
    input_token_limit=None,
    output_token_limit=None,
    input_tokens_used=0,
    output_tokens_used=0,
):
    import time

    ep = EndpointProfile(
        profile_id=name,
        name=name,
        created_at=time.time(),
        updated_at=time.time(),
        api_key="key",
        base_url="url",
        model="model",
        token_limit=token_limit,
        tokens_used=tokens_used,
        input_token_limit=input_token_limit,
        output_token_limit=output_token_limit,
        input_tokens_used=input_tokens_used,
        output_tokens_used=output_tokens_used,
    )
    registry.insert_endpoint_profile(ep)
    return ep


class TestTokenTrackerSingleton:
    def test_get_returns_none_before_initialize(self):
        assert TokenTracker.get() is None

    def test_initialize_sets_singleton(self, registry):
        TokenTracker.initialize(registry)
        assert TokenTracker.get() is not None

    def test_shutdown_clears_singleton(self, registry):
        TokenTracker.initialize(registry)
        TokenTracker.shutdown()
        assert TokenTracker.get() is None


class TestCheckLimit:
    def test_noop_with_none_profile(self, registry):
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()
        tracker.check_limit(None)  # Should not raise

    def test_noop_with_unknown_profile(self, registry):
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()
        tracker.check_limit("nonexistent")  # Should not raise

    def test_noop_with_no_limit(self, registry):
        _insert_profile(registry, "unlimited", token_limit=None)
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()
        tracker.check_limit("unlimited")  # Should not raise

    def test_raises_when_over_total_limit(self, registry):
        ep = _insert_profile(registry, "limited", token_limit=1000, tokens_used=0)
        registry.increment_endpoint_tokens(ep.profile_id, 1000)
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()
        with pytest.raises(TokenLimitExceededError, match="Total token limit exceeded"):
            tracker.check_limit("limited")

    def test_raises_when_over_input_limit(self, registry):
        ep = _insert_profile(registry, "input_limited", input_token_limit=500)
        registry.increment_endpoint_tokens(ep.profile_id, 600, input_tokens=500, output_tokens=100)
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()
        with pytest.raises(TokenLimitExceededError, match="Input token limit exceeded"):
            tracker.check_limit("input_limited")

    def test_raises_when_over_output_limit(self, registry):
        ep = _insert_profile(registry, "output_limited", output_token_limit=300)
        registry.increment_endpoint_tokens(ep.profile_id, 500, input_tokens=200, output_tokens=300)
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()
        with pytest.raises(TokenLimitExceededError, match="Output token limit exceeded"):
            tracker.check_limit("output_limited")

    def test_allows_under_limit(self, registry):
        ep = _insert_profile(registry, "ok", token_limit=1000, tokens_used=0)
        registry.increment_endpoint_tokens(ep.profile_id, 500)
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()
        tracker.check_limit("ok")  # Should not raise

    def test_zero_limit_blocks_immediately(self, registry):
        _insert_profile(registry, "zero", token_limit=0, tokens_used=0)
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()
        with pytest.raises(TokenLimitExceededError):
            tracker.check_limit("zero")


class TestRecordUsage:
    def test_increments_counter_with_dict(self, registry):
        ep = _insert_profile(registry, "track", token_limit=10000)
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()
        tracker.record_usage(
            "track",
            {
                "total_tokens": 500,
                "cached_input_tokens": 100,
                "uncached_input_tokens": 200,
                "output_tokens": 150,
                "reasoning_tokens": 50,
            },
        )
        loaded = registry.get_endpoint_profile(ep.profile_id)
        assert loaded.tokens_used == 500
        assert loaded.input_tokens_used == 300  # 100 + 200
        assert loaded.output_tokens_used == 200  # 150 + 50
        assert loaded.cached_input_tokens_used == 100
        assert loaded.uncached_input_tokens_used == 200

    def test_increments_counter_with_int_legacy(self, registry):
        ep = _insert_profile(registry, "legacy", token_limit=10000)
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()
        tracker.record_usage("legacy", 500)
        loaded = registry.get_endpoint_profile(ep.profile_id)
        assert loaded.tokens_used == 500
        assert loaded.input_tokens_used == 0
        assert loaded.output_tokens_used == 0
        assert loaded.cached_input_tokens_used == 0
        assert loaded.uncached_input_tokens_used == 0

    def test_noop_with_none_profile(self, registry):
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()
        tracker.record_usage(None, {"total_tokens": 500})  # Should not raise

    def test_noop_with_zero_tokens(self, registry):
        ep = _insert_profile(registry, "zero_tok", token_limit=10000)
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()
        tracker.record_usage("zero_tok", {"total_tokens": 0})
        loaded = registry.get_endpoint_profile(ep.profile_id)
        assert loaded.tokens_used == 0

    def test_80_pct_warning_fires_once(self, registry, caplog):
        _insert_profile(registry, "warn", token_limit=1000)
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()

        with caplog.at_level(logging.WARNING):
            tracker.record_usage("warn", {"total_tokens": 800})  # 80% — should warn
            assert "Token usage warning" in caplog.text
            assert "total" in caplog.text

        caplog.clear()
        with caplog.at_level(logging.WARNING):
            tracker.record_usage("warn", {"total_tokens": 50})  # 85% — should NOT warn again
            assert "Token usage warning" not in caplog.text

    def test_80_pct_warning_fires_independently_per_limit(self, registry, caplog):
        _insert_profile(registry, "multi", token_limit=1000, input_token_limit=500, output_token_limit=500)
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()

        # Trigger input warning (80% of 500 = 400)
        with caplog.at_level(logging.WARNING):
            tracker.record_usage(
                "multi",
                {
                    "total_tokens": 450,
                    "cached_input_tokens": 0,
                    "uncached_input_tokens": 400,
                    "output_tokens": 50,
                },
            )
            assert "input" in caplog.text

        caplog.clear()
        # Trigger output warning (accumulate to 80% of 500 = 400)
        with caplog.at_level(logging.WARNING):
            tracker.record_usage(
                "multi",
                {
                    "total_tokens": 400,
                    "cached_input_tokens": 0,
                    "uncached_input_tokens": 50,
                    "output_tokens": 350,
                },
            )
            assert "output" in caplog.text

    def test_clear_warning_allows_refire(self, registry, caplog):
        ep = _insert_profile(registry, "rewarn", token_limit=1000)
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()

        with caplog.at_level(logging.WARNING):
            tracker.record_usage("rewarn", {"total_tokens": 850})  # 85%
            assert "Token usage warning" in caplog.text

        # Reset and clear warning
        registry.reset_endpoint_tokens(ep.profile_id)
        tracker.clear_warning("rewarn")

        caplog.clear()
        with caplog.at_level(logging.WARNING):
            tracker.record_usage("rewarn", {"total_tokens": 850})  # 85% again
            assert "Token usage warning" in caplog.text

    def test_clear_warning_clears_all_limit_keys(self, registry, caplog):
        ep = _insert_profile(registry, "clearall", token_limit=1000, input_token_limit=500, output_token_limit=500)
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()

        # Trigger all warnings
        tracker.record_usage(
            "clearall",
            {
                "total_tokens": 850,
                "cached_input_tokens": 0,
                "uncached_input_tokens": 425,
                "output_tokens": 425,
            },
        )

        # Clear all
        registry.reset_endpoint_tokens(ep.profile_id)
        tracker.clear_warning("clearall")

        caplog.clear()
        with caplog.at_level(logging.WARNING):
            tracker.record_usage(
                "clearall",
                {
                    "total_tokens": 850,
                    "cached_input_tokens": 0,
                    "uncached_input_tokens": 425,
                    "output_tokens": 425,
                },
            )
            # All 3 warnings should fire again
            assert caplog.text.count("Token usage warning") == 3


class TestThreadSafety:
    def test_initialize_is_serialized_across_threads(self, registry, monkeypatch):
        original_init = TokenTracker.__init__
        active = 0
        max_active = 0
        active_lock = threading.Lock()

        def instrumented_init(self, reg):
            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.01)
                original_init(self, reg)
            finally:
                with active_lock:
                    active -= 1

        monkeypatch.setattr(TokenTracker, "__init__", instrumented_init)

        barrier = threading.Barrier(8)
        errors: list[Exception] = []

        def worker() -> None:
            try:
                barrier.wait()
                TokenTracker.initialize(registry)
            except Exception as e:  # pragma: no cover - exercised only on failure
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert max_active == 1
        assert TokenTracker.get() is not None

    def test_warning_set_access_is_serialized_across_threads(self, registry, monkeypatch):
        _insert_profile(registry, "threadsafe_warn", token_limit=1000)
        TokenTracker.initialize(registry)
        tracker = TokenTracker.get()
        assert tracker is not None

        class InstrumentedSet(set):
            def __init__(self):
                super().__init__()
                self._active = 0
                self.max_active = 0
                self._active_lock = threading.Lock()

            def _enter(self) -> None:
                with self._active_lock:
                    self._active += 1
                    self.max_active = max(self.max_active, self._active)

            def _exit(self) -> None:
                with self._active_lock:
                    self._active -= 1

            def __contains__(self, key):
                self._enter()
                try:
                    time.sleep(0.002)
                    return super().__contains__(key)
                finally:
                    self._exit()

            def add(self, key):
                self._enter()
                try:
                    time.sleep(0.002)
                    return super().add(key)
                finally:
                    self._exit()

        instrumented = InstrumentedSet()
        tracker._warned_profiles = instrumented

        def _ignore_warning(*_args, **_kwargs) -> None:
            return None

        monkeypatch.setattr("context_aware_translation.llm.token_tracker.logger.warning", _ignore_warning)

        barrier = threading.Barrier(12)
        errors: list[Exception] = []

        def worker() -> None:
            try:
                barrier.wait()
                tracker._check_warning("threadsafe_warn", "total", 800, 1000)
            except Exception as e:  # pragma: no cover - exercised only on failure
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert instrumented.max_active == 1
        assert "threadsafe_warn:total" in tracker._warned_profiles
