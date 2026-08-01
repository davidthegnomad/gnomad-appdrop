"""Paths and defaults for Gnomad AppDrop."""

from __future__ import annotations

import os
from pathlib import Path

HOME = Path.home()

# Drop zone — Mac-like ~/Applications
APPLICATIONS_DIR = Path(
    os.environ.get("APPDROP_APPLICATIONS", HOME / "Applications")
)

# Extracted / installed binaries live here
OPT_DIR = Path(os.environ.get("APPDROP_OPT", HOME / ".local" / "opt"))

# Desktop entries + icons for the menu
DESKTOP_DIR = Path(
    os.environ.get(
        "APPDROP_DESKTOP",
        HOME / ".local" / "share" / "applications",
    )
)
ICON_DIR = Path(
    os.environ.get(
        "APPDROP_ICONS",
        HOME / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps",
    )
)

# Gnomad AppDrop state (installed app registry)
STATE_DIR = Path(
    os.environ.get("APPDROP_STATE", HOME / ".local" / "share" / "appdrop")
)
REGISTRY_PATH = STATE_DIR / "installed.json"

ARCHIVE_SUFFIXES = (
    ".tar.gz",
    ".tgz",
    ".tar.xz",
    ".txz",
    ".tar.bz2",
    ".tbz2",
    ".tar",
    ".zip",
)
APPIMAGE_SUFFIXES = (".appimage",)
DEB_SUFFIXES = (".deb",)
SUPPORTED_SUFFIXES = ARCHIVE_SUFFIXES + APPIMAGE_SUFFIXES + DEB_SUFFIXES

# Names that look like helpers, not the main app
SKIP_EXEC_NAMES = frozenset(
    {
        "uninstall",
        "uninstaller",
        "setup",
        "install",
        "installer",
        "update",
        "updater",
        "crashpad_handler",
        "chrome_crashpad_handler",
        "qtwebengineprocess",
        "xdg-open",
    }
)

# Prefer these when choosing among several executables
PREFERRED_EXEC_NAMES = (
    "apprun",
    "run",
    "launch",
    "start",
)


def ensure_dirs() -> None:
    for path in (APPLICATIONS_DIR, OPT_DIR, DESKTOP_DIR, ICON_DIR, STATE_DIR):
        path.mkdir(parents=True, exist_ok=True)
