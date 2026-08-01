"""Tests for package identity probing (names users can find in the menu)."""

from __future__ import annotations

import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from appdrop import config  # noqa: E402
from appdrop.install import install_path, uninstall  # noqa: E402
from appdrop.metadata import (  # noqa: E402
    parse_desktop_text,
    probe_archive,
    probe_identity,
)


class MetadataUnitTests(unittest.TestCase):
    def test_parse_desktop_prefers_untranslated_name(self) -> None:
        fields = parse_desktop_text(
            "\n".join(
                [
                    "[Desktop Entry]",
                    "Type=Application",
                    "Name=Telegram Desktop",
                    "Name[es]=Telegram Escritorio",
                    "Exec=Telegram",
                    "Keywords=tg;chat;",
                    "",
                ]
            )
        )
        self.assertEqual(fields["Name"], "Telegram Desktop")
        self.assertEqual(fields["Keywords"], "tg;chat;")

    def test_tsetup_archive_named_telegram(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / "Telegram"
            staging.mkdir()
            (staging / "Telegram").write_bytes(b"\x7fELF" + b"\0" * 32)
            (staging / "Telegram").chmod(0o755)
            (staging / "Updater").write_bytes(b"\x7fELF" + b"\0" * 32)
            (staging / "Updater").chmod(0o755)
            tar_path = Path(tmp) / "tsetup.7.0.7.tar.xz"
            with tarfile.open(tar_path, "w:xz") as tar:
                tar.add(staging, arcname="Telegram")

            ident = probe_identity(tar_path)
            self.assertEqual(ident.name, "Telegram Desktop")
            self.assertEqual(ident.app_id, "telegram-desktop")
            self.assertIn(ident.source, {"well-known", "exec"})

    def test_archive_desktop_name_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / "WeirdName-9.9"
            staging.mkdir()
            (staging / "bin").mkdir()
            binary = staging / "bin" / "coolapp"
            binary.write_bytes(b"\x7fELF" + b"\0" * 32)
            binary.chmod(0o755)
            (staging / "coolapp.desktop").write_text(
                "[Desktop Entry]\nType=Application\n"
                "Name=Cool App\nExec=coolapp\nCategories=Utility;\n",
                encoding="utf-8",
            )
            tar_path = Path(tmp) / "weirdname-9.9.tar.gz"
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(staging, arcname="WeirdName-9.9")

            ident = probe_archive(tar_path)
            assert ident is not None
            self.assertEqual(ident.name, "Cool App")
            self.assertEqual(ident.source, "desktop")


class MetadataInstallTests(unittest.TestCase):
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

    def test_install_registers_searchable_name(self) -> None:
        staging = Path(self._tmpdir.name) / "Telegram"
        staging.mkdir()
        (staging / "Telegram").write_bytes(b"#!/bin/sh\necho hi\n")
        (staging / "Telegram").chmod(0o755)
        (staging / "Updater").write_bytes(b"#!/bin/sh\n")
        (staging / "Updater").chmod(0o755)
        tar_path = Path(self._tmpdir.name) / "tsetup.7.0.7.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(staging, arcname="Telegram")

        result = install_path(tar_path, move_source=False)
        self.assertEqual(result.name, "Telegram Desktop")
        self.assertEqual(result.app_id, "telegram-desktop")
        desktop = Path(result.desktop_path).read_text(encoding="utf-8")
        self.assertIn("Name=Telegram Desktop", desktop)
        self.assertIn("Keywords=", desktop)
        self.assertIn("telegram", desktop.lower())
        uninstall(result.app_id)


if __name__ == "__main__":
    unittest.main()
