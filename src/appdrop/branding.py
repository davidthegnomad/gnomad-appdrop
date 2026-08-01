"""Gnomad Studio branding constants and asset paths."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

STUDIO_NAME = "Gnomad Studio"
STUDIO_URL = "https://gnomad.studio"
SITE_URL = "https://davidcole.cloud"
APP_PAGE_URL = f"{SITE_URL}/apps/appdrop"
DOWNLOAD_URL = f"{SITE_URL}/apps/appdrop/download"
GITHUB_URL = "https://github.com/davidthegnomad/gnomad-appdrop"
GITHUB_ISSUES_URL = f"{GITHUB_URL}/issues"
BUG_REPORT_URL = f"{GITHUB_URL}/issues/new"
SUPPORT_EMAIL = "david@gnomad.studio"
PRODUCT_NAME = "Gnomad AppDrop"
# Must match the installed .desktop basename / StartupWMClass (Wayland taskbar).
APP_ID = "gnomad-appdrop"


def support_mailto(*, subject: str = "Gnomad AppDrop support") -> str:
    return f"mailto:{SUPPORT_EMAIL}?subject={quote(subject)}"


def bug_report_mailto(*, version: str = "") -> str:
    subject = "Gnomad AppDrop bug report"
    if version:
        subject = f"{subject} (v{version})"
    body = (
        "What happened?\n\n"
        "Steps to reproduce:\n1.\n2.\n\n"
        f"AppDrop version: {version or '(unknown)'}\n"
        "Linux distro / desktop:\n"
    )
    return (
        f"mailto:{SUPPORT_EMAIL}"
        f"?subject={quote(subject)}"
        f"&body={quote(body)}"
    )

_ASSETS = Path(__file__).resolve().parent / "assets"


def asset(name: str) -> Path:
    return _ASSETS / name


def splash_path() -> Path | None:
    p = asset("splash.png")
    return p if p.is_file() else None


def icon_path() -> Path | None:
    for name in ("llama-logo.png", "icon.png"):
        p = asset(name)
        if p.is_file():
            return p
    return None


def studio_logo_path() -> Path | None:
    p = asset("gnomad-studio-logo.png")
    return p if p.is_file() else None


def llama_logo_path() -> Path | None:
    p = asset("llama-logo.png")
    return p if p.is_file() else None


def install_gesture_path() -> Path | None:
    p = asset("install-gesture.png")
    return p if p.is_file() else None
