"""Probe package metadata so installs get real app names, not archive filenames."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import debpkg
from .config import (
    APPIMAGE_SUFFIXES,
    ARCHIVE_SUFFIXES,
    DEB_SUFFIXES,
    SKIP_EXEC_NAMES,
    SUPPORTED_SUFFIXES,
)
from .detect import sanitize_app_id

log = logging.getLogger("appdrop.metadata")

# Higher wins when merging probe results.
# well-known beats bare exec so tsetup → "Telegram Desktop" (not just "Telegram").
_SOURCE_PRIORITY = {
    "desktop": 50,
    "deb-control": 40,
    "well-known": 35,
    "exec": 30,
    "filename": 10,
}

_NON_EXEC_SUFFIXES = frozenset(
    {
        ".txt",
        ".md",
        ".rst",
        ".html",
        ".htm",
        ".xml",
        ".json",
        ".yml",
        ".yaml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".desktop",
        ".png",
        ".svg",
        ".jpg",
        ".jpeg",
        ".ico",
        ".xpm",
        ".gif",
        ".webp",
        ".bmp",
        ".so",
        ".a",
        ".o",
        ".la",
        ".dll",
        ".dylib",
        ".pyc",
        ".py",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".java",
        ".go",
        ".rs",
        ".ts",
        ".js",
        ".css",
        ".scss",
        ".map",
        ".pak",
        ".dat",
        ".db",
        ".sqlite",
        ".zip",
        ".gz",
        ".xz",
        ".bz2",
        ".7z",
        ".deb",
        ".rpm",
        ".dmg",
        ".appimage",
        ".sha256",
        ".asc",
        ".sig",
        ".license",
        ".licence",
    }
)

# Filename patterns when vendors ship installer-style names (tsetup, etc.).
_WELL_KNOWN: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"^tsetup([._-]|$)", re.I), "Telegram Desktop", "telegram-desktop"),
    (re.compile(r"^telegram([._-]|$)", re.I), "Telegram Desktop", "telegram-desktop"),
    (re.compile(r"^discord([._-]|$)", re.I), "Discord", "discord"),
    (re.compile(r"^blender([._-]|$)", re.I), "Blender", "blender"),
    (re.compile(r"^godot([._-]|$)", re.I), "Godot Engine", "godot"),
    (re.compile(r"^go\d+\.", re.I), "Go", "go"),
    (re.compile(r"^node[-v]", re.I), "Node.js", "nodejs"),
    (re.compile(r"^firefox[-.]", re.I), "Firefox", "firefox"),
    (re.compile(r"^thunderbird[-.]", re.I), "Thunderbird", "thunderbird"),
    (re.compile(r"^libreoffice", re.I), "LibreOffice", "libreoffice"),
    (re.compile(r"^google[-_]?chrome", re.I), "Google Chrome", "google-chrome"),
    (re.compile(r"^chromium", re.I), "Chromium", "chromium"),
    (re.compile(r"^code[-_.]", re.I), "Visual Studio Code", "code"),
    (re.compile(r"^obs[-_.]", re.I), "OBS Studio", "obs-studio"),
)


@dataclass
class AppIdentity:
    """Best-effort identity for an installable package."""

    app_id: str
    name: str
    source: str = "filename"
    comment: str = ""
    categories: str = "Utility;"
    keywords: str = ""
    icon_hint: str = ""
    exec_hint: str = ""
    extras: dict[str, str] = field(default_factory=dict)


def _strip_known_suffix(name: str) -> str:
    lower = name.lower()
    for suffix in sorted(SUPPORTED_SUFFIXES, key=len, reverse=True):
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def _strip_version_tokens(base: str) -> str:
    """Drop trailing version-ish tokens: foo-1.2.3, app_1.2.3-1_amd64."""
    # Also strip common arch/os suffixes before version trim.
    cleaned = re.sub(
        r"(?i)([._-])(linux|ubuntu|debian|fedora|nobara|x86_64|amd64|arm64|"
        r"aarch64|x64|i386|i686|current)(\b|$)",
        "",
        base,
    )
    parts = cleaned.replace("_", "-").split("-")
    kept: list[str] = []
    for part in parts:
        if not part:
            continue
        if part[0].isdigit() and any(c.isdigit() for c in part) and kept:
            break
        # Pure arch leftovers
        if part.lower() in {"x86", "64", "32"}:
            continue
        kept.append(part)
    return "-".join(kept) if kept else base


def display_name_from_raw(raw: str, *, app_id: str = "") -> str:
    base = _strip_version_tokens(_strip_known_suffix(raw))
    pretty = base.replace("-", " ").replace("_", " ").strip()
    pretty = re.sub(r"\s+", " ", pretty)
    if not pretty:
        pretty = app_id or "App"
    # Preserve known acronyms lightly
    titled = pretty.title()
    for token, fix in (
        ("Js", "JS"),
        ("Id", "ID"),
        ("Io", "IO"),
        ("Api", "API"),
        ("Vpn", "VPN"),
        ("Sdk", "SDK"),
        ("Cli", "CLI"),
        ("Gpu", "GPU"),
        ("Cpu", "CPU"),
        ("Ai", "AI"),
    ):
        titled = re.sub(rf"\b{token}\b", fix, titled)
    return titled


def pretty_exec_name(exec_name: str) -> str:
    """Human label from a binary basename (Telegram → Telegram, go → Go)."""
    stem = Path(exec_name).stem or exec_name
    if stem.lower() in {"apprun", "run", "launch", "start"}:
        return ""
    if stem.isupper() and len(stem) <= 4:
        return stem
    if stem[0].isupper() and not stem.isupper():
        # Vendor already camel/Title cased (Telegram, LibreOffice)
        return stem.replace("_", " ").replace("-", " ")
    return display_name_from_raw(stem, app_id=sanitize_app_id(stem))


def parse_desktop_text(text: str) -> dict[str, str]:
    """Parse the primary [Desktop Entry] group into a dict."""
    fields: dict[str, str] = {}
    in_entry = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            if fields and in_entry:
                break
            in_entry = line == "[Desktop Entry]"
            continue
        if not in_entry or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        # Prefer untranslated Name= over Name[locale]=
        if "[" in key and key.split("[", 1)[0] in {
            "Name",
            "GenericName",
            "Comment",
            "Keywords",
        }:
            continue
        fields[key] = val.strip()
    return fields


def identity_from_desktop_fields(
    fields: dict[str, str],
    *,
    desktop_basename: str = "",
) -> AppIdentity | None:
    if fields.get("Type", "Application") not in {"", "Application"}:
        return None
    name = fields.get("Name", "").strip()
    if not name:
        return None

    app_id = ""
    if desktop_basename:
        stem = Path(desktop_basename).stem
        if stem and stem.lower() not in {"app", "application", "launcher"}:
            app_id = sanitize_app_id(stem)

    exec_hint = ""
    if fields.get("Exec"):
        token = fields["Exec"].split()[0]
        if token and not token.startswith("%"):
            exec_hint = Path(token).name

    if not app_id and exec_hint:
        app_id = sanitize_app_id(Path(exec_hint).stem)
    if not app_id:
        app_id = sanitize_app_id(name)

    keywords = fields.get("Keywords", "")
    if "telegram" in name.lower() and "telegram" not in keywords.lower():
        keywords = (keywords.rstrip(";") + ";telegram;chat;messaging;").lstrip(";")

    return AppIdentity(
        app_id=app_id,
        name=name,
        source="desktop",
        comment=fields.get("Comment", ""),
        categories=fields.get("Categories", "Utility;") or "Utility;",
        keywords=keywords,
        icon_hint=fields.get("Icon", ""),
        exec_hint=exec_hint,
    )


def _merge(base: AppIdentity, override: AppIdentity | None) -> AppIdentity:
    if override is None:
        return base
    if _SOURCE_PRIORITY.get(override.source, 0) < _SOURCE_PRIORITY.get(base.source, 0):
        # Keep higher-priority fields; fill gaps from lower
        return AppIdentity(
            app_id=base.app_id or override.app_id,
            name=base.name or override.name,
            source=base.source,
            comment=base.comment or override.comment,
            categories=base.categories if base.categories != "Utility;" else override.categories,
            keywords=base.keywords or override.keywords,
            icon_hint=base.icon_hint or override.icon_hint,
            exec_hint=base.exec_hint or override.exec_hint,
        )
    return AppIdentity(
        app_id=override.app_id or base.app_id,
        name=override.name or base.name,
        source=override.source,
        comment=override.comment or base.comment,
        categories=override.categories or base.categories,
        keywords=override.keywords or base.keywords,
        icon_hint=override.icon_hint or base.icon_hint,
        exec_hint=override.exec_hint or base.exec_hint,
    )


def _well_known_from_filename(filename: str) -> AppIdentity | None:
    stem = _strip_known_suffix(filename)
    for pattern, name, app_id in _WELL_KNOWN:
        if pattern.search(stem) or pattern.search(filename):
            return AppIdentity(app_id=app_id, name=name, source="well-known")
    return None


def _filename_identity(filename: str) -> AppIdentity:
    stripped = _strip_version_tokens(_strip_known_suffix(filename))
    app_id = sanitize_app_id(stripped)
    return AppIdentity(
        app_id=app_id,
        name=display_name_from_raw(filename, app_id=app_id),
        source="filename",
    )


def _score_archive_member(name: str) -> int:
    """Heuristic score for a path that might be the main binary (no extract)."""
    path = name.replace("\\", "/").rstrip("/")
    if not path or path.endswith("/"):
        return -10_000
    base = Path(path).name
    lower = base.lower()
    stem = Path(base).stem.lower()
    if lower in SKIP_EXEC_NAMES or stem in SKIP_EXEC_NAMES:
        return -10_000
    suffix = Path(base).suffix.lower()
    if suffix in _NON_EXEC_SUFFIXES:
        return -10_000
    if lower.startswith(".") or lower.endswith("~"):
        return -10_000

    score = 0
    parts = [p for p in path.split("/") if p and p != "."]
    if lower == "apprun":
        score += 100
    if len(parts) >= 2 and parts[-1].lower() == parts[-2].lower():
        # Telegram/Telegram, Blender/blender
        score += 80
    if len(parts) >= 2 and parts[-2].lower() in {"bin", "usr"}:
        score += 40
    if "/bin/" in f"/{path.lower()}/":
        score += 25
    # Prefer shallow trees
    score -= max(0, len(parts) - 2) * 8
    if any(x in path.lower() for x in ("helper", "crash", "plugin", "resources/")):
        score -= 50
    if lower in {"ffmpeg", "ffprobe", "curl", "wget", "python", "python3", "node"}:
        score -= 40
    # Prefer names with letters (skip bare version dirs leaking through)
    if any(c.isalpha() for c in base):
        score += 10
    return score


def _identity_from_member_names(names: list[str]) -> AppIdentity | None:
    scored: list[tuple[int, str]] = []
    for name in names:
        score = _score_archive_member(name)
        if score > 0:
            scored.append((score, name.replace("\\", "/")))
    if not scored:
        return None
    scored.sort(key=lambda t: (-t[0], t[1]))
    best = Path(scored[0][1]).name
    pretty = pretty_exec_name(best)
    if not pretty:
        return None
    return AppIdentity(
        app_id=sanitize_app_id(Path(best).stem),
        name=pretty,
        source="exec",
        exec_hint=best,
    )


def _probe_desktop_from_tar(tar: tarfile.TarFile) -> AppIdentity | None:
    desktops: list[tarfile.TarInfo] = []
    for member in tar.getmembers():
        if not member.isfile():
            continue
        name = member.name.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            continue
        if Path(name).name.endswith(".desktop") and "/." not in f"/{name}/":
            # Prefer applications/ paths
            desktops.append(member)
    if not desktops:
        return None

    def desk_key(m: tarfile.TarInfo) -> tuple:
        n = m.name.lower().replace("\\", "/")
        return (
            0 if "/applications/" in n else 1,
            0 if n.endswith(".desktop") else 1,
            len(n),
            n,
        )

    for member in sorted(desktops, key=desk_key):
        handle = tar.extractfile(member)
        if handle is None:
            continue
        try:
            text = handle.read(256_000).decode("utf-8", errors="replace")
        except OSError:
            continue
        fields = parse_desktop_text(text)
        ident = identity_from_desktop_fields(
            fields, desktop_basename=Path(member.name).name
        )
        if ident:
            return ident
    return None


def probe_archive(path: Path) -> AppIdentity | None:
    lower = path.name.lower()
    try:
        if lower.endswith(".zip"):
            with zipfile.ZipFile(path, "r") as zf:
                names = zf.namelist()
                # Desktop files first
                desk_names = [
                    n
                    for n in names
                    if n.replace("\\", "/").rstrip("/").endswith(".desktop")
                    and not n.endswith("/")
                ]
                desk_names.sort(
                    key=lambda n: (
                        0 if "/applications/" in n.lower() else 1,
                        len(n),
                        n.lower(),
                    )
                )
                for name in desk_names:
                    try:
                        text = zf.read(name).decode("utf-8", errors="replace")
                    except (OSError, KeyError, zipfile.BadZipFile):
                        continue
                    ident = identity_from_desktop_fields(
                        parse_desktop_text(text),
                        desktop_basename=Path(name).name,
                    )
                    if ident:
                        return ident
                return _identity_from_member_names(names)
        with tarfile.open(path, "r:*") as tar:
            desktop = _probe_desktop_from_tar(tar)
            if desktop:
                return desktop
            return _identity_from_member_names([m.name for m in tar.getmembers()])
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        log.debug("Archive probe failed for %s: %s", path.name, exc)
        return None


def probe_deb(path: Path) -> AppIdentity | None:
    identity: AppIdentity | None = None
    control = debpkg.read_control(path)
    package = control.get("Package", "").strip()
    if package:
        # Short description = first line before long description join artifacts
        desc = control.get("Description", "").strip()
        short = desc.split("  ")[0].strip() if desc else ""
        # read_control joins continuations with space; short is usually first sentence-ish
        if " " in desc and desc.split()[0:1]:
            # Prefer text before a doubled space or obvious long-desc join
            short = re.split(r"\s{2,}|\s(?=[A-Z][a-z].{20,})", desc, maxsplit=1)[0].strip()
        name = short if short and len(short) < 80 else display_name_from_raw(package)
        identity = AppIdentity(
            app_id=sanitize_app_id(package),
            name=name,
            source="deb-control",
            comment=short or "",
        )

    # Prefer a real .desktop Name inside the payload when present
    try:
        with debpkg.open_data_tar(path) as tar:
            desktop = _probe_desktop_from_tar(tar)
            if desktop:
                identity = _merge(
                    identity
                    or AppIdentity(
                        app_id=desktop.app_id,
                        name=desktop.name,
                        source="filename",
                    ),
                    desktop,
                )
    except (debpkg.DebError, OSError, tarfile.TarError) as exc:
        log.debug("Deb desktop probe failed for %s: %s", path.name, exc)

    return identity


def probe_appimage(path: Path) -> AppIdentity | None:
    """Extract embedded .desktop via AppImage runtime (no full install)."""
    if not path.is_file():
        return None
    # Quick ELF check
    try:
        with path.open("rb") as fh:
            if fh.read(4) != b"\x7fELF":
                return None
    except OSError:
        return None

    with tempfile.TemporaryDirectory(prefix="appdrop-ai-") as tmp:
        work = Path(tmp)
        link = work / "app.AppImage"
        try:
            link.symlink_to(path.resolve())
        except OSError:
            shutil.copy2(path, link)
        try:
            link.chmod(link.stat().st_mode | 0o111)
        except OSError:
            pass

        try:
            subprocess.run(  # noqa: S603
                [str(link), "--appimage-extract", "*.desktop"],
                cwd=work,
                check=False,
                capture_output=True,
                timeout=90,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("AppImage desktop extract failed for %s: %s", path.name, exc)
            # Fallback: extract a little more broadly
            try:
                subprocess.run(  # noqa: S603
                    [str(link), "--appimage-extract"],
                    cwd=work,
                    check=False,
                    capture_output=True,
                    timeout=120,
                )
            except (OSError, subprocess.SubprocessError) as exc2:
                log.debug("AppImage full extract failed for %s: %s", path.name, exc2)
                return None

        root = work / "squashfs-root"
        if not root.is_dir():
            return None
        desktops = sorted(root.rglob("*.desktop"))
        for desk in desktops:
            if desk.is_symlink() or not desk.is_file():
                continue
            try:
                text = desk.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            ident = identity_from_desktop_fields(
                parse_desktop_text(text), desktop_basename=desk.name
            )
            if ident:
                return ident
    return None


def probe_identity(path: Path) -> AppIdentity:
    """Return the best identity for a package path (safe, read-mostly)."""
    path = path.expanduser().resolve()
    filename = path.name
    lower = filename.lower()

    identity = _filename_identity(filename)
    identity = _merge(identity, _well_known_from_filename(filename))

    try:
        if any(lower.endswith(s) for s in DEB_SUFFIXES):
            identity = _merge(identity, probe_deb(path))
        elif any(lower.endswith(s) for s in APPIMAGE_SUFFIXES):
            identity = _merge(identity, probe_appimage(path))
        elif any(lower.endswith(s) for s in ARCHIVE_SUFFIXES):
            identity = _merge(identity, probe_archive(path))
    except Exception as exc:  # noqa: BLE001 — probe must never block install
        log.debug("Identity probe failed for %s: %s", filename, exc)

    # Ensure keywords help menu search for common apps
    if identity.name and not identity.keywords:
        words = re.findall(r"[A-Za-z0-9]+", identity.name)
        if words:
            identity.keywords = ";".join(w.lower() for w in words) + ";"

    return identity


def read_desktop_name(desktop_path: Path) -> str | None:
    try:
        fields = parse_desktop_text(
            desktop_path.read_text(encoding="utf-8", errors="replace")
        )
    except OSError:
        return None
    name = fields.get("Name", "").strip()
    return name or None
