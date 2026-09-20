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


if __name__ == "__main__":
    unittest.main()
