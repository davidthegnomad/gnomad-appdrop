#!/usr/bin/env bash
# Build a downloadable zip: unzip → double-click Install Gnomad AppDrop
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${VERSION:-1.1.0}"
OUT_DIR="${OUT_DIR:-$ROOT/dist}"
STAGE="$OUT_DIR/Gnomad-AppDrop-Setup"
ZIP="$OUT_DIR/Gnomad-AppDrop-${VERSION}-Setup.zip"

rm -rf "$STAGE"
mkdir -p "$STAGE/packaging" "$STAGE/src"

cp -a "$ROOT/src/appdrop" "$STAGE/src/"
find "$STAGE" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '*.pyc' -delete 2>/dev/null || true
cp -a "$ROOT/packaging/install.sh" "$STAGE/packaging/"
cp -a "$ROOT/packaging/uninstall.sh" "$STAGE/packaging/"
cp -a "$ROOT/packaging/setup_wizard.py" "$STAGE/packaging/"
cp -a "$ROOT/packaging/appdrop.desktop" "$STAGE/packaging/"
cp -a "$ROOT/packaging/appdrop-watch.service" "$STAGE/packaging/"
cp -a "$ROOT/packaging/gnomad-appdrop.xml" "$STAGE/packaging/" 2>/dev/null || true
cp -a "$ROOT/pyproject.toml" "$STAGE/"
cp -a "$ROOT/README.md" "$STAGE/"
cp -a "$ROOT/Install-Gnomad-AppDrop" "$STAGE/"
cp -a "$ROOT/Install Gnomad AppDrop.desktop" "$STAGE/"
cp -a "$ROOT/START-HERE.txt" "$STAGE/" 2>/dev/null || true
mkdir -p "$STAGE/branding" "$STAGE/src/appdrop/assets"
mkdir -p "$STAGE/branding"
# Ship splash/icon/logos in the Setup zip (skip large hero/og — those live on the website)
for f in icon.png splash.png gnomad-studio-logo.png david-the-gnomad-logo.png; do
  [[ -f "$ROOT/branding/$f" ]] && cp -a "$ROOT/branding/$f" "$STAGE/branding/"
done
cp -a "$ROOT/src/appdrop/assets/." "$STAGE/src/appdrop/assets/" 2>/dev/null || true

chmod +x "$STAGE/Install-Gnomad-AppDrop" "$STAGE/packaging/install.sh" "$STAGE/packaging/uninstall.sh"

cat > "$STAGE/Install Gnomad AppDrop.desktop" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Install Gnomad AppDrop
Comment=One-click setup — makes drag-and-drop app installs work on Linux
Exec=bash -c 'DIR="$(dirname "$(readlink -f "%k" 2>/dev/null || realpath "%k" 2>/dev/null || echo %k)")"; cd "$DIR" && ./Install-Gnomad-AppDrop'
Icon=system-software-install
Terminal=false
Categories=Utility;
StartupNotify=true
EOF
chmod +x "$STAGE/Install Gnomad AppDrop.desktop"

rm -f "$ZIP"
(
  cd "$OUT_DIR"
  zip -r -q "$(basename "$ZIP")" "Gnomad-AppDrop-Setup"
)

echo "Built: $ZIP"
echo
echo "Give someone that zip. They:"
echo "  1. Unzip it"
echo "  2. Open Gnomad-AppDrop-Setup"
echo "  3. Double-click “Install Gnomad AppDrop” (or run Install-Gnomad-AppDrop)"
