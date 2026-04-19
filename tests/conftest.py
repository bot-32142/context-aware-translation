import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from context_aware_translation.config import Config  # noqa: E402


@pytest.fixture
def temp_config(tmp_path: Path) -> Config:
    work = tmp_path / "data"
    from context_aware_translation.config import (
        ExtractorConfig,
        GlossaryTranslationConfig,
        ReviewConfig,
        SummarizorConfig,
        TranslatorConfig,
    )

    # Each step config must be self-contained with complete API settings
    base_settings = {
        "api_key": "DUMMY_API_KEY",
        "base_url": "https://api.test.com/v1",
        "model": "test-model",
    }
    cfg = Config(
        working_dir=work,
        translation_target_language="简体中文",
        extractor_config=ExtractorConfig(**base_settings),
        summarizor_config=SummarizorConfig(**base_settings),
        translator_config=TranslatorConfig(**base_settings),
        glossary_config=GlossaryTranslationConfig(**base_settings),
        review_config=ReviewConfig(**base_settings),
    )
    yield cfg
