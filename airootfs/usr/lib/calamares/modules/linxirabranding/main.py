#!/usr/bin/env python3

import os
from pathlib import Path
import re
import shlex
import shutil

import libcalamares


def pretty_name():
    return "Configure Linxira OS branding"


def _copy_file(source, target_root, relative_target=None):
    source_path = Path(source)
    target_path = Path(target_root) / (relative_target or source_path.relative_to("/"))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.is_symlink():
        target_path.unlink()
    shutil.copy2(source_path, target_path)


def _install_target_plasma_layout(source, target_root, relative_target=None):
    source_path = Path(source)
    target_path = Path(target_root) / (relative_target or source_path.relative_to("/"))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    contents = source_path.read_text(encoding="utf-8")
    contents = contents.replace("applications:linxira-installer.desktop,", "")
    target_path.write_text(contents, encoding="utf-8")


def _enable_plymouth(mkinitcpio_path):
    contents = mkinitcpio_path.read_text(encoding="utf-8")
    match = re.search(r"^HOOKS=\(([^)]*)\)", contents, flags=re.MULTILINE)
    if not match:
        raise RuntimeError("HOOKS is missing from /etc/mkinitcpio.conf")

    hooks = match.group(1).split()
    if "plymouth" not in hooks:
        anchor = "systemd" if "systemd" in hooks else "udev"
        hooks.insert(hooks.index(anchor) + 1, "plymouth")
        replacement = "HOOKS=(" + " ".join(hooks) + ")"
        contents = contents[:match.start()] + replacement + contents[match.end():]
        mkinitcpio_path.write_text(contents, encoding="utf-8")


def _remove_obsolete_modules(mkinitcpio_path):
    contents = mkinitcpio_path.read_text(encoding="utf-8")
    match = re.search(r"^MODULES=\(([^)]*)\)", contents, flags=re.MULTILINE)
    if not match:
        raise RuntimeError("MODULES is missing from /etc/mkinitcpio.conf")

    modules = shlex.split(match.group(1))
    obsolete_modules = {"crc32c-intel", "crc32c_intel"}
    modules = [module for module in modules if module not in obsolete_modules]
    replacement = "MODULES=(" + " ".join(modules) + ")"
    contents = contents[:match.start()] + replacement + contents[match.end():]
    mkinitcpio_path.write_text(contents, encoding="utf-8")


def _fix_console_keymap(root):
    vconsole_path = Path(root) / "etc/vconsole.conf"
    if not vconsole_path.exists():
        return

    contents = vconsole_path.read_text(encoding="utf-8")
    match = re.search(r'^KEYMAP=(?:"([^"]+)"|(\S+))', contents, flags=re.MULTILINE)
    if not match:
        return

    keymap = match.group(1) or match.group(2)
    keymap_root = Path(root) / "usr/share/kbd/keymaps"
    keymap_exists = any(keymap_root.rglob(f"{keymap}.map")) or any(
        keymap_root.rglob(f"{keymap}.map.gz")
    )
    if not keymap_exists:
        contents = contents[:match.start()] + "KEYMAP=us" + contents[match.end():]
        vconsole_path.write_text(contents, encoding="utf-8")


def run():
    root = libcalamares.globalstorage.value("rootMountPoint")
    if not root or not os.path.ismount(root):
        return "Target is not mounted", "The target root mount is unavailable."

    try:
        _copy_file("/etc/os-release", root)
        _copy_file("/etc/fastfetch/config.d/linxira.jsonc", root)
        _copy_file("/usr/share/linxira/catalog/catalog-v2.json", root)
        _copy_file("/usr/share/linxira/catalog/catalog-v2.schema.json", root)
        _copy_file("/usr/share/doc/linxira-artwork/TRADEMARKS.md", root)
        _copy_file("/usr/local/bin/linxira-config", root)
        _copy_file("/usr/bin/linxira-package-center", root)
        _copy_file("/usr/bin/linxira-components", root)
        _copy_file("/usr/bin/linxira-welcome", root)
        _copy_file("/usr/share/applications/org.linxira.Welcome.desktop", root)
        _copy_file("/usr/share/applications/org.linxira.PackageCenter.desktop", root)
        _copy_file("/etc/xdg/autostart/org.linxira.Welcome.desktop", root)
        shutil.copytree(
            "/usr/lib/linxira-components",
            Path(root) / "usr/lib/linxira-components",
            dirs_exist_ok=True,
        )
        shutil.copytree(
            "/usr/share/linxira/welcome",
            Path(root) / "usr/share/linxira/welcome",
            dirs_exist_ok=True,
        )
        _copy_file("/etc/skel/.bashrc", root)
        _copy_file("/etc/skel/.config/kdeglobals", root)
        _install_target_plasma_layout(
            "/etc/skel/.config/plasma-org.kde.plasma.desktop-appletsrc",
            root,
        )

        theme_source = Path("/usr/share/plymouth/themes/linxira")
        theme_target = Path(root) / "usr/share/plymouth/themes/linxira"
        shutil.copytree(theme_source, theme_target, dirs_exist_ok=True)

        plymouth_config = Path(root) / "etc/plymouth/plymouthd.conf"
        plymouth_config.parent.mkdir(parents=True, exist_ok=True)
        plymouth_config.write_text("[Daemon]\nTheme=linxira\nShowDelay=0\n", encoding="utf-8")
        mkinitcpio_path = Path(root) / "etc/mkinitcpio.conf"
        _fix_console_keymap(root)
        _remove_obsolete_modules(mkinitcpio_path)
        _enable_plymouth(mkinitcpio_path)
    except (OSError, RuntimeError) as error:
        return "Branding configuration failed", str(error)

    libcalamares.job.setprogress(1.0)
    return None
