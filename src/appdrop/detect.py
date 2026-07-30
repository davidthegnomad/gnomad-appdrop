"""Detect main executable, icons, and bundled .desktop files."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from .config import PREFERRED_EXEC_NAMES, SKIP_EXEC_NAMES

ICON_GLOBS = ("*.png", "*.svg", "*.xpm", "*.ico", "*.jpg", "*.jpeg")
DESKTOP_GLOB = "*.desktop"

# ELF magic / shebang — treat as runnable even without +x set
_ELF = b"\x7fELF"
_SCRIPT = b"#!"


def is_probably_executable(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        # Follow only if target exists and is a file
        if path.is_symlink():
            try:
                target = path.resolve(strict=True)
            except (OSError, RuntimeError):
                return False
            if not target.is_file():
                return False
            path = target
        else:
            return False

    name = path.name.lower()
    if name.endswith(
        (".so", ".so.1", ".dll", ".dylib", ".o", ".a", ".la", ".pyc")
    ):
        return False
    if name in SKIP_EXEC_NAMES:
        return False
    if name.startswith("lib") and ".so" in name:
        return False

    mode = path.stat().st_mode
    if mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
        return True

    # Some tarballs ship binaries without +x
    try:
        with path.open("rb") as fh:
            head = fh.read(4)
    except OSError:
        return False
    return head.startswith(_ELF) or head.startswith(_SCRIPT)


def find_desktop_files(root: Path) -> list[Path]:
    return sorted(root.rglob(DESKTOP_GLOB))


def find_icons(root: Path) -> list[Path]:
    icons: list[Path] = []
    for pattern in ICON_GLOBS:
        icons.extend(root.rglob(pattern))
    # Prefer larger / named icons roughly by path depth then name
    def score(p: Path) -> tuple:
        n = p.name.lower()
        size_hint = 0
        m = re.search(r"(\d{2,4})", str(p))
        if m:
            size_hint = int(m.group(1))
        preferred = any(
            key in n for key in ("icon", "logo", "app", "brand")
        )
        return (-int(preferred), -size_hint, len(p.parts), n)

    return sorted(set(icons), key=score)


def find_executables(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("*"):
        if is_probably_executable(path):
            found.append(path)
    return found


def choose_main_executable(
    root: Path,
    app_name: str,
    candidates: list[Path] | None = None,
) -> Path | None:
    if candidates is None:
        candidates = find_executables(root)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    app_l = app_name.lower().replace(" ", "").replace("-", "").replace("_", "")
    scored: list[tuple[int, Path]] = []

    for path in candidates:
        score = 0
        name = path.name.lower()
        stem = path.stem.lower()
        rel = str(path.relative_to(root)).lower()

        if name == "apprun":
            score += 100
        if stem.replace("-", "").replace("_", "") == app_l:
            score += 80
        if app_l and app_l in stem.replace("-", "").replace("_", ""):
            score += 40
        if name in PREFERRED_EXEC_NAMES:
            score += 50
        if path.parent == root or path.parent.name.lower() in {"bin", "usr"}:
            score += 20
        if "/bin/" in f"/{rel}/":
            score += 15
        # Penalize deep helper trees
        score -= max(0, len(path.relative_to(root).parts) - 3) * 5
        if "helper" in rel or "crash" in rel or "plugin" in rel:
            score -= 40
        scored.append((score, path))

    scored.sort(key=lambda t: (-t[0], str(t[1])))
    return scored[0][1]


def ensure_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def sanitize_app_id(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9._+-]+", "-", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name or "app"
