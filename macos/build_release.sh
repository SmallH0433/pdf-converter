#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
VERSION="1.3.4"
APP_NAME="PDF转换工具.app"
DMG_NAME="PDF-Converter-macOS-arm64-${VERSION}.dmg"
ZIP_NAME="PDF-Converter-macOS-arm64-${VERSION}.zip"
STAGING_DIR="${PROJECT_DIR}/build/macos-dmg"

cd "$PROJECT_DIR"
export PYINSTALLER_CONFIG_DIR="$PROJECT_DIR/.pyinstaller-cache"

"$PROJECT_DIR/.venv/bin/python" -m PyInstaller \
    --noconfirm \
    --clean \
    "$PROJECT_DIR/PDF转换工具-macOS.spec"

codesign --force --deep --sign - "$PROJECT_DIR/dist/$APP_NAME"
codesign --verify --deep --strict --verbose=2 "$PROJECT_DIR/dist/$APP_NAME"
"$PROJECT_DIR/dist/$APP_NAME/Contents/MacOS/PDF转换工具" --verify-ocr

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"
ditto "$PROJECT_DIR/dist/$APP_NAME" "$STAGING_DIR/$APP_NAME"
ln -s /Applications "$STAGING_DIR/Applications"

rm -f "$PROJECT_DIR/dist/$DMG_NAME" "$PROJECT_DIR/dist/$ZIP_NAME"
hdiutil create \
    -volname "PDF 转换工具" \
    -srcfolder "$STAGING_DIR" \
    -ov \
    -format UDZO \
    "$PROJECT_DIR/dist/$DMG_NAME"

ditto -c -k --sequesterRsrc --keepParent \
    "$PROJECT_DIR/dist/$APP_NAME" \
    "$PROJECT_DIR/dist/$ZIP_NAME"

shasum -a 256 "$PROJECT_DIR/dist/$DMG_NAME" "$PROJECT_DIR/dist/$ZIP_NAME"
