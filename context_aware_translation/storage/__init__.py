"""Storage package with compatibility aliases for reorganized submodules."""

from __future__ import annotations

import sys
from importlib import import_module

_COMPAT_SUBMODULES = {
    "book_db": "schema.book_db",
    "context_tree_db": "schema.context_tree_db",
    "registry_db": "schema.registry_db",
    "document_repository": "repositories.document_repository",
    "llm_batch_store": "repositories.llm_batch_store",
    "task_store": "repositories.task_store",
    "term_repository": "repositories.term_repository",
    "translation_batch_task_store": "repositories.translation_batch_task_store",
}

for _legacy_name, _target_name in _COMPAT_SUBMODULES.items():
    sys.modules.setdefault(f"{__name__}.{_legacy_name}", import_module(f"{__name__}.{_target_name}"))

del _legacy_name
del _target_name
