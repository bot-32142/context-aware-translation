"""Global token usage tracker for endpoint profile limits."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from context_aware_translation.storage.endpoint_profile import EndpointProfile
    from context_aware_translation.storage.schema.registry_db import RegistryDB

logger = logging.getLogger(__name__)


class TokenLimitExceededError(Exception):
    """Raised when endpoint profile token limit is exceeded."""

    pass


class TokenTracker:
    """Singleton tracker for token usage per endpoint profile.

    Initialize once at app startup with a RegistryDB instance.
    LLMClient.chat() calls check_limit() before and record_usage() after each API call.
    If not initialized, all methods are no-ops.
    """

    _instance: TokenTracker | None = None
    _instance_lock = threading.RLock()

    def __init__(self, registry: RegistryDB) -> None:
        self._registry = registry
        self._warned_profiles: set[str] = set()
        self._warned_profiles_lock = threading.Lock()

    def _resolve_endpoint_profile(self, profile_ref: str) -> EndpointProfile | None:
        """Resolve an endpoint profile by ID."""
        return self._registry.get_endpoint_profile(profile_ref)

    @classmethod
    def initialize(cls, registry: RegistryDB) -> None:
        """Initialize the global tracker. Call once at app startup."""
        with cls._instance_lock:
            cls._instance = cls(registry)

    @classmethod
    def get(cls) -> TokenTracker | None:
        """Get the global tracker instance, or None if not initialized."""
        with cls._instance_lock:
            return cls._instance

    @classmethod
    def shutdown(cls) -> None:
        """Clear the global tracker (for app shutdown or testing)."""
        with cls._instance_lock:
            cls._instance = None

    def check_limit(self, profile_ref: str | None) -> None:
        """Check if endpoint profile has exceeded any token limit.

        Checks total, input, AND output limits independently.
        Raises TokenLimitExceededError if any limit is exceeded.
        No-op if profile_ref is None or profile has no limits.
        """
        if profile_ref is None:
            return
        ep = self._resolve_endpoint_profile(profile_ref)
        if ep is None:
            return
        if ep.token_limit is not None and ep.tokens_used >= ep.token_limit:
            raise TokenLimitExceededError(
                f"Total token limit exceeded for endpoint '{ep.name}': "
                f"{ep.tokens_used:,} / {ep.token_limit:,} tokens used"
            )
        if ep.input_token_limit is not None and ep.input_tokens_used >= ep.input_token_limit:
            raise TokenLimitExceededError(
                f"Input token limit exceeded for endpoint '{ep.name}': "
                f"{ep.input_tokens_used:,} / {ep.input_token_limit:,} input tokens used"
            )
        if ep.output_token_limit is not None and ep.output_tokens_used >= ep.output_token_limit:
            raise TokenLimitExceededError(
                f"Output token limit exceeded for endpoint '{ep.name}': "
                f"{ep.output_tokens_used:,} / {ep.output_token_limit:,} output tokens used"
            )

    def record_usage(self, profile_ref: str | None, token_usage: int | dict[str, Any]) -> None:
        """Record token usage and emit 80% warnings if thresholds crossed.

        Args:
            profile_ref: Endpoint profile ID reference (None = no-op).
            token_usage: Either an int (total tokens, legacy) or a dict with keys:
                total_tokens, cached_input_tokens, uncached_input_tokens,
                output_tokens, reasoning_tokens.

        No-op if profile_ref is None or profile not found.
        Warning fires only once per profile per limit type per tracker lifetime.
        """
        if profile_ref is None:
            return

        # Normalize input
        if isinstance(token_usage, int):
            total_tokens = token_usage
            input_tokens = 0
            output_tokens = 0
            cached_input = 0
            uncached_input = 0
        else:
            total_tokens = token_usage.get("total_tokens", 0)
            cached_input = token_usage.get("cached_input_tokens", 0)
            uncached_input = token_usage.get("uncached_input_tokens", 0)
            input_tokens = cached_input + uncached_input
            out = token_usage.get("output_tokens", 0)
            reasoning = token_usage.get("reasoning_tokens", 0)
            output_tokens = out + reasoning

        if total_tokens <= 0:
            return

        ep = self._resolve_endpoint_profile(profile_ref)
        if ep is None:
            return
        updated = self._registry.increment_endpoint_tokens(
            ep.profile_id,
            total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input,
            uncached_input_tokens=uncached_input,
        )
        if updated is None:
            return

        # Check 80% warnings for each limit type independently
        self._check_warning(ep.name, "total", updated.tokens_used, updated.token_limit)
        self._check_warning(ep.name, "input", updated.input_tokens_used, updated.input_token_limit)
        self._check_warning(ep.name, "output", updated.output_tokens_used, updated.output_token_limit)

    def _check_warning(self, profile_name: str, limit_type: str, used: int, limit: int | None) -> None:
        """Emit 80% warning for a specific limit type if threshold crossed."""
        if limit is None or limit <= 0:
            return
        key = f"{profile_name}:{limit_type}"
        usage_pct = used / limit
        if usage_pct < 0.8 or usage_pct >= 1.0:
            return

        should_warn = False
        with self._warned_profiles_lock:
            if key not in self._warned_profiles:
                self._warned_profiles.add(key)
                should_warn = True

        if should_warn:
            logger.warning(
                "Token usage warning: endpoint '%s' %s at %.0f%% (%s / %s tokens)",
                profile_name,
                limit_type,
                usage_pct * 100,
                f"{used:,}",
                f"{limit:,}",
            )

    def clear_warning(self, profile_name: str) -> None:
        """Clear all 80% warning flags for a profile (called after manual reset)."""
        with self._warned_profiles_lock:
            for limit_type in ("total", "input", "output"):
                self._warned_profiles.discard(f"{profile_name}:{limit_type}")
