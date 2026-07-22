#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  printf 'Usage: %s CALAMARES_PACKAGE ARTWORK_PACKAGE ROOTLESS_ARCH_ROOT\n' "${0##*/}" >&2
  exit 2
fi

profile_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
calamares_package=$(realpath "$1")
artwork_package=$(realpath "$2")
root=$(realpath "$3")

[[ -f "$calamares_package" ]]
[[ -f "$artwork_package" ]]
[[ -x "$root/usr/bin/pacman" ]]
command -v arch-chroot >/dev/null
command -v unshare >/dev/null
command -v bsdtar >/dev/null

unshare --map-auto --map-root-user env \
  ROOT="$root" PROFILE_DIR="$profile_dir" CALAMARES_PACKAGE="$calamares_package" ARTWORK_PACKAGE="$artwork_package" \
  bash -euo pipefail -c '
    rm -f "$ROOT/dev/fd" "$ROOT/dev/stdin" "$ROOT/dev/stdout" "$ROOT/dev/stderr"
    install -Dm644 "$CALAMARES_PACKAGE" "$ROOT/root/$(basename "$CALAMARES_PACKAGE")"
    mkdir -p "$ROOT/etc/calamares" "$ROOT/usr/lib/calamares/modules"
    cp -a "$PROFILE_DIR/airootfs/etc/calamares/." "$ROOT/etc/calamares/"
    cp -a "$PROFILE_DIR/airootfs/usr/lib/calamares/modules/linxirapacstrap" \
      "$PROFILE_DIR/airootfs/usr/lib/calamares/modules/linxirabranding" \
      "$PROFILE_DIR/airootfs/usr/lib/calamares/modules/linxirasession" \
      "$PROFILE_DIR/airootfs/usr/lib/calamares/modules/linxiravalidate" \
      "$ROOT/usr/lib/calamares/modules/"
    install -Dm644 "$PROFILE_DIR/target-packages.x86_64" \
      "$ROOT/etc/calamares/target-packages.x86_64"
    install -Dm644 "$PROFILE_DIR/offline-candidate-packages.x86_64" \
      "$ROOT/etc/calamares/offline-candidate-packages.x86_64"
    bsdtar -xOf "$ARTWORK_PACKAGE" usr/share/linxira/linxira-logo.svg \
      >"$ROOT/etc/calamares/branding/linxira/linxira-logo.svg"
  '

arch-chroot -N "$root" pacman -U --noconfirm "/root/$(basename "$calamares_package")"
arch-chroot -N "$root" env QT_QPA_PLATFORM=offscreen calamares --version

set +e
output=$(arch-chroot -N "$root" env QT_QPA_PLATFORM=offscreen \
  timeout --signal=TERM 15 calamares -d 2>&1)
status=$?
set -e
printf '%s\n' "$output"

if [[ $status -ne 0 && $status -ne 124 ]]; then
  printf 'Calamares exited unexpectedly with status %d.\n' "$status" >&2
  exit 1
fi
if grep -E -q 'Module .* not found|Cannot load|Configuration Error|YAML.*[Ee]rror' <<<"$output"; then
  printf 'Calamares reported a module or configuration error.\n' >&2
  exit 1
fi

printf 'CALAMARES_CONFIG_LOAD_OK\n'
