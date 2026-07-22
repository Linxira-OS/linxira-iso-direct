#!/usr/bin/env python3

import os
from pathlib import Path
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


def _package_installed(root, package):
    result = subprocess.run(
        ["arch-chroot", root, "pacman", "-Q", package],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def run():
    root = libcalamares.globalstorage.value("rootMountPoint")
    failures = []

    if not root or not os.path.ismount(root):
        return "Target is not mounted", "The target root mount is unavailable."

    try:
        desktop, selected_session, selected_packages = _selection_requirements(root)
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
        "linxira-component-manager",
        "linxira-completion-agent",
        "linxira-components",
        "linxira-config-hub",
        "linxira-gaming-manager",
        "linxira-recovery-diagnostics",
        "linxira-package-center",
        "linxira-update",
        "linxira-welcome",
        "kinfocenter",
        "plasma-systemmonitor",
        "wireplumber",
        "xdg-desktop-portal",
        "xdg-desktop-portal-kde",
    ) + selected_packages
    for package in required_packages:
        if not _package_installed(root, package):
            failures.append("missing package: " + package)
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
        "/usr/bin/linxira-recovery-diagnostics",
        "/usr/bin/linxira-package-center",
        "/usr/bin/linxira-update",
        "/usr/bin/linxira-welcome",
        "/usr/share/applications/org.linxira.PackageCenter.desktop",
        "/usr/share/applications/org.linxira.ComponentManager.desktop",
        "/usr/share/applications/org.linxira.GamingManager.desktop",
        "/usr/share/applications/org.linxira.RecoveryDiagnostics.desktop",
        "/usr/bin/linxira-components-service",
        "/usr/lib/systemd/system/linxira-components.service",
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
