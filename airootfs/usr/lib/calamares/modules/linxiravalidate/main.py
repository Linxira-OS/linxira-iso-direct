#!/usr/bin/env python3

import os
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess

import libcalamares


OBSOLETE_INITCPIO_MODULE = re.compile(
    r"(?<![A-Za-z0-9_-])crc32c(?:-|_)intel(?![A-Za-z0-9_-])"
)
DESKTOP_REQUIREMENTS = {
    # 2026-09-20: COSMIC 第二个一等桌面 —— 逐包校验, 与 catalog artifact ids 对齐。
    # 2026-09-21 修复: 会话文件实为 cosmic.desktop(Arch cosmic-session 包)。
    "desktop-cosmic": (
        "cosmic.desktop",
        (
            "cosmic-app-library",
            "cosmic-applets",
            "cosmic-bg",
            "cosmic-comp",
            "cosmic-files",
            "cosmic-icon-theme",
            "cosmic-idle",
            "cosmic-launcher",
            "cosmic-monitor",
            "cosmic-notifications",
            "cosmic-osd",
            "cosmic-panel",
            "cosmic-randr",
            "cosmic-screenshot",
            "cosmic-session",
            "cosmic-settings",
            "cosmic-settings-daemon",
            "cosmic-sound-theme",
            "cosmic-store",
            "cosmic-terminal",
            "cosmic-text-editor",
            "cosmic-wallpapers",
            "cosmic-workspaces",
            "pop-icon-theme",
            "sddm",
            "xdg-desktop-portal-cosmic",
            "vulkan-swrast",
        ),
    ),
    "desktop-plasma": ("plasma.desktop", ()),
    # 2026-10-25: 只保留 Plasma + COSMIC 两个桌面, 其余桌面条目已从目录删除。
    # 2026-08-13: 无桌面模式 —— 无 session/无显示管理器校验
    "desktop-server": (None, ()),
    # 2026-09-20: 超精简无桌面安装 —— 同无桌面, 基线为最小清单
    "desktop-server-minimal": (None, ()),
}


SERVER_DESKTOPS = {"desktop-server", "desktop-server-minimal"}


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


EXPECTED_VERSIONS_PATH = "/etc/linxira/expected-versions"
VERCMP = "/usr/bin/vercmp"


