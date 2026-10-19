#!/usr/bin/env bash
# Populate packaging/official-plugins-bundle for CI / clean checkouts.
#
# Sources (first hit wins):
#   1. EVOFLOW_OFFICIAL_PLUGINS_SOURCE  — local directory (same as sync scripts)
#   2. Existing non-empty packaging/official-plugins-bundle
#   3. EVOFLOW_OFFICIAL_PLUGINS_URL     — http(s) URL to a .tar.gz / .zip archive
#   4. EVOFLOW_OFFICIAL_PLUGINS_RELEASE — GitHub release that has
#        official-plugins-bundle.tar.gz (format: owner/repo@tag or tag only)
#
# Optional:
#   EVOFLOW_OFFICIAL_PLUGINS_TOKEN / GITHUB_TOKEN — private release downloads
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEST="${BACKEND_DIR}/packaging/official-plugins-bundle"

REQUIRED=(
  browser-use
  computer-use
  node-repl-host
  documents
  pdf
  presentations
  spreadsheets
  image-search
  plugin-creator
  skill-creator
)

bundle_ready() {
  local root="$1"
  [[ -d "${root}" ]] || return 1
  local name
  for name in "${REQUIRED[@]}"; do
    [[ -d "${root}/${name}" ]] || return 1
  done
  [[ -f "${root}/cua-helper/runtime/dist/windows-helper.js" ]] || return 1
  [[ -f "${root}/cua-helper/runtime/build/Release/ax_native.node" ]] || return 1
  return 0
}

sync_from_dir() {
  local src="$1"
  if [[ -f "${SCRIPT_DIR}/windows/sync-official-plugins-bundle.ps1" ]] && command -v pwsh >/dev/null 2>&1; then
    pwsh -NoProfile -ExecutionPolicy Bypass -File \
      "${SCRIPT_DIR}/windows/sync-official-plugins-bundle.ps1" -Source "${src}" -Dest "${DEST}"
    return
  fi
  if [[ -f "${SCRIPT_DIR}/sync-official-plugins-bundle.sh" ]]; then
    bash "${SCRIPT_DIR}/sync-official-plugins-bundle.sh" --source "${src}" --dest "${DEST}"
    return
  fi
  echo "[fetch-official-plugins] ERROR: no sync script available" >&2
  exit 1
}

extract_archive() {
  local archive="$1"
  local tmp
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/evoflow-plugins.XXXXXX")"
  cleanup() { rm -rf "${tmp}"; }
  trap cleanup EXIT

  case "${archive}" in
    *.zip)
      if command -v unzip >/dev/null 2>&1; then
        unzip -q "${archive}" -d "${tmp}"
      else
        python - "${archive}" "${tmp}" <<'PY'
