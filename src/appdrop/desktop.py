"""Create and update FreeDesktop .desktop launchers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import config


def write_desktop_entry(
    *,
    app_id: str,
    name: str,
    exec_path: Path,
    icon: str | Path | None = None,
    comment: str = "",
    categories: str = "Utility;",
    terminal: bool = False,
    path_cwd: Path | None = None,
) -> Path:
    config.DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    desktop_path = config.DESKTOP_DIR / f"{app_id}.desktop"

    icon_value = ""
    if icon is not None:
        icon_p = Path(icon)
        if icon_p.is_file():
            config.ICON_DIR.mkdir(parents=True, exist_ok=True)
            dest = config.ICON_DIR / f"{app_id}{icon_p.suffix.lower()}"
            shutil.copy2(icon_p, dest)
            icon_value = str(dest)
        else:
            icon_value = str(icon)

    # Quote Exec for paths with spaces
    exec_str = str(exec_path)
    if any(c in exec_str for c in " \t\"'\\"):
        exec_str = f'"{exec_str}"'

    lines = [
        "[Desktop Entry]",
        "Version=1.0",
        f"Type=Application",
        f"Name={name}",
        f"Exec={exec_str}",
        "TryExec=" + str(exec_path),
        f"Terminal={'true' if terminal else 'false'}",
        "StartupNotify=true",
        f"Categories={categories}",
        "X-Gnomad AppDrop=true",
    ]
    if comment:
        lines.append(f"Comment={comment}")
    if icon_value:
        lines.append(f"Icon={icon_value}")
    if path_cwd is not None:
        lines.append(f"Path={path_cwd}")

    desktop_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    desktop_path.chmod(0o755)
    refresh_desktop_database()
    return desktop_path


def adopt_bundled_desktop(
    src: Path,
    *,
    app_id: str,
    exec_path: Path,
    install_root: Path,
) -> Path:
    """Copy a vendor .desktop and rewrite Exec/Icon to absolute install paths."""
    config.DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.DESKTOP_DIR / f"{app_id}.desktop"
    text = src.read_text(encoding="utf-8", errors="replace")
    out: list[str] = []
    for line in text.splitlines():
        if line.startswith("Exec="):
            # Keep args after binary if present
            rest = line[5:].strip()
            # Common pattern: Exec=app %u  or  Exec=./AppRun
            parts = rest.split()
            args = parts[1:] if parts else []
            exec_str = str(exec_path)
            if any(c in exec_str for c in " \t\"'\\"):
                exec_str = f'"{exec_str}"'
            out.append("Exec=" + " ".join([exec_str, *args]))
        elif line.startswith("Icon="):
            icon_val = line[5:].strip()
            icon_path = Path(icon_val)
            if not icon_path.is_file():
                # Relative to bundle
                candidate = install_root / icon_val
                if not candidate.is_file():
                    candidate = src.parent / icon_val
                if candidate.is_file():
                    config.ICON_DIR.mkdir(parents=True, exist_ok=True)
                    copied = config.ICON_DIR / f"{app_id}{candidate.suffix.lower()}"
                    shutil.copy2(candidate, copied)
                    out.append(f"Icon={copied}")
                else:
                    out.append(line)
            else:
                out.append(line)
        else:
            out.append(line)
    if not any(l.startswith("X-Gnomad AppDrop=") for l in out):
        out.append("X-Gnomad AppDrop=true")
    dest.write_text("\n".join(out) + "\n", encoding="utf-8")
    dest.chmod(0o755)
    refresh_desktop_database()
    return dest


def remove_desktop_entry(app_id: str) -> None:
    path = config.DESKTOP_DIR / f"{app_id}.desktop"
    if path.exists():
        path.unlink()
    for icon in config.ICON_DIR.glob(f"{app_id}.*"):
        icon.unlink(missing_ok=True)
    refresh_desktop_database()


def refresh_desktop_database() -> None:
    exe = shutil.which("update-desktop-database")
    if not exe:
        return
    try:
        subprocess.run(
            [exe, str(config.DESKTOP_DIR)],
            check=False,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        pass
