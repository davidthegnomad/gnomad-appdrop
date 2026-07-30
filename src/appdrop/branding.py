"""Gnomad Studio branding constants and asset paths."""

from __future__ import annotations

from pathlib import Path

STUDIO_NAME = "Gnomad Studio"
STUDIO_URL = "https://gnomadstudio.org"
SITE_URL = "https://davidcole.cloud"
APP_PAGE_URL = f"{SITE_URL}/apps/appdrop"
DOWNLOAD_URL = f"{SITE_URL}/apps/appdrop/download"
GITHUB_URL = "https://github.com/davidthegnomad/gnomad-appdrop"
PRODUCT_NAME = "Gnomad AppDrop"

_ASSETS = Path(__file__).resolve().parent / "assets"


def asset(name: str) -> Path:
    return _ASSETS / name


def splash_path() -> Path | None:
    p = asset("splash.png")
    return p if p.is_file() else None


def icon_path() -> Path | None:
    p = asset("icon.png")
    return p if p.is_file() else None


def studio_logo_path() -> Path | None:
    p = asset("gnomad-studio-logo.png")
    return p if p.is_file() else None
