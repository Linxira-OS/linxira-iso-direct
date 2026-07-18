# Direct-Arch ISO Profile

This profile builds a development installer ISO from Arch packages plus locally
built Calamares, Shelly, and Linxira artwork packages. Discover is deliberately
excluded; Shelly is the default graphical package manager in both the live
environment and the fixed Standard target package set. KDE Plasma is the
default desktop in both environments.

Fresh Shelly profiles leave AUR, Flatpak, AppImage, and background tray checks
disabled. Enabling background checks does not enable or query another source.

Build with a verified local package artifact:

```bash
./build-direct-iso.sh \
  --shelly-package /path/to/shelly-2.4.1.4-1-x86_64.pkg.tar.zst \
  --calamares-package /path/to/calamares-3.3.14-1-x86_64.pkg.tar.zst \
  --artwork-package /path/to/linxira-artwork-1.0.3-1-any.pkg.tar.zst \
  --plymouth-theme-directory /path/to/linxira-plymouth-theme \
  --output ./out
```

The wrapper copies the profile to a temporary directory and creates two
repositories. `linxira-local` is a build-only repository for Calamares, Shelly,
and the canonical artwork package and is removed afterward. `linxira-offline`
contains the exact target package closure and is embedded under
`/opt/linxira/offline-repo`; Calamares uses it without copying that repository
configuration into the target.

Both repositories accept unsigned development packages. Release images must
replace this with packages and repository metadata signed by the Linxira key.
The build-only `linxira-local` stanza is removed from the live pacman
configuration before the SquashFS image is created.

`profile-symlinks.list` records the Linux symlinks that cannot be represented
reliably when this profile is stored on Windows. The build wrapper recreates
them in its temporary Linux profile before invoking `mkarchiso`.

The current Calamares slice supports an unencrypted, GPT, Btrfs installation
with the documented subvolumes, GRUB, `linux` plus `linux-lts`, Plasma, and
Shelly. It validates required packages, kernels, GRUB configuration, Btrfs
mounts, and absence of live-installer content before reporting success.

This slice still requires disposable-VM installation and boot acceptance. BIOS,
encryption, the responsive kernel profile, signed offline metadata, and initial
Timeshift snapshot creation remain release blockers.

Calamares configuration can be loaded without modifying the host system by
using a rootless Arch root:

```bash
bash scripts/validate-calamares-config.sh \
  /path/to/calamares-3.3.14-1-x86_64.pkg.tar.zst \
  /path/to/linxira-artwork-1.0.3-1-any.pkg.tar.zst \
  /path/to/rootless-arch-root
```
