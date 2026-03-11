# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Context-Aware Translation UI."""

import sys
import tomllib
from importlib import metadata as importlib_metadata
from pathlib import Path

import opencc
import PySide6
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

# Get the project root
project_root = Path(SPECPATH)

# Read version from pyproject.toml (single source of truth)
with open(project_root / 'pyproject.toml', 'rb') as f:
    _pyproject = tomllib.load(f)
APP_VERSION = _pyproject['project']['version']

# Collect data files
datas = [
    # UI resources
    (str(project_root / 'context_aware_translation' / 'ui' / 'resources'),
     'context_aware_translation/ui/resources'),
    # QML resources
    (str(project_root / 'context_aware_translation' / 'ui' / 'qml'),
     'context_aware_translation/ui/qml'),
    # Translation files
    (str(project_root / 'context_aware_translation' / 'ui' / 'translations'),
     'context_aware_translation/ui/translations'),
    # Bundled tokenizer (avoids runtime download from HuggingFace)
    (str(project_root / 'context_aware_translation' / 'resources' / 'tokenizers' / 'deepseek-v3'),
     'context_aware_translation/resources/tokenizers/deepseek-v3'),
]

# Bundle Qt style plugins explicitly so packaged app can use native styles.
binaries = []
qt_styles_dir = Path(PySide6.__file__).resolve().parent / 'Qt' / 'plugins' / 'styles'
if qt_styles_dir.exists():
    for plugin in qt_styles_dir.iterdir():
        if plugin.is_file():
            binaries.append((str(plugin), 'PySide6/Qt/plugins/styles'))

# Explicit native-lib collection for packages that commonly miss implicit hook coverage.
for module_name in ('pikepdf', 'faiss', 'pypdfium2_raw'):
    try:
        binaries += collect_dynamic_libs(module_name)
    except Exception as exc:  # noqa: BLE001
        print(f"[cat-ui.spec] warning: failed to collect dynamic libs for {module_name}: {exc}")

# pypdfium2_raw also ships version metadata that some builds/runtime checks read.
try:
    datas += collect_data_files('pypdfium2_raw')
except Exception as exc:  # noqa: BLE001
    print(f"[cat-ui.spec] warning: failed to collect data files for pypdfium2_raw: {exc}")

# Ensure bundled pandoc executable/data (from pypandoc-binary distribution) are included.
try:
    datas += collect_data_files('pypandoc')
except Exception as exc:  # noqa: BLE001
    print(f"[cat-ui.spec] warning: failed to collect data files for pypandoc: {exc}")

# OpenCC requires config/dictionary assets at runtime (e.g. config/jp2s.json).
# Collect file-by-file to avoid platform-specific directory-copy behavior.


