"""Gnomad AppDrop GUI — drop zone + status for Nobara/Linux."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from . import branding, config
from .config import ensure_dirs
from .install import InstallError, install_path, list_installed, uninstall
from .watcher import watch


def run_gui() -> int:
    ensure_dirs()
    # Prefer GTK on Nobara (GNOME/KDE both fine with PyGObject when present)
    try:
        return _run_gtk()
    except Exception:
        return _run_tk()


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


def _run_gtk() -> int:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GLib, Gtk, Gdk, GdkPixbuf

    # Brief branded splash before main window
    splash_file = branding.splash_path()
    if splash_file:
        splash = Gtk.Window(title=branding.PRODUCT_NAME)
        splash.set_decorated(False)
        splash.set_position(Gtk.WindowPosition.CENTER)
        splash.set_border_width(0)
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                str(splash_file), 640, 360, True
            )
            splash.add(Gtk.Image.new_from_pixbuf(pix))
            splash.show_all()
            GLib.timeout_add(1600, splash.destroy)
            # Pump events so splash paints
            for _ in range(20):
                while Gtk.events_pending():
                    Gtk.main_iteration_do(False)
                import time

                time.sleep(0.08)
        except Exception:
            splash.destroy()

    class AppDropWindow(Gtk.Window):
        def __init__(self) -> None:
            super().__init__(title=branding.PRODUCT_NAME)
            self.set_default_size(540, 520)
            self.set_border_width(16)
            self._stop = False
            self._watcher: threading.Thread | None = None
            icon = branding.icon_path()
            if icon:
                try:
                    self.set_icon_from_file(str(icon))
                except Exception:
                    pass

            css = b"""
            .drop-zone {
                background-color: #0d1110;
                border: 2px dashed #3dff9a;
                border-radius: 12px;
                padding: 24px;
            }
            .title { font-size: 22px; font-weight: bold; color: #7CFFB2; }
            .muted { color: #a8a8b3; }
            """
            provider = Gtk.CssProvider()
            provider.load_from_data(css)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            self.add(root)

            header = Gtk.Box(spacing=10)
            logo = branding.studio_logo_path() or branding.icon_path()
            if logo:
                try:
                    pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                        str(logo), 48, 48, True
                    )
                    header.pack_start(Gtk.Image.new_from_pixbuf(pix), False, False, 0)
                except Exception:
                    pass
            title_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            title = Gtk.Label(label=branding.PRODUCT_NAME)
            title.get_style_context().add_class("title")
            title.set_xalign(0)
            by = Gtk.Label(label=f"by {branding.STUDIO_NAME}")
            by.get_style_context().add_class("muted")
            by.set_xalign(0)
            title_col.pack_start(title, False, False, 0)
            title_col.pack_start(by, False, False, 0)
            header.pack_start(title_col, False, False, 0)
            root.pack_start(header, False, False, 0)

            subtitle = Gtk.Label(
                label=(
                    "Drop .tar.gz / .zip / .AppImage files into your Applications "
                    "folder — or onto this window — and Gnomad AppDrop will install them "
                    "and add a launcher to your app menu."
                )
            )
            subtitle.set_line_wrap(True)
            subtitle.get_style_context().add_class("muted")
            subtitle.set_xalign(0)
            root.pack_start(subtitle, False, False, 0)

            self.drop_label = Gtk.Label(
                label=f"Drop files here\nor into\n{config.APPLICATIONS_DIR}"
            )
            self.drop_label.set_justify(Gtk.Justification.CENTER)
            drop = Gtk.EventBox()
            drop.get_style_context().add_class("drop-zone")
            drop.add(self.drop_label)
            drop.drag_dest_set(
                Gtk.DestDefaults.ALL,
                [],
                Gdk.DragAction.COPY,
            )
            drop.drag_dest_add_uri_targets()
            drop.connect("drag-data-received", self._on_drag)
            root.pack_start(drop, True, True, 0)

            btn_row = Gtk.Box(spacing=8)
            open_btn = Gtk.Button(label="Open Applications Folder")
            open_btn.connect(
                "clicked", lambda *_: _open_folder(config.APPLICATIONS_DIR)
            )
            pick_btn = Gtk.Button(label="Install File…")
            pick_btn.connect("clicked", self._pick_file)
            btn_row.pack_start(open_btn, False, False, 0)
            btn_row.pack_start(pick_btn, False, False, 0)
            root.pack_start(btn_row, False, False, 0)

            self.status = Gtk.Label(label="Watcher: starting…")
            self.status.set_xalign(0)
            root.pack_start(self.status, False, False, 0)

            scroll = Gtk.ScrolledWindow()
            scroll.set_min_content_height(120)
            self.listbox = Gtk.ListBox()
            scroll.add(self.listbox)
            root.pack_start(scroll, True, True, 0)

            links = Gtk.Box(spacing=8)
            for label, url in (
                (branding.STUDIO_NAME, branding.STUDIO_URL),
                ("Download page", branding.DOWNLOAD_URL),
                ("GitHub", branding.GITHUB_URL),
            ):
                btn = Gtk.LinkButton(uri=url, label=label)
                links.pack_start(btn, False, False, 0)
            root.pack_start(links, False, False, 0)

            self.connect("destroy", self._on_destroy)
            self._refresh_list()
            self._start_watcher()

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
            filt.set_name("Archives & AppImages")
            for ext in ("*.tar.gz", "*.tgz", "*.tar.xz", "*.tar.bz2", "*.tar", "*.zip", "*.AppImage", "*.appimage"):
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
                    GLib.idle_add(
                        self._set_status,
                        f"Installed {result.name} — check your app menu",
                    )
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
                    label.set_hexpand(True)
                    rm = Gtk.Button(label="Remove")
                    rm.connect(
                        "clicked",
                        lambda _b, app_id=app.app_id: self._remove(app_id),
                    )
                    box.pack_start(label, True, True, 0)
                    box.pack_end(rm, False, False, 0)
                    row.add(box)
                    self.listbox.add(row)
            self.listbox.show_all()

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


def _run_tk() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("Gnomad AppDrop")
    root.geometry("520x420")
    root.minsize(420, 320)

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
                        f"Installed {result.name} — check your app menu"
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
                    "Archives & AppImages",
                    "*.tar.gz *.tgz *.tar.xz *.tar.bz2 *.tar *.zip *.AppImage",
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
    ttk.Button(btns, text="Install File…", command=pick).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(btns, text="Remove Selected", command=remove_selected).pack(side=tk.LEFT)

    link_row = ttk.Frame(frm)
    link_row.pack(fill=tk.X, pady=(8, 0))
    ttk.Button(
        link_row, text="Gnomad Studio", command=lambda: _open_url(branding.STUDIO_URL)
    ).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(
        link_row, text="Download page", command=lambda: _open_url(branding.DOWNLOAD_URL)
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
