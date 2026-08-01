# AppDrop SESSION_STATE

**Updated:** 2026-08-01  
**Version:** 1.1.0

## Done this session

- Smart package naming (`metadata.py`): `.desktop` / deb control / archive binary / well-known (`tsetup` → Telegram Desktop) before filename fallback
- GUI **Open** button + `appdrop open <id>` for installed apps
- Keywords on generated launchers for menu search
- Support: `david@gnomad.studio`
- **Report a Bug** (GitHub Issues) in footer + Help dialog; Email Support in Help
- Help copy updated (naming, Open, support)
- Migrated local Telegram + Go installs to searchable ids
- Diagnosed Flatpak Chrome as daily driver (vs AppDrop test `.deb`)
- Cleared stale `/mnt/1TBCrucial` automount that broke Flatpak Chrome link opens

## Ship checklist

- [x] Tests green (22)
- [x] GitHub release `v1.1.0` + Setup zip (`23300a6`)
- [x] davidcole.cloud apps data → 1.1.0 (`44c61a0`) + Hostinger deploy CI

## Notes

- Installed runtime copy: `~/.local/share/appdrop/src` (sync after release)
- Site download prefers GitHub Releases CDN (Hostinger sticky cache)
