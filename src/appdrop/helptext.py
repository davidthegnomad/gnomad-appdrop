"""In-app Help copy for Gnomad AppDrop."""

from __future__ import annotations

from . import branding, config
from . import __version__

HELP_TITLE = "How Gnomad AppDrop works"

HELP_BODY = f"""\
Gnomad AppDrop installs Linux apps the Mac way: drop a package into \
Applications, and it appears in your app menu.

Version {__version__}

INSTALL
• Drop a file onto the illustration, or into {config.APPLICATIONS_DIR}
• Or click Install File… and pick a package
• Or right-click a download → Open With → Gnomad AppDrop, then drag it in

SUPPORTED FILES
• .AppImage
• .deb  (unpacked locally — system dependencies are not installed)
• .tar.gz / .tgz / .tar.xz / .tar.bz2 / .tar / .zip

WHERE THINGS GO
• Drop folder:  {config.APPLICATIONS_DIR}
• Installed apps:  {config.OPT_DIR}/<app-id>/
• Menu launchers:  {config.DESKTOP_DIR}/

FINDING YOUR APPS
• AppDrop reads package metadata so menu names match the real program
  (e.g. tsetup… → Telegram Desktop), not the download filename
• Use Open next to an installed app, or search your system app menu

REMOVE AN APP
• Use Remove next to the app in Installed Apps
• That deletes the local files and the menu launcher

TIPS
• Prefer AppImage or a self-contained .deb when you can
• .deb packages that need system libraries may not run after unpacking
• AppDrop never uses sudo or dpkg — installs stay in your home directory

SUPPORT
• Email: {branding.SUPPORT_EMAIL}
• Report a bug (GitHub): {branding.BUG_REPORT_URL}
• Or use Report a Bug / Email Support in this Help window

{branding.STUDIO_NAME}
{branding.STUDIO_URL}
{branding.APP_PAGE_URL}
"""