def _collect_data_tree(src_dir: Path, dst_root: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for file_path in sorted(src_dir.rglob('*')):
        if not file_path.is_file():
            continue
        rel_parent = file_path.parent.relative_to(src_dir)
        dst_dir = dst_root if rel_parent == Path('.') else f"{dst_root}/{rel_parent.as_posix()}"
        items.append((str(file_path), dst_dir))
    return items


def _collect_matching_files(src_dir: Path, pattern: str, dst_root: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for file_path in sorted(src_dir.glob(pattern)):
        if file_path.is_file():
            items.append((str(file_path), dst_root))
    return items


def _collect_opencc_assets() -> list[tuple[str, str]]:
    """Collect OpenCC config/dictionary files across platform-specific wheel layouts."""
    collected: list[tuple[str, str]] = []

    # Preferred: use wheel manifest, which remains accurate even if files are not under opencc/config.
    try:
        dist = importlib_metadata.distribution('opencc-python-reimplemented')
        for rel_path in dist.files or []:
            abs_path = Path(dist.locate_file(rel_path))
            if not abs_path.is_file():
                continue
            rel_posix = str(rel_path).replace('\\', '/')
            marker = f"/{rel_posix}"
            if '/config/' in marker and abs_path.suffix.lower() == '.json':
                collected.append((str(abs_path), 'opencc/config'))
            elif '/dictionary/' in marker:
                collected.append((str(abs_path), 'opencc/dictionary'))
    except importlib_metadata.PackageNotFoundError:
        pass

    # Also scan imported package location to cover files omitted from wheel RECORD on some builds.
    opencc_pkg_dir = Path(opencc.__file__).resolve().parent
    for file_path in sorted((opencc_pkg_dir / 'config').glob('*.json')):
        if file_path.is_file():
            collected.append((str(file_path), 'opencc/config'))
    for file_path in sorted((opencc_pkg_dir / 'dictionary').glob('*')):
        if file_path.is_file():
            collected.append((str(file_path), 'opencc/dictionary'))

    # De-duplicate while preserving order.
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for src, dst in collected:
        key = (str(Path(src)), dst)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((src, dst))
    return deduped


opencc_datas = _collect_opencc_assets()
vendored_opencc_root = project_root / 'context_aware_translation' / 'resources' / 'opencc'
vendored_config_dir = vendored_opencc_root / 'config'
vendored_dict_dir = vendored_opencc_root / 'dictionary'
if vendored_config_dir.exists() and vendored_dict_dir.exists():
    opencc_datas = _collect_data_tree(vendored_config_dir, 'opencc/config') + _collect_data_tree(
        vendored_dict_dir, 'opencc/dictionary'
    )

has_jp2s = any(dst == 'opencc/config' and Path(src).name == 'jp2s.json' for src, dst in opencc_datas)
has_dictionary = any(dst == 'opencc/dictionary' for _src, dst in opencc_datas)
if not has_jp2s or not has_dictionary:
    opencc_pkg_dir = Path(opencc.__file__).resolve().parent
    raise RuntimeError(
        'cat-ui.spec: OpenCC assets not found. '
        f'has_jp2s={has_jp2s}, has_dictionary={has_dictionary}, '
        f'opencc_pkg_dir={opencc_pkg_dir}'
    )
datas += opencc_datas

# Bundle Qt QML imports explicitly. Python hidden imports do not include the
# runtime QtQuick/QtQml module tree used by `import QtQuick` in .qml files.
qt_qml_dir = Path(PySide6.__file__).resolve().parent / 'Qt' / 'qml'
if qt_qml_dir.exists():
    datas += _collect_data_tree(qt_qml_dir, 'PySide6/Qt/qml')

# Bundle Qt's own translations so standard widget chrome can localize in
# packaged builds, even when QLibraryInfo points at a non-bundled install path.
qt_translations_dir = Path(PySide6.__file__).resolve().parent / 'Qt' / 'translations'
if qt_translations_dir.exists():
    datas += _collect_matching_files(qt_translations_dir, 'qtbase_*.qm', 'PySide6/Qt/translations')

# Hidden imports for PySide6 and other dependencies
hiddenimports = [
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
    'PySide6.QtXml',
    # Database
    'sqlite3',
    # For async operations
    'asyncio',
    # ML/AI dependencies that may be dynamically imported
    'transformers',
    'torch',
    'numpy',
    'PIL',
    'PIL.Image',
    # HTTP clients
    'httpx',
    'openai',
    # Storage
    'context_aware_translation.storage',
    'context_aware_translation.storage.book_manager',
    'context_aware_translation.storage.term_db',
    'context_aware_translation.storage.config_profile',
    'context_aware_translation.storage.book',
    'context_aware_translation.storage.registry_db',
    'context_aware_translation.storage.storage_manager',
    'context_aware_translation.storage.document_repository',
    # Core
    'context_aware_translation.core',
    'context_aware_translation.core.progress',
    # Documents
    'context_aware_translation.documents',
    'context_aware_translation.documents.base',
    # LLM
    'context_aware_translation.llm',
    'context_aware_translation.llm.client',
    # Translator
    'context_aware_translation.workflow.session',
    'context_aware_translation.config',
]

# Transformers loads model families via importlib at runtime.
# Bundle all model-family modules to avoid runtime ModuleNotFoundError
# (e.g., ernie4_5, qwen, glm, etc.) in packaged builds.
hiddenimports += collect_submodules('transformers.models')
# Explicit ERNIE imports for OCR/layout stacks that resolve these modules dynamically.
hiddenimports += [
    'transformers.models.ernie4_5',
    'transformers.models.ernie4_5.configuration_ernie4_5',
    'transformers.models.ernie4_5.modeling_ernie4_5',
    'transformers.models.ernie4_5_moe',
    'transformers.models.ernie4_5_moe.configuration_ernie4_5_moe',
    'transformers.models.ernie4_5_moe.modeling_ernie4_5_moe',
]

# Exclude unnecessary modules to reduce size
excludes = [
    'tkinter',
]

a = Analysis(
    [str(project_root / 'context_aware_translation' / 'ui' / 'main.py')],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# Strip NVIDIA/CUDA libraries on non-macOS platforms where CPU-only PyTorch is used.
# These libraries are ~5-8 GB and unnecessary for CPU-only builds.
if sys.platform != 'darwin':
    a.binaries = [b for b in a.binaries if not b[0].startswith(('nvidia', 'nvidia/'))]
    a.datas = [d for d in a.datas if not d[0].startswith(('nvidia', 'nvidia/'))]

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CAT-UI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=sys.platform == 'darwin',  # macOS app bundle only
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # TODO: Add icon file
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CAT-UI',
)

# macOS app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='CAT-UI.app',
        icon=None,  # TODO: Add .icns file
        bundle_identifier='com.context-aware-translation.cat-ui',
        info_plist={
            'CFBundleName': 'Context-Aware Translation',
            'CFBundleDisplayName': 'Context-Aware Translation',
            'CFBundleVersion': APP_VERSION,
            'CFBundleShortVersionString': APP_VERSION,
            'NSHighResolutionCapable': True,
            'NSRequiresAquaSystemAppearance': False,  # Support dark mode
        },
    )
