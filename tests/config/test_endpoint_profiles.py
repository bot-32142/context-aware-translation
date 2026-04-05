"""Unit tests for endpoint profile system."""

import tempfile
from pathlib import Path

import pytest

from context_aware_translation.config import (
    Config,
    EndpointProfile,
    ExtractorConfig,
    GlossaryTranslationConfig,
    LLMConfig,
    PolishBatchConfig,
    ReviewConfig,
    SummarizorConfig,
    TranslatorBatchConfig,
    TranslatorConfig,
    _resolve_with_profile,
    ensure_valid_persisted_config_payload,
    infer_translator_batch_provider,
    load_config_from_yaml,
    validate_persisted_config_payload,
)


class TestEndpointProfile:
    """Tests for EndpointProfile dataclass."""

    def test_endpoint_profile_creation(self):
        """Test creating an EndpointProfile with all fields."""
        profile = EndpointProfile(
            name="test",
            api_key="sk-test",
            base_url="https://api.test.com",
            api_version="v1",
            timeout=60.0,
            max_retries=5,
            model="test-model",
            temperature=0.5,
            concurrency=10,
            kwargs={"extra": "value"},
        )
        assert profile.name == "test"
        assert profile.api_key == "sk-test"
        assert profile.base_url == "https://api.test.com"
        assert profile.model == "test-model"
        assert profile.kwargs == {"extra": "value"}

    def test_endpoint_profile_defaults(self):
        """Test EndpointProfile default values."""
        profile = EndpointProfile(name="minimal")
        assert profile.api_key is None
        assert profile.base_url is None
        assert profile.timeout == 120.0
        assert profile.max_retries == 3
        assert profile.temperature == 0.0
        assert profile.concurrency == 5
        assert profile.kwargs == {}


