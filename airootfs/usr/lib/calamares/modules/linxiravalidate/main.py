#!/usr/bin/env python3

import os
from pathlib import Path
import re
import subprocess

import libcalamares


OBSOLETE_INITCPIO_MODULE = re.compile(
    r"(?<![A-Za-z0-9_-])crc32c(?:-|_)intel(?![A-Za-z0-9_-])"
)


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


def run():
    root = libcalamares.globalstorage.value("rootMountPoint")
    failures = []

    if not root or not os.path.ismount(root):
        return "Target is not mounted", "The target root mount is unavailable."

    for package in (
        "shelly",
        "linux",
        "linux-lts",
        "grub",
        "sddm",
        "linxira-artwork",
        "linxira-catalog",
        "linxira-component-manager",
        "linxira-components",
        "linxira-config-hub",
        "linxira-package-center",
        "linxira-welcome",
        "kinfocenter",
        "plasma-systemmonitor",
    ):
        result = subprocess.run(
            ["arch-chroot", root, "pacman", "-Q", package],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            failures.append("missing package: " + package)

    required_paths = (
        "/boot/grub/grub.cfg",
        "/boot/initramfs-linux.img",
        "/boot/initramfs-linux-lts.img",
        "/boot/vmlinuz-linux",
        "/boot/vmlinuz-linux-lts",
        "/etc/fstab",
        "/usr/bin/linxira-config",
        "/usr/bin/linxira-component-manager",
        "/usr/bin/linxira-components",
        "/usr/bin/linxira-package-center",
        "/usr/bin/linxira-welcome",
        "/usr/share/applications/org.linxira.PackageCenter.desktop",
        "/usr/share/applications/org.linxira.ComponentManager.desktop",
        "/usr/share/applications/org.linxira.Welcome.desktop",
        "/etc/xdg/autostart/org.linxira.Welcome.desktop",
        "/usr/share/linxira/catalog/catalog-v2.json",
        "/usr/share/linxira/catalog/catalog-v2.schema.json",
        "/usr/share/linxira/catalog/catalog-v3.json",
        "/usr/share/linxira/catalog/catalog-v3.schema.json",
        "/usr/share/linxira/welcome/i18n/zh_CN.json",
    )
    for path in required_paths:
        target_path = _target_path(root, path)
        if not os.path.isfile(target_path):
            failures.append("missing file: " + path)
        elif path.startswith("/boot/initramfs-") and os.path.getsize(target_path) == 0:
            failures.append("empty initramfs: " + path)

    for path in _obsolete_initcpio_configs(root):
        failures.append("obsolete initramfs module in: " + path)

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
