#!/usr/bin/env bash
# Fetch the Linxira self-built package closure from the official [linxira]
# repository so build-direct-iso.sh can be run reproducibly from released
# artifacts instead of locally built .pkg.tar.zst files.
#
# The local-path interface of build-direct-iso.sh is retained: this script is
# the "pull from the official repo" path. Local artifacts remain acceptable
# only for third-party packages that were cached locally; self-built Linxira
# packages should come from this official repository.
set -euo pipefail

usage() {
  printf 'Usage: %s [--repo URL] [--arch x86_64] [--output DIR] [--help] [PKG...]\n' "${0##*/}" >&2
  printf 'Fetches the Linxira self-built packages needed by build-direct-iso.sh.\n' >&2
  printf 'Default packages cover the full build-direct-iso.sh artifact set.\n' >&2
}

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
profile_dir=$(cd -- "$script_dir/.." && pwd)
repo_url=${LINXIRA_REPO_URL:-https://linxira-os.github.io/linxira-packages}
arch=${LINXIRA_ARCH:-x86_64}
output_dir="${profile_dir}/.linxira-packages"

default_packages=(
  shelly
  calamares
  linxira-artwork
  linxira-catalog
  linxira-components
  linxira-component-manager
  linxira-completion-agent
  linxira-config-hub
  linxira-package-center
  linxira-gaming-manager
  linxira-hwd-detector
  linxira-hardware-driver-manager
  linxira-recovery-diagnostics
  linxira-update
  linxira-welcome
  linxira-keyring
)

packages=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      repo_url=$2
      shift 2
      ;;
    --arch)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      arch=$2
      shift 2
      ;;
    --output)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      output_dir=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      packages+=("$1")
      shift
      ;;
  esac
done
if [[ ${#packages[@]} -eq 0 ]]; then
  packages=("${default_packages[@]}")
fi

command -v bsdtar >/dev/null || { printf 'bsdtar is required.\n' >&2; exit 1; }

repo=${repo_url%/}
db_url="${repo}/${arch}/linxira.db.tar.zst"
mkdir -p "$output_dir"

tmpdir=$(mktemp -d "${profile_dir}/.linxira-fetch.XXXXXX")
cleanup() {
  rm -rf "$tmpdir" 2>/dev/null || true
}
trap cleanup EXIT

printf 'Downloading %s ...\n' "$db_url" >&2
curl -fsSL "$db_url" -o "$tmpdir/linxira.db.tar.zst"
bsdtar -xf "$tmpdir/linxira.db.tar.zst" -C "$tmpdir"

declare -A available
for desc in "$tmpdir"/*/desc; do
  [[ -f "$desc" ]] || continue
  pkgname=$(awk '/^%NAME%$/{getline; print; exit}' "$desc")
  filename=$(awk '/^%FILENAME%$/{getline; print; exit}' "$desc")
  [[ -n "$pkgname" && -n "$filename" ]] && available[$pkgname]=$filename
done

missing=()
for pkg in "${packages[@]}"; do
  filename=${available[$pkg]:-}
  if [[ -z "$filename" ]]; then
    missing+=("$pkg")
    continue
  fi
  url="${repo}/${arch}/${filename}"
  printf 'Fetching %s -> %s\n' "$pkg" "$filename" >&2
  curl -fsSL "$url" -o "${output_dir}/${filename}"
done

if [[ ${#missing[@]} -gt 0 ]]; then
  printf 'The official [linxira] repository does not provide: %s\n' "${missing[*]}" >&2
  printf 'These packages are not yet released; build them locally and pass the paths to build-direct-iso.sh.\n' >&2
  exit 1
fi

printf 'Fetched %d package(s) into %s\n' "${#packages[@]}" "$output_dir" >&2