class TestResolveWithProfile:
    """Tests for _resolve_with_profile function."""

    def test_no_profile_returns_original(self):
        """Config without profile reference returns unchanged."""
        config = LLMConfig(api_key="key", base_url="url", model="model")
        profiles = {}
        result = _resolve_with_profile(config, profiles)
        assert result is config

    def test_profile_values_merged(self):
        """Profile values are merged into config."""
        profiles = {
            "prod": EndpointProfile(
                name="prod",
                api_key="prod-key",
                base_url="https://prod.api",
                model="prod-model",
            )
        }
        config = LLMConfig(endpoint_profile="prod")
        result = _resolve_with_profile(config, profiles)

        assert result.api_key == "prod-key"
        assert result.base_url == "https://prod.api"
        assert result.model == "prod-model"
        assert result.endpoint_profile == "prod"  # Preserved after resolution for token tracking

    def test_config_values_override_profile(self):
        """Config values take precedence over profile values."""
        profiles = {
            "prod": EndpointProfile(
                name="prod",
                api_key="prod-key",
                base_url="https://prod.api",
                model="prod-model",
            )
        }
        config = LLMConfig(endpoint_profile="prod", model="custom-model")
        result = _resolve_with_profile(config, profiles)

        assert result.api_key == "prod-key"  # From profile
        assert result.model == "custom-model"  # Override

    def test_missing_profile_raises_error(self):
        """Referencing non-existent profile raises ValueError."""
        profiles = {}
        config = LLMConfig(endpoint_profile="nonexistent")

        with pytest.raises(ValueError, match="not found"):
            _resolve_with_profile(config, profiles)

    def test_explicit_default_scalars_override_profile(self):
        """Explicit default-valued overrides still beat profile values."""
        profiles = {
            "prod": EndpointProfile(
                name="prod",
                api_key="prod-key",
                base_url="https://prod.api",
                model="prod-model",
                timeout=240.0,
                max_retries=7,
                temperature=0.8,
                concurrency=11,
            )
        }
        config = LLMConfig.from_dict(
            {
                "endpoint_profile": "prod",
                "timeout": 120.0,
                "max_retries": 3,
                "temperature": 0.0,
                "concurrency": 5,
            }
        )

        result = _resolve_with_profile(config, profiles)

        assert result.timeout == 120.0
        assert result.max_retries == 3
        assert result.temperature == 0.0
        assert result.concurrency == 5

    def test_kwargs_merged(self):
        """Profile and config kwargs are merged correctly."""
        profiles = {
            "test": EndpointProfile(
                name="test",
                api_key="key",
                kwargs={"a": 1, "b": 2},
            )
        }
        config = LLMConfig(endpoint_profile="test", kwargs={"b": 3, "c": 4})
        result = _resolve_with_profile(config, profiles)

        # Config kwargs override profile kwargs
        assert result.kwargs == {"a": 1, "b": 3, "c": 4}

    def test_kwargs_from_profile_only(self):
        """Profile kwargs are used when config has no kwargs."""
        profiles = {
            "test": EndpointProfile(
                name="test",
                api_key="key",
                base_url="https://test.api",
                model="model",
                kwargs={"extra_body": {"google": {"thinking_config": {"thinking_level": "MINIMAL"}}}},
            )
        }
        config = LLMConfig(endpoint_profile="test")
        result = _resolve_with_profile(config, profiles)

        assert result.kwargs == {"extra_body": {"google": {"thinking_config": {"thinking_level": "MINIMAL"}}}}

    def test_kwargs_empty_when_neither_has_kwargs(self):
        """Result kwargs are empty when neither profile nor config set kwargs."""
        profiles = {
            "test": EndpointProfile(
                name="test",
                api_key="key",
                base_url="https://test.api",
                model="model",
            )
        }
        config = LLMConfig(endpoint_profile="test")
        result = _resolve_with_profile(config, profiles)

        assert result.kwargs == {}

    def test_internal_profile_metadata_kwargs_are_stripped(self):
        """App-managed metadata must not leak into resolved LLM kwargs."""
        profiles = {
            "test": EndpointProfile(
                name="test",
                api_key="key",
                base_url="https://test.api",
                model="model",
                kwargs={
                    "provider": "gemini",
                    "_ui_display_name": "Gemini Personal Tweak",
                    "_wizard_template_key": "gemini:gemini-2.5-pro",
                    "extra_body": {"google": {"thinking_config": {"thinking_level": "MINIMAL"}}},
                },
            )
        }
        config = LLMConfig(endpoint_profile="test", kwargs={"reasoning_effort": "low"})
        result = _resolve_with_profile(config, profiles)

        assert result.kwargs == {
            "extra_body": {"google": {"thinking_config": {"thinking_level": "MINIMAL"}}},
            "reasoning_effort": "low",
        }

    def test_translator_batch_config_round_trip(self):
        translator_batch = TranslatorBatchConfig(batch_size=321)

        payload = translator_batch.to_dict()
        restored = TranslatorBatchConfig.from_dict(payload)

        assert restored.batch_size == 321

    def test_polish_batch_config_round_trip(self):
        polish_batch = PolishBatchConfig(batch_size=222)

        payload = polish_batch.to_dict()
        restored = PolishBatchConfig.from_dict(payload)

        assert restored.batch_size == 222

    def test_gemini_named_model_on_custom_endpoint_is_not_marked_batch_capable(self):
        translator_config = TranslatorConfig(
            api_key="key",
            base_url="https://openrouter.ai/api/v1",
            model="gemini-2.5-pro",
        )

        assert infer_translator_batch_provider(translator_config) is None

    def test_translator_config_strip_epub_ruby_defaults_true(self):
        restored = TranslatorConfig.from_dict({})
        assert restored.strip_epub_ruby is True
        assert restored.to_dict()["strip_epub_ruby"] is True

    def test_translator_config_strip_epub_ruby_round_trips_false(self):
        restored = TranslatorConfig.from_dict({"strip_epub_ruby": False})
        assert restored.strip_epub_ruby is False
        assert restored.to_dict()["strip_epub_ruby"] is False