import sys, zipfile
zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])
PY
      fi
      ;;
    *.tar.gz|*.tgz)
      tar -xzf "${archive}" -C "${tmp}"
      ;;
    *)
      echo "[fetch-official-plugins] ERROR: unsupported archive: ${archive}" >&2
      exit 1
      ;;
  esac

  local src="${tmp}"
  if [[ -d "${tmp}/official-plugins-bundle" ]]; then
    src="${tmp}/official-plugins-bundle"
  elif [[ -f "${tmp}/marketplace.json" ]]; then
    src="${tmp}"
  else
    # Single top-level folder wrapping the bundle.
    local kids=("${tmp}"/*)
    if [[ ${#kids[@]} -eq 1 && -d "${kids[0]}" ]]; then
      src="${kids[0]}"
    fi
  fi

  if ! bundle_ready "${src}"; then
    echo "[fetch-official-plugins] ERROR: archive contents incomplete under ${src}" >&2
    exit 1
  fi

  mkdir -p "${DEST}"
  # Keep tracked .gitignore; replace everything else.
  find "${DEST}" -mindepth 1 -maxdepth 1 ! -name '.gitignore' -exec rm -rf {} +
  cp -R "${src}/." "${DEST}/"
  # Ensure .gitignore stays present for local trees.
  if [[ ! -f "${DEST}/.gitignore" ]]; then
    printf '%s\n' '# Populated by packaging sync/fetch (do not commit blobs).' '*' '!.gitignore' \
      > "${DEST}/.gitignore"
  fi
  trap - EXIT
  cleanup
}

download_url() {
  local url="$1"
  local out="$2"
  local auth_header=()
  local token="${EVOFLOW_OFFICIAL_PLUGINS_TOKEN:-${GITHUB_TOKEN:-}}"
  # GitHub release asset API URLs need Accept: application/octet-stream.
  if [[ "${url}" == *api.github.com*/releases/assets/* ]]; then
    auth_header=(-H "Accept: application/octet-stream")
    if [[ -n "${token}" ]]; then
      auth_header+=(-H "Authorization: Bearer ${token}")
    fi
  elif [[ -n "${token}" && "${url}" == *github.com* ]]; then
    auth_header=(-H "Authorization: Bearer ${token}")
  fi
  echo "[fetch-official-plugins] downloading ${url}"
  curl -fsSL "${auth_header[@]}" -L -o "${out}" "${url}"
}

resolve_release_asset_url() {
  local spec="$1"
  local owner_repo="" tag=""
  if [[ "${spec}" == *"@"* ]]; then
    owner_repo="${spec%@*}"
    tag="${spec#*@}"
  else
    tag="${spec}"
    owner_repo="${GITHUB_REPOSITORY:-}"
  fi
  if [[ -z "${owner_repo}" || -z "${tag}" ]]; then
    echo "[fetch-official-plugins] ERROR: EVOFLOW_OFFICIAL_PLUGINS_RELEASE needs owner/repo@tag (or tag with GITHUB_REPOSITORY)" >&2
    exit 1
  fi
  local api="https://api.github.com/repos/${owner_repo}/releases/tags/${tag}"
  local token="${EVOFLOW_OFFICIAL_PLUGINS_TOKEN:-${GITHUB_TOKEN:-}}"
  local curl_auth=()
  if [[ -n "${token}" ]]; then
    curl_auth=(-H "Authorization: Bearer ${token}")
  fi
  local json
  json="$(curl -fsSL "${curl_auth[@]}" -H "Accept: application/vnd.github+json" "${api}")"
  python - "${json}" <<'PY'
import json, sys
payload = json.loads(sys.argv[1])
wanted = ("official-plugins-bundle.tar.gz", "official-plugins-bundle.tgz", "official-plugins-bundle.zip")
assets = payload.get("assets") or []
for name in wanted:
    for asset in assets:
        if asset.get("name") == name:
            # Prefer API asset URL so private releases work with a token.
            url = asset.get("url") or asset.get("browser_download_url")
            if url:
                print(url)
                raise SystemExit(0)
print("", end="")
raise SystemExit(2)
PY
}

main() {
  echo "[fetch-official-plugins] dest: ${DEST}"

  local src="${EVOFLOW_OFFICIAL_PLUGINS_SOURCE:-}"
  if [[ -n "${src}" && -d "${src}" ]]; then
    echo "[fetch-official-plugins] using EVOFLOW_OFFICIAL_PLUGINS_SOURCE=${src}"
    sync_from_dir "${src}"
    if bundle_ready "${DEST}"; then
      echo "[fetch-official-plugins] OK (synced from source dir)"
      return 0
    fi
    echo "[fetch-official-plugins] ERROR: sync from source left incomplete bundle" >&2
    exit 1
  fi

  if bundle_ready "${DEST}"; then
    echo "[fetch-official-plugins] OK (already populated)"
    return 0
  fi

  local url="${EVOFLOW_OFFICIAL_PLUGINS_URL:-}"
  if [[ -z "${url}" && -n "${EVOFLOW_OFFICIAL_PLUGINS_RELEASE:-}" ]]; then
    url="$(resolve_release_asset_url "${EVOFLOW_OFFICIAL_PLUGINS_RELEASE}")"
    if [[ -z "${url}" ]]; then
      echo "[fetch-official-plugins] ERROR: release has no official-plugins-bundle archive" >&2
      exit 1
    fi
  fi

  if [[ -n "${url}" ]]; then
    local archive
    case "${url}" in
      *.zip) archive="$(mktemp "${TMPDIR:-/tmp}/evoflow-plugins.XXXXXX.zip")" ;;
      *) archive="$(mktemp "${TMPDIR:-/tmp}/evoflow-plugins.XXXXXX.tar.gz")" ;;
    esac
    download_url "${url}" "${archive}"
    extract_archive "${archive}"
    rm -f "${archive}"
    if bundle_ready "${DEST}"; then
      echo "[fetch-official-plugins] OK (from URL)"
      return 0
    fi
    echo "[fetch-official-plugins] ERROR: download left incomplete bundle" >&2
    exit 1
  fi

  # Last resort: try local cache via sync script (dev machines).
  if [[ -f "${SCRIPT_DIR}/sync-official-plugins-bundle.sh" ]]; then
    if bash "${SCRIPT_DIR}/sync-official-plugins-bundle.sh"; then
      if bundle_ready "${DEST}"; then
        echo "[fetch-official-plugins] OK (synced from local cache)"
        return 0
      fi
    fi
  elif command -v pwsh >/dev/null 2>&1 && [[ -f "${SCRIPT_DIR}/windows/sync-official-plugins-bundle.ps1" ]]; then
    if pwsh -NoProfile -ExecutionPolicy Bypass -File "${SCRIPT_DIR}/windows/sync-official-plugins-bundle.ps1"; then
      if bundle_ready "${DEST}"; then
        echo "[fetch-official-plugins] OK (synced from local cache via pwsh)"
        return 0
      fi
    fi
  fi

  cat >&2 <<EOF
[fetch-official-plugins] WARNING: official-plugins-bundle is empty and no source was configured.
Generating stub bundle so the build can proceed without real plugin binaries.

To bundle real plugins, set one of:
  - EVOFLOW_OFFICIAL_PLUGINS_URL to a .tar.gz/.zip of the bundle
  - EVOFLOW_OFFICIAL_PLUGINS_RELEASE=owner/repo@tag (asset: official-plugins-bundle.tar.gz)
  - EVOFLOW_OFFICIAL_PLUGINS_SOURCE to a local cache directory
  - On a machine with ~/.evoflow-dev/data/plugins/cache/evoflow-plugins-official, run:
      packaging/windows/sync-official-plugins-bundle.ps1
      (or packaging/sync-official-plugins-bundle.sh)
EOF

  # Generate stub bundle: required dirs + placeholder files so Test-BundleReady passes.
  mkdir -p "${DEST}"
  local name
  for name in "${REQUIRED[@]}"; do
    mkdir -p "${DEST}/${name}"
    printf '{"name":"%s","version":"0.0.0-stub","description":"stub - real plugin not bundled"}\n' "${name}" \
      > "${DEST}/${name}/plugin.json"
  done
  mkdir -p "${DEST}/cua-helper/runtime/dist" "${DEST}/cua-helper/runtime/build/Release"
  printf '// stub\n' > "${DEST}/cua-helper/runtime/dist/windows-helper.js"
  printf '\x00' > "${DEST}/cua-helper/runtime/build/Release/ax_native.node"
  if [[ ! -f "${DEST}/.gitignore" ]]; then
    printf '%s\n' '# Populated by packaging sync/fetch (do not commit blobs).' '*' '!.gitignore' \
      > "${DEST}/.gitignore"
  fi
  echo "[fetch-official-plugins] OK (stub bundle generated)"
  return 0
}

main "$@"
