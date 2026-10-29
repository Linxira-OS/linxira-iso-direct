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
WORKSPACE_TEMPLATE_DIR = Path("/usr/share/linxira/workspace-guard")
WORKSPACE_TEMPLATE_FILES = ("linxira-workspace-guard-install.sh",)

# 顶层平铺双内核: linux(最新) 与 linux-lts 都直接可见, GRUB_DEFAULT=0 默认最新。
# 2026-09-20 修复: GRUB_DEFAULT=0 的"第一项"由 grub 10_linux 字符串排序决定,
# "linux-lts" 会被误排到 "linux" 之前 —— 默认启动落进 LTS。GRUB_TOP_LEVEL
# 显式钉死主线内核为顶层默认项, LTS 仅作平铺菜单中的回退项。
GRUB_SETTINGS = [
    # 记住上次启动项: Windows 重启回 Windows, Linux 重启回 Linux。
    # 初次安装由 _seed_saved_entry 写入 saved_entry=0(主线内核); 之后 GRUB
    # 在用户选择条目时更新。不再固定 GRUB_DEFAULT=0 把用户按在 Linux。
    ("GRUB_DEFAULT", "saved"),
    ("GRUB_SAVEDEFAULT", "true"),
    ("GRUB_TOP_LEVEL", '"/boot/vmlinuz-linux"'),
    ("GRUB_TIMEOUT", "5"),
    ("GRUB_DISABLE_SUBMENU", "true"),
    ("GRUB_DISABLE_RECOVERY", "true"),
    # 默认开 os-prober; 安装期检测到目标 ESP 的 Windows 后改为 true,
    # 只保留确定性生成的 Windows 条目, 避免两个同名条目。
    ("GRUB_DISABLE_OS_PROBER", "false"),
    ("GRUB_CMDLINE_LINUX_DEFAULT", '"quiet splash nowatchdog nvme_load=YES"'),
    # 2026-10-26: 安装后保持与 ISO 一致的引导外观(不再是一片黑白纯文本)。
    ("GRUB_TERMINAL_OUTPUT", '"gfxterm"'),
    ("GRUB_TIMEOUT_STYLE", '"menu"'),
    ("GRUB_THEME", '"/boot/grub/themes/linxira/theme-24.txt"'),
    # 优先尝试高分辨率; 全部不支持时回退 auto。2.8K/4K 不再落进 1024x768。
    ("GRUB_GFXMODE", '"3840x2160,2880x1800,2560x1600,2560x1440,1920x1080,auto"'),
    ("GRUB_GFXPAYLOAD_LINUX", '"keep"'),
    # 主题自己用 desktop-color 画近黑底; 不再叠加旧 splash, 避免 2.8K 拉伸发糊。
    ("GRUB_BACKGROUND", '""'),
    ("GRUB_COLOR_NORMAL", '"light-gray/black"'),
    ("GRUB_COLOR_HIGHLIGHT", '"black/light-cyan"'),
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
        destination = target_dir / name
        shutil.copy2(source, destination)
        if name.endswith(".sh"):
            destination.chmod(0o755)

    workspace_target_dir = root / "usr/share/linxira/workspace-guard"
    workspace_target_dir.mkdir(parents=True, exist_ok=True)
    for name in WORKSPACE_TEMPLATE_FILES:
        source = WORKSPACE_TEMPLATE_DIR / name
        if not source.is_file():
            raise RuntimeError(f"missing workspace-guard template: {source}")
        destination = workspace_target_dir / name
        shutil.copy2(source, destination)
        destination.chmod(0o755)


def _root_identity(fstab_path):
    """Return (uuid, fstype, subvolume) of the root mount from the target fstab."""
    for line in fstab_path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) < 3 or fields[1] != "/" or fields[0].startswith("#"):
            continue
        spec, fstype = fields[0], fields[2]
        if spec.startswith("UUID="):
            subvolume = ""
            for option in fields[3].split(","):
                if option.startswith("subvol="):
                    subvolume = option[len("subvol="):]
            return spec[len("UUID="):], fstype, subvolume
    return None