class TestConfigWithProfiles:
    """Tests for Config with endpoint profiles."""

    def test_step_config_profile_resolution(self):
        """Step config profile is resolved in __post_init__."""
        profiles = {
            "test": EndpointProfile(
                name="test",
                api_key="test-key",
                base_url="https://test.api",
                model="test-model",
            )
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(
                translation_target_language="Chinese",
                output_dir=tmpdir,
                endpoint_profiles=profiles,
                extractor_config=ExtractorConfig(endpoint_profile="test"),
                summarizor_config=SummarizorConfig(endpoint_profile="test"),
                translator_config=TranslatorConfig(endpoint_profile="test"),
                glossary_config=GlossaryTranslationConfig(endpoint_profile="test"),
                review_config=ReviewConfig(endpoint_profile="test"),
            )

            assert config.extractor_config.api_key == "test-key"
            assert config.extractor_config.model == "test-model"

    def test_step_configs_with_same_profile(self):
        """Multiple step configs can share the same profile."""
        profiles = {
            "base": EndpointProfile(
                name="base",
                api_key="base-key",
                base_url="https://base.api",
                model="base-model",
            )
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(
                translation_target_language="Chinese",
                output_dir=tmpdir,
                endpoint_profiles=profiles,
                extractor_config=ExtractorConfig(endpoint_profile="base"),
                summarizor_config=SummarizorConfig(endpoint_profile="base"),
                translator_config=TranslatorConfig(endpoint_profile="base"),
                glossary_config=GlossaryTranslationConfig(endpoint_profile="base"),
                review_config=ReviewConfig(endpoint_profile="base"),
            )

            # All configs use the same profile
            assert config.extractor_config.api_key == "base-key"
            assert config.extractor_config.model == "base-model"
            assert config.summarizor_config.api_key == "base-key"
            assert config.translator_config.api_key == "base-key"

    def test_step_config_own_profile(self):
        """Step config can have its own profile."""
        profiles = {
            "base": EndpointProfile(
                name="base",
                api_key="base-key",
                base_url="https://base.api",
                model="base-model",
            ),
            "translator": EndpointProfile(
                name="translator",
                api_key="trans-key",
                base_url="https://trans.api",
                model="trans-model",
            ),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(
                translation_target_language="Chinese",
                output_dir=tmpdir,
                endpoint_profiles=profiles,
                extractor_config=ExtractorConfig(endpoint_profile="base"),
                summarizor_config=SummarizorConfig(endpoint_profile="base"),
                translator_config=TranslatorConfig(endpoint_profile="translator"),
                glossary_config=GlossaryTranslationConfig(endpoint_profile="base"),
                review_config=ReviewConfig(endpoint_profile="base"),
            )

            # translator_config uses its own profile
            assert config.translator_config.api_key == "trans-key"
            assert config.translator_config.model == "trans-model"

            # extractor_config uses base profile
            assert config.extractor_config.api_key == "base-key"


class TestLoadConfigFromYaml:
    """Tests for YAML loading with endpoint profiles."""

    def test_yaml_with_endpoint_profiles(self):
        """YAML with endpoint_profiles section loads correctly."""
        yaml_content = """
endpoint_profiles:
  myprofile:
    api_key: yaml-key
    base_url: https://yaml.api
    model: yaml-model

llm:
  extractor_config:
    endpoint_profile: myprofile
  summarizor_config:
    endpoint_profile: myprofile
  translator_config:
    endpoint_profile: myprofile
  glossary_config:
    endpoint_profile: myprofile
  review_config:
    endpoint_profile: myprofile
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            yaml_path = f.name

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                config = load_config_from_yaml(yaml_path, "Chinese", tmpdir)

                assert config.extractor_config.api_key == "yaml-key"
                assert config.extractor_config.base_url == "https://yaml.api"
                assert config.extractor_config.model == "yaml-model"
        finally:
            Path(yaml_path).unlink()

    def test_yaml_with_direct_step_configs(self):
        """YAML with direct step config values works."""
        yaml_content = """
llm:
  extractor_config:
    api_key: direct-key
    base_url: https://direct.api
    model: direct-model
  summarizor_config:
    api_key: direct-key
    base_url: https://direct.api
    model: direct-model
    noise_filtering_threshold: 0.5
  translator_config:
    api_key: direct-key
    base_url: https://direct.api
    model: direct-model
  glossary_config:
    api_key: direct-key
    base_url: https://direct.api
    model: direct-model
  review_config:
    api_key: direct-key
    base_url: https://direct.api
    model: direct-model
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            yaml_path = f.name

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                config = load_config_from_yaml(yaml_path, "Chinese", tmpdir)

                assert config.extractor_config.api_key == "direct-key"
                assert config.extractor_config.model == "direct-model"
                assert config.summarizor_config is not None
                assert config.summarizor_config.model == "direct-model"
                assert not hasattr(config.summarizor_config, "noise_filtering_threshold")
        finally:
            Path(yaml_path).unlink()


class TestValidation:
    """Tests for config validation."""

    def test_validation_fails_without_required_fields(self):
        """Config without api_key/base_url/model fails validation."""
        with tempfile.TemporaryDirectory() as tmpdir, pytest.raises(ValueError, match="must be provided"):
            Config(
                translation_target_language="Chinese",
                output_dir=tmpdir,
                # No step configs provided
            )

    def test_validation_passes_with_profile(self):
        """Config with profile providing required fields passes validation."""
        profiles = {
            "complete": EndpointProfile(
                name="complete",
                api_key="key",
                base_url="url",
                model="model",
            )
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            # Should not raise
            config = Config(
                translation_target_language="Chinese",
                output_dir=tmpdir,
                endpoint_profiles=profiles,
                extractor_config=ExtractorConfig(endpoint_profile="complete"),
                summarizor_config=SummarizorConfig(endpoint_profile="complete"),
                translator_config=TranslatorConfig(endpoint_profile="complete"),
                glossary_config=GlossaryTranslationConfig(endpoint_profile="complete"),
                review_config=ReviewConfig(endpoint_profile="complete"),
            )
            assert config.extractor_config.api_key == "key"


class TestRuntimeConfigSnapshot:
    """Tests for validated workflow runtime snapshot access."""

    def test_get_workflow_runtime_config_returns_non_optional_fields(self):
        base = {
            "api_key": "k",
            "base_url": "https://api.example.com/v1",
            "model": "m",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(
                translation_target_language="Chinese",
                output_dir=tmpdir,
                extractor_config=ExtractorConfig(**base),
                summarizor_config=SummarizorConfig(**base),
                translator_config=TranslatorConfig(**base),
                glossary_config=GlossaryTranslationConfig(**base),
                review_config=ReviewConfig(**base),
            )

            runtime = config.get_workflow_runtime_config()
            assert runtime.sqlite_path == config.sqlite_path
            assert runtime.extractor_config.model == "m"
            assert runtime.summarizor_config.model == "m"
            assert runtime.translator_config.model == "m"
            assert runtime.glossary_config.model == "m"

    def test_get_workflow_runtime_config_raises_when_required_field_missing(self):
        base = {
            "api_key": "k",
            "base_url": "https://api.example.com/v1",
            "model": "m",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(
                translation_target_language="Chinese",
                output_dir=tmpdir,
                extractor_config=ExtractorConfig(**base),
                summarizor_config=SummarizorConfig(**base),
                translator_config=TranslatorConfig(**base),
                glossary_config=GlossaryTranslationConfig(**base),
                review_config=ReviewConfig(**base),
            )

            config.translator_config = None
            with pytest.raises(ValueError, match="translator_config"):
                config.get_workflow_runtime_config()


class TestPersistedPayloadValidation:
    """Tests for persistence-time config payload validation."""

    def test_validate_persisted_config_payload_detects_missing_sections(self):
        errors = validate_persisted_config_payload({"translation_target_language": "zh-CN"})
        assert any("extractor_config is required" in e for e in errors)

    def test_validate_persisted_config_payload_accepts_endpoint_profile_reference(self):
        config_payload = {
            "translation_target_language": "zh-CN",
            "extractor_config": {"endpoint_profile": "shared"},
            "summarizor_config": {"endpoint_profile": "shared"},
            "translator_config": {"endpoint_profile": "shared"},
            "glossary_config": {"endpoint_profile": "shared"},
            "review_config": {"endpoint_profile": "shared"},
        }

        errors = validate_persisted_config_payload(
            config_payload, endpoint_profile_exists=lambda name: name == "shared"
        )
        assert errors == []

    def test_validate_persisted_config_payload_accepts_endpoint_profile_id_reference(self):
        config_payload = {
            "translation_target_language": "zh-CN",
            "extractor_config": {"endpoint_profile": "shared-id"},
            "summarizor_config": {"endpoint_profile": "shared-id"},
            "translator_config": {"endpoint_profile": "shared-id"},
            "glossary_config": {"endpoint_profile": "shared-id"},
            "review_config": {"endpoint_profile": "shared-id"},
        }

        errors = validate_persisted_config_payload(
            config_payload, endpoint_profile_exists=lambda ref: ref == "shared-id"
        )
        assert errors == []

    def test_ensure_valid_persisted_config_payload_raises(self):
        with pytest.raises(ValueError, match="Invalid config payload"):
            ensure_valid_persisted_config_payload({"translation_target_language": "zh-CN"})

    def test_validate_persisted_payload_accepts_translator_batch_with_batch_size_only(self):
        config_payload = {
            "translation_target_language": "zh-CN",
            "extractor_config": {"endpoint_profile": "shared"},
            "summarizor_config": {"endpoint_profile": "shared"},
            "translator_config": {"endpoint_profile": "shared"},
            "glossary_config": {"endpoint_profile": "shared"},
            "translator_batch_config": {
                "batch_size": 500,
            },
            "polish_batch_config": {
                "batch_size": 250,
            },
        }

        errors = validate_persisted_config_payload(
            config_payload,
            endpoint_profile_exists=lambda name: name == "shared",
        )
        assert errors == []
