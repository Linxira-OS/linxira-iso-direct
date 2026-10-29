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
        # 显式解释器: 脚本即使没有可执行位也能运行。
        self.assertTrue(command.startswith("-/bin/bash "), command)
        self.assertIn("linxira-workspace-guard-install.sh", command)

    def test_timeshift_module_uses_an_explicit_interpreter(self):
        module = yaml.safe_load(
            (
                PROFILE_ROOT
                / "airootfs/etc/calamares/modules/shellprocess_linxira-timeshift.conf"
            ).read_text(encoding="utf-8")
        )
        command = module["script"][0]["command"]
        self.assertTrue(command.startswith("-/bin/sh "), command)
        self.assertIn("linxira-timeshift-enable.sh", command)

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
        # 同盘目录: 不建分区, 不改分区表, 不写 fstab。
        self.assertIn("STORE=/var/lib/linxira/guard", source)
        self.assertNotIn("sfdisk", source)
        self.assertNotIn("mkfs.ext4", source)
        self.assertNotIn("/etc/fstab", source)
        self.assertIn("chmod 600", source)
        # 失败一律跳过而不是中断安装。
        self.assertNotIn("set -e", source)
        self.assertIn("linxira-config workspace-guard adopt-installer", source)

    def test_install_script_never_partitions_other_disks(self):
        source = INSTALL_SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("root_disk", "root_source", "pick_disk", "lsblk", "partx", "blkid"):
            self.assertNotIn(forbidden, source)

    def test_official_handbook_ships_on_the_iso(self):
        packages = TARGET_PACKAGES.read_text(encoding="utf-8").split()
        self.assertIn("linxira-wiki", packages)
        self.assertEqual(len(packages), len(set(packages)), "target package list has duplicates")
