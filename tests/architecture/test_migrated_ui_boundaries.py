from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = REPO_ROOT / "context_aware_translation" / "ui"
MIGRATED_UI_ROOTS = [UI_ROOT / "adapters", UI_ROOT / "features"]
FORBIDDEN_IMPORT_PREFIXES = (
    "context_aware_translation.storage",
    "context_aware_translation.workflow",
    "context_aware_translation.core",
    "context_aware_translation.documents",
    "context_aware_translation.llm",
    "context_aware_translation.config",
)
FORBIDDEN_CALL_ATTRIBUTES = {"preflight", "preflight_task", "has_active_claims"}


def _iter_migrated_python_files() -> list[Path]:
    files: list[Path] = []
    for root in MIGRATED_UI_ROOTS:
        if not root.exists():
            continue
        files.extend(path for path in root.rglob("*.py") if path.name != "__init__.py")
    return sorted(files)


def _module_imports(tree: ast.AST) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module, node.lineno))
    return found


def test_migrated_ui_modules_do_not_import_backend_internals() -> None:
    violations: list[str] = []
    for path in _iter_migrated_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module_name, lineno in _module_imports(tree):
            if module_name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno} imports {module_name}")
    assert not violations, "\n".join(violations)


def test_migrated_ui_modules_do_not_call_raw_taskengine_preflight_helpers() -> None:
    violations: list[str] = []
    for path in _iter_migrated_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in FORBIDDEN_CALL_ATTRIBUTES
            ):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} calls .{node.func.attr}(...)")
    assert not violations, "\n".join(violations)
