#!/usr/bin/env python3

import os
import subprocess

import libcalamares


def pretty_name():
    return "Validate installed system"


def _target_path(root, path):
    return os.path.join(root, path.lstrip("/"))


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
        "/boot/vmlinuz-linux",
        "/boot/vmlinuz-linux-lts",
        "/etc/fstab",
        "/usr/local/bin/linxira-config",
        "/usr/share/linxira/catalog/catalog-v2.json",
        "/var/lib/linxira/installer-selection.json",
    )
    for path in required_paths:
        if not os.path.isfile(_target_path(root, path)):
            failures.append("missing file: " + path)

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
