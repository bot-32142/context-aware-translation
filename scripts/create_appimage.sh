#!/usr/bin/env bash
# Create an AppImage from the PyInstaller output.
# Usage: ./scripts/create_appimage.sh <version> <platform_name>
#   e.g. ./scripts/create_appimage.sh v0.1.1 linux-x86_64
set -euo pipefail

VERSION="${1:-v0.0.0-dev}"
PLATFORM="${2:-linux-x86_64}"
APP_NAME="CAT-UI"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DIST_DIR="$PROJECT_DIR/dist/$APP_NAME"
RELEASE_DIR="$PROJECT_DIR/release"
BUILD_DIR="$PROJECT_DIR/build"
APPDIR="$BUILD_DIR/${APP_NAME}.AppDir"

mkdir -p "$RELEASE_DIR" "$BUILD_DIR"

# --- Download appimagetool ---
APPIMAGETOOL="$BUILD_DIR/appimagetool"
if [[ ! -f "$APPIMAGETOOL" ]]; then
    echo "Downloading appimagetool..."
    curl -fSL -o "$APPIMAGETOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$APPIMAGETOOL"
fi

# --- Build AppDir structure ---
echo "Building AppDir structure..."
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Copy PyInstaller output
echo "Copying PyInstaller output to AppDir (this may take a while)..."
cp -r "$DIST_DIR"/* "$APPDIR/usr/bin/"
echo "Copy complete ($(du -sh "$APPDIR/usr/bin" | cut -f1))"

# Desktop entry
cat > "$APPDIR/cat-ui.desktop" << 'DESKTOP'
[Desktop Entry]
Name=Context-Aware Translation
Exec=CAT-UI
Icon=cat-ui
Type=Application
Categories=Office;Translation;
Comment=Context-aware document translation with glossary management
DESKTOP
cp "$APPDIR/cat-ui.desktop" "$APPDIR/usr/share/applications/"

# Icon (placeholder - replace with a real icon later)
# Generate a simple 256x256 icon via Python/Pillow if available, otherwise use a 1px fallback
echo "Generating application icon..."
timeout 30 python3 -c "
import sys
sys.modules['torch'] = None  # prevent heavy imports
from PIL import Image, ImageDraw, ImageFont
img = Image.new('RGBA', (256, 256), (52, 120, 246, 255))
draw = ImageDraw.Draw(img)
try:
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 72)
except OSError:
    font = ImageFont.load_default()
bbox = draw.textbbox((0, 0), 'CAT', font=font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
draw.text(((256 - tw) / 2, (256 - th) / 2), 'CAT', fill='white', font=font)
img.save('$APPDIR/cat-ui.png')
" 2>/dev/null || {
    echo "Warning: Could not generate icon with Pillow, using minimal placeholder"
    # 1x1 blue PNG as absolute fallback
    printf '\x89PNG\r\n\x1a\n' > "$APPDIR/cat-ui.png"
    printf '\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02' >> "$APPDIR/cat-ui.png"
    printf '\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx' >> "$APPDIR/cat-ui.png"
    printf '\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N' >> "$APPDIR/cat-ui.png"
    printf '\x00\x00\x00\x00IEND\xaeB\x60\x82' >> "$APPDIR/cat-ui.png"
}
cp "$APPDIR/cat-ui.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/"

# AppRun entry point
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
SELF="$(readlink -f "$0")"
HERE="${SELF%/*}"
export PATH="${HERE}/usr/bin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/bin:${LD_LIBRARY_PATH:-}"
exec "${HERE}/usr/bin/CAT-UI" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# --- Build the AppImage ---
# APPIMAGE_EXTRACT_AND_RUN avoids the FUSE requirement in CI environments
echo "Building AppImage (compressing $(du -sh "$APPDIR" | cut -f1) AppDir)..."
export APPIMAGE_EXTRACT_AND_RUN=1
ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" \
    "$RELEASE_DIR/${APP_NAME}-${VERSION}-${PLATFORM}.AppImage"

echo "AppImage created: $RELEASE_DIR/${APP_NAME}-${VERSION}-${PLATFORM}.AppImage"
ls -lh "$RELEASE_DIR/${APP_NAME}-${VERSION}-${PLATFORM}.AppImage"
