from pathlib import Path
import unittest

import yaml


PROFILE_ROOT = Path(__file__).parents[1]
MODULE = PROFILE_ROOT / "airootfs/etc/calamares/modules/shellprocess_linxira-workspace-guard.conf"
SETTINGS = PROFILE_ROOT / "airootfs/etc/calamares/settings.conf"
INSTALL_SCRIPT = (
    PROFILE_ROOT / "airootfs/usr/share/linxira/workspace-guard/linxira-workspace-guard-install.sh"
)
TARGET_PACKAGES = PROFILE_ROOT / "target-packages.x86_64"


class WorkspaceGuardInstallTests(unittest.TestCase):
    def test_module_runs_inside_the_installed_system(self):
        module = yaml.safe_load(MODULE.read_text(encoding="utf-8"))
        self.assertFalse(module["dontChroot"])
        command = module["script"][0]["command"]
        # "-" 前缀: 守护是加分项, 建不出来也不能让装机失败。
        self.assertTrue(command.startswith("-"), command)
        self.assertIn("linxira-workspace-guard-install.sh", command)

    def test_module_is_wired_after_timeshift(self):
        sequence = yaml.safe_load(SETTINGS.read_text(encoding="utf-8"))["sequence"][1]["exec"]
        self.assertIn("shellprocess@linxira-workspace-guard", sequence)
        self.assertLess(
            sequence.index("shellprocess@linxira-timeshift"),
            sequence.index("shellprocess@linxira-workspace-guard"),
        )
        # 校验在最后: 守护失败也要走到 linxiravalidate 与 umount。
        self.assertLess(
            sequence.index("shellprocess@linxira-workspace-guard"),
            sequence.index("linxiravalidate@validate"),
        )

    def test_install_script_is_safe_by_construction(self):
        source = INSTALL_SCRIPT.read_text(encoding="utf-8")
        # 守护分区不进 fstab —— 开机不挂载, 没有 root 就够不着快照。
        self.assertIn("/etc/fstab", source)
        self.assertIn("mkfs.ext4", source)
        self.assertIn("chmod 600", source)
        # 失败一律跳过而不是中断安装。
        self.assertNotIn("set -e", source)
        self.assertIn("workspace guard stays off", source)
        self.assertIn("linxira-config workspace-guard adopt-installer", source)

    def test_install_script_refuses_to_touch_the_system_disk(self):
        source = INSTALL_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("root_disk", source)
        self.assertIn("root_source", source)
        self.assertIn("MIN_SIZE_GIB=32", source)

    def test_official_handbook_ships_on_the_iso(self):
        packages = TARGET_PACKAGES.read_text(encoding="utf-8").split()
        self.assertIn("linxira-wiki", packages)
        self.assertEqual(len(packages), len(set(packages)), "target package list has duplicates")
