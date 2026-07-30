"""Watch ~/Applications and auto-install dropped archives / AppImages."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from . import config
from .config import ensure_dirs
from .install import InstallError, InstallResult, install_path, is_supported

log = logging.getLogger("appdrop.watcher")

NotifyFn = Callable[[str, str], None]  # title, body


def _file_stable(
    path: Path,
    *,
    settle_seconds: float = 2.5,
    checks: int = 3,
    interval: float = 1.0,
) -> bool:
    """Require size unchanged across several polls and mtime older than settle."""
    try:
        prev = path.stat().st_size
        if prev <= 0:
            return False
    except OSError:
        return False

    for _ in range(checks - 1):
        time.sleep(interval)
        try:
            st = path.stat()
        except OSError:
            return False
        if st.st_size != prev or st.st_size <= 0:
            return False
        prev = st.st_size

    try:
        st = path.stat()
    except OSError:
        return False
    # Also require the file hasn't been written recently
    if (time.time() - st.st_mtime) < settle_seconds:
        return False
    return st.st_size > 0


def watch(
    directory: Path | None = None,
    *,
    poll_interval: float = 2.0,
    move_source: bool = True,
    notify: NotifyFn | None = None,
    stop_flag: Callable[[], bool] | None = None,
) -> None:
    directory = directory or config.APPLICATIONS_DIR
    ensure_dirs()
    seen: set[str] = set()
    pending_stable: dict[str, int] = {}
    # Ignore files already present at startup unless they're new drops
    for path in directory.iterdir():
        if path.is_file():
            seen.add(path.name)

    log.info("Watching %s for archives and AppImages", directory)
    if notify:
        notify("Gnomad AppDrop", f"Watching {directory}")

    while True:
        if stop_flag and stop_flag():
            break
        try:
            names = {p.name for p in directory.iterdir() if p.is_file()}
        except OSError as exc:
            log.warning("Cannot read %s: %s", directory, exc)
            time.sleep(poll_interval)
            continue

        for name in sorted(names - seen):
            path = directory / name
            if name.endswith((".part", ".crdownload", ".download", ".tmp")):
                continue
            if not is_supported(path):
                seen.add(name)
                continue
            if not _file_stable(path):
                # Don't mark seen yet — retry next poll
                pending_stable[name] = pending_stable.get(name, 0) + 1
                if pending_stable[name] > 120:
                    # Give up after ~4 min of instability
                    log.warning("Giving up on unstable file: %s", name)
                    seen.add(name)
                    pending_stable.pop(name, None)
                continue
            pending_stable.pop(name, None)
            try:
                result = install_path(path, move_source=move_source)
                _announce(result, notify)
                log.info("Installed %s → %s", result.name, result.exec_path)
            except InstallError as exc:
                log.error("%s", exc)
                if notify:
                    notify("Gnomad AppDrop install failed", str(exc))
            except Exception as exc:  # noqa: BLE001
                log.exception("Unexpected error installing %s", name)
                if notify:
                    notify("Gnomad AppDrop error", f"{name}: {exc}")
            seen.add(name)

        # Allow re-drop of same filename later
        seen &= names
        pending_stable = {k: v for k, v in pending_stable.items() if k in names}
        # If move_source removed the file, drop from seen so a new copy can install
        seen = {n for n in seen if (directory / n).exists() or n in names}

        time.sleep(poll_interval)


def _announce(result: InstallResult, notify: NotifyFn | None) -> None:
    msg = f"{result.name} is ready in your app menu"
    if notify:
        notify("Gnomad AppDrop installed", msg)
    else:
        _desktop_notify("Gnomad AppDrop installed", msg)


def _desktop_notify(title: str, body: str) -> None:
    import shutil
    import subprocess

    if shutil.which("notify-send"):
        try:
            subprocess.run(
                ["notify-send", "-a", "Gnomad AppDrop", title, body],
                check=False,
                capture_output=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            pass
