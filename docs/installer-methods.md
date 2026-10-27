# Installer methods (current and deferred)

## Current: Calamares GUI only

The ISO installs through Calamares. `airootfs/etc/calamares/settings.conf` is the
single sequence; partitioning is the upstream C++ `partition` module. There is
no preseed or unattended module in the Arch `calamares` package we ship.

The live ISO already carries the archiso automation hook
(`airootfs/root/.automated_script.sh`, kernel parameter `script=`), but nothing
currently uses it to install.

## Deferred: unattended / CLI install

Decision (2026-10-27): do not implement in the current release cycle.

When revisited, the intended shape is:

- `linxira.autoinstall=1` kernel parameter, handled by a systemd unit (not the
  tty1-only archiso hook, so serial consoles work).
- Config read from QEMU `fw_cfg`
  (`/sys/firmware/qemu_fw_cfg/by_name/opt/linxira/autoinstall/raw`), a small
  `LINXIRA`-labelled FAT disk, or HTTP only when explicitly allowed.
- `linxira-install --config install.yaml --yes`, with `--dry-run` and `--json`.
- v1 scope: blank disk only (GPT + 1 GiB ESP + btrfs subvolumes + GRUB).
  Alongside-Windows, LUKS, and manual layouts stay GUI-only.
- Shared core extracted from `linxirapacstrap`, `linxiravalidate`, and
  `linxiraboot` so Calamares and the CLI cannot drift.

## Deferred: server profile package split

`desktop-server` currently installs the full `target-packages.x86_64` baseline,
including desktop-only GUI packages. Splitting it into `base` and
`desktop-common` layers is deferred until at least one year of release
stability. It also requires profile-aware validation in `linxiravalidate`.

## Deferred: VM / cloud images

No qcow2, OCI, or cloud-init variants in the current cycle. If demand appears,
build one image with cloud-init as an optional datasource; do not ship separate
cloud and non-cloud artifacts. The ISO remains the single large download.

## WSL

WSL uses a prebuilt rootfs tarball and skips the installer entirely. Default
root is acceptable; user creation is optional. No cloud-init.
