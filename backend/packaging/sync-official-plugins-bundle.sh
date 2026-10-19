#!/usr/bin/env bash
# Fill packaging/official-plugins-bundle from a local official plugin cache (Unix).
#
# Default sources (first hit wins):
#   1. --source / EVOFLOW_OFFICIAL_PLUGINS_SOURCE
#   2. ~/.evoflow-dev/data/plugins/cache/evoflow-plugins-official
#   3. ~/.evoflow/data/plugins/cache/evoflow-plugins-official
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE="${EVOFLOW_OFFICIAL_PLUGINS_SOURCE:-}"
DEST="${BACKEND_DIR}/packaging/official-plugins-bundle"

REQUIRED=(
  browser-use
  computer-use
  documents
  pdf
  presentations
  spreadsheets
  image-search
  plugin-creator
  skill-creator
  node-repl-host
)
RUNTIME_DIRS=(cua-helper)
SKIP_NAMES=(evoflow-guide hello-command evoflow-skill-kit zcode-guide github)

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source|-Source) SOURCE="${2:-}"; shift 2 ;;
    --dest|-Dest) DEST="${2:-}"; shift 2 ;;
    *)
      echo "[sync-official-plugins] unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

plugin_tree_ok() {
  local root="$1"
  [[ -d "${root}" ]] || return 1
  local d
  for d in "${root}"/*; do
    [[ -d "${d}" ]] && return 0
  done
  return 1
}

resolve_source() {
  local candidates=()
  [[ -n "${SOURCE}" ]] && candidates+=("${SOURCE}")
  [[ -n "${EVOFLOW_OFFICIAL_PLUGINS_SOURCE:-}" ]] && candidates+=("${EVOFLOW_OFFICIAL_PLUGINS_SOURCE}")
  candidates+=(
    "${HOME}/.evoflow-dev/data/plugins/cache/evoflow-plugins-official"
    "${HOME}/.evoflow/data/plugins/cache/evoflow-plugins-official"
  )
  local c
  for c in "${candidates[@]}"; do
    if plugin_tree_ok "${c}"; then
      printf '%s\n' "${c}"
      return 0
    fi
  done
  return 1
}

latest_version_dir() {
  local plugin_root="$1"
  # Prefer highest semver-ish directory name (macOS find has no -printf).
  local names=()
  local d
  for d in "${plugin_root}"/*; do
    [[ -d "${d}" ]] || continue
    names+=("$(basename "${d}")")
  done
  if [[ ${#names[@]} -eq 0 ]]; then
    return 0
  fi
  printf '%s\n' "${names[@]}" | sort -t. -k1,1n -k2,2n -k3,3n | tail -n 1
}

contains() {
  local needle="$1"; shift
  local x
  for x in "$@"; do
    [[ "${x}" == "${needle}" ]] && return 0
  done
  return 1
}

resolved="$(resolve_source || true)"
if [[ -z "${resolved}" ]]; then
  cat >&2 <<EOF
[sync-official-plugins] no source cache found.
Set --source or EVOFLOW_OFFICIAL_PLUGINS_SOURCE to a directory like:
  \$HOME/.evoflow-dev/data/plugins/cache/evoflow-plugins-official
EOF
  exit 1
fi

echo "[sync-official-plugins] source: ${resolved}"
echo "[sync-official-plugins] dest:   ${DEST}"

mkdir -p "${DEST}"
find "${DEST}" -mindepth 1 -maxdepth 1 ! -name '.gitignore' -exec rm -rf {} +

copied=0
for name in "${REQUIRED[@]}" "${RUNTIME_DIRS[@]}"; do
  src_plugin="${resolved}/${name}"
  if [[ ! -d "${src_plugin}" ]]; then
    echo "[sync-official-plugins] missing required plugin in source: ${name}" >&2
    exit 1
  fi
  ver="$(latest_version_dir "${src_plugin}")"
  if [[ -z "${ver}" ]]; then
    echo "[sync-official-plugins] no version directory under ${src_plugin}" >&2
    exit 1
  fi
  mkdir -p "${DEST}/${name}"
  cp -R "${src_plugin}/${ver}" "${DEST}/${name}/${ver}"
  echo "[sync-official-plugins] copied ${name}/${ver}"
  copied=$((copied + 1))
done

# Optional extras (same skip list as Windows).
while IFS= read -r dir; do
  [[ -n "${dir}" ]] || continue
  name="$(basename "${dir}")"
  contains "${name}" "${REQUIRED[@]}" && continue
  contains "${name}" "${RUNTIME_DIRS[@]}" && continue
  contains "${name}" "${SKIP_NAMES[@]}" && continue
  [[ -d "${DEST}/${name}" ]] && continue
  ver="$(latest_version_dir "${dir}")"
  [[ -n "${ver}" ]] || continue
  mkdir -p "${DEST}/${name}"
  cp -R "${dir}/${ver}" "${DEST}/${name}/${ver}"
  echo "[sync-official-plugins] copied extra ${name}/${ver}"
  copied=$((copied + 1))
done < <(find "${resolved}" -mindepth 1 -maxdepth 1 -type d)

# marketplace.json: prefer source copy, else generate a minimal listing.
if [[ -f "${resolved}/marketplace.json" ]]; then
  cp "${resolved}/marketplace.json" "${DEST}/marketplace.json"
else
  python - "${DEST}" <<'PY'
import json, sys
from pathlib import Path
dest = Path(sys.argv[1])
plugins = []
for child in sorted(dest.iterdir()):
    if not child.is_dir() or child.name in {"cua-helper"}:
        continue
    versions = [p for p in child.iterdir() if p.is_dir()]
    if not versions:
        continue
    ver = sorted(versions, key=lambda p: p.name)[-1]
    meta = {"name": child.name, "version": ver.name, "source": "filesystem", "cachePath": ""}
    for rel in (".evoflow-plugin/plugin.json", ".zcode-plugin/plugin.json", "package.json"):
        path = ver / rel
        if path.is_file():
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                obj = {}
            if isinstance(obj, dict):
                meta["name"] = obj.get("name") or meta["name"]
                meta["version"] = obj.get("version") or meta["version"]
                meta["displayName"] = obj.get("displayName") or meta["name"]
                meta["description"] = obj.get("description") or ""
                author = obj.get("author") or obj.get("publisher")
                if isinstance(author, dict) and author.get("name"):
                    meta["author"] = {"name": author["name"]}
            break
    plugins.append(meta)
payload = {
    "name": "evoflow-plugins-official",
    "description": "EvoFlow official plugins (packaged with the installer).",
    "plugins": plugins,
}
(dest / "marketplace.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
fi

missing=()
for name in "${REQUIRED[@]}"; do
  [[ -d "${DEST}/${name}" ]] || missing+=("${name}")
done
helper_entry="${DEST}/cua-helper/runtime/dist/windows-helper.js"
helper_addon="${DEST}/cua-helper/runtime/build/Release/ax_native.node"
if [[ ! -f "${helper_entry}" || ! -f "${helper_addon}" ]]; then
  missing+=("cua-helper/runtime (windows-helper.js + ax_native.node)")
fi
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "[sync-official-plugins] incomplete bundle, missing: ${missing[*]}" >&2
  exit 1
fi

if [[ ! -f "${DEST}/.gitignore" ]]; then
  printf '%s\n' '# Populated by packaging sync/fetch (do not commit blobs).' '*' '!.gitignore' \
    > "${DEST}/.gitignore"
fi

mb="$(du -sk "${DEST}" | awk '{printf "%.1f", $1/1024}')"
echo "[sync-official-plugins] OK: ${copied} trees, ${mb} MB -> ${DEST}"
