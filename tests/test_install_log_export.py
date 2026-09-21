from pathlib import Path
import unittest


PROFILE_ROOT = Path(__file__).parents[1]
EXPORTER = PROFILE_ROOT / "airootfs/usr/local/bin/linxira-install-log-export"


class InstallLogExportTests(unittest.TestCase):
    def test_installer_log_exporter_is_available(self):
        # 2026-09-21: 安装失败时用户需要一键导出/上传日志 —— live 会话内
        # linxira-install-log-export 收集 calamares/回执/journal 并上传。
        source = EXPORTER.read_text(encoding="utf-8")
        self.assertIn("calamares/*.log", source)
        self.assertIn("installer-selection.json", source)
        self.assertIn("https://0x0.st", source)
        self.assertIn("--no-upload", source)
        # 自动提权到 root(calamares 日志在 /root 下)
        self.assertIn('exec sudo bash "$0"', source)


if __name__ == "__main__":
    unittest.main()
