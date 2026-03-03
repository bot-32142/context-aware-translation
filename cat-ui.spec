# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Context-Aware Translation UI."""

import sys
import tomllib
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
# Include directories directly from installed package path to avoid hook/glob variance.
opencc_pkg_dir = Path(opencc.__file__).resolve().parent
opencc_config_dir = opencc_pkg_dir / 'config'
opencc_dict_dir = opencc_pkg_dir / 'dictionary'
if not opencc_config_dir.exists() or not opencc_dict_dir.exists():
    raise RuntimeError(
        f"cat-ui.spec: OpenCC package data dirs missing: config={opencc_config_dir.exists()} "
        f"dictionary={opencc_dict_dir.exists()}"
    )

jp2s_cfg = opencc_config_dir / 'jp2s.json'
if not jp2s_cfg.exists():
    raise RuntimeError(f"cat-ui.spec: required OpenCC config missing: {jp2s_cfg}")


def _add_data_tree(src_dir: Path, dst_root: str) -> None:
    """Add all files under *src_dir* to datas, preserving relative layout."""
    for file_path in sorted(src_dir.rglob('*')):
        if not file_path.is_file():
            continue
        rel_parent = file_path.parent.relative_to(src_dir)
        dst_dir = dst_root if rel_parent == Path('.') else f"{dst_root}/{rel_parent.as_posix()}"
        datas.append((str(file_path), dst_dir))


# Add OpenCC assets file-by-file; this is more reliable across PyInstaller platforms.
_add_data_tree(opencc_config_dir, 'opencc/config')
_add_data_tree(opencc_dict_dir, 'opencc/dictionary')

# Hidden imports for PySide6 and other dependencies
hiddenimports = [
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
