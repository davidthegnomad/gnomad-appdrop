"""Gnomad AppDrop GUI — drop zone + status for Nobara/Linux."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from . import branding, config
from .config import ensure_dirs
from .helptext import HELP_BODY, HELP_TITLE
from .install import InstallError, install_path, launch, list_installed, uninstall
from .watcher import watch

# Default window was 760×780; open ~15% larger for the illustrated layout.
WINDOW_WIDTH = 874
WINDOW_HEIGHT = 897
# Hero illustration: 25% smaller than the original 782×521 gesture art.
GESTURE_WIDTH = 586
GESTURE_HEIGHT = 391


def run_gui(open_paths: list[Path] | None = None) -> int:
    ensure_dirs()
    paths = [p.expanduser().resolve() for p in (open_paths or []) if p]
    # Prefer GTK on Nobara (GNOME/KDE both fine with PyGObject when present)
    try:
        return _run_gtk(paths)
    except Exception:
        return _run_tk(paths)


def _configure_app_identity() -> None:
    """Tell GTK/Wayland who we are so the taskbar uses our llama icon."""
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, GLib, Gtk

        GLib.set_prgname(branding.APP_ID)
        GLib.set_application_name(branding.PRODUCT_NAME)
        try:
            Gdk.set_program_class(branding.APP_ID)
        except Exception:
            pass
        icon = branding.icon_path()
        if icon and icon.is_file():
            try:
                Gtk.Window.set_default_icon_from_file(str(icon))
            except Exception:
                pass
    except Exception:
        return


def _open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for cmd in (("xdg-open", str(path)), ("gio", "open", str(path))):
        try:
            subprocess.Popen(  # noqa: S603
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except OSError:
            continue


def _open_url(url: str) -> None:
    for cmd in (("xdg-open", url), ("gio", "open", url)):
        try:
            subprocess.Popen(  # noqa: S603
                list(cmd),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return
        except OSError:
            continue


def _open_with_status(paths: list[Path]) -> str:
    """Open Applications (+ source folders) so the user can drag like the art."""
    ensure_dirs()
    _open_folder(config.APPLICATIONS_DIR)
    parents: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        parent = path.parent if path.is_file() else path
        if parent not in parents and parent != config.APPLICATIONS_DIR:
            parents.append(parent)
    for parent in parents:
        _open_folder(parent)

    existing = [p for p in paths if p.exists()]
    if not existing:
        return "Open with: file not found — drop an archive onto this window"
    if len(existing) == 1:
        return (
            f"Drag {existing[0].name} into Applications "
            f"(or onto this window) — like the illustration"
        )
    return (
        f"Drag {len(existing)} files into Applications "
        f"(or onto this window) — like the illustration"
    )


def _run_gtk(open_paths: list[Path]) -> int:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GLib, Gtk, Gdk, GdkPixbuf

    _configure_app_identity()

    splash_ref: dict[str, Gtk.Window | None] = {"win": None}

    def _close_splash() -> bool:
        win = splash_ref.get("win")
        if win is not None:
            win.destroy()
            splash_ref["win"] = None
        return False

    # Non-blocking splash — no busy-loop (Wayland-friendly)
    splash_file = branding.splash_path()
    if splash_file:
        try:
            splash = Gtk.Window(title=branding.PRODUCT_NAME)
            splash.set_decorated(False)
            splash.set_position(Gtk.WindowPosition.CENTER)
            splash.set_border_width(0)
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                str(splash_file), 640, 360, True
            )
            splash.add(Gtk.Image.new_from_pixbuf(pix))
            splash.show_all()
            splash_ref["win"] = splash
            GLib.timeout_add(1400, _close_splash)
        except Exception:
            splash_ref["win"] = None

    class AppDropWindow(Gtk.Window):
        def __init__(self) -> None:
            super().__init__(title=branding.PRODUCT_NAME)
            self.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
            self.set_border_width(0)
            self._stop = False
            self._watcher: threading.Thread | None = None
            self._open_paths = list(open_paths)
            icon = branding.icon_path()
            if icon:
                try:
                    self.set_icon_from_file(str(icon))
                except Exception:
                    pass

            css = b"""
            window, .app-shell {
                background-color: #111015;
                color: #f5f3f7;
            }
            .app-shell { padding: 24px 34px 20px 34px; }
            .brand-icon {
                border-radius: 13px;
            }
            .title {
                font-size: 22px;
                font-weight: 700;
                color: #ffffff;
            }
            .eyebrow {
                font-size: 11px;
                font-weight: 600;
                color: #9c94ad;
                letter-spacing: 1px;
            }
            .eyebrow link { color: #9c94ad; }
            .eyebrow link:hover { color: #75dfff; }
            .header-separator {
                color: #4e4956;
                font-size: 15px;
            }
            .drop-zone {
                background-color: #15131b;
                border: 1px solid rgba(191, 174, 255, 0.24);
                border-radius: 24px;
                padding: 1px;
            }
            .drop-zone:hover {
                border-color: rgba(92, 213, 255, 0.62);
            }
            .instruction {
                font-size: 16px;
                font-weight: 600;
                color: #f5f3f7;
            }
            .muted { color: #9c94ad; }
            .status {
                color: #7ddfff;
                font-size: 12px;
            }
            button {
                background-image: none;
                background-color: rgba(255, 255, 255, 0.07);
                color: #f5f3f7;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 18px;
                padding: 8px 18px;
                box-shadow: none;
            }
            button:hover {
                background-color: rgba(255, 255, 255, 0.12);
                border-color: rgba(255, 255, 255, 0.22);
            }
            button.primary {
                background-color: #35bce5;
                color: #071116;
                border-color: #69d9f7;
                font-weight: 700;
            }
            button.remove {
                background-color: transparent;
                color: #aaa4b5;
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 12px;
                padding: 5px 12px;
                font-size: 11px;
            }
            button.remove:hover {
                color: #ffb7c3;
                border-color: rgba(255, 130, 155, 0.38);
                background-color: rgba(255, 100, 130, 0.08);
            }
            .installed-scroll {
                background-color: rgba(255, 255, 255, 0.025);
                border: 1px solid rgba(255, 255, 255, 0.07);
                border-radius: 16px;
            }
            list, row { background-color: transparent; }
            row {
                border-top: 1px solid rgba(255, 255, 255, 0.07);
                padding: 8px 10px;
            }
            .installed-heading {
                font-size: 11px;
                font-weight: 600;
                color: #777181;
                letter-spacing: 1px;
            }
            .app-name { color: #d8d4de; }
            .footer {
                color: #696473;
                font-size: 11px;
                letter-spacing: 0.5px;
                padding-top: 3px;
            }
            .footer link { color: #817b8c; }
            .footer link:hover { color: #75dfff; }
            """
            provider = Gtk.CssProvider()
            provider.load_from_data(css)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            root.get_style_context().add_class("app-shell")
            self.add(root)

            # Compact, single-line identity bar. The illustration remains the
            # star while the llama mark is still clear at header scale.
            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=11)
            header.set_halign(Gtk.Align.CENTER)
            header.set_valign(Gtk.Align.CENTER)
            logo = branding.llama_logo_path() or branding.icon_path()
            if logo:
                try:
                    pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                        str(logo), 48, 48, True
                    )
                    logo_image = Gtk.Image.new_from_pixbuf(pix)
                    logo_image.get_style_context().add_class("brand-icon")
                    header.pack_start(logo_image, False, False, 0)
                except Exception:
                    pass
            title = Gtk.Label(label=branding.PRODUCT_NAME)
            title.get_style_context().add_class("title")
            title.set_xalign(0.5)
            divider = Gtk.Label(label="·")
            divider.get_style_context().add_class("header-separator")
            by = Gtk.Label()
            by.get_style_context().add_class("eyebrow")
            by.set_xalign(0.5)
            by.set_markup(
                f'<a href="{branding.STUDIO_URL}">BY {branding.STUDIO_NAME.upper()}</a>'
            )
            by.connect("activate-link", self._on_footer_link)
            header.pack_start(title, False, False, 0)
            header.pack_start(divider, False, False, 0)
            header.pack_start(by, False, False, 0)
            root.pack_start(header, False, False, 0)

            if self._open_paths:
                names = ", ".join(p.name for p in self._open_paths[:2])
                if len(self._open_paths) > 2:
                    names += f", +{len(self._open_paths) - 2} more"
                instruction_text = f"Drag {names} into Applications"
            else:
                instruction_text = "Drop an app here. Find it in your app menu."
            instruction = Gtk.Label(label=instruction_text)
            instruction.get_style_context().add_class("instruction")
            instruction.set_xalign(0.5)
            root.pack_start(instruction, False, False, 0)

            # The illustration is also the live drag target.
            drop = Gtk.EventBox()
            drop.get_style_context().add_class("drop-zone")
            drop.set_halign(Gtk.Align.CENTER)
            drop.set_valign(Gtk.Align.START)
            drop.set_hexpand(False)
            drop.set_vexpand(False)
            drop.set_size_request(GESTURE_WIDTH + 2, GESTURE_HEIGHT + 2)
            gesture = branding.install_gesture_path()
            if gesture:
                try:
                    pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                        str(gesture), GESTURE_WIDTH, GESTURE_HEIGHT, True
                    )
                    drop.add(Gtk.Image.new_from_pixbuf(pix))
                except Exception:
                    drop.add(Gtk.Label(label="Linux app  →  Applications"))
            else:
                drop.add(Gtk.Label(label="Linux app  →  Applications"))
            drop.drag_dest_set(
                Gtk.DestDefaults.ALL,
                [],
                Gdk.DragAction.COPY,
            )
            drop.drag_dest_add_uri_targets()
            drop.connect("drag-data-received", self._on_drag)
            # Keep the hero at its designed size. Vertical window growth belongs
            # to the installed-app list below, never to the illustration.
            root.pack_start(drop, False, False, 0)

            detail = Gtk.Label(
                label=(
                    ".AppImage, .deb, .tar.gz, .tar.xz, or .zip  •  "
                    "Installs locally  •  No terminal needed"
                )
            )
            detail.get_style_context().add_class("muted")
            detail.set_xalign(0.5)
            root.pack_start(detail, False, False, 0)

            btn_row = Gtk.Box(spacing=8)
            btn_row.set_halign(Gtk.Align.CENTER)
            open_btn = Gtk.Button(label="Open Applications")
            open_btn.connect(
                "clicked", lambda *_: _open_folder(config.APPLICATIONS_DIR)
            )
            pick_btn = Gtk.Button(label="Install File…")
            pick_btn.get_style_context().add_class("primary")
            pick_btn.connect("clicked", self._pick_file)
            btn_row.pack_start(open_btn, False, False, 0)
            btn_row.pack_start(pick_btn, False, False, 0)
            root.pack_start(btn_row, False, False, 0)

            self.status = Gtk.Label(label="Watcher: starting…")
            self.status.get_style_context().add_class("status")
            self.status.set_xalign(0.5)
            root.pack_start(self.status, False, False, 0)

            self.installed_heading = Gtk.Label(label="INSTALLED APPS")
            self.installed_heading.get_style_context().add_class(
                "installed-heading"
            )
            self.installed_heading.set_xalign(0)
            root.pack_start(self.installed_heading, False, False, 0)

            scroll = Gtk.ScrolledWindow()
            scroll.get_style_context().add_class("installed-scroll")
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_min_content_height(92)
            scroll.set_vexpand(True)
            self.listbox = Gtk.ListBox()
            scroll.add(self.listbox)
            root.pack_start(scroll, True, True, 0)

            footer = Gtk.Label()
            footer.get_style_context().add_class("footer")
            footer.set_xalign(0.5)
            footer.set_markup(
                f'<a href="{branding.STUDIO_URL}">GNOMAD STUDIO</a>'
                "   ·   "
                f'<a href="{branding.DOWNLOAD_URL}">DOWNLOAD</a>'
                "   ·   "
                f'<a href="appdrop:help">HELP</a>'
                "   ·   "
                f'<a href="appdrop:bug">REPORT A BUG</a>'
                "   ·   "
                f'<a href="{branding.GITHUB_URL}">GITHUB</a>'
            )
            footer.connect("activate-link", self._on_footer_link)
            root.pack_start(footer, False, False, 0)

            self.connect("destroy", self._on_destroy)
            self._refresh_list()
            self._start_watcher()
            if self._open_paths:
                # Defer so the window paints before file-manager windows open.
                GLib.timeout_add(350, self._handle_open_with)

        def _handle_open_with(self) -> bool:
            self._set_status(_open_with_status(self._open_paths))
            return False

        def _on_footer_link(self, _label, uri: str) -> bool:
            if uri == "appdrop:help":
                self._show_help()
                return True
            if uri == "appdrop:bug":
                self._report_bug()
                return True
            _open_url(uri)
            return True

        def _report_bug(self) -> None:
            # Prefer GitHub Issues; mailto is also in Help for email-only users.
            _open_url(branding.BUG_REPORT_URL)

        def _email_support(self) -> None:
            _open_url(branding.support_mailto())

        def _show_help(self) -> None:
            dialog = Gtk.Dialog(
                title=HELP_TITLE,
                transient_for=self,
                modal=True,
                destroy_with_parent=True,
            )
            dialog.set_default_size(520, 560)
            dialog.add_button("Report a Bug", Gtk.ResponseType.YES)
            dialog.add_button("Email Support", Gtk.ResponseType.APPLY)
            dialog.add_button("Close", Gtk.ResponseType.CLOSE)
            dialog.set_border_width(0)

            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_border_width(18)
            body = Gtk.Label(label=HELP_BODY)
            body.set_xalign(0)
            body.set_yalign(0)
            body.set_line_wrap(True)
            body.set_selectable(True)
            scroll.add(body)
            dialog.get_content_area().pack_start(scroll, True, True, 0)
            dialog.show_all()
            response = dialog.run()
            dialog.destroy()
            if response == Gtk.ResponseType.YES:
                self._report_bug()
            elif response == Gtk.ResponseType.APPLY:
                self._email_support()

        def _start_watcher(self) -> None:
            def notify(title: str, body: str) -> None:
                GLib.idle_add(self._set_status, f"{title}: {body}")
                GLib.idle_add(self._refresh_list)

            def run() -> None:
                watch(
                    move_source=True,
                    notify=notify,
                    stop_flag=lambda: self._stop,
                )

            self._watcher = threading.Thread(target=run, daemon=True)
            self._watcher.start()
            self._set_status(f"Watching {config.APPLICATIONS_DIR}")

        def _set_status(self, text: str) -> None:
            self.status.set_text(text)

        def _on_drag(self, _widget, _ctx, _x, _y, data, _info, _time) -> None:
            uris = data.get_uris() or []
            for uri in uris:
                if not uri.startswith("file://"):
                    continue
                path = Path(GLib.filename_from_uri(uri)[0])
                self._install_async(path)

        def _pick_file(self, *_args) -> None:
            dialog = Gtk.FileChooserDialog(
                title="Install app package",
                parent=self,
                action=Gtk.FileChooserAction.OPEN,
            )
            dialog.add_buttons(
                Gtk.STOCK_CANCEL,
                Gtk.ResponseType.CANCEL,
                Gtk.STOCK_OPEN,
                Gtk.ResponseType.OK,
            )
            filt = Gtk.FileFilter()
            filt.set_name("Apps, archives & packages")
            for ext in ("*.tar.gz", "*.tgz", "*.tar.xz", "*.tar.bz2", "*.tar", "*.zip", "*.AppImage", "*.appimage", "*.deb"):
                filt.add_pattern(ext)
            dialog.add_filter(filt)
            if dialog.run() == Gtk.ResponseType.OK:
                self._install_async(Path(dialog.get_filename()))
            dialog.destroy()

        def _install_async(self, path: Path) -> None:
            self._set_status(f"Installing {path.name}…")

            def work() -> None:
                try:
                    result = install_path(path, move_source=False)
                    message = (
                        f"Installed {result.name} — use Open below or your app menu"
                    )
                    if result.kind == "deb":
                        message += " (system dependencies are not installed)"
                    GLib.idle_add(self._set_status, message)
                    GLib.idle_add(self._refresh_list)
                except InstallError as exc:
                    GLib.idle_add(self._set_status, f"Failed: {exc}")
                except Exception as exc:  # noqa: BLE001
                    GLib.idle_add(self._set_status, f"Error: {exc}")

            threading.Thread(target=work, daemon=True).start()

        def _refresh_list(self) -> None:
            for child in self.listbox.get_children():
                self.listbox.remove(child)
            apps = list_installed()
            self.installed_heading.set_text(
                f"INSTALLED APPS  ·  {len(apps)}"
            )
            if not apps:
                row = Gtk.ListBoxRow()
                row.add(Gtk.Label(label="No apps installed yet.", xalign=0))
                self.listbox.add(row)
            else:
                for app in apps:
                    row = Gtk.ListBoxRow()
                    box = Gtk.Box(spacing=8)
                    label = Gtk.Label(
                        label=f"{app.name}  ({app.kind})  —  {app.app_id}",
                        xalign=0,
                    )
                    label.get_style_context().add_class("app-name")
                    label.set_hexpand(True)
                    open_btn = Gtk.Button(label="Open")
                    open_btn.connect(
                        "clicked",
                        lambda _b, app_id=app.app_id: self._open_app(app_id),
                    )
                    rm = Gtk.Button(label="Remove")
                    rm.get_style_context().add_class("remove")
                    rm.connect(
                        "clicked",
                        lambda _b, app_id=app.app_id: self._remove(app_id),
                    )
                    box.pack_start(label, True, True, 0)
                    box.pack_end(rm, False, False, 0)
                    box.pack_end(open_btn, False, False, 0)
                    row.add(box)
                    self.listbox.add(row)
            self.listbox.show_all()

        def _open_app(self, app_id: str) -> None:
            try:
                launch(app_id)
                self._set_status(f"Opening {app_id}…")
            except InstallError as exc:
                self._set_status(f"Could not open: {exc}")

        def _remove(self, app_id: str) -> None:
            uninstall(app_id)
            self._set_status(f"Removed {app_id}")
            self._refresh_list()

        def _on_destroy(self, *_args) -> None:
            self._stop = True
            Gtk.main_quit()

    win = AppDropWindow()
    win.show_all()
    Gtk.main()
    return 0


def _run_tk(open_paths: list[Path]) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("Gnomad AppDrop")
    root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
    root.minsize(520, 480)

    stop = {"flag": False}

    frm = ttk.Frame(root, padding=16)
    frm.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frm, text="Gnomad AppDrop", font=("Sans", 18, "bold")).pack(anchor="w")
    ttk.Label(frm, text="by Gnomad Studio · gnomadstudio.org", wraplength=480).pack(
        anchor="w", pady=(0, 4)
    )
    ttk.Label(
        frm,
        text=(
            f"Drop .tar.gz / .AppImage files into:\n{config.APPLICATIONS_DIR}\n\n"
            "Or use Install File… below. "
            "(Window drag-and-drop needs GTK; folder watch still works.)"
        ),
        wraplength=480,
        justify=tk.LEFT,
    ).pack(anchor="w", pady=(4, 12))

    status = tk.StringVar(value="Watcher: starting…")
    ttk.Label(frm, textvariable=status).pack(anchor="w")

    list_frame = ttk.Frame(frm)
    list_frame.pack(fill=tk.BOTH, expand=True, pady=8)
    listbox = tk.Listbox(list_frame)
    listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll = ttk.Scrollbar(list_frame, command=listbox.yview)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    listbox.config(yscrollcommand=scroll.set)

    app_ids: list[str] = []

    def refresh() -> None:
        listbox.delete(0, tk.END)
        app_ids.clear()
        apps = list_installed()
        if not apps:
            listbox.insert(tk.END, "No apps installed yet.")
            return
        for app in apps:
            app_ids.append(app.app_id)
            listbox.insert(tk.END, f"{app.name} ({app.kind}) — {app.app_id}")

    def do_install(path: Path) -> None:
        status.set(f"Installing {path.name}…")

        def work() -> None:
            try:
                result = install_path(path, move_source=False)
                root.after(
                    0,
                    lambda: status.set(
                        f"Installed {result.name} — use Open below or your app menu"
                    ),
                )
                root.after(0, refresh)
            except InstallError as exc:
                root.after(0, lambda: status.set(f"Failed: {exc}"))
            except Exception as exc:  # noqa: BLE001
                root.after(0, lambda: status.set(f"Error: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def pick() -> None:
        path = filedialog.askopenfilename(
            title="Install app package",
            filetypes=[
                (
                    "Apps, archives & packages",
                    "*.tar.gz *.tgz *.tar.xz *.tar.bz2 *.tar *.zip *.AppImage *.deb",
                ),
                ("All files", "*.*"),
            ],
        )
        if path:
            do_install(Path(path))

    def remove_selected() -> None:
        sel = listbox.curselection()
        if not sel or not app_ids:
            return
        idx = sel[0]
        if idx >= len(app_ids):
            return
        app_id = app_ids[idx]
        if messagebox.askyesno("Remove", f"Uninstall {app_id}?"):
            uninstall(app_id)
            status.set(f"Removed {app_id}")
            refresh()

    btns = ttk.Frame(frm)
    btns.pack(fill=tk.X)
    ttk.Button(
        btns, text="Open Applications Folder", command=lambda: _open_folder(config.APPLICATIONS_DIR)
    ).pack(side=tk.LEFT, padx=(0, 8))
    def open_selected() -> None:
        sel = listbox.curselection()
        if not sel or not app_ids:
            return
        idx = sel[0]
        if idx >= len(app_ids):
            return
        app_id = app_ids[idx]
        try:
            launch(app_id)
            status.set(f"Opening {app_id}…")
        except InstallError as exc:
            status.set(f"Could not open: {exc}")

    ttk.Button(btns, text="Install File…", command=pick).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(btns, text="Open Selected", command=open_selected).pack(
        side=tk.LEFT, padx=(0, 8)
    )
    ttk.Button(btns, text="Remove Selected", command=remove_selected).pack(side=tk.LEFT)

    def show_help() -> None:
        messagebox.showinfo(HELP_TITLE, HELP_BODY)

    link_row = ttk.Frame(frm)
    link_row.pack(fill=tk.X, pady=(8, 0))
    ttk.Button(
        link_row, text="Gnomad Studio", command=lambda: _open_url(branding.STUDIO_URL)
    ).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(
        link_row, text="Download page", command=lambda: _open_url(branding.DOWNLOAD_URL)
    ).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(link_row, text="Help", command=show_help).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(
        link_row,
        text="Report a Bug",
        command=lambda: _open_url(branding.BUG_REPORT_URL),
    ).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(
        link_row,
        text="Email Support",
        command=lambda: _open_url(branding.support_mailto()),
    ).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(
        link_row, text="GitHub", command=lambda: _open_url(branding.GITHUB_URL)
    ).pack(side=tk.LEFT)

    def notify(title: str, body: str) -> None:
        root.after(0, lambda: status.set(f"{title}: {body}"))
        root.after(0, refresh)

    def run_watch() -> None:
        watch(
            move_source=True,
            notify=notify,
            stop_flag=lambda: stop["flag"],
        )

    threading.Thread(target=run_watch, daemon=True).start()
    if open_paths:
        status.set(_open_with_status(open_paths))
    else:
        status.set(f"Watching {config.APPLICATIONS_DIR}")
    refresh()

    def on_close() -> None:
        stop["flag"] = True
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(run_gui())
