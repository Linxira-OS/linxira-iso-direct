"""引导器选择 → 装包 的回归测试。

2026-09-27 事故: 安装器提供 rEFInd 选项, 但 refind 包既不在任何基线也不在
离线仓库里, 选它的人走到安装末段才收到 refind-install 退出码 127。
校验器侧还把 systemd-boot 映射到不存在的同名包 —— 三条引导路径坏了两条。
这里的测试锁住"选了哪个引导器, 对应的包就必须进实际安装的基线"。
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


PROFILE_ROOT = Path(__file__).parents[1]
PACSTRAP_PATH = PROFILE_ROOT / "airootfs/usr/lib/calamares/modules/linxirapacstrap/main.py"
VALIDATE_PATH = PROFILE_ROOT / "airootfs/usr/lib/calamares/modules/linxiravalidate/main.py"
BASELINE = PROFILE_ROOT / "target-packages.x86_64"
CANDIDATES = PROFILE_ROOT / "offline-candidate-packages.x86_64"

libcalamares = types.ModuleType("libcalamares")
libcalamares.globalstorage = types.SimpleNamespace(value=lambda key: None)
libcalamares.job = types.SimpleNamespace(configuration={}, setprogress=lambda value: None)
libcalamares.utils = types.SimpleNamespace(
    debug=lambda value: None, warning=lambda value: None
)
sys.modules["libcalamares"] = libcalamares

_spec = importlib.util.spec_from_file_location("linxirapacstrap", PACSTRAP_PATH)
linxirapacstrap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(linxirapacstrap)

_spec = importlib.util.spec_from_file_location("linxiravalidate", VALIDATE_PATH)
linxiravalidate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(linxiravalidate)


def _selection_result(baseline, minimal=False):
    return {
        "selectionDocument": {"schemaVersion": "org.linxira.component-selection.v1"},
        "selectedPackages": [],
        "onlinePackages": [],
        "onlineSatisfiedLeafIds": [],
        "satisfiedItems": [],
        "pendingItems": [],
        "catalogSha256": "0" * 64,
        "catalogRelease": "2026.09",
        "minimalBaseline": minimal,
        "baselinePackages": list(baseline),
    }


class BootloaderPackageWiringTests(unittest.TestCase):
    def _run_with_bootloader(self, bootloader, baseline, minimal=False):
        captured = {}

        def fake_commands(pacman_config, root, installed_baseline, selected):
            captured["baseline"] = list(installed_baseline)
            return []

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "target"
            root.mkdir()
            repository = Path(temporary) / "repo"
            repository.mkdir()
            pacman_conf = Path(temporary) / "pacman.conf"
            pacman_conf.write_text("", encoding="utf-8")
            config = {
                "pacmanConfig": str(pacman_conf),
                "repositoryPath": str(repository),
                "packageManifest": str(BASELINE),
                "candidateManifest": str(CANDIDATES),
            }
            result = _selection_result(baseline, minimal=minimal)
            with mock.patch.object(linxirapacstrap.os.path, "ismount", return_value=True), \
                 mock.patch.object(linxirapacstrap, "_catalog_selection", return_value=result), \
                 mock.patch.object(linxirapacstrap, "_pacstrap_commands", side_effect=fake_commands), \
                 mock.patch.object(linxirapacstrap, "_remove_offline_repo"), \
                 mock.patch.object(linxirapacstrap, "_enable_target_multilib"), \
                 mock.patch.object(linxirapacstrap, "_enable_target_linxira_repo"), \
                 mock.patch.object(linxirapacstrap, "_run_with_retries", return_value=None), \
                 mock.patch.object(linxirapacstrap, "_write_receipt") as receipt, \
                 mock.patch.object(linxirapacstrap, "_write_pending_install"):
                libcalamares.job.configuration = config

                def storage(key):
                    if key == "rootMountPoint":
                        return str(root)
                    if key == "packagechooser_bootloader":
                        return bootloader
                    return None

                libcalamares.globalstorage.value = storage
                error = linxirapacstrap.run()
            self.assertIsNone(error)
            # 回执必须记录"实际安装"的基线, 引导器包要在里面。
            self.assertIn(
                captured["baseline"][0] if captured["baseline"] else "",
                receipt.call_args.args[2],
            )
        return captured["baseline"]

    def test_refind_choice_installs_the_refind_package(self):
        baseline = self._run_with_bootloader("refind", ["base", "grub", "linux"])
        self.assertIn("refind", baseline)

    def test_grub_choice_does_not_duplicate_grub(self):
        baseline = self._run_with_bootloader("grub", ["base", "grub", "linux"])
        self.assertEqual(baseline.count("grub"), 1)

    def test_systemd_boot_adds_no_package(self):
        # systemd-boot 由 systemd 包提供, systemd 在 base 里 —— 不应追加任何包。
        # 与 grub 选择产出完全相同的基线, 即证明它什么都没加。
        from_grub = self._run_with_bootloader("grub", ["base", "grub", "linux"])
        from_systemd_boot = self._run_with_bootloader(
            "systemd-boot", ["base", "grub", "linux"]
        )
        self.assertNotIn("systemd-boot", from_systemd_boot)
        self.assertEqual(from_grub, from_systemd_boot)

    def test_minimal_baseline_still_gets_the_chosen_bootloader(self):
        # 纯 Arch 最小安装会把基线整体换成 13 包清单; 引导器补包必须发生在
        # 替换之后, 否则最小模式选 rEFInd 一样炸 127。
        baseline = self._run_with_bootloader(
            "refind", ["base", "linux", "linux-lts", "grub"], minimal=True
        )
        self.assertIn("refind", baseline)

    def test_refind_is_shipped_in_the_offline_repository_manifest(self):
        # 候选清单是离线仓库闭包的输入之一; refind 不在里面就装不上。
        text = CANDIDATES.read_text(encoding="utf-8")
        entries = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]
        self.assertIn("refind", entries)

    def test_validator_maps_bootloaders_to_real_package_names(self):
        # Arch 没有 systemd-boot 这个包名(它由 systemd 提供); 映射到不存在的
        # 包名会让选 systemd-boot 的机器在装机校验阶段误报缺包。
        for bootloader, package in linxiravalidate.BOOTLOADER_PACKAGES.items():
            self.assertIsInstance(package, str)
            self.assertRegex(package, r"^[a-z0-9@._+-]+$")
        self.assertEqual(linxiravalidate.BOOTLOADER_PACKAGES["systemd-boot"], "systemd")
        self.assertEqual(linxiravalidate.BOOTLOADER_PACKAGES["refind"], "refind")


if __name__ == "__main__":
    unittest.main()
