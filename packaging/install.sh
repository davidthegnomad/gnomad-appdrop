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

# Wrapper on PATH
cat > "$BIN_DIR/appdrop" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$APP_DIR/src\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m appdrop "\$@"
EOF
chmod +x "$BIN_DIR/appdrop"

# Desktop launcher for the GUI
cp "$ROOT/packaging/appdrop.desktop" "$DESKTOP_DIR/appdrop.desktop"
sed -i "s|@BIN@|$BIN_DIR/appdrop|g" "$DESKTOP_DIR/appdrop.desktop"
chmod +x "$DESKTOP_DIR/appdrop.desktop"

# Branding icon
ICON_SRC=""
if [[ -f "$ROOT/src/appdrop/assets/icon.png" ]]; then
  ICON_SRC="$ROOT/src/appdrop/assets/icon.png"
elif [[ -f "$ROOT/branding/icon.png" ]]; then
  ICON_SRC="$ROOT/branding/icon.png"
fi
if [[ -n "$ICON_SRC" ]]; then
  ICON_DEST="$HOME/.local/share/icons/hicolor/256x256/apps/gnomad-appdrop.png"
  mkdir -p "$(dirname "$ICON_DEST")"
  cp "$ICON_SRC" "$ICON_DEST"
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
  fi
fi

# Optional background watcher (user systemd)
cp "$ROOT/packaging/appdrop-watch.service" "$SYSTEMD_DIR/appdrop-watch.service"
sed -i "s|@BIN@|$BIN_DIR/appdrop|g" "$SYSTEMD_DIR/appdrop-watch.service"

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
