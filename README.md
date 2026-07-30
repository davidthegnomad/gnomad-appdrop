# Gnomad AppDrop for Nobara Linux

Mac-style drag-and-drop app installs for Linux.

Drop a `.tar.gz`, `.zip`, or `.AppImage` into **Applications** — it lands in your app menu.

---

## Install (simple)

1. Get the setup folder (or `Gnomad-AppDrop-*-Setup.zip` from `dist/`).
2. Open it and **double-click `Install Gnomad AppDrop`**.
3. Read the screen → click **Install** → click **Open Gnomad AppDrop**.

That’s it. No terminal required.

If double-click doesn’t run it (GNOME sometimes blocks downloads):

- Right-click `Install-Gnomad-AppDrop` → **Run as Program**, or  
- Right-click `Install Gnomad AppDrop` → **Allow Launching**, then open it.

### Build the download zip (on this machine)

```bash
chmod +x packaging/build_download.sh
./packaging/build_download.sh
# → dist/Gnomad-AppDrop-1.0.0-Setup.zip
```

Copy that zip to your Nobara PC.

---

## How you'll use it every day

1. Download an app (AppImage or Linux tarball).
2. Drop it into your **Applications** folder (Gnomad AppDrop can open that folder).
3. Launch it from your normal app menu.

---

## What it sets up

| Path | Role |
| --- | --- |
| `~/Applications` | Drop zone |
| `~/.local/opt/<app>/` | Installed files |
| `~/.local/share/applications/` | Menu launchers |
| `appdrop-watch` user service | Auto-install on drop |

## Extra commands (optional)

```bash
appdrop gui
appdrop list
appdrop uninstall <id>
```

## Notes

- Stdlib-only core. Optional: `sudo dnf install python3-gobject gtk3` for window drag-and-drop in the GUI.
- Source-only tarballs (need compile) are rejected with a clear message.
- Uninstall Gnomad AppDrop: `./packaging/uninstall.sh`
