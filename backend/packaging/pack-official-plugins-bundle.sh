#!/usr/bin/env bash
# Create official-plugins-bundle.tar.gz for CI / release asset upload.
#
# Usage (from a machine that already has the synced bundle):
#   bash backend/packaging/pack-official-plugins-bundle.sh
#   # -> backend/packaging/official-plugins-bundle.tar.gz
#
# Upload that archive to a GitHub Release (asset name must match), then set
# EVOFLOW_OFFICIAL_PLUGINS_RELEASE=owner/repo@tag in CI secrets/vars.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUNDLE="${BACKEND_DIR}/packaging/official-plugins-bundle"
OUT="${1:-${BACKEND_DIR}/packaging/official-plugins-bundle.tar.gz}"

if [[ ! -d "${BUNDLE}/browser-use" ]]; then
  echo "[pack-official-plugins] bundle empty — run sync-official-plugins-bundle first" >&2
  exit 1
fi

tmp="$(mktemp -d "${TMPDIR:-/tmp}/evoflow-pack-plugins.XXXXXX")"
cleanup() { rm -rf "${tmp}"; }
trap cleanup EXIT

stage="${tmp}/official-plugins-bundle"
mkdir -p "${stage}"
# Copy contents but skip the local .gitignore (archive consumers don't need it).
shopt -s dotglob nullglob
for item in "${BUNDLE}"/*; do
  base="$(basename "${item}")"
  [[ "${base}" == ".gitignore" ]] && continue
  cp -R "${item}" "${stage}/${base}"
done
shopt -u dotglob nullglob

mkdir -p "$(dirname "${OUT}")"
tar -C "${tmp}" -czf "${OUT}" official-plugins-bundle
mb="$(du -sk "${OUT}" | awk '{printf "%.1f", $1/1024}')"
echo "[pack-official-plugins] wrote ${OUT} (${mb} MB)"
