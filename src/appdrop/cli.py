"""CLI entry points for Gnomad AppDrop."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__, config
from .config import ensure_dirs
from .install import (
    InstallError,
    install_path,
    launch,
    list_installed,
    process_drop_dir,
    uninstall,
)
from .watcher import watch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="appdrop",
        description=(
            "Mac-style app installer for Nobara/Linux: drop .tar.gz / .AppImage "
            f"/ .deb into {config.APPLICATIONS_DIR} and get a menu launcher."
        ),
    )
    parser.add_argument("--version", action="version", version=f"Gnomad AppDrop {__version__}")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_install = sub.add_parser("install", help="Install one archive or AppImage")
    p_install.add_argument("path", type=Path)
    p_install.add_argument(
        "--keep",
        action="store_true",
        help="Keep the source file (default: leave it in place for CLI install)",
    )

    p_watch = sub.add_parser(
        "watch",
        help=f"Watch {config.APPLICATIONS_DIR} and auto-install drops",
    )
    p_watch.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="Override Applications drop folder",
    )
    p_watch.add_argument(
        "--keep",
        action="store_true",
        help="Do not delete source files after install",
    )
    p_watch.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Poll interval seconds (default: 2)",
    )

    p_scan = sub.add_parser(
        "scan",
        help="Install any supported files currently in the Applications folder",
    )
    p_scan.add_argument("--keep", action="store_true")

    sub.add_parser("list", help="List apps installed by Gnomad AppDrop")

    p_open = sub.add_parser("open", help="Launch an AppDrop-installed app")
    p_open.add_argument("app_id", help="App id (see: appdrop list)")

    p_rm = sub.add_parser("uninstall", help="Remove an Gnomad AppDrop-installed app")
    p_rm.add_argument("app_id", help="App id (see: appdrop list)")

    p_gui = sub.add_parser(
        "gui",
        help="Open the Gnomad AppDrop window (optional files for Open With)",
    )
    p_gui.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files from right-click Open With — opens AppDrop for drag-to-Applications",
    )
    sub.add_parser("init", help="Create ~/Applications and related folders")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if args.cmd == "init":
        ensure_dirs()
        print(f"Ready. Drop archives into: {config.APPLICATIONS_DIR}")
        print(f"Apps install to:          {config.OPT_DIR}")
        print(f"Launchers go to:          {config.DESKTOP_DIR}")
        return 0

    if args.cmd == "install":
        try:
            result = install_path(args.path, move_source=False)
        except InstallError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Installed {result.name}")
        print(f"  id:      {result.app_id}")
        print(f"  exec:    {result.exec_path}")
        print(f"  desktop: {result.desktop_path}")
        return 0

    if args.cmd == "watch":
        ensure_dirs()
        watch(
            args.dir,
            poll_interval=args.interval,
            move_source=not args.keep,
        )
        return 0

    if args.cmd == "scan":
        results = process_drop_dir(move_source=not args.keep)
        if not results:
            print("No supported files found in Applications folder.")
            return 0
        rc = 0
        for item in results:
            if isinstance(item, Exception):
                print(f"error: {item}", file=sys.stderr)
                rc = 1
            else:
                print(f"Installed {item.name} ({item.app_id})")
        return rc

    if args.cmd == "list":
        apps = list_installed()
        if not apps:
            print("No Gnomad AppDrop apps installed.")
            return 0
        for app in apps:
            print(f"{app.app_id:24} {app.name:24} {app.kind:8} {app.exec_path}")
        return 0

    if args.cmd == "open":
        try:
            launch(args.app_id)
        except InstallError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Opening {args.app_id}")
        return 0

    if args.cmd == "uninstall":
        uninstall(args.app_id)
        print(f"Removed {args.app_id}")
        return 0

    if args.cmd == "gui":
        from .gui import run_gui

        return run_gui(getattr(args, "paths", None))

    parser.error(f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
