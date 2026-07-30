#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
rm -f "$PREFIX/bin/appdrop"
rm -rf "$PREFIX/share/appdrop"
rm -f "$PREFIX/share/applications/appdrop.desktop"
systemctl --user disable --now appdrop-watch.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/appdrop-watch.service"
echo "Gnomad AppDrop uninstalled (installed apps in ~/.local/opt were left alone)."
echo "Remove them with: appdrop uninstall <id>  (before uninstalling Gnomad AppDrop)"
