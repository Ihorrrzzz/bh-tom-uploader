#!/usr/bin/env bash
# Build the macOS app bundle + DMG. Run ON macOS (PyInstaller cannot cross-compile).
#   ./scripts/build_macos.sh
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="2.0.0"
ARCH="$(uname -m)"   # arm64 (Apple Silicon) or x86_64 (Intel)

python3 -m venv .venv-build
source .venv-build/bin/activate
pip install --upgrade pip
pip install -r requirements.txt pyinstaller

pyinstaller --noconfirm --clean --windowed --name "BHTOM Uploader" \
  --icon bhtom_uploader/resources/app.icns \
  --add-data "bhtom_uploader/resources:bhtom_uploader/resources" \
  --exclude-module tkinter --exclude-module _tkinter \
  --osx-bundle-identifier space.bhtom.uploader \
  main.py

cp config.ini "dist/BHTOM Uploader.app/Contents/MacOS/config.ini"

# self-check the frozen bundle (offscreen; verifies Qt plugins + Keychain backend)
(
  cd "dist/BHTOM Uploader.app/Contents/MacOS"
  QT_QPA_PLATFORM=offscreen "./BHTOM Uploader" --smoke
  cat smoke_result.txt
  rm -f smoke_result.txt
)

# drag-to-Applications DMG
rm -rf dist/dmgroot
mkdir dist/dmgroot
cp -R "dist/BHTOM Uploader.app" dist/dmgroot/
ln -s /Applications dist/dmgroot/Applications
hdiutil create -volname "BHTOM Uploader" -srcfolder dist/dmgroot -ov -format UDZO \
  "dist/BHTOM-Uploader-${VERSION}-${ARCH}.dmg"
rm -rf dist/dmgroot

echo "DONE: dist/BHTOM-Uploader-${VERSION}-${ARCH}.dmg"
echo "Note: the app is unsigned - first launch needs right-click > Open (Gatekeeper)."
