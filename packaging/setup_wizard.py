#!/usr/bin/env python3
"""Gnomad AppDrop Setup — one-click installer with a plain-language welcome screen."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Release zip may place this script beside src/ instead of under packaging/
if not (ROOT / "src" / "appdrop").is_dir() and (Path(__file__).resolve().parent / "src" / "appdrop").is_dir():
    ROOT = Path(__file__).resolve().parent

TITLE = "Install Gnomad AppDrop"
WELCOME = """Gnomad AppDrop makes Linux apps install like on a Mac.

WHAT IT DOES
• You drop a .tar.gz, .zip, or .AppImage into your Applications folder
• Gnomad AppDrop installs it and puts it in your app menu
• No terminal commands needed after setup

HOW YOU'LL USE IT
1. Download an app (AppImage or Linux tarball)
2. Drop it into the Applications folder (Gnomad AppDrop opens it for you)
3. Find the app in your menu and launch it

Click Install to set this up on your computer now.
It only installs for your user account — no admin password needed."""

SUCCESS = """Gnomad AppDrop is ready.

What was set up:
• Applications folder for dropping installs
• Gnomad AppDrop in your app menu
• Background helper that watches for new drops

How to use it:
1. Open Gnomad AppDrop from your app menu (or click Finish to open it)
2. Click “Open Applications Folder”
3. Drop a .AppImage or .tar.gz into that folder
4. Wait a second — it appears in your app menu

