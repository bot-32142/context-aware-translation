from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import yaml

from context_aware_translation import configure_logging
from context_aware_translation.llm.image_generator import ImageBackend

if TYPE_CHECKING:
    from context_aware_translation.storage.models.book import Book
    from context_aware_translation.storage.schema.registry_db import RegistryDB

T = TypeVar("T", bound="LLMConfig")

SQLITE_FILENAME = "terms.db"
DEFAULT_OUTPUT_DIR = Path(".")
DEFAULT_WORKING_SUBDIR = "data"
CONFIG_SNAPSHOT_VERSION = 1
_INTERNAL_ENDPOINT_PROFILE_KWARGS = frozenset({"provider", "_ui_display_name", "_wizard_template_key"})


def _strip_internal_endpoint_profile_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in kwargs.items() if str(key) not in _INTERNAL_ENDPOINT_PROFILE_KWARGS}


def _explicit_llm_fields(data: dict[str, Any], config_class: type[LLMConfig]) -> set[str]:
    valid_field_names = {field_info.name for field_info in fields(config_class)}
    valid_field_names.discard("_explicit_fields")
    return {str(key) for key in data if str(key) in valid_field_names}


@dataclass
class EndpointProfile:
    """
    Reusable API endpoint configuration.

    Defines connection settings that can be shared across multiple LLMConfigs.
    When an LLMConfig references a profile, profile values serve as defaults
    that can be overridden by LLMConfig's own values.
    """

    name: str  # Unique identifier for the profile
    api_key: str | None = None
    base_url: str | None = None
    api_version: str | None = None
    timeout: float = 120.0
    max_retries: int = 3
    model: str | None = None
    temperature: float = 0.0
    concurrency: int = 5
    kwargs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        return {
            "name": self.name,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "api_version": self.api_version,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "model": self.model,
            "temperature": self.temperature,
            "concurrency": self.concurrency,
            "kwargs": self.kwargs,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EndpointProfile:
        """Create from dictionary."""
        return cls(**data)


@dataclass
class LLMConfig:
    """
    Base configuration for LLM API calls.
    Can be used as base config or as per-step override config.
    If a field is None in a step config, it falls back to the base config value.
    """

    # API Connection Settings
    api_key: str | None = None  # Required: must be set in base or step config
    base_url: str | None = None  # Required: must be set in base or step config
    api_version: str | None = None
    timeout: float = 120.0
    max_retries: int = 3

    # Model Settings (can be overridden per-step)
    model: str | None = None  # Required: must be set in base or step config
    temperature: float = 0.0
    concurrency: int = 5  # Optional: per-step concurrency
    # Profile reference (resolved at config load time); stores endpoint profile ID.
    endpoint_profile: str | None = None
    # Additional kwargs for LLM API calls (merged with passed kwargs, passed kwargs take precedence)
    kwargs: dict[str, Any] = field(default_factory=dict)
    # Track which fields were explicitly present in persisted payloads.
    _explicit_fields: set[str] = field(default_factory=set, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        return {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "api_version": self.api_version,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "model": self.model,
            "temperature": self.temperature,
            "concurrency": self.concurrency,
            "endpoint_profile": self.endpoint_profile,
            "kwargs": self.kwargs,
        }

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        """Create from dictionary, ignoring unknown keys for forward/backward compatibility."""
        valid_field_names = {field_info.name for field_info in fields(cls)}
        valid_field_names.discard("_explicit_fields")
        filtered_data = {k: v for k, v in data.items() if k in valid_field_names}
        filtered_data["_explicit_fields"] = _explicit_llm_fields(data, cls)
        return cls(**filtered_data)


@dataclass
class ExtractorConfig(LLMConfig):
    """Configuration for term extraction step."""

    # Extraction-specific settings
    max_gleaning: int = 3
    max_term_name_length: int = 200

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        base = super().to_dict()
        base.update(
            {
                "max_gleaning": self.max_gleaning,
                "max_term_name_length": self.max_term_name_length,
            }
        )
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExtractorConfig:
        """Create from dictionary."""
        return cls(
            api_key=data.get("api_key"),
            base_url=data.get("base_url"),
            api_version=data.get("api_version"),
            timeout=data.get("timeout", 60),
            max_retries=data.get("max_retries", 3),
            model=data.get("model"),
            temperature=data.get("temperature", 0.0),
            concurrency=data.get("concurrency", 5),
            endpoint_profile=data.get("endpoint_profile"),
            kwargs=data.get("kwargs", {}),
            _explicit_fields=_explicit_llm_fields(data, cls),
            max_gleaning=data.get("max_gleaning", 3),
            max_term_name_length=data.get("max_term_name_length", 200),
        )


@dataclass
class SummarizorConfig(LLMConfig):
    """Configuration for term summarization/translation step."""

    # Summarization-specific settings
    max_term_description_length: int = 1200

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        base = super().to_dict()
        base.update(
            {
                "max_term_description_length": self.max_term_description_length,
            }
        )
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SummarizorConfig:
        """Create from dictionary."""
        return cls(
            api_key=data.get("api_key"),
            base_url=data.get("base_url"),
            api_version=data.get("api_version"),
            timeout=data.get("timeout", 60),
            max_retries=data.get("max_retries", 3),
            model=data.get("model"),
            temperature=data.get("temperature", 0.0),
            concurrency=data.get("concurrency", 5),
            endpoint_profile=data.get("endpoint_profile"),
            kwargs=data.get("kwargs", {}),
            _explicit_fields=_explicit_llm_fields(data, cls),
            max_term_description_length=data.get("max_term_description_length", 1200),
        )


@dataclass
class TranslatorConfig(LLMConfig):
    """Configuration for text translation step."""

    # Translation-specific settings
    enable_polish: bool = True
    num_of_chunks_per_llm_call: int = 3
    max_tokens_per_llm_call: int = 4000
    chunk_size: int = 1000  # Max token size per chunk for text processing

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        base = super().to_dict()
        base.update(
            {
                "enable_polish": self.enable_polish,
                "num_of_chunks_per_llm_call": self.num_of_chunks_per_llm_call,
                "max_tokens_per_llm_call": self.max_tokens_per_llm_call,
                "chunk_size": self.chunk_size,
            }
        )
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TranslatorConfig:
        """Create from dictionary."""
        return cls(
            api_key=data.get("api_key"),
            base_url=data.get("base_url"),
            api_version=data.get("api_version"),
            timeout=data.get("timeout", 60),
            max_retries=data.get("max_retries", 3),
            model=data.get("model"),
            temperature=data.get("temperature", 0.0),
            concurrency=data.get("concurrency", 5),
            endpoint_profile=data.get("endpoint_profile"),
            kwargs=data.get("kwargs", {}),
            _explicit_fields=_explicit_llm_fields(data, cls),
            enable_polish=data.get("enable_polish", True),
            num_of_chunks_per_llm_call=data.get("num_of_chunks_per_llm_call", 3),
            max_tokens_per_llm_call=data.get("max_tokens_per_llm_call", 4000),
            chunk_size=data.get("chunk_size", 1000),
        )


@dataclass
class TranslatorBatchConfig:
    """Dedicated configuration for async translator batch jobs."""

    provider: str
    api_key: str
    model: str
    batch_size: int = 100
    thinking_mode: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        return {
            "provider": self.provider,
            "api_key": self.api_key,
            "model": self.model,
            "batch_size": self.batch_size,
            "thinking_mode": self.thinking_mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TranslatorBatchConfig:
        """Create from dictionary."""
        return cls(
            provider=str(data.get("provider") or ""),
            api_key=str(data.get("api_key") or ""),
            model=str(data.get("model") or ""),
            batch_size=int(data.get("batch_size", 100)),
            thinking_mode=str(data.get("thinking_mode", "auto")),
        )


_SUPPORTED_BATCH_PROVIDERS = {"gemini_ai_studio"}
_SUPPORTED_THINKING_MODES = {"auto", "off", "low", "medium", "high"}


def _validate_translator_batch_config(config: TranslatorBatchConfig, *, config_name: str) -> None:
    provider = str(config.provider or "").strip().lower()
    if not provider:
        raise ValueError(f"{config_name}.provider is required")
    if provider not in _SUPPORTED_BATCH_PROVIDERS:
        raise ValueError(
            f"{config_name}.provider '{config.provider}' is unsupported; supported values: "
            + ", ".join(sorted(_SUPPORTED_BATCH_PROVIDERS))
        )

    if not str(config.api_key or "").strip():
        raise ValueError(f"{config_name}.api_key is required")
    if not str(config.model or "").strip():
        raise ValueError(f"{config_name}.model is required")

    if int(config.batch_size) <= 0:
        raise ValueError(f"{config_name}.batch_size must be greater than 0")
    if int(config.batch_size) > 5000:
        raise ValueError(f"{config_name}.batch_size must not exceed 5000")

    thinking_mode = str(config.thinking_mode or "").strip().lower()
    if thinking_mode not in _SUPPORTED_THINKING_MODES:
        raise ValueError(
            f"{config_name}.thinking_mode '{config.thinking_mode}' is invalid; allowed values: "
            + ", ".join(sorted(_SUPPORTED_THINKING_MODES))
        )


@dataclass
class MangaTranslatorConfig(LLMConfig):
    """Configuration for manga vision-based translation step."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MangaTranslatorConfig:
        return cls(
            api_key=data.get("api_key"),
            base_url=data.get("base_url"),
            api_version=data.get("api_version"),
            timeout=data.get("timeout", 300),
            max_retries=data.get("max_retries", 3),
            model=data.get("model"),
            temperature=data.get("temperature", 0.0),
            concurrency=data.get("concurrency", 5),
            endpoint_profile=data.get("endpoint_profile"),
            kwargs=data.get("kwargs", {}),
            _explicit_fields=_explicit_llm_fields(data, cls),
        )


@dataclass
class GlossaryTranslationConfig(LLMConfig):
    """Configuration for glossary translation step."""

    pass


@dataclass
class ReviewConfig(LLMConfig):
    """Configuration for term review step."""

    pass


@dataclass
class ImageReembeddingConfig(LLMConfig):
    """Configuration for image re-embedding step."""

    backend: str = ImageBackend.GEMINI  # Backend to use for image re-embedding

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        base = super().to_dict()
        base.update(
            {
                "backend": self.backend,
            }
        )
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImageReembeddingConfig:
        """Create from dictionary."""
        return cls(
            api_key=data.get("api_key"),
            base_url=data.get("base_url"),
            api_version=data.get("api_version"),
            timeout=data.get("timeout", 60),
            max_retries=data.get("max_retries", 3),
            model=data.get("model"),
            temperature=data.get("temperature", 0.0),
            concurrency=data.get("concurrency", 5),
            endpoint_profile=data.get("endpoint_profile"),
            kwargs=data.get("kwargs", {}),
            _explicit_fields=_explicit_llm_fields(data, cls),
            backend=data.get("backend", ImageBackend.GEMINI),
        )


@dataclass
class OCRConfig(LLMConfig):
    """Configuration for OCR step using vision LLM."""

    # Post-processing settings
    strip_llm_artifacts: bool = True  # Remove tokenizer artifacts (<pad>, etc.) from output

    # Image compression settings for OCR
    ocr_dpi: int = 150  # DPI to compress images to before sending to LLM (lower = faster)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        base = super().to_dict()
        base.update(
            {
                "strip_llm_artifacts": self.strip_llm_artifacts,
                "ocr_dpi": self.ocr_dpi,
            }
        )
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OCRConfig:
        """Create from dictionary."""
        return cls(
            api_key=data.get("api_key"),
            base_url=data.get("base_url"),
            api_version=data.get("api_version"),
            timeout=data.get("timeout", 60),
            max_retries=data.get("max_retries", 3),
            model=data.get("model"),
            temperature=data.get("temperature", 0.0),
            concurrency=data.get("concurrency", 5),
            endpoint_profile=data.get("endpoint_profile"),
            kwargs=data.get("kwargs", {}),
            _explicit_fields=_explicit_llm_fields(data, cls),
            strip_llm_artifacts=data.get("strip_llm_artifacts", True),
            ocr_dpi=data.get("ocr_dpi", 150),
        )


# Registry mapping config attribute names to their classes
# Used by _resolve_any_step_config, from_book, and load_config_from_yaml
#
# NOTE: This registry includes all step configs that need auto-resolution.
STEP_CONFIG_REGISTRY: dict[str, type[LLMConfig]] = {
    "extractor_config": ExtractorConfig,
    "summarizor_config": SummarizorConfig,
    "translator_config": TranslatorConfig,
    "glossary_config": GlossaryTranslationConfig,
    "review_config": ReviewConfig,
    "ocr_config": OCRConfig,
    "image_reembedding_config": ImageReembeddingConfig,
    "manga_translator_config": MangaTranslatorConfig,
}

# Step configs that are always resolved (not optional)
REQUIRED_STEP_CONFIGS = (
    "extractor_config",
    "summarizor_config",
    "translator_config",
    "glossary_config",
)

# Step configs that are only resolved if provided
OPTIONAL_STEP_CONFIGS = (
    "review_config",
    "ocr_config",
    "image_reembedding_config",
    "manga_translator_config",
)


def _step_config_from_payload(config_class: type[T], payload: dict[str, Any]) -> T:
    """Build a step config from persisted payload while ignoring unknown keys."""
    valid_field_names = {f.name for f in fields(config_class)}
    filtered_payload = {k: v for k, v in payload.items() if k in valid_field_names}
    return config_class(**filtered_payload)


@dataclass(frozen=True)
class WorkflowRuntimeConfig:
    """Validated config snapshot required by workflow runtime bootstrap."""

    translation_target_language: str
    llm_concurrency: int
    sqlite_path: Path
    extractor_config: ExtractorConfig
    summarizor_config: SummarizorConfig
    translator_config: TranslatorConfig
    translator_batch_config: TranslatorBatchConfig | None
    glossary_config: GlossaryTranslationConfig
    review_config: ReviewConfig | None
    ocr_config: OCRConfig | None
    image_reembedding_config: ImageReembeddingConfig | None
    manga_translator_config: MangaTranslatorConfig | None


def _get_extra_fields(config_class: type[LLMConfig], override: LLMConfig | None) -> dict[str, Any] | None:
    """
    Extract extra fields (non-LLMConfig fields) from a step config instance.

    Uses dataclass introspection to find fields that are defined in config_class
    but not in LLMConfig base class.

    Args:
        config_class: The step config class (e.g., ExtractorConfig)
        override: Instance of the config, or None

    Returns:
        Dict of extra field names to their values, or None if override is None
    """
    if override is None:
        return None

    # Get field names from LLMConfig base class
    llm_field_names = {f.name for f in fields(LLMConfig)}

    # Get extra fields (fields in config_class but not in LLMConfig)
    extra_fields = {}
    for f in fields(config_class):
        if f.name not in llm_field_names:
            extra_fields[f.name] = getattr(override, f.name)

    return extra_fields if extra_fields else None


def _resolve_any_step_config(
    override: LLMConfig | None,
    config_name: str,
    profiles: dict[str, EndpointProfile] | None = None,
    default_concurrency: int | None = None,
) -> LLMConfig:
    """
    Universal resolver for any step config using registry lookup.

    Each step config must be self-contained with complete API settings
    (via endpoint_profile or explicit values).

    Args:
        override: Step config (must be provided for required configs)
        config_name: Name of the config attribute (e.g., "extractor_config")
        profiles: Dict of available EndpointProfiles for resolution
        default_concurrency: Default concurrency if not set

    Returns:
        Resolved step config with profile values merged if applicable.
        Note: Returns LLMConfig base type; actual runtime type is the
        specific config class from the registry.

    Raises:
        ValueError: If override is None (step config required) or missing required fields
    """
    config_class = STEP_CONFIG_REGISTRY[config_name]
    extra_fields = _get_extra_fields(config_class, override)
    return _resolve_step_config(override, config_class, config_name, profiles, extra_fields, default_concurrency)


def _resolve_with_profile(
    config: LLMConfig,
    profiles: dict[str, EndpointProfile],
) -> LLMConfig:
    """
    Resolve an LLMConfig by merging profile values with config overrides.

    Resolution order (later wins):
    1. EndpointProfile defaults (if endpoint_profile is set)
    2. LLMConfig explicit values

    Args:
        config: LLMConfig instance (may have endpoint_profile reference)
        profiles: Dict of available EndpointProfiles keyed by profile ID

    Returns:
        New LLMConfig with profile values merged

    Raises:
        ValueError: If referenced profile doesn't exist
    """
    if config.endpoint_profile is None:
        return config

    if config.endpoint_profile not in profiles:
        raise ValueError(f"Endpoint profile not found: {config.endpoint_profile}")

    profile = profiles[config.endpoint_profile]

    explicit_fields = config._explicit_fields if hasattr(config, "_explicit_fields") else set()

    # Create new LLMConfig with profile as base, config values override.
    return LLMConfig(
        api_key=config.api_key if config.api_key is not None else profile.api_key,
        base_url=config.base_url if config.base_url is not None else profile.base_url,
        api_version=config.api_version if config.api_version is not None else profile.api_version,
        timeout=config.timeout if "timeout" in explicit_fields else profile.timeout,
        max_retries=config.max_retries if "max_retries" in explicit_fields else profile.max_retries,
        model=config.model if config.model is not None else profile.model,
        temperature=config.temperature if "temperature" in explicit_fields else profile.temperature,
        concurrency=config.concurrency if "concurrency" in explicit_fields else profile.concurrency,
        kwargs=_strip_internal_endpoint_profile_kwargs({**profile.kwargs, **config.kwargs}),
        endpoint_profile=config.endpoint_profile,  # Preserve for token tracking
        _explicit_fields=set(explicit_fields),
    )


def _resolve_step_config(
    override: T | None,
    config_class: type[T],
    config_name: str,
    profiles: dict[str, EndpointProfile] | None = None,
    extra_fields: dict[str, Any] | None = None,
    default_concurrency: int | None = None,
) -> T:
    """
    Generic resolver for step configs that inherit from LLMConfig.

    Each step config must be self-contained with complete API settings
    (via endpoint_profile or explicit values).

    Args:
        override: Step config (must be provided)
        config_class: The config class to instantiate (e.g., ExtractorConfig)
        config_name: Name for error messages (e.g., "extractor_config")
        profiles: Dict of available EndpointProfiles for resolution
        extra_fields: Dict of extra fields to copy from override (e.g., {"max_gleaning": override.max_gleaning})
        default_concurrency: Default concurrency if not set

    Returns:
        Resolved step config with profile values merged if applicable.

    Raises:
        ValueError: If override is None or missing required fields

    Note: When override is created from YAML, Python dataclasses automatically apply
    default values for any fields not present in the YAML data.
    """
    if override is None:
        raise ValueError(f"{config_name} must be provided (step configs are required)")

    # Resolve endpoint profile if set
    resolved_llm: LLMConfig
    if override.endpoint_profile is not None and profiles:
        resolved_llm = _resolve_with_profile(override, profiles)
    else:
        resolved_llm = LLMConfig(
            api_key=override.api_key,
            base_url=override.base_url,
            api_version=override.api_version,
            timeout=override.timeout,
            max_retries=override.max_retries,
            model=override.model,
            temperature=override.temperature,
            concurrency=override.concurrency,
            kwargs=override.kwargs.copy() if override.kwargs else {},
            endpoint_profile=None,
        )

    # Apply default concurrency if not set
    if resolved_llm.concurrency is None and default_concurrency is not None:
        resolved_llm.concurrency = default_concurrency

    # Create resolved config with extra fields
    resolved = config_class(
        **resolved_llm.__dict__,
        **(extra_fields or {}),
    )

    # Validate required fields
    if not resolved.api_key:
        raise ValueError(f"api_key must be set in {config_name} (via endpoint_profile or explicit value)")
    if not resolved.base_url:
        raise ValueError(f"base_url must be set in {config_name} (via endpoint_profile or explicit value)")
    if not resolved.model:
        raise ValueError(f"model must be set in {config_name} (via endpoint_profile or explicit value)")
    return resolved


@dataclass
class Config:
    translation_target_language: str
    llm_concurrency: int = 20
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)
    working_dir: Path | None = None  # default to output_dir / data
    sqlite_path: Path | None = None  # default to working_dir / terms.db
    log_dir: Path | None = None  # default to working_dir / logs
    book_id: str | None = None  # If created from a book, stores the book_id

    # Endpoint profiles for sharing API settings
    endpoint_profiles: dict[str, EndpointProfile] = field(default_factory=dict)

    # LLM Configuration (step configs must be self-contained with complete API settings)
    extractor_config: ExtractorConfig | None = None
    glossary_config: GlossaryTranslationConfig | None = None
    summarizor_config: SummarizorConfig | None = None
    translator_config: TranslatorConfig | None = None
    translator_batch_config: TranslatorBatchConfig | None = None
    review_config: ReviewConfig | None = None
    ocr_config: OCRConfig | None = None
    image_reembedding_config: ImageReembeddingConfig | None = None
    manga_translator_config: MangaTranslatorConfig | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize entire config to dictionary."""
        result: dict[str, Any] = {
            "translation_target_language": self.translation_target_language,
            "llm_concurrency": self.llm_concurrency,
            "output_dir": str(self.output_dir),
            "book_id": self.book_id,
        }

        if self.working_dir:
            result["working_dir"] = str(self.working_dir)
        if self.sqlite_path:
            result["sqlite_path"] = str(self.sqlite_path)
        if self.log_dir:
            result["log_dir"] = str(self.log_dir)

        # Endpoint profiles
        result["endpoint_profiles"] = {name: profile.to_dict() for name, profile in self.endpoint_profiles.items()}

        # Step configs
        if self.extractor_config:
            result["extractor_config"] = self.extractor_config.to_dict()
        if self.glossary_config:
            result["glossary_config"] = self.glossary_config.to_dict()
        if self.summarizor_config:
            result["summarizor_config"] = self.summarizor_config.to_dict()
        if self.translator_config:
            result["translator_config"] = self.translator_config.to_dict()
        if self.translator_batch_config:
            result["translator_batch_config"] = self.translator_batch_config.to_dict()
        if self.review_config:
            result["review_config"] = self.review_config.to_dict()
        if self.ocr_config:
            result["ocr_config"] = self.ocr_config.to_dict()
        if self.image_reembedding_config:
            result["image_reembedding_config"] = self.image_reembedding_config.to_dict()
        if self.manga_translator_config:
            result["manga_translator_config"] = self.manga_translator_config.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        """
        Create Config from dictionary.

        Note: This creates a Config without triggering __post_init__ validation,
        so it's suitable for loading pre-validated configs from storage.
        For full validation, use the regular constructor.

        Args:
            data: Dictionary with config fields

        Returns:
            Config instance
        """
        # Parse endpoint profiles
        endpoint_profiles: dict[str, EndpointProfile] = {}
        for name, profile_data in data.get("endpoint_profiles", {}).items():
            endpoint_profiles[name] = EndpointProfile.from_dict(profile_data)

        # Parse step configs
        extractor_config = None
        if "extractor_config" in data and data["extractor_config"]:
            extractor_config = ExtractorConfig.from_dict(data["extractor_config"])

        glossary_config = None
        if "glossary_config" in data and data["glossary_config"]:
            glossary_config = GlossaryTranslationConfig.from_dict(data["glossary_config"])

        summarizor_config = None
        if "summarizor_config" in data and data["summarizor_config"]:
            summarizor_config = SummarizorConfig.from_dict(data["summarizor_config"])

        translator_config = None
        if "translator_config" in data and data["translator_config"]:
            translator_config = TranslatorConfig.from_dict(data["translator_config"])

        translator_batch_config = None
        if "translator_batch_config" in data and data["translator_batch_config"]:
            translator_batch_config = TranslatorBatchConfig.from_dict(data["translator_batch_config"])

        review_config = None
        if "review_config" in data and data["review_config"]:
            review_config = ReviewConfig.from_dict(data["review_config"])

        ocr_config = None
        if "ocr_config" in data and data["ocr_config"]:
            ocr_config = OCRConfig.from_dict(data["ocr_config"])

        image_reembedding_config = None
        if "image_reembedding_config" in data and data["image_reembedding_config"]:
            image_reembedding_config = ImageReembeddingConfig.from_dict(data["image_reembedding_config"])

        manga_translator_config = None
        if "manga_translator_config" in data and data["manga_translator_config"]:
            manga_translator_config = MangaTranslatorConfig.from_dict(data["manga_translator_config"])

        return cls(
            translation_target_language=data["translation_target_language"],
            llm_concurrency=data.get("llm_concurrency", 20),
            output_dir=Path(data["output_dir"]) if "output_dir" in data else DEFAULT_OUTPUT_DIR,
            working_dir=Path(data["working_dir"]) if data.get("working_dir") else None,
            sqlite_path=Path(data["sqlite_path"]) if data.get("sqlite_path") else None,
            log_dir=Path(data["log_dir"]) if data.get("log_dir") else None,
            book_id=data.get("book_id"),
            endpoint_profiles=endpoint_profiles,
            extractor_config=extractor_config,
            glossary_config=glossary_config,
            summarizor_config=summarizor_config,
            translator_config=translator_config,
            translator_batch_config=translator_batch_config,
            review_config=review_config,
            ocr_config=ocr_config,
            image_reembedding_config=image_reembedding_config,
            manga_translator_config=manga_translator_config,
        )

    def validate(self) -> list[str]:
        """
        Validate config completeness.
        Returns list of error messages (empty if valid).
        """
        errors: list[str] = []

        if not self.translation_target_language:
            errors.append("Target language is required")

        if not self.extractor_config:
            errors.append("Extractor config is required")

        if not self.translator_config:
            errors.append("Translator config is required")

        if not self.glossary_config:
            errors.append("Glossary config is required")

        if not self.summarizor_config:
            errors.append("Summarizor config is required")

        # Validate endpoint profiles have required fields
        for name, profile in self.endpoint_profiles.items():
            if not profile.api_key:
                errors.append(f"Endpoint profile '{name}' is missing api_key")
            if not profile.base_url:
                errors.append(f"Endpoint profile '{name}' is missing base_url")

        return errors

    def get_workflow_runtime_config(self) -> WorkflowRuntimeConfig:
        """Return a validated workflow runtime snapshot with non-optional required fields."""
        missing: list[str] = []

        if self.translation_target_language == "":
            missing.append("translation_target_language")
        if self.sqlite_path is None:
            missing.append("sqlite_path")
        if self.extractor_config is None:
            missing.append("extractor_config")
        if self.summarizor_config is None:
            missing.append("summarizor_config")
        if self.translator_config is None:
            missing.append("translator_config")
        if self.glossary_config is None:
            missing.append("glossary_config")

        if missing:
            raise ValueError(f"Config missing required workflow fields: {', '.join(sorted(missing))}")

        if self.summarizor_config.model is None:  # type: ignore[union-attr]
            missing.append("summarizor_config.model")
        if self.translator_config.model is None:  # type: ignore[union-attr]
            missing.append("translator_config.model")

        if missing:
            raise ValueError(f"Config missing required workflow fields: {', '.join(sorted(missing))}")

        return WorkflowRuntimeConfig(
            translation_target_language=self.translation_target_language,
            llm_concurrency=self.llm_concurrency,
            sqlite_path=self.sqlite_path,  # type: ignore[arg-type]
            extractor_config=self.extractor_config,  # type: ignore[arg-type]
            summarizor_config=self.summarizor_config,  # type: ignore[arg-type]
            translator_config=self.translator_config,  # type: ignore[arg-type]
            translator_batch_config=self.translator_batch_config,
            glossary_config=self.glossary_config,  # type: ignore[arg-type]
            review_config=self.review_config,
            ocr_config=self.ocr_config,
            image_reembedding_config=self.image_reembedding_config,
            manga_translator_config=self.manga_translator_config,
        )

    def __post_init__(self) -> None:
        self.output_dir = Path(self.output_dir)
        if self.working_dir is None:
            self.working_dir = self.output_dir / DEFAULT_WORKING_SUBDIR
        else:
            self.working_dir = Path(self.working_dir)
        if self.sqlite_path is None:
            self.sqlite_path = self.working_dir / SQLITE_FILENAME
        if self.log_dir is None:
            self.log_dir = self.working_dir / "logs"
        else:
            self.log_dir = Path(self.log_dir)

        # Resolve required step configs (each must be self-contained with complete API settings)
        # NOTE: Uses setattr which loses compile-time type specificity, but runtime
        # types are correct (each config_name maps to its proper class via registry)
        for config_name in REQUIRED_STEP_CONFIGS:
            current_value = getattr(self, config_name)
            resolved = _resolve_any_step_config(
                current_value, config_name, self.endpoint_profiles, self.llm_concurrency
            )
            setattr(self, config_name, resolved)

        # Resolve optional step configs (only if provided)
        for config_name in OPTIONAL_STEP_CONFIGS:
            current_value = getattr(self, config_name)
            if current_value is not None:
                resolved = _resolve_any_step_config(
                    current_value, config_name, self.endpoint_profiles, self.llm_concurrency
                )
                setattr(self, config_name, resolved)

        if self.translator_batch_config is not None:
            _validate_translator_batch_config(self.translator_batch_config, config_name="translator_batch_config")
            self.translator_batch_config.provider = self.translator_batch_config.provider.strip().lower()
            self.translator_batch_config.thinking_mode = self.translator_batch_config.thinking_mode.strip().lower()

        # Ensure directories exist and configure logging
        ensure_dirs(self)
        configure_logging(self)

    @classmethod
    def from_book(
        cls,
        book: Book,
        library_root: Path,
        registry: RegistryDB,
    ) -> Config:
        """
        Create a Config instance from a Book.

        Loads configuration from the book's profile (if profile_id is set) or
        from the book's custom config (if profile_id is None).

        Args:
            book: The Book instance
            library_root: Root directory of the library (contains books/ folder)
            registry: RegistryDB instance to load config from

        Returns:
            Config configured for this book with paths pointing to the book's folder

        Raises:
            ValueError: If config cannot be loaded (profile not found or no custom config)
        """
        # Compute book folder path
        book_path = library_root / "books" / book.book_id

        # Load config from profile or custom config
        config_dict: dict[str, Any]
        if book.profile_id is not None:
            profile = registry.get_profile(book.profile_id)
            if profile is None:
                raise ValueError(f"Profile not found: {book.profile_id}")
            config_dict = profile.config
        else:
            custom_config = registry.get_book_config(book.book_id)
            if custom_config is None:
                raise ValueError(f"No custom config found for book: {book.book_id}")
            config_dict = custom_config

        # Build endpoint-profile step configs if present using registry.
        step_configs: dict[str, LLMConfig | None] = {}
        for config_name, config_class in STEP_CONFIG_REGISTRY.items():
            if config_name in config_dict:
                step_configs[config_name] = _step_config_from_payload(config_class, config_dict[config_name])
            else:
                step_configs[config_name] = None

        translator_batch_payload = config_dict.get("translator_batch_config")
        translator_batch_config = None
        if isinstance(translator_batch_payload, dict):
            translator_batch_config = TranslatorBatchConfig.from_dict(translator_batch_payload)

        # Build endpoint profiles from config_dict or by resolving profile IDs from registry.
        endpoint_profiles_dict = config_dict.get("endpoint_profiles", {})
        endpoint_profiles: dict[str, EndpointProfile] = {}

        # First, load any embedded endpoint profiles from config_dict
        for profile_name, profile_data in endpoint_profiles_dict.items():
            endpoint_profiles[profile_name] = EndpointProfile(
                name=profile_name,
                **profile_data,
            )

        # Then, resolve any endpoint profile IDs referenced in step configs
        # that aren't already in the endpoint_profiles dict
        for step_config in step_configs.values():
            if step_config is not None and step_config.endpoint_profile:
                profile_ref = step_config.endpoint_profile
                if profile_ref not in endpoint_profiles:
                    ep = registry.get_endpoint_profile(profile_ref)
                    if ep is not None:
                        endpoint_profiles[profile_ref] = EndpointProfile(
                            name=ep.name,
                            api_key=ep.api_key,
                            base_url=ep.base_url,
                            model=ep.model,
                            temperature=ep.temperature,
                            kwargs=ep.kwargs or {},
                            timeout=ep.timeout,
                            max_retries=ep.max_retries,
                            concurrency=ep.concurrency,
                        )

        # Create config with book-specific paths
        return cls(
            translation_target_language=config_dict["translation_target_language"],
            llm_concurrency=config_dict.get("llm_concurrency", 20),
            output_dir=book_path,
            working_dir=book_path,
            sqlite_path=book_path / "book.db",
            log_dir=book_path / "logs",
            book_id=book.book_id,
            endpoint_profiles=endpoint_profiles,
            extractor_config=step_configs.get("extractor_config"),  # type: ignore[arg-type]
            glossary_config=step_configs.get("glossary_config"),  # type: ignore[arg-type]
            summarizor_config=step_configs.get("summarizor_config"),  # type: ignore[arg-type]
            translator_config=step_configs.get("translator_config"),  # type: ignore[arg-type]
            translator_batch_config=translator_batch_config,
            review_config=step_configs.get("review_config"),  # type: ignore[arg-type]
            ocr_config=step_configs.get("ocr_config"),  # type: ignore[arg-type]
            image_reembedding_config=step_configs.get("image_reembedding_config"),  # type: ignore[arg-type]
            manga_translator_config=step_configs.get("manga_translator_config"),  # type: ignore[arg-type]
        )


def validate_persisted_config_payload(
    config: dict[str, Any],
    endpoint_profile_exists: Callable[[str], bool] | None = None,
) -> list[str]:
    """Validate serialized config payload prior to persistence."""
    errors: list[str] = []

    if not isinstance(config, dict):
        return ["config must be a dictionary"]

    target_language = config.get("translation_target_language")
    if not isinstance(target_language, str) or target_language.strip() == "":
        errors.append("translation_target_language is required")

    endpoint_profiles = config.get("endpoint_profiles", {})
    if endpoint_profiles is None:
        endpoint_profiles = {}
    if not isinstance(endpoint_profiles, dict):
        errors.append("endpoint_profiles must be a dictionary")
        endpoint_profiles = {}

    for config_name in REQUIRED_STEP_CONFIGS:
        step_cfg = config.get(config_name)
        if not isinstance(step_cfg, dict):
            errors.append(f"{config_name} is required")
            continue

        endpoint_profile = step_cfg.get("endpoint_profile")
        if isinstance(endpoint_profile, str) and endpoint_profile.strip():
            found_local = endpoint_profile in endpoint_profiles
            found_external = endpoint_profile_exists(endpoint_profile) if endpoint_profile_exists else False
            if not found_local and not found_external:
                errors.append(f"{config_name}.endpoint_profile '{endpoint_profile}' not found")
            continue

        if not step_cfg.get("api_key"):
            errors.append(f"{config_name}.api_key is required when endpoint_profile is not set")
        if not step_cfg.get("base_url"):
            errors.append(f"{config_name}.base_url is required when endpoint_profile is not set")
        if not step_cfg.get("model"):
            errors.append(f"{config_name}.model is required when endpoint_profile is not set")

    translator_batch_cfg = config.get("translator_batch_config")
    if translator_batch_cfg is not None:
        if not isinstance(translator_batch_cfg, dict):
            errors.append("translator_batch_config must be a dictionary")
        else:
            provider = str(translator_batch_cfg.get("provider") or "").strip().lower()
            if not provider:
                errors.append("translator_batch_config.provider is required")
            elif provider not in _SUPPORTED_BATCH_PROVIDERS:
                errors.append(
                    "translator_batch_config.provider must be one of: " + ", ".join(sorted(_SUPPORTED_BATCH_PROVIDERS))
                )

            if not str(translator_batch_cfg.get("api_key") or "").strip():
                errors.append("translator_batch_config.api_key is required")
            if not str(translator_batch_cfg.get("model") or "").strip():
                errors.append("translator_batch_config.model is required")

            batch_size_value = translator_batch_cfg.get("batch_size", 100)
            try:
                batch_size = int(batch_size_value)
            except (TypeError, ValueError):
                errors.append("translator_batch_config.batch_size must be an integer greater than 0")
            else:
                if batch_size <= 0:
                    errors.append("translator_batch_config.batch_size must be greater than 0")
                elif batch_size > 5000:
                    errors.append("translator_batch_config.batch_size must not exceed 5000")

            thinking_mode = str(translator_batch_cfg.get("thinking_mode", "auto") or "").strip().lower()
            if thinking_mode not in _SUPPORTED_THINKING_MODES:
                errors.append(
                    "translator_batch_config.thinking_mode must be one of: "
                    + ", ".join(sorted(_SUPPORTED_THINKING_MODES))
                )

    return errors


def ensure_valid_persisted_config_payload(
    config: dict[str, Any],
    endpoint_profile_exists: Callable[[str], bool] | None = None,
) -> None:
    """Raise ValueError if serialized config payload is invalid for persistence."""
    errors = validate_persisted_config_payload(config, endpoint_profile_exists=endpoint_profile_exists)
    if errors:
        raise ValueError("Invalid config payload: " + "; ".join(errors))


def load_config_from_yaml(
    yaml_path: str | Path,
    translation_target_language: str,
    output_dir: Path | str,
) -> Config:
    """
    Load Config from a YAML file, merging with command-line arguments.

    Note: Fields configurable from command line (translation_target_language,
    output_dir) should not be in the YAML file and will be ignored if present.
    These must be provided as function arguments.

    Args:
        yaml_path: Path to the YAML configuration file
        translation_target_language: Target language (from --language)
        output_dir: Output directory (from --output_dir)
    Returns:
        Config instance loaded from YAML with command-line values merged

    Raises:
        ImportError: If PyYAML is not installed
        FileNotFoundError: If the YAML file doesn't exist
    """
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"Config file not found: {yaml_path}")

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # Parse endpoint_profiles section
    endpoint_profiles_data = data.pop("endpoint_profiles", {})
    endpoint_profiles: dict[str, EndpointProfile] = {}
    for profile_name, profile_data in endpoint_profiles_data.items():
        endpoint_profiles[profile_name] = EndpointProfile(
            name=profile_name,
            **profile_data,
        )

    # Remove command-line-only and hardcoded fields if present (with warning)
    cmdline_only_fields = ["translation_target_language", "output_dir"]
    hardcoded_fields = [
        "translation_name_similarity_threshold",  # Hardcoded, not configurable
        "tuple_delimiter",  # Hardcoded, not configurable
        "completion_delimiter",  # Hardcoded, not configurable
    ]
    for field_name in cmdline_only_fields + hardcoded_fields:
        if field_name in data:
            warnings.warn(
                f"Field '{field_name}' in YAML config is ignored as it must be set via command line or detected dynamically. "
                f"Remove it from the YAML file.",
                UserWarning,
                stacklevel=2,
            )
            data.pop(field_name)

    # Extract LLM config section (contains step configs)
    llm_data = data.pop("llm", {})
    data.pop("ocr", None)

    # Extract step configs from llm section
    # Each step config must be self-contained with complete API settings
    step_config_data = {
        "extractor_config": llm_data.pop("extractor_config", None),
        "summarizor_config": llm_data.pop("summarizor_config", None),
        "translator_config": llm_data.pop("translator_config", None),
        "glossary_config": llm_data.pop("glossary_config", None),
        "review_config": llm_data.pop("review_config", None),
        "ocr_config": llm_data.pop("ocr_config", None),
        "image_reembedding_config": llm_data.pop("image_reembedding_config", None),
        "manga_translator_config": llm_data.pop("manga_translator_config", None),
    }
    translator_batch_payload = llm_data.pop("translator_batch_config", None)

    # Build step configs using registry
    step_configs: dict[str, LLMConfig | None] = {}
    for config_name, config_data in step_config_data.items():
        config_class = STEP_CONFIG_REGISTRY[config_name]
        if config_data is not None:
            step_configs[config_name] = _step_config_from_payload(config_class, config_data)
        else:
            step_configs[config_name] = None

    translator_batch_config = (
        TranslatorBatchConfig.from_dict(translator_batch_payload)
        if isinstance(translator_batch_payload, dict)
        else None
    )

    # Convert path strings to Path objects
    for key in ["working_dir", "sqlite_path", "log_dir"]:
        if key in data and data[key] is not None:
            data[key] = Path(data[key])

    # Create Config with command-line values
    return Config(
        translation_target_language=translation_target_language,
        output_dir=Path(output_dir),
        endpoint_profiles=endpoint_profiles,
        extractor_config=step_configs.get("extractor_config"),  # type: ignore[arg-type]
        glossary_config=step_configs.get("glossary_config"),  # type: ignore[arg-type]
        summarizor_config=step_configs.get("summarizor_config"),  # type: ignore[arg-type]
        translator_config=step_configs.get("translator_config"),  # type: ignore[arg-type]
        translator_batch_config=translator_batch_config,
        review_config=step_configs.get("review_config"),  # type: ignore[arg-type]
        ocr_config=step_configs.get("ocr_config"),  # type: ignore[arg-type]
        image_reembedding_config=step_configs.get("image_reembedding_config"),  # type: ignore[arg-type]
        manga_translator_config=step_configs.get("manga_translator_config"),  # type: ignore[arg-type]
        **data,
    )


def ensure_dirs(config: Config) -> None:
    """
    Ensure all configured directories exist.
    """
    config.output_dir.mkdir(parents=True, exist_ok=True)
    if config.working_dir is not None:
        config.working_dir.mkdir(parents=True, exist_ok=True)
    if config.log_dir is not None:
        config.log_dir.mkdir(parents=True, exist_ok=True)
