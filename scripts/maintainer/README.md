# scripts/maintainer/

Release helpers for the public repo. Not needed for day-to-day contribute.

> **升版本先看仓库根目录 [RELEASE.md](../../RELEASE.md)**  
> （改 `VERSION`、写 CHANGELOG / PRODUCT-NOTES / `latest.json`、打 tag。）

| Path | Purpose |
|------|---------|
| `windows/local-publish*` | Local TOS / NSIS / public Release helpers |
| `windows/release-evopanel-public*` | One-shot version bump + Windows public release |
| `windows/republish-public-release.ps1` | CI: upload assets + public `update/latest.json` |
| `windows/upload-release-assets-only.ps1` | Used by republish (Windows assets) |
| `windows/prune-public-github-releases.ps1` | Keep N newest public releases |
| `windows/release-notes/PRODUCT-NOTES-x.y.z.md` | GitHub Release「本版更新」正文 |
| `windows/public-release-body.txt` | Footer appended to GitHub Release body |
| `update/` | Updater draft → publish after installer ready |

Desktop CI entrypoint: `.github/workflows/release-desktop-public.yml`
（Windows / macOS：`release-windows-public.yml`、`release-macos-public.yml`）。
