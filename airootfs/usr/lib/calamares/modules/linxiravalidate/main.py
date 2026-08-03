#!/usr/bin/env python3

import os
from pathlib import Path
import hashlib
import json
import re
import subprocess

import libcalamares


OBSOLETE_INITCPIO_MODULE = re.compile(
    r"(?<![A-Za-z0-9_-])crc32c(?:-|_)intel(?![A-Za-z0-9_-])"
)
DESKTOP_REQUIREMENTS = {
    "desktop-plasma": ("plasma.desktop", ()),
    "desktop-gnome": (
        "gnome.desktop",
        (
            "file-roller",
            "gnome-control-center",
            "gnome-disk-utility",
            "gnome-keyring",
            "gnome-session",
            "gnome-shell",
            "gnome-terminal",
            "gst-plugin-pipewire",
            "nautilus",
            "xdg-desktop-portal-gnome",
            "xdg-desktop-portal-gtk",
        ),
    ),
}


def pretty_name():
    return "Validate installed system"


def _target_path(root, path):
    return os.path.join(root, path.lstrip("/"))


def _obsolete_initcpio_configs(root):
    root_path = Path(root)
    candidates = [root_path / "etc/mkinitcpio.conf"]
    candidates.extend((root_path / "etc/mkinitcpio.conf.d").glob("*.conf"))
    candidates.extend((root_path / "etc/mkinitcpio.d").glob("*.preset"))

    obsolete = []
    for path in candidates:
        if not path.is_file():
            continue
        if OBSOLETE_INITCPIO_MODULE.search(path.read_text(encoding="utf-8")):
            obsolete.append("/" + path.relative_to(root_path).as_posix())
    return obsolete


def _reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key: " + key)
        value[key] = item
    return value


