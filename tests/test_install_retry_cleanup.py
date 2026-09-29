from pathlib import Path
import re
import unittest


ROOT = Path(__file__).parents[1]
LAUNCHER = ROOT / "airootfs/usr/local/bin/linxira-installer-shell"
CLEANUP = ROOT / "airootfs/usr/local/bin/linxira-install-cleanup"
SETTINGS = ROOT / "airootfs/etc/calamares/settings.conf"
SHELLCONF = ROOT / "airootfs/etc/calamares/modules/shellprocess_linxira-cleanup.conf"
PARTITION = ROOT / "airootfs/etc/calamares/modules/partition.conf"


class InstallRetryCleanupTests(unittest.TestCase):
    """2026-09-28 用户实测: 安装失败一次后, 分区页整体不可操作, 无法进入下一步。

    根因: 失败后 Calamares 不执行收尾 umount, 同一 live 会话重试时目标分区
    仍挂载, 分区页看到全部 busy → 无任何可用操作。修复: 安装器启动时
    (任何页面渲染之前)清理现场 + exec 序列兜底 + 擦盘预选。
    """

    def test_launcher_cleans_before_calamares_starts(self):
        script = LAUNCHER.read_text(encoding="utf-8")
        cleanup_at = script.index("linxira-install-cleanup")
        calamares_at = script.index("/usr/bin/calamares")
        self.assertLess(cleanup_at, calamares_at)
        # 同一次 pkexec 内先清理后 exec, 不产生额外授权弹窗
        self.assertIn("exec /usr/bin/calamares", script)
        # 清理失败不阻断安装
        self.assertIn("sh /usr/local/bin/linxira-install-cleanup 2>/dev/null || true", script)

    def test_cleanup_script_clears_stale_mounts_and_never_fails(self):
        script = CLEANUP.read_text(encoding="utf-8")
        self.assertIn("/tmp/calamares-root-", script)
        self.assertIn("/target", script)
        self.assertIn("umount -R", script)
        self.assertIn("swapoff -a", script)
        self.assertIn("vgchange -an", script)
        self.assertIn("crypto_LUKS", script)
        self.assertTrue(script.rstrip().endswith("exit 0"))

    def test_cleanup_module_runs_before_partition_job(self):
        settings = SETTINGS.read_text(encoding="utf-8")
        exec_at = settings.index("  - exec:")
        self.assertLess(settings.index("shellprocess@linxira-cleanup", exec_at),
                        re.search(r"^\s*- partition$", settings[exec_at:], re.MULTILINE).start() + exec_at)
        conf = SHELLCONF.read_text(encoding="utf-8")
        # 清理的是 live 宿主的挂载表, 绝不能进 chroot
        self.assertIn("chroot: false", conf)

    def test_partition_page_stays_on_proven_none(self):
        # 2026-09-29: erase 预选触发 calamares 启动 SIGABRT(134), 回退 none;
        # 重试可用性由启动清场保证, 不依赖预选。
        conf = PARTITION.read_text(encoding="utf-8")
        self.assertIn("initialPartitioningChoice: none", conf)
        self.assertIn("allowManualPartitioning: false", conf)

    def test_cleanup_script_is_executable_in_the_iso(self):
        # 2026-09-29 实测: 漏登记 file_permissions → 脚本 644 → pkexec 报
        # Permission denied, 清场静默失效。执行位唯一来源是 profiledef.sh。
        profile = (ROOT / "profiledef.sh").read_text(encoding="utf-8")
        self.assertIn('["/usr/local/bin/linxira-install-cleanup"]="0:0:755"', profile)
        self.assertIn('["/usr/local/bin/linxira-install-log-export"]="0:0:755"', profile)
        launcher = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("sh /usr/local/bin/linxira-install-cleanup", launcher)


if __name__ == "__main__":
    unittest.main()
