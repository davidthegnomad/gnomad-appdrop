"""Install archives and AppImages into ~/.local/opt and register launchers."""

from __future__ import annotations

import json
import logging
import os
import shutil
import stat
import tarfile
import threading
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .config import (
    APPIMAGE_SUFFIXES,
    ARCHIVE_SUFFIXES,
    SUPPORTED_SUFFIXES,
    ensure_dirs,
)
from .desktop import adopt_bundled_desktop, remove_desktop_entry, write_desktop_entry
from .detect import (
    choose_main_executable,
    ensure_executable,
    exec_hint_from_desktop,
    find_desktop_files,
    find_executables,
    find_icons,
    sanitize_app_id,
)

log = logging.getLogger("appdrop.install")

_REGISTRY_LOCK = threading.Lock()


@dataclass
class InstallResult:
    app_id: str
    name: str
    source: str
    install_dir: str
    exec_path: str
    desktop_path: str
    kind: str  # archive | appimage
    installed_at: str


class InstallError(Exception):
    pass


def _strip_known_suffix(name: str) -> str:
    lower = name.lower()
    for suffix in sorted(SUPPORTED_SUFFIXES, key=len, reverse=True):
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def _display_name(app_id: str, raw: str) -> str:
    base = _strip_known_suffix(raw)
    # Drop trailing version-ish bits: foo-1.2.3
    parts = base.replace("_", "-").split("-")
    cleaned: list[str] = []
    for part in parts:
        if part and part[0].isdigit() and any(c.isdigit() for c in part):
            # stop at first version-looking token if we already have a name
            if cleaned:
                break
        cleaned.append(part)
    pretty = " ".join(cleaned) if cleaned else app_id
    return pretty.replace("-", " ").title()


def _within_dest(path: Path, dest: Path) -> bool:
    try:
        path.relative_to(dest)
        return True
    except ValueError:
        return False