def _selection_requirements(root):
    receipt_path = Path(root) / "var/lib/linxira/installer-selection.json"
    receipt = json.loads(
        receipt_path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    selection = receipt.get("selectionDocument")
    if (
        receipt.get("schemaVersion") != "org.linxira.installer.selection-receipt.v1"
        or receipt.get("status") != "installed"
        or not isinstance(selection, dict)
        or selection.get("schemaVersion") != "org.linxira.component-selection.v1"
        or selection.get("catalogSha256") != receipt.get("catalogSha256")
        or selection.get("catalogRelease") != receipt.get("catalogRelease")
        or selection.get("selectedLeafIds") != receipt.get("selectedLeafIds")
        or selection.get("selectedBundleIds") != receipt.get("selectedBundleIds")
    ):
        raise ValueError("installer receipt provenance is missing or inconsistent")
    selected = set(selection["selectedLeafIds"]) & set(DESKTOP_REQUIREMENTS)
    if len(selected) != 1:
        raise ValueError("installer receipt must select exactly one desktop")
    desktop = selected.pop()
    session, packages = DESKTOP_REQUIREMENTS[desktop]
    return desktop, session, packages


def _selected_package_requirements(root):
    root_path = Path(root)
    receipt_path = root_path / "var/lib/linxira/installer-selection.json"
    receipt = json.loads(
        receipt_path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    catalog_path = root_path / "usr/share/linxira/catalog/catalog-v3.json"
    catalog_raw = catalog_path.read_bytes()
    if hashlib.sha256(catalog_raw).hexdigest() != receipt.get("catalogSha256"):
        raise ValueError("installed Catalog v3 digest does not match the installer receipt")
    catalog = json.loads(catalog_raw, object_pairs_hook=_reject_duplicate_keys)
    if catalog.get("catalogVersion") != 3 or catalog.get("release") != receipt.get("catalogRelease"):
        raise ValueError("installed Catalog v3 identity does not match the installer receipt")

    leaves = {
        item["id"]: item
        for section in ("desktops", "applications", "components", "operations")
        for item in catalog.get(section, [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    selected = receipt.get("selectedLeafIds")
    satisfied = receipt.get("satisfiedItems")
    pending = receipt.get("pendingItems")
    installed_items = receipt.get("installedItems")
    deferred_items = receipt.get("deferredItems")
    item_statuses = receipt.get("itemStatuses")
    installed = receipt.get("installedSelectedPackages")
    if not all(
        isinstance(value, list)
        for value in (
            selected,
            satisfied,
            pending,
            installed_items,
            deferred_items,
            item_statuses,
            installed,
        )
    ):
        raise ValueError("installer receipt package provenance is incomplete")
    if any(len(set(value)) != len(value) for value in (selected, satisfied, pending)):
        raise ValueError("installer receipt contains duplicate selection IDs")
    if not set(satisfied).issubset(set(selected)) or not set(pending).issubset(set(selected)):
        raise ValueError("installer receipt satisfied or pending items are not selected")
    if set(satisfied) | set(pending) != set(selected) or set(satisfied) & set(pending):
        raise ValueError("installer receipt does not classify every selected item")
    if installed_items != satisfied or deferred_items != pending:
        raise ValueError("installer receipt installed and deferred classifications disagree")
    satisfied_set = set(satisfied)
    expected_statuses = [
        {
            "id": leaf_id,
            "status": "installed" if leaf_id in satisfied_set else "explicitly-deferred",
        }
        for leaf_id in selected
    ]
    if item_statuses != expected_statuses:
        raise ValueError("installer receipt item statuses are inconsistent")

    packages = set()
    for leaf_id in satisfied:
        leaf = leaves.get(leaf_id)
        artifact = leaf.get("artifact", {}) if isinstance(leaf, dict) else {}
        if (
            not isinstance(leaf, dict)
            or leaf.get("provider") != "pacman"
            or leaf.get("source") != "arch"
            or artifact.get("type") not in {"package", "package-group"}
            or not isinstance(artifact.get("ids"), list)
        ):
            raise ValueError("satisfied item is not an Arch package leaf: " + str(leaf_id))
        packages.update(artifact["ids"])
    if any(not isinstance(package, str) for package in installed) or not set(installed).issubset(packages):
        raise ValueError("installer receipt lists an unauthorized selected package")
    return sorted(packages)


def _package_installed(root, package):
    result = subprocess.run(
        ["arch-chroot", root, "pacman", "-Q", package],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _package_or_group_installed(root, target):
    if _package_installed(root, target):
        return True
    result = subprocess.run(
        ["arch-chroot", root, "pacman", "-Sgq", target],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    members = tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
    return result.returncode == 0 and bool(members) and all(
        _package_installed(root, member) for member in members
    )


def _package_version(root, package):
    result = subprocess.run(
        ["arch-chroot", root, "pacman", "-Q", package],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    fields = result.stdout.strip().split()
    return fields[1] if result.returncode == 0 and len(fields) == 2 and fields[0] == package else None


def run():
    root = libcalamares.globalstorage.value("rootMountPoint")
    failures = []

    if not root or not os.path.ismount(root):
        return "Target is not mounted", "The target root mount is unavailable."

    try:
        desktop, selected_session, selected_packages = _selection_requirements(root)
        selected_packages = tuple(selected_packages) + tuple(_selected_package_requirements(root))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return "Installed system validation failed", "invalid installer selection receipt: " + str(error)

    required_packages = (
        "shelly",
        "linux",
        "linux-lts",
        "grub",
        "sddm",
        "linxira-artwork",
        "linxira-catalog",
        "linxira-chwd-detector",
        "linxira-component-manager",
        "linxira-completion-agent",
        "linxira-components",
        "linxira-config-hub",
        "linxira-gaming-manager",
        "linxira-hardware-driver-manager",
        "linxira-recovery-diagnostics",
        "linxira-package-center",
        "linxira-update",
        "linxira-welcome",
        "kinfocenter",
        "plasma-systemmonitor",
        "wireplumber",
        "xdg-desktop-portal",
        "xdg-desktop-portal-kde",
    )
    for package in required_packages:
        if not _package_installed(root, package):
            failures.append("missing package: " + package)
    for package in selected_packages:
        if not _package_or_group_installed(root, package):
            failures.append("missing selected package or group: " + package)
    required_versions = {
        "linxira-chwd-detector": "0.1.0-1",
        "linxira-components": "0.7.0-3",
        "linxira-hardware-driver-manager": "0.4.0-2",
    }
    for package, version in required_versions.items():
        installed = _package_version(root, package)
        if installed is None:
            failures.append("could not verify package version: " + package)
        elif installed != version:
            failures.append(f"unexpected package version: {package} {installed} (expected {version})")
    if _package_installed(root, "gdm"):
        failures.append("unsupported display manager installed: gdm")

    required_paths = (
        "/boot/grub/grub.cfg",
        "/boot/initramfs-linux.img",
        "/boot/initramfs-linux-lts.img",
        "/boot/vmlinuz-linux",
        "/boot/vmlinuz-linux-lts",
        "/etc/fstab",
        "/usr/bin/linxira-config",
        "/usr/bin/linxira-component-manager",
        "/usr/bin/linxira-completion-agent",
        "/usr/bin/linxira-components",
        "/usr/bin/linxira-gaming-manager",
        "/usr/bin/linxira-chwd-detector",
        "/usr/bin/linxira-hardware-driver-manager",
        "/usr/bin/linxira-recovery-diagnostics",
        "/usr/bin/linxira-package-center",
        "/usr/bin/linxira-update",
        "/usr/bin/linxira-welcome",
        "/usr/share/applications/org.linxira.PackageCenter.desktop",
        "/usr/share/applications/org.linxira.ComponentManager.desktop",
        "/usr/share/applications/org.linxira.GamingManager.desktop",
        "/usr/share/applications/org.linxira.HardwareDriverManager.desktop",
        "/usr/share/applications/org.linxira.RecoveryDiagnostics.desktop",
        "/usr/bin/linxira-components-service",
        "/usr/bin/linxira-components-worker",
        "/usr/lib/systemd/system/linxira-components.service",
        "/usr/lib/systemd/system/linxira-components-worker@.service",
        "/usr/share/dbus-1/system.d/org.linxira.Components1.conf",
        "/usr/share/polkit-1/actions/org.linxira.components.policy",
        "/usr/share/applications/org.linxira.Welcome.desktop",
        "/etc/xdg/autostart/org.linxira.Welcome.desktop",
        "/etc/xdg/autostart/org.linxira.Completion.desktop",
        "/etc/xdg/autostart/linxira-update-tray.desktop",
        "/usr/lib/systemd/user/linxira-update.timer",
        "/usr/share/linxira/catalog/catalog-v2.json",
        "/usr/share/linxira/catalog/catalog-v2.schema.json",
        "/usr/share/linxira/catalog/catalog-v3.json",
        "/usr/share/linxira/catalog/catalog-v3.schema.json",
        "/usr/share/linxira/welcome/i18n/zh_CN.json",
        "/var/lib/linxira/installer-selection.json",
        "/usr/share/wayland-sessions/plasma.desktop",
        "/usr/share/wayland-sessions/" + selected_session,
    )
    for path in required_paths:
        target_path = _target_path(root, path)
        if not os.path.isfile(target_path):
            failures.append("missing file: " + path)
        elif path.startswith("/boot/initramfs-") and os.path.getsize(target_path) == 0:
            failures.append("empty initramfs: " + path)

    for path in _obsolete_initcpio_configs(root):
        failures.append("obsolete initramfs module in: " + path)

    state_path = Path(root) / "var/lib/sddm/state.conf"
    expected_state = "[Last]\nSession=" + selected_session + "\n"
    if not state_path.is_file():
        failures.append("missing file: /var/lib/sddm/state.conf")
    elif state_path.read_text(encoding="utf-8") != expected_state:
        failures.append("SDDM default session does not match selected desktop: " + desktop)

    display_manager = Path(root) / "etc/systemd/system/display-manager.service"
    if not display_manager.is_symlink():
        failures.append("SDDM is not the sole display-manager service owner")
    elif os.readlink(display_manager) != "/usr/lib/systemd/system/sddm.service":
        failures.append("display-manager.service does not point to sddm.service")

    fstab_path = _target_path(root, "/etc/fstab")
    if os.path.isfile(fstab_path):
        with open(fstab_path, encoding="utf-8") as fstab:
            contents = fstab.read()
        for subvolume in ("@", "@home", "@log", "@cache", "@tmp", "@swap"):
            if "subvol=/" + subvolume not in contents and "subvol=" + subvolume not in contents:
                failures.append("fstab missing subvolume: " + subvolume)

    passwd_path = _target_path(root, "/etc/passwd")
    if os.path.isfile(passwd_path):
        with open(passwd_path, encoding="utf-8") as passwd:
            if any(line.startswith("installer:") for line in passwd):
                failures.append("live installer user retained")

    pacman_path = _target_path(root, "/etc/pacman.conf")
    if os.path.isfile(pacman_path):
        with open(pacman_path, encoding="utf-8") as pacman_conf:
            if "linxira-offline" in pacman_conf.read():
                failures.append("offline repository retained")

    grub_default_path = _target_path(root, "/etc/default/grub")
    if os.path.isfile(grub_default_path):
        contents = Path(grub_default_path).read_text(encoding="utf-8")
        if 'GRUB_DISTRIBUTOR="Linxira OS"' not in contents:
            failures.append("GRUB distributor is not branded as Linxira OS")
    else:
        failures.append("missing file: /etc/default/grub")

    grub_cfg_path = _target_path(root, "/boot/grub/grub.cfg")
    if os.path.isfile(grub_cfg_path):
        contents = Path(grub_cfg_path).read_text(encoding="utf-8", errors="replace")
        if "menuentry 'Arch Linux'" in contents or "Advanced options for Arch Linux" in contents:
            failures.append("GRUB menu still uses Arch Linux branding")
        if "Linxira OS" not in contents:
            failures.append("GRUB menu does not contain Linxira OS branding")

    live_only_paths = (
        "/etc/calamares",
        "/etc/xdg/autostart/linxira-installer.desktop",
        "/etc/sddm.conf.d/10-linxira-live.conf",
        "/etc/polkit-1/rules.d/49-linxira-installer.rules",
        "/usr/local/bin/linxira-installer-shell",
        "/usr/local/bin/linxira-live-session",
        "/usr/share/wayland-sessions/linxira-live.desktop",
        "/usr/lib/tmpfiles.d/linxira-live-tmpfiles.conf",
    )
    for path in live_only_paths:
        if os.path.exists(_target_path(root, path)):
            failures.append("live installer content retained: " + path)

    if failures:
        return "Installed system validation failed", "\n".join(failures)

    libcalamares.job.setprogress(1.0)
    return None
