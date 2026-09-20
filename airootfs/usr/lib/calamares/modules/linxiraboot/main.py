#!/usr/bin/env python3

import os
from pathlib import Path
import re
import shutil

import libcalamares


GRUB_TARGET = Path("etc/default/grub")
GRUB_BTRFS_TARGET = Path("etc/default/grub-btrfs/config")
MKINITCPIO_TARGET = Path("etc/mkinitcpio.conf")
TEMPLATE_DIR = Path("/usr/share/linxira/timeshift")
TEMPLATE_FILES = ("timeshift.json", "linxira-timeshift-autosnap.hook", "linxira-timeshift-enable.sh", "linxira-timeshift-prune.sh")

# 顶层平铺双内核: linux(最新) 与 linux-lts 都直接可见, GRUB_DEFAULT=0 默认最新。
# 2026-09-20 修复: GRUB_DEFAULT=0 的"第一项"由 grub 10_linux 字符串排序决定,
# "linux-lts" 会被误排到 "linux" 之前 —— 默认启动落进 LTS。GRUB_TOP_LEVEL
# 显式钉死主线内核为顶层默认项, LTS 仅作平铺菜单中的回退项。
GRUB_SETTINGS = [
    ("GRUB_DEFAULT", "0"),
    ("GRUB_TOP_LEVEL", '"/boot/vmlinuz-linux"'),
    ("GRUB_TIMEOUT", "5"),
    ("GRUB_DISABLE_SUBMENU", "true"),
    ("GRUB_DISABLE_RECOVERY", "true"),
    ("GRUB_DISABLE_OS_PROBER", "false"),
    ("GRUB_CMDLINE_LINUX_DEFAULT", '"quiet splash nowatchdog nvme_load=YES"'),
]

# 快照菜单: timeshift 后端 + 菜单条目上限 + 日期与描述
GRUB_BTRFS_SETTINGS = [
    ("GRUB_BTRFS_SNAPSHOT_BACKEND", '"timeshift"'),
    ("GRUB_BTRFS_LIMIT", '"10"'),
    ("GRUB_BTRFS_TITLE_FORMAT", '("date" "desc")'),
]


def pretty_name():
    return "Configure Linxira OS boot menu and snapshots"


def _set_config_value(path, key, value):
    """Replace (including commented-out) or append KEY=value in place."""
    pattern = re.compile(rf"^(#\s*)?{re.escape(key)}=.*$", re.MULTILINE)
    line = f"{key}={value}"
    contents = path.read_text(encoding="utf-8") if path.exists() else ""
    if pattern.search(contents):
        contents = pattern.sub(line, contents, count=1)
    else:
        contents = contents.rstrip("\n")
        contents = contents + ("\n" if contents else "") + line + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def _append_mkinitcpio_hook(path):
    """grub-btrfs 上游要求 grub-btrfs-overlayfs 位于 HOOKS 末尾。"""
    contents = path.read_text(encoding="utf-8")
    match = re.search(r"^HOOKS=\(([^)]*)\)", contents, flags=re.MULTILINE)
    if not match:
        raise RuntimeError("HOOKS is missing from /etc/mkinitcpio.conf")

    hooks = match.group(1).split()
    if "grub-btrfs-overlayfs" not in hooks:
        hooks.append("grub-btrfs-overlayfs")
        replacement = "HOOKS=(" + " ".join(hooks) + ")"
        contents = contents[:match.start()] + replacement + contents[match.end():]
        path.write_text(contents, encoding="utf-8")


def _copy_templates(root):
    target_dir = root / "usr/share/linxira/timeshift"
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in TEMPLATE_FILES:
        source = TEMPLATE_DIR / name
        if not source.is_file():
            raise RuntimeError(f"missing timeshift template: {source}")
        shutil.copy2(source, target_dir / name)


def run():
    root_value = libcalamares.globalstorage.value("rootMountPoint")
    if not root_value or not os.path.ismount(root_value):
        return "Target is not mounted", "The target root mount is unavailable."

    root = Path(root_value)
    try:
        grub_path = root / GRUB_TARGET
        for key, value in GRUB_SETTINGS:
            _set_config_value(grub_path, key, value)

        grub_btrfs_path = root / GRUB_BTRFS_TARGET
        if not grub_btrfs_path.exists():
            raise RuntimeError("/etc/default/grub-btrfs/config not found (grub-btrfs missing?)")
        for key, value in GRUB_BTRFS_SETTINGS:
            _set_config_value(grub_btrfs_path, key, value)

        _append_mkinitcpio_hook(root / MKINITCPIO_TARGET)
        _copy_templates(root)
    except (OSError, RuntimeError) as error:
        return "Boot and snapshot configuration failed", str(error)

    libcalamares.job.setprogress(1.0)
    return None
