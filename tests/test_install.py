"""Smoke tests for Gnomad AppDrop install/detect (stdlib unittest)."""

from __future__ import annotations

import tarfile
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from appdrop import config  # noqa: E402
from appdrop.desktop import adopt_bundled_desktop, quote_desktop_exec  # noqa: E402
from appdrop.detect import (  # noqa: E402
    choose_main_executable,
    exec_hint_from_desktop,
    sanitize_app_id,
)
from appdrop.install import InstallError, install_path, uninstall  # noqa: E402


class DetectTests(unittest.TestCase):
    def test_sanitize(self) -> None:
        self.assertEqual(sanitize_app_id("Foo Bar 1.2"), "foo-bar-1.2")

    def test_choose_apprun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "helper").write_bytes(b"\x7fELF" + b"\0" * 20)
            (root / "helper").chmod(0o755)
            (root / "AppRun").write_bytes(b"\x7fELF" + b"\0" * 20)
            (root / "AppRun").chmod(0o755)
            main = choose_main_executable(root, "demo")
            self.assertEqual(main.name, "AppRun")

    def test_prefer_desktop_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ffmpeg").write_bytes(b"\x7fELF" + b"\0" * 20)
            (root / "ffmpeg").chmod(0o755)
            (root / "CoolApp").write_bytes(b"\x7fELF" + b"\0" * 20)
            (root / "CoolApp").chmod(0o755)
            main = choose_main_executable(
                root, "other", preferred_name="CoolApp"
            )
            self.assertEqual(main.name, "CoolApp")

    def test_exec_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            desk = root / "app.desktop"
            desk.write_text(
                "[Desktop Entry]\nType=Application\nName=X\nExec=./CoolApp %u\n",
                encoding="utf-8",
            )
            self.assertEqual(exec_hint_from_desktop(desk, root), "CoolApp")


class DesktopTests(unittest.TestCase):
    def test_quote_exec(self) -> None:
        self.assertEqual(quote_desktop_exec("/opt/app"), "/opt/app")
        q = quote_desktop_exec('/opt/App"evil')
        self.assertTrue(q.startswith('"'))
        self.assertIn('\\"', q)

    def test_adopt_strips_dangerous_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config.DESKTOP_DIR = base / "applications"
            config.ICON_DIR = base / "icons"
            config.DESKTOP_DIR.mkdir()
            config.ICON_DIR.mkdir()
            root = base / "app"
            root.mkdir()
            binary = root / "CoolApp"
            binary.write_bytes(b"#!/bin/sh\n")
            binary.chmod(0o755)
            src = root / "evil.desktop"
            src.write_text(
                "\n".join(
                    [
                        "[Desktop Entry]",
                        "Type=Application",
                        "Name=Cool",
                        "Exec=./CoolApp",
                        "X-GNOME-Autostart-enabled=true",
                        "DBusActivatable=true",
                        "Actions=Nuke;",
                        "[Desktop Action Nuke]",
                        "Name=Nuke",
                        "Exec=rm -rf /",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            dest = adopt_bundled_desktop(
                src, app_id="cool", exec_path=binary, install_root=root
            )
            text = dest.read_text(encoding="utf-8")
            self.assertIn("Exec=", text)
            self.assertIn(str(binary), text)
            self.assertNotIn("Autostart", text)
            self.assertNotIn("DBusActivatable", text)
            self.assertNotIn("Actions=", text)
            self.assertNotIn("rm -rf", text)


class InstallTests(unittest.TestCase):
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

    def _make_tarball(self, name: str = "CoolApp-1.0.tar.gz") -> Path:
        staging = Path(self._tmpdir.name) / "stage" / "CoolApp-1.0"
        staging.mkdir(parents=True)
        binary = staging / "CoolApp"
        binary.write_bytes(b"#!/bin/sh\necho hi\n")
        binary.chmod(0o755)
        (staging / "icon.png").write_bytes(
            b"\x89PNG\r\n\x1a\n" + b"\0" * 16
        )
        tar_path = Path(self._tmpdir.name) / name
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(staging, arcname="CoolApp-1.0")
        return tar_path

    def test_install_tarball(self) -> None:
        tar_path = self._make_tarball()
        result = install_path(tar_path, move_source=False)
        self.assertTrue(Path(result.exec_path).is_file())
        self.assertTrue(Path(result.desktop_path).is_file())
        desktop = Path(result.desktop_path).read_text(encoding="utf-8")
        self.assertIn("Type=Application", desktop)
        self.assertIn("X-Gnomad-AppDrop=true", desktop)
        self.assertIn(result.exec_path, desktop)
        uninstall(result.app_id)
        self.assertFalse(Path(result.desktop_path).exists())

    def test_source_only_fails(self) -> None:
        staging = Path(self._tmpdir.name) / "srcpkg"
        staging.mkdir()
        (staging / "README").write_text("source only\n", encoding="utf-8")
        (staging / "main.c").write_text("int main(){return 0;}\n", encoding="utf-8")
        tar_path = Path(self._tmpdir.name) / "srcpkg.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(staging, arcname="srcpkg")
        with self.assertRaises(InstallError):
            install_path(tar_path, move_source=False)

    def test_symlink_in_tar_rejected(self) -> None:
        staging = Path(self._tmpdir.name) / "evil"
        staging.mkdir()
        (staging / "CoolApp").write_bytes(b"#!/bin/sh\n")
        (staging / "CoolApp").chmod(0o755)
        tar_path = Path(self._tmpdir.name) / "evil.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(staging / "CoolApp", arcname="CoolApp")
            info = tarfile.TarInfo(name="link-out")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
        with self.assertRaises(InstallError):
            install_path(tar_path, move_source=False)


if __name__ == "__main__":
    unittest.main()