def _write_rescue_entry(root, grub_script_dir):
    """Emit a bootable 'Rescue' menu entry: same root, text console only.

    常规引导损坏(图形栈/显示管理器起不来)时, 无需外接介质即可进入
    纯文本控制台修复系统。条目由安装期生成的真实 UUID 驱动, grub-mkconfig
    每次重生成都会带上。fstab 不可解析时静默跳过(不阻塞安装)。
    """
    fstab = root / "etc/fstab"
    if not fstab.is_file():
        return False
    identity = _root_identity(fstab)
    if identity is None:
        libcalamares.utils.warning(
            "linxiraboot: root UUID not found in fstab; rescue entry skipped"
        )
        return False
    uuid, fstype, subvolume = identity
    kernel_args = f"root=UUID={uuid} rw"
    prefix = ""
    if fstype == "btrfs" and subvolume:
        kernel_args += f" rootflags=subvol={subvolume}"
        prefix = f"/{subvolume}"
    script = "\n".join([
        "#!/bin/sh",
        "# Linxira rescue entry: text-console boot of the installed root.",
        "# Generated by linxiraboot at install time; regenerated on grub-mkconfig.",
        "cat << 'EOF'",
        "menuentry 'Linxira OS Rescue (text console)' --class linxira {",
        "\tsearch --no-floppy --fs-uuid --set=root " + uuid,
        f"\tlinux {prefix}/boot/vmlinuz-linux {kernel_args} systemd.unit=multi-user.target",
        f"\tinitrd {prefix}/boot/initramfs-linux.img",
        "}",
        "EOF",
        "",
    ])
    grub_script_dir.mkdir(parents=True, exist_ok=True)
    (grub_script_dir / "41_linxira-rescue").write_text(script, encoding="utf-8")
    os.chmod(grub_script_dir / "41_linxira-rescue", 0o755)
    return True


GRUB_SPLASH_SOURCE = Path("/usr/share/linxira/grub/splash.png")
GRUB_THEME_SOURCE = Path("/usr/share/linxira/grub/themes/linxira")


def _install_grub_splash(root):
    """复制引导背景到目标 /boot/grub, 并留一份在 /usr/share/linxira/grub。

    grub-mkconfig(由 bootloader 模块随后执行)会按 GRUB_BACKGROUND 引用它。
    """
    if not GRUB_SPLASH_SOURCE.is_file():
        raise RuntimeError(f"GRUB splash image missing: {GRUB_SPLASH_SOURCE}")
    target_boot = root / "boot/grub"
    target_boot.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(GRUB_SPLASH_SOURCE, target_boot / "linxira-splash.png")
    target_share = root / "usr/share/linxira/grub"
    target_share.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(GRUB_SPLASH_SOURCE, target_share / "splash.png")
    if GRUB_THEME_SOURCE.is_dir():
        destination = target_boot / "themes/linxira"
        shutil.copytree(GRUB_THEME_SOURCE, destination, dirs_exist_ok=True)


def _target_version(root):
    """Read the image version written by the build, with os-release fallback."""
    release = root / "etc/linxira-release"
    if release.is_file():
        version = release.read_text(encoding="utf-8").strip().splitlines()
        if version:
            return version[0].strip()
    os_release = root / "etc/os-release"
    if os_release.is_file():
        for line in os_release.read_text(encoding="utf-8").splitlines():
            if line.startswith("VERSION_ID="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def _brand_theme_title(root):
    """Put the concrete image version in the GRUB theme title."""
    version = _target_version(root)
    if not version:
        return
    title = f"Linxira OS {version}".replace("\\", "\\\\").replace('"', '\\"')
    theme_dir = root / "boot/grub/themes/linxira"
    for path in theme_dir.glob("theme-*.txt"):
        text = path.read_text(encoding="utf-8")
        text = re.sub(r'^title-text:.*$', f'title-text: "{title}"', text, count=1, flags=re.MULTILINE)
        path.write_text(text, encoding="utf-8")


def _seed_saved_entry(root):
    """Create a valid GRUB environment block so saved default starts at entry 0."""
    grub_dir = root / "boot/grub"
    grub_dir.mkdir(parents=True, exist_ok=True)
    env = grub_dir / "grubenv"
    if env.exists():
        return
    block = "# GRUB Environment Block\nsaved_entry=0\n"
    block += "#" * (1024 - len(block))
    env.write_text(block, encoding="utf-8")


ESP_MOUNTPOINTS = ("/boot/efi", "/efi")
WINDOWS_LOADER = "EFI/Microsoft/Boot/bootmgfw.efi"


def _esp_identity(fstab_path):
    """Return (mountpoint, uuid) of the EFI system partition from the target fstab."""
    wanted = set(ESP_MOUNTPOINTS)
    for line in fstab_path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) < 3 or fields[0].startswith("#"):
            continue
        if fields[1] not in wanted:
            continue
        spec = fields[0]
        if spec.startswith("UUID="):
            return fields[1], spec[len("UUID="):]
    return None


