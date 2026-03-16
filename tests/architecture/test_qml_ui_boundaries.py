from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = REPO_ROOT / "context_aware_translation" / "ui"
QML_UI_ROOTS = [UI_ROOT / "viewmodels", UI_ROOT / "shell_hosts"]
FORBIDDEN_BACKEND_IMPORT_PREFIXES = (
    "context_aware_translation.storage",
    "context_aware_translation.workflow",
    "context_aware_translation.core",
    "context_aware_translation.documents",
    "context_aware_translation.llm",
    "context_aware_translation.config",
)
FORBIDDEN_VIEWMODEL_IMPORT_PREFIXES = (
    "PySide6.QtWidgets",
    "context_aware_translation.ui.features",
    "context_aware_translation.ui.main_window",
)
FORBIDDEN_CALL_ATTRIBUTES = {"preflight", "preflight_task", "has_active_claims"}


def _iter_qml_ui_python_files() -> list[Path]:
    files: list[Path] = []
    for root in QML_UI_ROOTS:
        if not root.exists():
            continue
        files.extend(path for path in root.rglob("*.py") if path.name != "__init__.py")
    return sorted(files)


def _iter_viewmodel_python_files() -> list[Path]:
    viewmodels_root = UI_ROOT / "viewmodels"
    if not viewmodels_root.exists():
        return []
    return sorted(path for path in viewmodels_root.rglob("*.py") if path.name != "__init__.py")


def _module_imports(tree: ast.AST) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module, node.lineno))
    return found


def test_qml_ui_python_layers_do_not_import_backend_internals() -> None:
    violations: list[str] = []
    for path in _iter_qml_ui_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module_name, lineno in _module_imports(tree):
            if module_name.startswith(FORBIDDEN_BACKEND_IMPORT_PREFIXES):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno} imports {module_name}")
    assert not violations, "\n".join(violations)


def test_qml_viewmodels_do_not_depend_on_qwidgets_or_feature_widgets() -> None:
    violations: list[str] = []
    for path in _iter_viewmodel_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module_name, lineno in _module_imports(tree):
            if module_name.startswith(FORBIDDEN_VIEWMODEL_IMPORT_PREFIXES):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno} imports {module_name}")
    assert not violations, "\n".join(violations)


def test_qml_ui_python_layers_do_not_call_raw_taskengine_preflight_helpers() -> None:
    violations: list[str] = []
    for path in _iter_qml_ui_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in FORBIDDEN_CALL_ATTRIBUTES
            ):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} calls .{node.func.attr}(...)")
    assert not violations, "\n".join(violations)
