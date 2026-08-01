"""Tests for .deb unpacking (ar container parsing + safe extraction)."""

from __future__ import annotations

import io
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from appdrop import config, debpkg  # noqa: E402
from appdrop.install import InstallError, install_path, uninstall  # noqa: E402

CONTROL = """Package: coolapp
Version: 1.2.3-1
Architecture: amd64
Maintainer: Gnomad Studio
Description: A cool app
 Extended description line.
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=Cool App
Exec=/usr/bin/coolapp %U
Icon=coolapp
Categories=Utility;
"""


def ar_member(name: str, data: bytes) -> bytes:
    header = (
        f"{name:<16}{0:<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}"
    ).encode("ascii") + b"`\n"
    assert len(header) == 60, len(header)
    padding = b"\n" if len(data) % 2 else b""
    return header + data + padding


def tar_bytes(entries: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for info, payload in entries:
            if payload is None:
                tar.addfile(info)
            else:
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def file_info(name: str, mode: int = 0o644) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.REGTYPE
    info.mode = mode
    return info


def symlink_info(name: str, target: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.SYMTYPE
    info.linkname = target
    return info


class DebTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        base = Path(self._tmpdir.name)
        self.apps = base / "DropZone"
        self.opt = base / "opt"
        self.desktop = base / "xdg-applications"
        self.icons = base / "icons"
        self.state = base / "state"
        for p in (self.apps, self.opt, self.desktop, self.icons, self.state):
            p.mkdir(parents=True)

        config.APPLICATIONS_DIR = self.apps
        config.OPT_DIR = self.opt
        config.DESKTOP_DIR = self.desktop
        config.ICON_DIR = self.icons
        config.STATE_DIR = self.state
        config.REGISTRY_PATH = self.state / "installed.json"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _make_deb(
        self,
        name: str = "coolapp_1.2.3-1_amd64.deb",
        *,
        extra: list[tuple[tarfile.TarInfo, bytes | None]] | None = None,
    ) -> Path:
        data = tar_bytes(
            [
                (file_info("./usr/bin/coolapp", 0o755), b"\x7fELF" + b"\0" * 32),
                (
                    file_info("./usr/share/applications/coolapp.desktop"),
                    DESKTOP.encode("utf-8"),
                ),
                *(extra or []),
            ]
        )
        control = tar_bytes([(file_info("./control"), CONTROL.encode("utf-8"))])

        deb = Path(self._tmpdir.name) / name
        deb.write_bytes(
            b"!<arch>\n"
            + ar_member("debian-binary", b"2.0\n")
            + ar_member("control.tar.gz", control)
            + ar_member("data.tar.gz", data)
        )
        return deb

    def test_read_control(self) -> None:
        fields = debpkg.read_control(self._make_deb())
        self.assertEqual(fields["Package"], "coolapp")
        self.assertEqual(fields["Version"], "1.2.3-1")
        self.assertIn("Extended description", fields["Description"])

    def test_is_deb(self) -> None:
        self.assertTrue(debpkg.is_deb(self._make_deb()))
        plain = Path(self._tmpdir.name) / "not.deb"
        plain.write_bytes(b"nope")
        self.assertFalse(debpkg.is_deb(plain))

    def test_install_deb(self) -> None:
        result = install_path(self._make_deb(), move_source=False)
        # app_id comes from the control file, not the versioned filename
        self.assertEqual(result.app_id, "coolapp")
        self.assertEqual(result.kind, "deb")
        self.assertTrue(Path(result.exec_path).is_file())
        self.assertTrue(Path(result.desktop_path).is_file())
        desktop = Path(result.desktop_path).read_text(encoding="utf-8")
        self.assertIn("X-Gnomad-AppDrop=true", desktop)
        self.assertIn(result.exec_path, desktop)

        uninstall(result.app_id)
        self.assertFalse(Path(result.desktop_path).exists())

    def test_relative_symlink_is_kept(self) -> None:
        result = install_path(
            self._make_deb(
                extra=[(symlink_info("./usr/bin/coolapp-alias", "coolapp"), None)]
            ),
            move_source=False,
        )
        alias = Path(result.install_dir) / "usr" / "bin" / "coolapp-alias"
        self.assertTrue(alias.is_symlink())

    def test_absolute_symlink_is_skipped(self) -> None:
        result = install_path(
            self._make_deb(
                extra=[(symlink_info("./usr/bin/passwd-link", "/etc/passwd"), None)]
            ),
            move_source=False,
        )
        leaked = Path(result.install_dir) / "usr" / "bin" / "passwd-link"
        self.assertFalse(leaked.exists() or leaked.is_symlink())

    def test_escaping_symlink_is_skipped(self) -> None:
        result = install_path(
            self._make_deb(
                extra=[(symlink_info("./usr/bin/escape", "../../../../etc/passwd"), None)]
            ),
            move_source=False,
        )
        leaked = Path(result.install_dir) / "usr" / "bin" / "escape"
        self.assertFalse(leaked.exists() or leaked.is_symlink())

    def test_helper_binaries_keep_exec_bit(self) -> None:
        # Chrome aborts at startup if chrome_crashpad_handler is not executable,
        # and helper names like this are excluded from main-binary detection.
        result = install_path(
            self._make_deb(
                extra=[
                    (
                        file_info("./usr/bin/chrome_crashpad_handler", 0o755),
                        b"\x7fELF" + b"\0" * 32,
                    )
                ]
            ),
            move_source=False,
        )
        helper = Path(result.install_dir) / "usr" / "bin" / "chrome_crashpad_handler"
        self.assertTrue(os.access(helper, os.X_OK))

    def test_data_files_stay_non_executable(self) -> None:
        result = install_path(self._make_deb(), move_source=False)
        desktop = (
            Path(result.install_dir)
            / "usr"
            / "share"
            / "applications"
            / "coolapp.desktop"
        )
        self.assertFalse(os.access(desktop, os.X_OK))

    def test_corrupt_deb_reports_cleanly(self) -> None:
        broken = Path(self._tmpdir.name) / "broken.deb"
        broken.write_bytes(b"!<arch>\n" + ar_member("debian-binary", b"2.0\n"))
        with self.assertRaises(InstallError):
            install_path(broken, move_source=False)
        self.assertFalse((self.opt / "broken").exists())


if __name__ == "__main__":
    unittest.main()
