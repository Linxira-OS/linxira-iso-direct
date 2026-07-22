# Direct-Arch ISO Profile

This profile builds a development installer ISO from Arch packages plus pinned
local artifacts for Calamares, Shelly, artwork, and Linxira system software. Discover is deliberately
excluded. Linxira Package Center is the catalog application installer; Shelly
remains available for reviewed recommendations and package browsing. Package
Center creates application plans and confirmations. Component Manager provides
the nested capability tree. Both authorize the root-only `linxira-components`
backend to execute one pacman transaction and persist its receipt. KDE Plasma is
the default desktop in both environments.

Fresh Shelly profiles leave AUR, Flatpak, AppImage, and background tray checks
disabled. Enabling background checks does not enable or query another source.

Build with a verified local package artifact:

```bash
./build-direct-iso.sh \
  --shelly-package /path/to/shelly-2.4.1.4-1-x86_64.pkg.tar.zst \
  --calamares-package /path/to/calamares-3.3.14-1-x86_64.pkg.tar.zst \
  --artwork-package /path/to/linxira-artwork-1.0.3-1-any.pkg.tar.zst \
  --catalog-package /path/to/linxira-catalog-3.0.0-1-any.pkg.tar.zst \
  --components-package /path/to/linxira-components-0.7.0-1-any.pkg.tar.zst \
  --component-manager-package /path/to/linxira-component-manager-0.1.0-1-any.pkg.tar.zst \
  --completion-agent-package /path/to/linxira-completion-agent-0.1.1-1-any.pkg.tar.zst \
  --gaming-manager-package /path/to/linxira-gaming-manager-0.3.0-1-any.pkg.tar.zst \
  --chwd-detector-package /path/to/linxira-chwd-detector-0.1.0-1-x86_64.pkg.tar.zst \
  --hardware-driver-manager-package /path/to/linxira-hardware-driver-manager-0.4.0-1-any.pkg.tar.zst \
  --recovery-diagnostics-package /path/to/linxira-recovery-diagnostics-0.2.0-1-any.pkg.tar.zst \
  --update-package /path/to/linxira-update-0.1.0-1-any.pkg.tar.zst \
  --config-hub-package /path/to/linxira-config-hub-2.2.0-1-any.pkg.tar.zst \
  --package-center-package /path/to/linxira-package-center-0.2.1-1-any.pkg.tar.zst \
  --welcome-package /path/to/linxira-welcome-1.0.0-2-any.pkg.tar.zst \
  --plymouth-theme-directory /path/to/linxira-plymouth-theme \
  --output ./out
```

The wrapper validates each package identity and critical archive path, then
copies the profile to a temporary directory and creates two repositories.
`linxira-local` is a build-only repository for all supplied artifacts and is
removed afterward. Live and target environments install the same Linxira-owned
files through pacman; the build never copies sibling working-tree source.
`linxira-offline`
contains the exact target package closure from a fresh build-scoped cache and is embedded under
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

The installer uses a fixed offline Plasma baseline and a separate reviewed
offline candidate manifest. The repository contains their dependency union,
but pacstrap adds only eligible included artifacts selected through Catalog v3.
Legacy
flat desktop, component, and application chooser pages were removed because
they used Catalog v2 and could start an unfrozen online package transaction.
The installer selection is supplied by the packaged native Calamares Catalog
v3 viewmodule. After first boot, Package Center and Component Manager remain the
canonical application and component selection surfaces.

GNOME wallpaper gsettings are intentionally deferred in this profile: canonical
wallpaper files are supplied by the packaged artwork rather than an ISO overlay,
so this repository cannot validate their installed path without building the
package or ISO. Plasma's existing package-owned wallpaper configuration remains
unchanged.

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