That’s it. Installing software should feel like drag-and-drop from now on."""


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True, text=True, **kwargs)


def do_install() -> tuple[bool, str]:
    install_sh = ROOT / "packaging" / "install.sh"
    if not install_sh.is_file():
        # Release zip layout: install.sh next to this script
        alt = ROOT / "install.sh"
        if alt.is_file():
            install_sh = alt
        else:
            return False, f"Could not find install script in {ROOT}"

    env = os.environ.copy()
    env["APPDROP_ENABLE_WATCH"] = "1"
    result = _run(["bash", str(install_sh)], cwd=str(ROOT), env=env)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "Install failed").strip()
        return False, err
    return True, (result.stdout or "").strip()


def open_appdrop() -> None:
    bin_path = Path.home() / ".local" / "bin" / "appdrop"
    if bin_path.is_file():
        subprocess.Popen(  # noqa: S603
            [str(bin_path), "gui"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def _try_zenity_wizard() -> bool:
    if not shutil.which("zenity"):
        return False

    ok = _run(
        [
            "zenity",
            "--question",
            f"--title={TITLE}",
            "--width=480",
            "--ok-label=Install",
            "--cancel-label=Cancel",
            f"--text={WELCOME}",
        ]
    )
    if ok.returncode != 0:
        return True  # user cancelled; still "handled"

    ok_install, detail = do_install()
    if not ok_install:
        _run(
            [
                "zenity",
                "--error",
                f"--title={TITLE}",
                "--width=420",
                f"--text=Install failed:\n\n{detail}",
            ]
        )
        return True

    done = _run(
        [
            "zenity",
            "--question",
            f"--title={TITLE}",
            "--width=480",
            "--ok-label=Open Gnomad AppDrop",
            "--cancel-label=Finish",
            f"--text={SUCCESS}",
        ]
    )
    if done.returncode == 0:
        open_appdrop()
    return True


def _try_kdialog_wizard() -> bool:
    if not shutil.which("kdialog"):
        return False

    ok = _run(
        [
            "kdialog",
            "--yesno",
            WELCOME,
            "--title",
            TITLE,
            "--yes-label",
            "Install",
            "--no-label",
            "Cancel",
        ]
    )
    if ok.returncode != 0:
        return True

    ok_install, detail = do_install()
    if not ok_install:
        _run(["kdialog", "--error", f"Install failed:\n\n{detail}", "--title", TITLE])
        return True

    done = _run(
        [
            "kdialog",
            "--yesno",
            SUCCESS,
            "--title",
            TITLE,
            "--yes-label",
            "Open Gnomad AppDrop",
            "--no-label",
            "Finish",
        ]
    )
    if done.returncode == 0:
        open_appdrop()
    return True


def _try_gtk_wizard() -> bool:
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
    except Exception:
        return False

    class Wizard(Gtk.Window):
        def __init__(self) -> None:
            super().__init__(title=TITLE)
            self.set_default_size(520, 520)
            self.set_border_width(20)
            self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            self.add(self._box)
            self._show_welcome()

        def _clear(self) -> None:
            for child in list(self._box.get_children()):
                self._box.remove(child)

        def _show_welcome(self) -> None:
            self._clear()
            head = Gtk.Label(label="Install Gnomad AppDrop")
            head.set_xalign(0)
            head.set_markup("<span size='x-large'><b>Install Gnomad AppDrop</b></span>")
            body = Gtk.Label(label=WELCOME)
            body.set_xalign(0)
            body.set_line_wrap(True)
            body.set_selectable(True)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.add(body)
            scroll.set_min_content_height(280)

            row = Gtk.Box(spacing=8)
            cancel = Gtk.Button(label="Cancel")
            cancel.connect("clicked", lambda *_: Gtk.main_quit())
            install = Gtk.Button(label="Install")
            install.get_style_context().add_class("suggested-action")
            install.connect("clicked", self._on_install)
            row.pack_end(install, False, False, 0)
            row.pack_end(cancel, False, False, 0)

            self._box.pack_start(head, False, False, 0)
            self._box.pack_start(scroll, True, True, 0)
            self._box.pack_start(row, False, False, 0)
            self.show_all()

        def _on_install(self, *_args) -> None:
            self._clear()
            wait = Gtk.Label(label="Installing…")
            self._box.pack_start(wait, True, True, 0)
            self.show_all()
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)

            ok, detail = do_install()
            if not ok:
                self._clear()
                err = Gtk.Label(label=f"Install failed:\n\n{detail}")
                err.set_line_wrap(True)
                err.set_xalign(0)
                close = Gtk.Button(label="Close")
                close.connect("clicked", lambda *_: Gtk.main_quit())
                self._box.pack_start(err, True, True, 0)
                self._box.pack_start(close, False, False, 0)
                self.show_all()
                return

            self._show_success()

        def _show_success(self) -> None:
            self._clear()
            head = Gtk.Label()
            head.set_markup("<span size='x-large'><b>You're all set</b></span>")
            head.set_xalign(0)
            body = Gtk.Label(label=SUCCESS)
            body.set_xalign(0)
            body.set_line_wrap(True)
            body.set_selectable(True)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.add(body)
            scroll.set_min_content_height(280)

            row = Gtk.Box(spacing=8)
            finish = Gtk.Button(label="Finish")
            finish.connect("clicked", lambda *_: Gtk.main_quit())
            open_btn = Gtk.Button(label="Open Gnomad AppDrop")
            open_btn.get_style_context().add_class("suggested-action")

            def _open(*_a) -> None:
                open_appdrop()
                Gtk.main_quit()

            open_btn.connect("clicked", _open)
            row.pack_end(open_btn, False, False, 0)
            row.pack_end(finish, False, False, 0)

            self._box.pack_start(head, False, False, 0)
            self._box.pack_start(scroll, True, True, 0)
            self._box.pack_start(row, False, False, 0)
            self.show_all()

    win = Wizard()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    return True


def _cli_wizard() -> None:
    print("=" * 60)
    print(TITLE)
    print("=" * 60)
    print(WELCOME)
    print()
    answer = input("Install now? [Y/n] ").strip().lower()
    if answer in {"n", "no"}:
        print("Cancelled.")
        return
    ok, detail = do_install()
    if not ok:
        print("Install failed:")
        print(detail)
        sys.exit(1)
    print()
    print(SUCCESS)
    open_q = input("Open Gnomad AppDrop now? [Y/n] ").strip().lower()
    if open_q not in {"n", "no"}:
        open_appdrop()


def main() -> int:
    # Prefer a real GUI so double-click feels like an installer
    if _try_gtk_wizard():
        return 0
    if _try_zenity_wizard():
        return 0
    if _try_kdialog_wizard():
        return 0
    _cli_wizard()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
