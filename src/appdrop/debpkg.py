"""Read Debian .deb packages (ar container) using the standard library."""

from __future__ import annotations

import contextlib
import logging
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator
from pathlib import Path

log = logging.getLogger("appdrop.debpkg")

AR_MAGIC = b"!<arch>\n"
_HEADER_SIZE = 60
_CHUNK = 1 << 20


class DebError(Exception):
    pass


def is_deb(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(8) == AR_MAGIC
    except OSError:
        return False


def _iter_members(fh) -> Iterator[tuple[str, int, int]]:
    """Yield (name, data_offset, size) for each ar member."""
    if fh.read(8) != AR_MAGIC:
        raise DebError("Not a Debian package (missing ar signature)")
    while True:
        header = fh.read(_HEADER_SIZE)
        if not header:
            return
        if len(header) < _HEADER_SIZE:
            raise DebError("Truncated Debian package header")
        if header[58:60] != b"`\n":
            raise DebError("Corrupt Debian package header")
        name = header[0:16].decode("ascii", "replace").strip().rstrip("/")
        try:
            size = int(header[48:58].decode("ascii", "replace").strip())
        except ValueError as exc:
            raise DebError("Bad member size in Debian package") from exc
        if size < 0:
            raise DebError("Negative member size in Debian package")
        offset = fh.tell()
        yield name, offset, size
        fh.seek(offset + size + (size % 2))


def _extract_member(path: Path, prefix: str, workdir: Path) -> tuple[Path, str]:
    with path.open("rb") as fh:
        for name, offset, size in _iter_members(fh):
            if not name.startswith(prefix):
                continue
            fh.seek(offset)
            out = workdir / Path(name).name
            remaining = size
            with out.open("wb") as dst:
                while remaining:
                    chunk = fh.read(min(_CHUNK, remaining))
                    if not chunk:
                        raise DebError(f"Truncated {name} in Debian package")
                    dst.write(chunk)
                    remaining -= len(chunk)
            return out, name
    raise DebError(f"No {prefix}* member in Debian package")


def _decompress(member_name: str, raw: Path, workdir: Path) -> Path:
    """tarfile reads gz/xz/bz2 directly; zstd needs stdlib 3.14+ or the CLI."""
    if not member_name.endswith(".zst"):
        return raw

    out = workdir / "decompressed.tar"
    try:
        from compression.zstd import ZstdFile
    except ImportError:
        ZstdFile = None

    if ZstdFile is not None:
        with ZstdFile(raw, "rb") as src, out.open("wb") as dst:
            shutil.copyfileobj(src, dst, _CHUNK)
        return out

    zstd = shutil.which("zstd")
    if not zstd:
        raise DebError(
            "This .deb uses zstd compression — install the 'zstd' package "
            "(sudo dnf install zstd) and try again"
        )
    try:
        subprocess.run(  # noqa: S603
            [zstd, "-d", "-q", "-f", "-o", str(out), str(raw)],
            check=True,
            capture_output=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DebError(f"Could not decompress zstd data: {exc}") from exc
    return out


@contextlib.contextmanager
def open_data_tar(path: Path) -> Iterator[tarfile.TarFile]:
    """Yield the package payload (data.tar.*) as an open TarFile."""
    with tempfile.TemporaryDirectory(prefix="appdrop-deb-") as tmp:
        workdir = Path(tmp)
        raw, member_name = _extract_member(path, "data.tar", workdir)
        tar_path = _decompress(member_name, raw, workdir)
        try:
            with tarfile.open(tar_path, "r:*") as tar:
                yield tar
        except tarfile.TarError as exc:
            raise DebError(f"Unreadable package payload: {exc}") from exc


def read_control(path: Path) -> dict[str, str]:
    """Parse the package control file. Returns {} when it cannot be read."""
    try:
        with tempfile.TemporaryDirectory(prefix="appdrop-deb-") as tmp:
            workdir = Path(tmp)
            raw, member_name = _extract_member(path, "control.tar", workdir)
            tar_path = _decompress(member_name, raw, workdir)
            with tarfile.open(tar_path, "r:*") as tar:
                member = next(
                    (
                        m
                        for m in tar.getmembers()
                        if m.isfile() and Path(m.name).name == "control"
                    ),
                    None,
                )
                if member is None:
                    return {}
                handle = tar.extractfile(member)
                if handle is None:
                    return {}
                text = handle.read().decode("utf-8", errors="replace")
    except (DebError, OSError, tarfile.TarError) as exc:
        log.debug("Could not read control file from %s: %s", path.name, exc)
        return {}

    fields: dict[str, str] = {}
    key = ""
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[0] in " \t":
            if key:
                fields[key] += " " + line.strip()
            continue
        name, sep, value = line.partition(":")
        if not sep:
            continue
        key = name.strip()
        fields[key] = value.strip()
    return fields
