#!/usr/bin/env bash
# Install Gnomad AppDrop on Nobara / Fedora-based desktops.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="$PREFIX/bin"
SHARE_DIR="$PREFIX/share"
APP_DIR="$SHARE_DIR/appdrop"
DESKTOP_DIR="$SHARE_DIR/applications"
SYSTEMD_DIR="$HOME/.config/systemd/user"

echo "==> Gnomad AppDrop install (prefix: $PREFIX)"

mkdir -p "$BIN_DIR" "$APP_DIR" "$DESKTOP_DIR" "$SYSTEMD_DIR" \
  "$HOME/Applications" "$HOME/.local/opt" \
  "$HOME/.local/share/icons/hicolor/256x256/apps"

# Copy package
rm -rf "$APP_DIR/src"
mkdir -p "$APP_DIR"
cp -a "$ROOT/src" "$APP_DIR/"
cp -a "$ROOT/pyproject.toml" "$APP_DIR/" 2>/dev/null || true
cp -a "$ROOT/README.md" "$APP_DIR/" 2>/dev/null || true

# Wrapper on PATH — argv0 must be gnomad-appdrop so Wayland matches the .desktop
cat > "$BIN_DIR/appdrop" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$APP_DIR/src\${PYTHONPATH:+:\$PYTHONPATH}"
exec -a gnomad-appdrop python3 -m appdrop "\$@"
EOF
chmod +x "$BIN_DIR/appdrop"

# Desktop launcher — basename must match Wayland app id (gnomad-appdrop)
DESKTOP_FILE="$DESKTOP_DIR/gnomad-appdrop.desktop"
cp "$ROOT/packaging/appdrop.desktop" "$DESKTOP_FILE"
# Remove older short name so Plasma/GNOME don't keep a stale Open With entry
rm -f "$DESKTOP_DIR/appdrop.desktop"

# Branding icon — install several sizes so titlebar + taskbar resolve it
ICON_SRC=""
if [[ -f "$ROOT/src/appdrop/assets/llama-logo.png" ]]; then
  ICON_SRC="$ROOT/src/appdrop/assets/llama-logo.png"
elif [[ -f "$ROOT/src/appdrop/assets/icon.png" ]]; then
  ICON_SRC="$ROOT/src/appdrop/assets/icon.png"
elif [[ -f "$ROOT/branding/icon.png" ]]; then
  ICON_SRC="$ROOT/branding/icon.png"
fi
ICON_PRIMARY=""
if [[ -n "$ICON_SRC" ]]; then
  # User hicolor needs an index.theme or GTK/Plasma ignore installed icons
  if [[ ! -f "$HOME/.local/share/icons/hicolor/index.theme" ]]; then
    cat > "$HOME/.local/share/icons/hicolor/index.theme" <<'EOF'
[Icon Theme]
Name=Hicolor
Comment=Fallback icon theme
Directories=16x16/apps,24x24/apps,32x32/apps,48x48/apps,64x64/apps,128x128/apps,256x256/apps

[16x16/apps]
Size=16
Context=Applications
Type=Fixed

[24x24/apps]
Size=24
Context=Applications
Type=Fixed

[32x32/apps]
Size=32
Context=Applications
Type=Fixed

[48x48/apps]
Size=48
Context=Applications
Type=Fixed

[64x64/apps]
Size=64
Context=Applications
Type=Fixed

[128x128/apps]
Size=128
Context=Applications
Type=Fixed

[256x256/apps]
Size=256
Context=Applications
Type=Fixed
EOF
  fi
  python3 - "$ICON_SRC" "$HOME/.local/share/icons/hicolor" <<'PY'
import pathlib, sys
from PIL import Image

src = pathlib.Path(sys.argv[1])
hicolor = pathlib.Path(sys.argv[2])
img = Image.open(src).convert("RGBA")
for size in (16, 24, 32, 48, 64, 128, 256):
    dest_dir = hicolor / f"{size}x{size}" / "apps"
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / "gnomad-appdrop.png"
    img.resize((size, size), Image.Resampling.LANCZOS).save(out, optimize=True)
print(hicolor / "256x256" / "apps" / "gnomad-appdrop.png")
PY
  ICON_PRIMARY="$HOME/.local/share/icons/hicolor/256x256/apps/gnomad-appdrop.png"
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
  fi
fi

python3 - "$DESKTOP_FILE" "$BIN_DIR/appdrop" "${ICON_PRIMARY:-gnomad-appdrop}" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
bin_path = sys.argv[2]
icon = sys.argv[3]
text = path.read_text(encoding="utf-8")
text = text.replace("@BIN@", bin_path).replace("@ICON@", icon)
path.write_text(text, encoding="utf-8")
PY
chmod +x "$DESKTOP_FILE"

# Help file managers recognize *.AppImage for Open With
MIME_DIR="$SHARE_DIR/mime/packages"
mkdir -p "$MIME_DIR"
if [[ -f "$ROOT/packaging/gnomad-appdrop.xml" ]]; then
  cp "$ROOT/packaging/gnomad-appdrop.xml" "$MIME_DIR/gnomad-appdrop.xml"
  if command -v update-mime-database >/dev/null 2>&1; then
    update-mime-database "$SHARE_DIR/mime" >/dev/null 2>&1 || true
  fi
fi

# Optional background watcher (user systemd)
cp "$ROOT/packaging/appdrop-watch.service" "$SYSTEMD_DIR/appdrop-watch.service"
python3 - "$SYSTEMD_DIR/appdrop-watch.service" "$BIN_DIR/appdrop" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
bin_path = sys.argv[2]
text = path.read_text(encoding="utf-8")
path.write_text(text.replace("@BIN@", bin_path), encoding="utf-8")
PY

# Optional GTK for window drag-and-drop
if command -v dnf >/dev/null 2>&1; then
  if ! python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk" 2>/dev/null; then
    echo "==> Optional: sudo dnf install python3-gobject gtk3  (enables window drag-and-drop)"
  fi
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi

# Ensure PATH hint
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    echo "==> Add to your shell RC if needed:"
    echo "    export PATH=\"$BIN_DIR:\$PATH\""
    ;;
esac

# Enable folder watcher by default for one-click setup
if [[ "${APPDROP_ENABLE_WATCH:-1}" == "1" ]]; then
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    systemctl --user enable --now appdrop-watch.service >/dev/null 2>&1 || true
  fi
fi

echo
echo "Installed."
echo "  Menu:    search for Gnomad AppDrop"
echo "  Drop:    $HOME/Applications"
echo "  CLI:     appdrop --help"
echo
"$BIN_DIR/appdrop" init