def _safe_extract_tar(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract tar members without symlinks, devices, or path escape."""
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    for member in tar.getmembers():
        name = member.name.replace("\\", "/")
        if name.startswith("/") or name.startswith("../") or "/../" in f"/{name}/":
            raise InstallError(f"Refusing unsafe tar path: {member.name}")
        if member.issym() or member.islnk():
            raise InstallError(f"Refusing symlink/hardlink in archive: {member.name}")
        if member.isdev() or member.isfifo() or member.ischr() or member.isblk():
            raise InstallError(f"Refusing special file in archive: {member.name}")
        if not (member.isfile() or member.isdir()):
            # Skip unknown types rather than extract them
            raise InstallError(f"Unsupported tar member type: {member.name}")

        target = (dest / name).resolve()
        if not _within_dest(target, dest) and target != dest:
            raise InstallError(f"Refusing unsafe tar path: {member.name}")

        try:
            tar.extract(member, path=dest, set_attrs=False)
        except TypeError:
            # Python < 3.12
            tar.extract(member, path=dest)

        # Drop setuid/setgid if present
        if target.exists() and target.is_file():
            mode = target.stat().st_mode
            if mode & (stat.S_ISUID | stat.S_ISGID):
                target.chmod(mode & ~(stat.S_ISUID | stat.S_ISGID))


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract zip members without path escape or setuid modes."""
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or name.startswith("../") or "/../" in f"/{name}/":
            raise InstallError(f"Refusing unsafe zip path: {info.filename}")

        # Zip external_attr upper 16 bits = Unix mode when present
        mode = (info.external_attr >> 16) & 0o7777
        if mode and stat.S_ISLNK(mode):
            raise InstallError(f"Refusing symlink in zip: {info.filename}")
        if mode & (stat.S_ISUID | stat.S_ISGID):
            raise InstallError(f"Refusing setuid/setgid in zip: {info.filename}")

        target = (dest / name).resolve()
        if not _within_dest(target, dest) and target != dest:
            raise InstallError(f"Refusing unsafe zip path: {info.filename}")

        zf.extract(info, path=dest)

        if target.exists() and target.is_file():
            st = target.stat()
            if st.st_mode & (stat.S_ISUID | stat.S_ISGID):
                target.chmod(st.st_mode & ~(stat.S_ISUID | stat.S_ISGID))


def _unwrap_single_root(install_dir: Path) -> Path:
    """If archive contained one top-level folder, treat that as the app root."""
    entries = [p for p in install_dir.iterdir() if p.name not in {".", ".."}]
    if len(entries) == 1 and entries[0].is_dir() and not entries[0].is_symlink():
        return entries[0]
    return install_dir


def _load_registry() -> dict[str, dict]:
    if not config.REGISTRY_PATH.exists():
        return {}
    try:
        return json.loads(config.REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_registry(data: dict[str, dict]) -> None:
    ensure_dirs()
    # Atomic-ish write to reduce corruption window
    tmp = config.REGISTRY_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, config.REGISTRY_PATH)


def list_installed() -> list[InstallResult]:
    with _REGISTRY_LOCK:
        reg = _load_registry()
    out: list[InstallResult] = []
    for item in reg.values():
        try:
            out.append(InstallResult(**item))
        except TypeError:
            continue
    return sorted(out, key=lambda r: r.name.lower())


def is_supported(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(s) for s in SUPPORTED_SUFFIXES)


def install_path(path: Path, *, move_source: bool = False) -> InstallResult:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise InstallError(f"Not a file: {path}")
    if not is_supported(path):
        raise InstallError(
            f"Unsupported file type: {path.name}. "
            f"Use {', '.join(SUPPORTED_SUFFIXES)}"
        )

    ensure_dirs()
    raw_name = path.name
    app_id = sanitize_app_id(_strip_known_suffix(raw_name))
    name = _display_name(app_id, raw_name)
    lower = raw_name.lower()

    with _REGISTRY_LOCK:
        if any(lower.endswith(s) for s in APPIMAGE_SUFFIXES):
            result = _install_appimage(path, app_id=app_id, name=name)
        elif any(lower.endswith(s) for s in ARCHIVE_SUFFIXES):
            result = _install_archive(path, app_id=app_id, name=name)
        else:
            raise InstallError(f"Unsupported file type: {path.name}")

        reg = _load_registry()
        reg[result.app_id] = asdict(result)
        _save_registry(reg)

    if move_source:
        try:
            path.unlink()
        except OSError:
            pass

    return result


def _install_appimage(path: Path, *, app_id: str, name: str) -> InstallResult:
    install_dir = config.OPT_DIR / app_id
    if install_dir.exists():
        shutil.rmtree(install_dir)
    install_dir.mkdir(parents=True)

    dest = install_dir / path.name
    shutil.copy2(path, dest)
    ensure_executable(dest)

    desktop = write_desktop_entry(
        app_id=app_id,
        name=name,
        exec_path=dest,
        comment=f"Installed by Gnomad AppDrop from {path.name}",
        path_cwd=install_dir,
    )
    return InstallResult(
        app_id=app_id,
        name=name,
        source=str(path),
        install_dir=str(install_dir),
        exec_path=str(dest),
        desktop_path=str(desktop),
        kind="appimage",
        installed_at=datetime.now(timezone.utc).isoformat(),
    )


def _install_archive(path: Path, *, app_id: str, name: str) -> InstallResult:
    install_dir = config.OPT_DIR / app_id
    if install_dir.exists():
        shutil.rmtree(install_dir)
    install_dir.mkdir(parents=True)

    lower = path.name.lower()
    if lower.endswith(".zip"):
        with zipfile.ZipFile(path, "r") as zf:
            _safe_extract_zip(zf, install_dir)
    else:
        with tarfile.open(path, "r:*") as tar:
            _safe_extract_tar(tar, install_dir)

    root = _unwrap_single_root(install_dir)
    bundled = find_desktop_files(root)
    hint = exec_hint_from_desktop(bundled[0], root) if bundled else None
    executables = find_executables(root)
    main = choose_main_executable(
        root, app_id, executables, preferred_name=hint
    )
    if main is None:
        shutil.rmtree(install_dir, ignore_errors=True)
        raise InstallError(
            f"No runnable binary found in {path.name}. "
            "This may be source code (needs compile) rather than a prebuilt app."
        )

    ensure_executable(main)
    icons = find_icons(root)
    icon = icons[0] if icons else None

    if bundled:
        desktop = adopt_bundled_desktop(
            bundled[0],
            app_id=app_id,
            exec_path=main,
            install_root=root,
        )
    else:
        desktop = write_desktop_entry(
            app_id=app_id,
            name=name,
            exec_path=main,
            icon=icon,
            comment=f"Installed by Gnomad AppDrop from {path.name}",
            path_cwd=main.parent,
        )

    return InstallResult(
        app_id=app_id,
        name=name,
        source=str(path),
        install_dir=str(install_dir),
        exec_path=str(main),
        desktop_path=str(desktop),
        kind="archive",
        installed_at=datetime.now(timezone.utc).isoformat(),
    )


def uninstall(app_id: str) -> None:
    app_id = sanitize_app_id(app_id)
    with _REGISTRY_LOCK:
        reg = _load_registry()
        entry = reg.pop(app_id, None)
        remove_desktop_entry(app_id)
        install_dir = config.OPT_DIR / app_id
        if entry and entry.get("install_dir"):
            install_dir = Path(entry["install_dir"])
        if install_dir.exists():
            try:
                shutil.rmtree(install_dir)
            except OSError as exc:
                log.warning(
                    "Could not fully remove %s: %s (some files may remain)",
                    install_dir,
                    exc,
                )
        _save_registry(reg)


def process_drop_dir(
    directory: Path | None = None,
    *,
    move_source: bool = True,
) -> list[InstallResult | Exception]:
    """Install every supported file sitting in the Applications drop folder."""
    directory = directory or config.APPLICATIONS_DIR
    ensure_dirs()
    results: list[InstallResult | Exception] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or not is_supported(path):
            continue
        # Skip partially-copied downloads
        if path.name.endswith((".part", ".crdownload", ".download", ".tmp")):
            continue
        try:
            results.append(install_path(path, move_source=move_source))
        except Exception as exc:  # noqa: BLE001 — collect per-file errors
            results.append(exc)
    return results
