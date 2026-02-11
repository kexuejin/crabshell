#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="CrabShell"
VERSION="$(node -p "require('${ROOT_DIR}/package.json').version")"

ARCH_RAW="$(uname -m)"
if [[ "$ARCH_RAW" == "arm64" ]]; then
  ARCH="aarch64"
elif [[ "$ARCH_RAW" == "x86_64" ]]; then
  ARCH="x64"
else
  ARCH="$ARCH_RAW"
fi

APP_BUNDLE_PATH="${ROOT_DIR}/src-tauri/target/release/bundle/macos/${APP_NAME}.app"
OUT_DIR="${ROOT_DIR}/src-tauri/target/release/bundle/dmg"
OUT_DMG="${OUT_DIR}/${APP_NAME}_${VERSION}_${ARCH}.dmg"

if [[ ! -d "$APP_BUNDLE_PATH" ]]; then
  echo "Error: app bundle not found at $APP_BUNDLE_PATH"
  echo "Run: npx tauri build --bundles app"
  exit 1
fi

mkdir -p "$OUT_DIR"
rm -f "$OUT_DMG"

STAGE_DIR="$(mktemp -d /tmp/crabshell-dmg-stage.XXXXXX)"
RW_DMG="${OUT_DIR}/rw.$$.$(basename "$OUT_DMG")"
MOUNT_POINT="/Volumes/${APP_NAME}-$$"

cleanup() {
  /usr/bin/hdiutil detach "$MOUNT_POINT" -quiet >/dev/null 2>&1 || true
  rm -f "$RW_DMG" >/dev/null 2>&1 || true
  rm -rf "$STAGE_DIR" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cp -R "$APP_BUNDLE_PATH" "$STAGE_DIR/"
ln -s /Applications "$STAGE_DIR/Applications"

echo "Creating temporary writable DMG..."
/usr/bin/hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$STAGE_DIR" \
  -ov \
  -format UDRW \
  "$RW_DMG"

echo "Converting to compressed DMG..."
if ! /usr/bin/hdiutil convert "$RW_DMG" -format UDZO -o "$OUT_DMG" -ov; then
  echo "UDZO conversion failed, fallback to UDRO..."
  /usr/bin/hdiutil convert "$RW_DMG" -format UDRO -o "$OUT_DMG" -ov
fi

echo "DMG created: $OUT_DMG"
