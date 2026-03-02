# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Context-Aware Translation UI."""

import sys
import tomllib
from pathlib import Path

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

# Exclude unnecessary modules to reduce size
excludes = [
    'tkinter',
]

a = Analysis(
    [str(project_root / 'context_aware_translation' / 'ui' / 'main.py')],
    pathex=[str(project_root)],
    binaries=[],
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