def _write_windows_entry(root, grub_script_dir):
    """确定性生成 Windows chainload 条目, 不依赖 os-prober。

    os-prober 在 Calamares chroot 里会跳过“已挂载”的分区(目标 ESP 挂在
    /tmp/calamares-root-*/boot/efi), 导致 Windows 条目时有时无。这里直接看
    目标 ESP 里有没有 bootmgfw.efi, 有就按 ESP 的 UUID 生成固定条目。
    """
    fstab = root / "etc/fstab"
    if not fstab.is_file():
        return False
    identity = _esp_identity(fstab)
    if identity is None:
        return False
    mountpoint, uuid = identity
    loader = root / mountpoint.lstrip("/") / WINDOWS_LOADER
    if not loader.is_file():
        return False
    script = "\n".join(
        [
            "#!/bin/sh",
            "exec tail -n +3 \"$0\"",
            "menuentry 'Windows Boot Manager' --class windows --class os {",
            "    insmod part_gpt",
            "    insmod fat",
            f"    search --no-floppy --fs-uuid --set=root {uuid}",
            f"    chainloader /{WINDOWS_LOADER}",
            "}",
            "",
        ]
    )
    grub_script_dir.mkdir(parents=True, exist_ok=True)
    path = grub_script_dir / "42_linxira-windows"
    path.write_text(script, encoding="utf-8")
    os.chmod(path, 0o755)
    return True


THEME_SELECTOR = """#!/bin/sh
exec tail -n +3 "$0"
# 2026-10-26: 按实际分辨率选主题变体(原生分辨率, 不强制降分辨率)。
theme_dir=/boot/grub/themes/linxira
if loadfont "$theme_dir/fonts/linxira-ui-24.pf2" ; then
    loadfont "$theme_dir/fonts/linxira-ui-32.pf2"
    loadfont "$theme_dir/fonts/linxira-ui-40.pf2"
    loadfont "$theme_dir/fonts/linxira-ui-48.pf2"
    loadfont "$theme_dir/fonts/linxira-ui-20.pf2"
    loadfont "$theme_dir/fonts/linxira-ui-bold-20.pf2"
    loadfont "$theme_dir/fonts/linxira-ui-bold-24.pf2"
    loadfont "$theme_dir/fonts/linxira-ui-bold-32.pf2"
    loadfont "$theme_dir/fonts/linxira-ui-bold-40.pf2"
    loadfont "$theme_dir/fonts/linxira-ui-bold-48.pf2"
    ui=20
    if [ -n "$gfxheight" ]; then
        if [ "$gfxheight" -gt 2000 ]; then
            ui=48
        elif [ "$gfxheight" -gt 1400 ]; then
            ui=40
        elif [ "$gfxheight" -gt 1000 ]; then
            ui=32
        elif [ "$gfxheight" -gt 700 ]; then
            ui=24
        fi
    fi
    set theme="$theme_dir/theme-$ui.txt"
fi
"""


def _write_theme_selector(root, grub_script_dir):
    grub_script_dir.mkdir(parents=True, exist_ok=True)
    path = grub_script_dir / "01_linxira_theme"
    path.write_text(THEME_SELECTOR, encoding="utf-8")
    os.chmod(path, 0o755)
    return True


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

        _install_grub_splash(root)
        _brand_theme_title(root)
        _seed_saved_entry(root)
        _append_mkinitcpio_hook(root / MKINITCPIO_TARGET)
        _copy_templates(root)
        _write_rescue_entry(root, root / "etc/grub.d")
        windows_entry = _write_windows_entry(root, root / "etc/grub.d")
        # 自建条目存在时关闭 os-prober, 否则会出现两个 Windows 条目
        # (括号里分别带/不带 "on /dev/...")。
        _set_config_value(
            grub_path,
            "GRUB_DISABLE_OS_PROBER",
            "true" if windows_entry else "false",
        )
        _write_theme_selector(root, root / "etc/grub.d")
    except (OSError, RuntimeError) as error:
        return "Boot and snapshot configuration failed", str(error)

    libcalamares.job.setprogress(1.0)
    return None
