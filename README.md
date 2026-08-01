# Gnomad AppDrop for Nobara Linux

Mac-style drag-and-drop app installs for Linux. A [Gnomad Studio](https://gnomadstudio.org) product.

Drop a `.tar.gz`, `.zip`, `.AppImage`, or `.deb` into **Applications** — it lands in your app menu.

**Download:** [davidcole.cloud/apps/appdrop/download](https://davidcole.cloud/apps/appdrop/download)  
**GitHub:** [davidthegnomad/gnomad-appdrop](https://github.com/davidthegnomad/gnomad-appdrop)  
**Support:** [david@gnomad.studio](mailto:david@gnomad.studio)  
**Report a bug:** [GitHub Issues](https://github.com/davidthegnomad/gnomad-appdrop/issues/new)

---

## Install (simple)

1. Get the setup folder (or `Gnomad-AppDrop-*-Setup.zip` from the download page / `dist/`).
2. Open it and **double-click `Install Gnomad AppDrop`**.
3. Read the splash → click **Install** → click **Open Gnomad AppDrop**.

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
appdrop open <id>
appdrop uninstall <id>
```

---

## Support

Email **david@gnomad.studio** or [open a GitHub issue](https://github.com/davidthegnomad/gnomad-appdrop/issues/new).

## Notes

- Stdlib-only core. Optional: `sudo dnf install python3-gobject gtk3` for window drag-and-drop in the GUI.
- Source-only tarballs (need compile) are rejected with a clear message.
- Uninstall Gnomad AppDrop: `./packaging/uninstall.sh`

### About `.deb` packages

`.deb` files are unpacked into `~/.local/opt` and given a menu launcher — nothing
is installed system-wide and `dpkg` is never called. Packages that bundle their
own libraries (Chrome, VS Code, Discord, Slack) generally work. Packages that
expect system dependencies may not run, since those dependencies are not
installed. For those, use your distro's package manager instead.
