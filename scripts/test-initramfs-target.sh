#!/usr/bin/env bash
set -euo pipefail

if (( EUID != 0 )); then
  exec sudo -- "$0" "$@"
fi

work_dir=${1:-/var/tmp/linxira-initramfs-integration}
target=${work_dir}/target
filesystem_image=${work_dir}/target.btrfs
pacstrap_log=${work_dir}/pacstrap.log
mkinitcpio_log=${work_dir}/mkinitcpio.log

if [[ -e $work_dir ]]; then
  printf 'Refusing to reuse integration directory: %s\n' "$work_dir" >&2
  exit 2
fi

install -d -m 0755 "$target"
truncate -s 4G "$filesystem_image"
mkfs.btrfs -q -f "$filesystem_image"
mount -o loop "$filesystem_image" "$target"
cleanup() {
  gpgconf --homedir "$target/etc/pacman.d/gnupg" --kill all \
    >/dev/null 2>&1 || true
  for _ in {1..20}; do
    if ! mountpoint -q "$target" || umount "$target" 2>/dev/null; then
      return
    fi
    sleep 0.25
  done
  umount "$target"
}
trap cleanup EXIT

pacstrap -K -M "$target" \
  base btrfs-progs linux linux-lts plymouth >"$pacstrap_log" 2>&1

test -s "$target/etc/mkinitcpio.d/linux.preset"
test -s "$target/etc/mkinitcpio.d/linux-lts.preset"
test -s "$target/boot/initramfs-linux.img"
test -s "$target/boot/initramfs-linux-lts.img"

sed -i \
  -e 's/^MODULES=.*/MODULES=()/' \
  -e 's/^HOOKS=.*/HOOKS=(base udev autodetect microcode kms modconf block keyboard keymap plymouth filesystems)/' \
  "$target/etc/mkinitcpio.conf"
printf 'KEYMAP=us\n' >"$target/etc/vconsole.conf"
if grep -R -n -E 'crc32c[-_]intel' \
  "$target/etc/mkinitcpio.conf" \
  "$target/etc/mkinitcpio.conf.d" \
  "$target/etc/mkinitcpio.d" >"${work_dir}/obsolete-modules.log" 2>&1; then
  printf 'obsolete CRC32C module remains in target configuration\n' >&2
  exit 1
fi

arch-chroot "$target" mkinitcpio -P >"$mkinitcpio_log" 2>&1
if grep -q '^==> ERROR:' "$mkinitcpio_log"; then
  printf 'mkinitcpio reported an error despite returning success\n' >&2
  exit 1
fi
test -s "$target/boot/initramfs-linux.img"
test -s "$target/boot/initramfs-linux-lts.img"
sha256sum \
  "$target/boot/initramfs-linux.img" \
  "$target/boot/initramfs-linux-lts.img" >"${work_dir}/initramfs.sha256"

printf 'initramfs integration passed: %s\n' "$work_dir"
