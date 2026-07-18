#!/usr/bin/env bash
set -euo pipefail

sed -i '/^\[linxira-local\]$/,/^$/d' /etc/pacman.conf
plymouth-set-default-theme linxira
mkinitcpio -p linux
