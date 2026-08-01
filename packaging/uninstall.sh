#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
rm -f "$PREFIX/bin/appdrop"
rm -rf "$PREFIX/share/appdrop"
rm -f "$PREFIX/share/applications/appdrop.desktop"
rm -f "$PREFIX/share/applications/gnomad-appdrop.desktop"
rm -f "$PREFIX/share/mime/packages/gnomad-appdrop.xml"
# Remove installed icon sizes
for size in 16 24 32 48 64 128 256; do
  rm -f "$HOME/.local/share/icons/hicolor/${size}x${size}/apps/gnomad-appdrop.png"
done
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi
if command -v update-mime-database >/dev/null 2>&1; then
  update-mime-database "$PREFIX/share/mime" >/dev/null 2>&1 || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$PREFIX/share/applications" >/dev/null 2>&1 || true
fi
systemctl --user disable --now appdrop-watch.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/appdrop-watch.service"
echo "Gnomad AppDrop uninstalled (installed apps in ~/.local/opt were left alone)."
echo "Remove them with: appdrop uninstall <id>  (before uninstalling Gnomad AppDrop)"
