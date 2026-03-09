from __future__ import annotations

from context_aware_translation.utils import cjk_normalize


def test_normalize_for_matching_handles_japanese_variants_before_t2s() -> None:
    cjk_normalize._get_converter.cache_clear()

    assert cjk_normalize.normalize_for_matching("天ぷら騎士団") == "天ぷら骑士团"
