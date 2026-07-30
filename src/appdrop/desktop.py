"""Create and update FreeDesktop .desktop launchers."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from . import config

# Only these keys may be copied from a vendor .desktop (no Actions / D-Bus / autostart).
_ALLOWED_DESKTOP_KEYS = frozenset(
    {
        "Type",
        "Version",
        "Name",
        "GenericName",
        "Comment",
        "Icon",
        "Exec",
        "TryExec",
        "Path",
        "Terminal",
        "StartupNotify",
        "StartupWMClass",
        "Categories",
        "Keywords",
    }
)

_FIELD_CODE = re.compile(r"%[fFuUdDnNickvm]")


def quote_desktop_exec(path: Path | str) -> str:
    """Escape a binary path for a FreeDesktop Exec= value (one argv token)."""
    s = str(path)
    # Spec: backslash-escape \, ", `, $, and wrap in double quotes when needed.
    if not any(c in s for c in ' \t"\'\\`$'):
        return s
    escaped = (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    return f'"{escaped}"'


def _sanitize_exec_args(args: list[str]) -> list[str]:
    """Keep only safe field codes / simple args — drop shell-looking tokens."""
    safe: list[str] = []
    for arg in args:
        if _FIELD_CODE.fullmatch(arg):
            safe.append(arg)
            continue
        if any(c in arg for c in ";|&`$(){}<>\n"):
            continue
        if arg.startswith("-") or arg.startswith("%") or re.fullmatch(r"[\w./:@+-]+", arg):
            safe.append(arg)
    return safe


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
        if icon_p.is_file() and not icon_p.is_symlink():
            config.ICON_DIR.mkdir(parents=True, exist_ok=True)
            dest = config.ICON_DIR / f"{app_id}{icon_p.suffix.lower()}"
            shutil.copy2(icon_p, dest)
            icon_value = str(dest)
        elif not icon_p.is_file():
            # Theme icon name — strip unsafe chars
            icon_value = re.sub(r"[^\w.+\-]", "", str(icon))

    exec_str = quote_desktop_exec(exec_path)

    lines = [
        "[Desktop Entry]",
        "Version=1.0",
        "Type=Application",
        f"Name={name}",
        f"Exec={exec_str}",
        f"TryExec={exec_path}",
        f"Terminal={'true' if terminal else 'false'}",
        "StartupNotify=true",
        f"Categories={categories}",
        "X-Gnomad-AppDrop=true",
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
    """Build a launcher from vendor metadata with an allowlisted key set."""
    config.DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.DESKTOP_DIR / f"{app_id}.desktop"
    text = src.read_text(encoding="utf-8", errors="replace")

    # Only parse the primary [Desktop Entry] group
    in_entry = False
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_entry = line == "[Desktop Entry]"
            continue
        if not in_entry or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key in _ALLOWED_DESKTOP_KEYS:
            fields[key] = val.strip()

    # Force trusted Exec / TryExec
    args: list[str] = []
    if "Exec" in fields:
        parts = fields["Exec"].split()
        args = _sanitize_exec_args(parts[1:] if parts else [])
    exec_line = " ".join([quote_desktop_exec(exec_path), *args]).strip()

    icon_value = ""
    if "Icon" in fields:
        icon_val = fields["Icon"]
        icon_path = Path(icon_val)
        candidates = []
        if icon_path.is_file() and not icon_path.is_symlink():
            candidates.append(icon_path)
        else:
            for c in (install_root / icon_val, src.parent / icon_val):
                if c.is_file() and not c.is_symlink():
                    candidates.append(c)
                    break
        if candidates:
            config.ICON_DIR.mkdir(parents=True, exist_ok=True)
            copied = config.ICON_DIR / f"{app_id}{candidates[0].suffix.lower()}"
            shutil.copy2(candidates[0], copied)
            icon_value = str(copied)
        else:
            icon_value = re.sub(r"[^\w.+\-]", "", icon_val)

    out = [
        "[Desktop Entry]",
        "Version=" + fields.get("Version", "1.0"),
        "Type=Application",
        f"Name={fields.get('Name', app_id)}",
        f"Exec={exec_line}",
        f"TryExec={exec_path}",
        f"Terminal={fields.get('Terminal', 'false')}",
        f"StartupNotify={fields.get('StartupNotify', 'true')}",
        f"Categories={fields.get('Categories', 'Utility;')}",
        "X-Gnomad-AppDrop=true",
    ]
    for key in ("GenericName", "Comment", "Keywords", "StartupWMClass", "Path"):
        if key in fields and fields[key]:
            # Path= must stay inside install root if absolute
            if key == "Path":
                p = Path(fields[key])
                if p.is_absolute() and not str(p.resolve()).startswith(
                    str(install_root.resolve())
                ):
                    continue
            out.append(f"{key}={fields[key]}")
    if icon_value:
        out.append(f"Icon={icon_value}")
    # Intentionally omit MimeType from vendor files to avoid hijacking associations
    # unless we want it later as an opt-in.

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
