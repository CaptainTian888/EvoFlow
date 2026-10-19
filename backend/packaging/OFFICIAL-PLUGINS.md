# Official plugins bundle (installer marketplace)

Product installers ship curated official plugins under
`_internal/evoflow/plugins/bundled_official` (PyInstaller datas). The source tree
`packaging/official-plugins-bundle/` is **gitignored** (only `.gitignore` is
tracked) so CI must populate it before `preflight-build-check.py`.

## Local build

```powershell
# From a machine that already has the official plugin cache:
.\backend\packaging\windows\sync-official-plugins-bundle.ps1

# Or Unix:
bash backend/packaging/sync-official-plugins-bundle.sh
```

Then build the gateway as usual (`build-gateway-exe.ps1` /
`build-gateway-macos.sh`). An empty bundle now **fails** the build (spec +
lean-assert), instead of shipping an empty marketplace.

## Publish archive for CI

```bash
bash backend/packaging/pack-official-plugins-bundle.sh
# -> backend/packaging/official-plugins-bundle.tar.gz  (~20MB compressed)
```

Upload that file as a GitHub Release asset named exactly
`official-plugins-bundle.tar.gz`.

## CI configuration

Release workflows call fetch **before** preflight. Configure one of:

| Variable / secret | Purpose |
| --- | --- |
| `secrets.EVOFLOW_OFFICIAL_PLUGINS_URL` | Direct https URL to `.tar.gz` / `.zip` |
| `vars.EVOFLOW_OFFICIAL_PLUGINS_RELEASE` | `owner/repo@tag` (or `tag` if `GITHUB_REPOSITORY` matches) |
| `secrets.EVOFLOW_OFFICIAL_PLUGINS_TOKEN` | Optional; falls back to `GITHUB_TOKEN` |

Installers keep **one** copy of the plugins (in-package). A sidecar
`official-plugins-bundle/` next to the gateway exe is treated as an error by
lean-assert (avoids ~50MB duplicate).
