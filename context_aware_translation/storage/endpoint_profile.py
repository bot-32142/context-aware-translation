"""Endpoint profile dataclass for LLM API configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class EndpointProfile:
    """
    Configuration for an LLM API endpoint.

    Stores API credentials and settings that can be reused across config profiles.
    """

    profile_id: str
    name: str
    created_at: float
    updated_at: float
    api_key: str = ""  # Stored encrypted or empty if using env var
    base_url: str = ""
    model: str = ""
    temperature: float = 0.0
    kwargs: dict[str, Any] = None  # type: ignore[assignment]
    timeout: int = 60
    max_retries: int = 3
    concurrency: int = 5
    description: str | None = None
    is_default: bool = False
    token_limit: int | None = None  # NULL = unlimited
    tokens_used: int = 0
    input_token_limit: int | None = None  # NULL = unlimited
    output_token_limit: int | None = None  # NULL = unlimited
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    cached_input_tokens_used: int = 0
    uncached_input_tokens_used: int = 0

    def __post_init__(self) -> None:
        if self.kwargs is None:
            self.kwargs = {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "kwargs": self.kwargs,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "concurrency": self.concurrency,
            "description": self.description,
            "is_default": self.is_default,
            "token_limit": self.token_limit,
            "tokens_used": self.tokens_used,
            "input_token_limit": self.input_token_limit,
            "output_token_limit": self.output_token_limit,
            "input_tokens_used": self.input_tokens_used,
            "output_tokens_used": self.output_tokens_used,
            "cached_input_tokens_used": self.cached_input_tokens_used,
            "uncached_input_tokens_used": self.uncached_input_tokens_used,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EndpointProfile:
        """Create from dictionary."""
        return cls(
            profile_id=data["profile_id"],
            name=data["name"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            api_key=data.get("api_key", ""),
            base_url=data.get("base_url", ""),
            model=data.get("model", ""),
            temperature=data.get("temperature", 0.0),
            kwargs=data.get("kwargs", {}),
            timeout=data.get("timeout", 60),
            max_retries=data.get("max_retries", 3),
            concurrency=data.get("concurrency", 5),
            description=data.get("description"),
            is_default=data.get("is_default", False),
            token_limit=data.get("token_limit"),
            tokens_used=data.get("tokens_used", 0),
            input_token_limit=data.get("input_token_limit"),
            output_token_limit=data.get("output_token_limit"),
            input_tokens_used=data.get("input_tokens_used", 0),
            output_tokens_used=data.get("output_tokens_used", 0),
            cached_input_tokens_used=data.get("cached_input_tokens_used", 0),
            uncached_input_tokens_used=data.get("uncached_input_tokens_used", 0),
        )
