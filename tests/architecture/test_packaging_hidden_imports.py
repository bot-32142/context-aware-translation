from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "cat-ui.spec"
REMOVED_STORAGE_IMPORTS = {
    "context_aware_translation.storage.book_manager",
    "context_aware_translation.storage.term_db",
    "context_aware_translation.storage.config_profile",
    "context_aware_translation.storage.book",
    "context_aware_translation.storage.registry_db",
    "context_aware_translation.storage.storage_manager",
    "context_aware_translation.storage.document_repository",
}
REQUIRED_STORAGE_IMPORTS = {
    "context_aware_translation.storage.library.book_manager",
    "context_aware_translation.storage.models.book",
    "context_aware_translation.storage.models.config_profile",
    "context_aware_translation.storage.repositories.document_repository",
    "context_aware_translation.storage.repositories.term_repository",
    "context_aware_translation.storage.schema.book_db",
    "context_aware_translation.storage.schema.registry_db",
}


def test_cat_ui_spec_uses_migrated_storage_hidden_imports() -> None:
    spec_text = SPEC_PATH.read_text(encoding="utf-8")

    stale_imports = sorted(name for name in REMOVED_STORAGE_IMPORTS if name in spec_text)
    assert not stale_imports, f"stale storage hidden imports remain in cat-ui.spec: {stale_imports}"

    missing_imports = sorted(name for name in REQUIRED_STORAGE_IMPORTS if name not in spec_text)
    assert not missing_imports, f"migrated storage hidden imports missing from cat-ui.spec: {missing_imports}"
