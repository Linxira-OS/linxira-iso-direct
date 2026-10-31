#!/bin/sh
# Linxira: remove the btrfs /boot/grub/grubenv after grub-install.
#
# UEFI installs use EFI/linxira/grubenv on the ESP (see 02_linxira-env).
# grub-install creates an empty /boot/grub/grubenv on btrfs; loading it can
# fail with "sparse file not allowed" before the menu appears.  Keep the boot
# env on FAT only.  BIOS installs have no ESP and must keep the btrfs block.
set -eu

[ -f /etc/fstab ] || exit 0
esp=$(awk '$2 == "/boot/efi" || $2 == "/efi" { print $2; exit }' /etc/fstab)
[ -n "${esp}" ] || exit 0
rm -f /boot/grub/grubenv
