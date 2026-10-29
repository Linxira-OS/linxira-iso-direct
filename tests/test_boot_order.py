from pathlib import Path
import unittest


PROFILE_ROOT = Path(__file__).parents[1]
GRUB_DEFAULTS = PROFILE_ROOT / "airootfs/etc/default/grub"
LINXIRABOOT = (
    PROFILE_ROOT / "airootfs/usr/lib/calamares/modules/linxiraboot/main.py"
)
TIMESHIFT_ENABLE = PROFILE_ROOT / "airootfs/usr/share/linxira/timeshift/linxira-timeshift-enable.sh"


class BootOrderTests(unittest.TestCase):
    def test_mainline_kernel_is_the_pinned_top_level_default(self):
        # 2026-09-20: grub 10_linux 字符串排序会把 "linux-lts" 误排在 "linux"
        # 之前, GRUB_DEFAULT=0 因此默认落进 LTS。GRUB_TOP_LEVEL 显式钉死主线。
        defaults = GRUB_DEFAULTS.read_text(encoding="utf-8")
        self.assertIn('GRUB_TOP_LEVEL="/boot/vmlinuz-linux"', defaults)
        self.assertNotIn('GRUB_DEFAULT="Linux linux"', defaults)
        source = LINXIRABOOT.read_text(encoding="utf-8")
        self.assertIn('("GRUB_TOP_LEVEL", \'"/boot/vmlinuz-linux"\')', source)

    def test_flat_menu_exposes_both_kernels_for_uefi_stage_selection(self):
        # 平铺菜单: linux 与 linux-lts 条目并列, 引导阶段即可直接选内核。
        defaults = GRUB_DEFAULTS.read_text(encoding="utf-8")
        self.assertIn("GRUB_DISABLE_SUBMENU=true", defaults)
        self.assertIn("GRUB_TIMEOUT=5", defaults)
        self.assertIn("GRUB_DISABLE_OS_PROBER=false", defaults)

    def test_snapshot_menu_daemon_is_timeshift_auto(self):
        # 可引导快照: grub-btrfsd 以 --timeshift-auto 运行, 自动定位
        # timeshift 快照并在每次快照后重建 grub-btrfs.cfg。
        source = TIMESHIFT_ENABLE.read_text(encoding="utf-8")
        self.assertIn("--timeshift-auto", source)
        self.assertIn("grub-mkconfig", source)


    def test_snapshot_menu_config_matches_upstream_grub_btrfs(self):
        # grub-btrfs 自动识别 Timeshift/Snapper; 没有 SNAPSHOT_BACKEND 变量。
        # TITLE_FORMAT 只接受 date/snapshot/type/description。
        source = LINXIRABOOT.read_text(encoding="utf-8")
        self.assertNotIn("GRUB_BTRFS_SNAPSHOT_BACKEND", source)
        self.assertIn(
            '("GRUB_BTRFS_TITLE_FORMAT", \'("date" "description")\')',
            source,
        )
        self.assertIn(
            '("GRUB_BTRFS_ENABLE_CRYPTODISK", \'"true"\')',
            source,
        )

    def test_snapshot_setup_is_bootloader_aware(self):
        # systemd-boot / rEFInd 安装时不能要求 grub-btrfs 配置, 也不能
        # 无条件启用 grub-btrfsd; 引导菜单由各自插件负责。
        boot = LINXIRABOOT.read_text(encoding="utf-8")
        self.assertIn("packagechooser_bootloader", boot)
        self.assertIn("etc/linxira/bootloader", boot)
        self.assertIn('if bootloader != "grub"', boot)

        services = (
            PROFILE_ROOT / "airootfs/etc/calamares/modules/services-systemd.conf"
        ).read_text(encoding="utf-8")
        self.assertNotIn("grub-btrfsd", services)

        timeshift = TIMESHIFT_ENABLE.read_text(encoding="utf-8")
        self.assertIn('BOOTLOADER="$(cat /etc/linxira/bootloader', timeshift)
        self.assertIn('[ "$BOOTLOADER" = "grub" ]', timeshift)
        self.assertIn("systemd-boot-snapshots", timeshift)
        self.assertIn("refind-btrfs", timeshift)


if __name__ == "__main__":
    unittest.main()

class FirmwareInteractionTests(unittest.TestCase):
    def test_installer_does_not_touch_the_generic_efi_fallback(self):
        # 共用 ESP 时覆盖 \EFI\BOOT\BOOTX64.EFI 会破坏固件回退路径。
        config = (PROFILE_ROOT / "airootfs/etc/calamares/modules/bootloader.conf").read_text(
            encoding="utf-8"
        )
        self.assertIn("installEFIFallback: false", config)
        self.assertIn("efiBootloaderId: linxira", config)
