from __future__ import annotations

from context_aware_translation.core.term_memory_builder import TermMemoryBuilder


class _NoopUpdater:
    async def bootstrap_summary(self, _descriptions, **_kwargs) -> str:
        return "stable summary"

    async def update_summary(self, current_summary, _evidence, **_kwargs) -> tuple[bool, str]:
        return False, current_summary


def test_term_memory_builder_appends_checkpoint_for_covered_noop_tail() -> None:
    builder = TermMemoryBuilder(_NoopUpdater())
    try:
        versions = builder.build_versions(
            "hero",
            {
                1: "first",
                2: "second",
                3: "third",
                4: "fourth",
                5: "fifth",
            },
        )
    finally:
        builder.close()

    assert len(versions) == 2
    assert versions[0].kind == "bootstrap"
    assert versions[0].latest_evidence_chunk == 4
    assert versions[-1].kind == "checkpoint"
    assert versions[-1].latest_evidence_chunk == 5
    assert versions[-1].summary_text == "stable summary"