def _version_is_newer_or_equal(installed, expected):
    """滚动发行: 安装期取离线仓库的冻结版本, 但允许更高版本(如在线先行升级)。

    只有比镜像更旧才判定失败; vercmp 不可用时退化为严格相等。
    """
    try:
        result = subprocess.run(
            [VERCMP, installed, expected],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return installed == expected
    if result.returncode != 0:
        return installed == expected
    try:
        return int(result.stdout.strip()) >= 0
    except (TypeError, ValueError):
        return installed == expected


def _expected_versions():
    """读取构建期生成的 包名 -> 版本 映射(行格式: 'name version')。"""
    versions = {}
    try:
        with open(EXPECTED_VERSIONS_PATH, encoding="utf-8") as handle:
            for line in handle:
                name, _, version = line.partition(" ")
                if name and version.strip():
                    versions[name.strip()] = version.strip()
    except OSError:
        return versions
    return versions


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


def _minimal_baseline_selected(root):
    receipt_path = Path(root) / "var/lib/linxira/installer-selection.json"
    receipt = json.loads(
        receipt_path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    return receipt.get("minimalBaseline") is True


def _require_paths(root, paths, failures):
    for path in paths:
        target_path = _target_path(root, path)
        if not os.path.isfile(target_path):
            failures.append("missing file: " + path)
        elif path.startswith("/boot/initramfs-") and os.path.getsize(target_path) == 0:
            failures.append("empty initramfs: " + path)


def _shared_target_checks(root, failures):
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


# 2026-09-27: Arch 没有名为 systemd-boot 的包 —— 它由 systemd 包提供。
# 此前映射到不存在的包名, 选 systemd-boot 的机器会在装机校验阶段误报缺包。
BOOTLOADER_PACKAGES = {"grub": "grub", "systemd-boot": "systemd", "refind": "refind"}
# 2026-09-28: ESP 恒为 /boot/efi(见 partition.conf 顶部 efi 段; 此前的
# bootloaderOverrides 是 CachyOS fork 键, Arch 官方 calamares 不认识, 已删)。
# 上游 bootloader 模块(v3.3.14)的真实落点:
#   grub          → grub.cfg 在 /boot/grub(内核与 /boot 同在 root 分区)
#   systemd-boot  → bootctl/kernel-install 写 /boot/efi/loader/loader.conf,
#                   内核经 kernel-install 拷入 ESP
#   refind        → refind-install 写 /boot/efi/EFI/refind/refind.conf,
#                   /boot/refind_linux.conf 生成在内核旁(root 分区)
BOOTLOADER_PATHS = {
    "grub": ("/boot/grub/grub.cfg",),
    "systemd-boot": ("/boot/efi/loader/loader.conf",),
    "refind": ("/boot/efi/EFI/refind/refind.conf",),
}


def _validate_minimal_system(root, bootloader, bootloader_package):
    # 2026-09-21: 「服务器 · 纯 Arch 最小安装」基线仅 13 包, 无 Linxira 工具链与
    # 桌面管线 —— 不适用标准校验清单, 只校验内核/引导与共享目标系统不变量。
    failures = []
    required_packages = ("base", "linux", "linux-lts")
    if bootloader_package:
        required_packages = required_packages + (bootloader_package,)
    for package in required_packages:
        if not _package_installed(root, package):
            failures.append("missing package: " + package)
    required_paths = (
        "/boot/initramfs-linux.img",
        "/boot/initramfs-linux-lts.img",
        "/boot/vmlinuz-linux",
        "/boot/vmlinuz-linux-lts",
        "/etc/fstab",
    ) + BOOTLOADER_PATHS.get(bootloader, BOOTLOADER_PATHS["grub"])
    _require_paths(root, required_paths, failures)
    _shared_target_checks(root, failures)
    if failures:
        return "Installed system validation failed", "\n".join(failures)
    libcalamares.job.setprogress(1.0)
    return None


LOADER_PATHS = {
    "grub": "EFI/linxira/grubx64.efi",
    "systemd-boot": "EFI/systemd/systemd-bootx64.efi",
    "refind": "EFI/refind/refind_x64.efi",
}


def _ensure_efi_fallback(root, bootloader="grub"):
    """独立 ESP 上补 \\EFI\\BOOT\\BOOTX64.EFI。

    UEFI 固件在 NVRAM 条目缺失时会回退到该路径; 但共用 Windows ESP 时它属于
    Windows, 不能覆盖。因此只在 ESP 上没有 Microsoft 引导文件时复制。
    三种引导器各复制各自的 loader。
    """
    relative = LOADER_PATHS.get(bootloader)
    if not relative:
        return False
    esp = Path(root) / "boot/efi"
    loader = esp / relative
    fallback = esp / "EFI/BOOT/BOOTX64.EFI"
    windows = esp / "EFI/Microsoft/Boot/bootmgfw.efi"
    if not loader.is_file() or windows.exists() or fallback.exists():
        return False
    fallback.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(loader, fallback)
    return True


def run():
    root = libcalamares.globalstorage.value("rootMountPoint")
    failures = []

    if not root or not os.path.ismount(root):
        return "Target is not mounted", "The target root mount is unavailable."

    try:
        _ensure_efi_fallback(
            root, libcalamares.globalstorage.value("packagechooser_bootloader") or "grub"
        )
    except OSError as error:
        libcalamares.utils.warning(f"linxiravalidate: EFI fallback copy failed: {error}")

    try:
        desktop, selected_session, selected_packages = _selection_requirements(root)
        selected_packages = tuple(selected_packages) + tuple(_selected_package_requirements(root))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return "Installed system validation failed", "invalid installer selection receipt: " + str(error)

    # 引导程序按用户选择校验(grub/systemd-boot/refind), 不再硬编码 grub
    bootloader = libcalamares.globalstorage.value("packagechooser_bootloader") or "grub"
    bootloader_package = BOOTLOADER_PACKAGES.get(bootloader)
    # 2026-09-21: 「服务器 · 纯 Arch 最小安装」走独立轻量校验清单
    if _minimal_baseline_selected(root):
        return _validate_minimal_system(root, bootloader, bootloader_package)

    required_packages = (
        "shelly",
        "linux",
        "linux-lts",
        "linxira-artwork",
        "linxira-catalog",
        "linxira-hwd-detector",
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
        "wireplumber",
        "xdg-desktop-portal",
    )
    # 2026-08-13: 服务器(无桌面)模式不要求 sddm/桌面 session; 最小服务器同理
    if desktop not in SERVER_DESKTOPS:
        required_packages = required_packages + ("sddm",)
    # 2026-09-21: KDE 专属件只随 Plasma 桌面安装 —— 基线的 xdg-desktop-portal-kde
    # 会拖出 plasma-workspace 闭包, 留下残缺 plasma.desktop 会话(SDDM 选中即黑屏)
    if desktop == "desktop-plasma":
        required_packages = required_packages + (
            "kinfocenter",
            "plasma-systemmonitor",
            "xdg-desktop-portal-kde",
        )
    if bootloader_package:
        required_packages = required_packages + (bootloader_package,)
    for package in required_packages:
        if not _package_installed(root, package):
            failures.append("missing package: " + package)
    for package in selected_packages:
        if not _package_or_group_installed(root, package):
            failures.append("missing selected package or group: " + package)
    # 2026-10-26: 期望版本由构建期写入 /etc/linxira/expected-versions(取自各产物
    # 的 pacman -Qp), 不在模块里写死 —— 否则每次发版都会漂移成安装失败。
    pinned = ("linxira-hwd-detector", "linxira-components", "linxira-hardware-driver-manager")
    expected_versions = _expected_versions()
    for package in pinned:
        version = expected_versions.get(package)
        if version is None:
            failures.append("missing expected version entry: " + package)
            continue
        installed = _package_version(root, package)
        if installed is None:
            failures.append("could not verify package version: " + package)
        elif not _version_is_newer_or_equal(installed, version):
            failures.append(
                f"installed package is older than the image: {package} {installed} (image {version})"
            )
    if _package_installed(root, "gdm"):
        failures.append("unsupported display manager installed: gdm")

    required_paths = (
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
        "/usr/bin/lhwd",
        "/usr/bin/linxira-hwd-detector",
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
        "/usr/share/linxira/catalog/catalog-v3.json",
        "/usr/share/linxira/catalog/catalog-v3.schema.json",
        "/usr/share/linxira/welcome/i18n/zh_CN.json",
        "/var/lib/linxira/installer-selection.json",
    )
    if desktop not in SERVER_DESKTOPS:
        required_paths = required_paths + (
            "/usr/share/wayland-sessions/" + selected_session,
        )
    required_paths = required_paths + BOOTLOADER_PATHS.get(bootloader, BOOTLOADER_PATHS["grub"])
    _require_paths(root, required_paths, failures)
    if desktop not in SERVER_DESKTOPS:
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

    _shared_target_checks(root, failures)
    if failures:
        return "Installed system validation failed", "\n".join(failures)

    libcalamares.job.setprogress(1.0)
    return None
