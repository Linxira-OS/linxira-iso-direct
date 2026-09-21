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

declare -A available available_csize available_sha256
for desc in "$tmpdir"/*/desc; do
  [[ -f "$desc" ]] || continue
  pkgname=$(awk '/^%NAME%$/{getline; print; exit}' "$desc")
  filename=$(awk '/^%FILENAME%$/{getline; print; exit}' "$desc")
  csize=$(awk '/^%CSIZE%$/{getline; print; exit}' "$desc")
  sha256=$(awk '/^%SHA256SUM%$/{getline; print; exit}' "$desc")
  [[ -n "$pkgname" && -n "$filename" ]] && available[$pkgname]=$filename
  available_csize[$pkgname]=$csize
  available_sha256[$pkgname]=$sha256
done

missing=()
for pkg in "${packages[@]}"; do
  filename=${available[$pkg]:-}
  if [[ -z "$filename" ]]; then
    missing+=("$pkg")
    continue
  fi
  url="${repo}/${arch}/${filename}"
  expected_size=${available_csize[$pkg]:-0}
  expected_sha=${available_sha256[$pkg]:-}
  # 2026-09-21: 镜像网络抖动会产出静默截断包, 逐包校验大小与 sha256, 重试三次。
  ok=0
  for attempt in 1 2 3; do
    printf 'Fetching %s -> %s (attempt %d)\n' "$pkg" "$filename" "$attempt" >&2
    curl -fsSL --retry 2 --retry-delay 2 "$url" -o "${output_dir}/${filename}.part" && \
      [[ "$(stat -c %s "${output_dir}/${filename}.part" 2>/dev/null)" == "$expected_size" ]] && \
      [[ "$(sha256sum "${output_dir}/${filename}.part" 2>/dev/null | awk '{print $1}')" == "$expected_sha" ]] && {
        mv -f "${output_dir}/${filename}.part" "${output_dir}/${filename}"
        ok=1
        break
      }
    rm -f "${output_dir}/${filename}.part"
    sleep 2
  done
  if [[ $ok -ne 1 ]]; then
    missing+=("$pkg (download failed checksum verification)")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  printf 'The official [linxira] repository does not provide: %s\n' "${missing[*]}" >&2
  printf 'These packages are not yet released; build them locally and pass the paths to build-direct-iso.sh.\n' >&2
  exit 1
fi

printf 'Fetched %d package(s) into %s\n' "${#packages[@]}" "$output_dir" >&2