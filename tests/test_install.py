"""Smoke tests for Gnomad AppDrop install/detect (stdlib unittest)."""

from __future__ import annotations

import os
import stat
import tarfile
import tempfile
import unittest
from pathlib import Path

# Allow running without install
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from appdrop import config  # noqa: E402
from appdrop.detect import choose_main_executable, sanitize_app_id  # noqa: E402
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

        # Point config at temp dirs
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


if __name__ == "__main__":
    unittest.main()
