from pathlib import Path
import unittest


PROFILE_ROOT = Path(__file__).parents[1]
ONLINE_SYNC_UNIT = (
    PROFILE_ROOT
    / "airootfs/etc/systemd/system/multi-user.target.wants/linxira-online-sync.service"
)
ONLINE_SYNC_SCRIPT = PROFILE_ROOT / "airootfs/usr/lib/linxira/linxira-online-sync"
FIRSTBOOT_TMPFILES = PROFILE_ROOT / "airootfs/usr/lib/tmpfiles.d/linxira-firstboot.conf"


class FirstBootContinuityTests(unittest.TestCase):
    def test_online_sync_unit_is_enabled_and_network_gated(self):
        # 2026-09-20: 离线安装的系统缺 [linxira] 同步库, 首次联网后补建。
        source = ONLINE_SYNC_UNIT.read_text(encoding="utf-8")
        self.assertIn("ConditionPathExists=!/var/lib/pacman/sync/linxira.db", source)
        self.assertIn("After=network-online.target", source)
        self.assertIn("Wants=network-online.target", source)
        self.assertIn("ExecStart=/usr/lib/linxira/linxira-online-sync", source)
        self.assertIn("Type=oneshot", source)

    def test_online_sync_script_is_idempotent_and_bounded(self):
        source = ONLINE_SYNC_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("-f /var/lib/pacman/sync/linxira.db", source)
        self.assertIn("pacman -Sy", source)
        self.assertIn("timeout 90", source)
        # 每次尝试都有界, 放弃时静默退出等待下次开机
        self.assertIn("for attempt in", source)
        self.assertTrue(source.rstrip().endswith("exit 0"))

    def test_user_update_timer_is_globally_enabled_via_tmpfiles(self):
        # 2026-09-20: linxira-update.timer 的 user preset 不会作用到
        # 安装器创建的用户, 自动更新检查此前从未启用。
        source = FIRSTBOOT_TMPFILES.read_text(encoding="utf-8")
        self.assertIn("L /etc/systemd/user/default.target.wants/linxira-update.timer", source)
        self.assertIn("/usr/lib/systemd/user/linxira-update.timer", source)


if __name__ == "__main__":
    unittest.main()
