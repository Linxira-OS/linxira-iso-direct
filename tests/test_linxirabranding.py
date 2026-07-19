import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "airootfs/usr/lib/calamares/modules/linxirabranding/main.py"
)
sys.modules.setdefault("libcalamares", types.ModuleType("libcalamares"))
spec = importlib.util.spec_from_file_location("linxirabranding", MODULE_PATH)
linxirabranding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(linxirabranding)


class BrandingConfigurationTests(unittest.TestCase):
    def test_invalid_console_keymap_falls_back_to_us(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            keymaps = root / "usr/share/kbd/keymaps/i386/qwerty"
            keymaps.mkdir(parents=True)
            (keymaps / "us.map.gz").touch()
            vconsole = root / "etc/vconsole.conf"
            vconsole.parent.mkdir(parents=True)
            vconsole.write_text("KEYMAP=cn\nXKBLAYOUT=cn\n", encoding="utf-8")

            linxirabranding._fix_console_keymap(root)

            self.assertEqual(
                vconsole.read_text(encoding="utf-8"),
                "KEYMAP=us\nXKBLAYOUT=cn\n",
            )

    def test_valid_console_keymap_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            keymaps = root / "usr/share/kbd/keymaps/i386/qwerty"
            keymaps.mkdir(parents=True)
            (keymaps / "de-latin1.map.gz").touch()
            vconsole = root / "etc/vconsole.conf"
            vconsole.parent.mkdir(parents=True)
            vconsole.write_text('KEYMAP="de-latin1"\n', encoding="utf-8")

            linxirabranding._fix_console_keymap(root)

            self.assertEqual(vconsole.read_text(encoding="utf-8"), 'KEYMAP="de-latin1"\n')

    def test_initramfs_configuration_removes_obsolete_module_and_adds_plymouth(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            mkinitcpio = Path(temporary_root) / "mkinitcpio.conf"
            mkinitcpio.write_text(
                "MODULES=(amdgpu crc32c_intel)\n"
                "HOOKS=(base systemd autodetect keyboard filesystems)\n",
                encoding="utf-8",
            )

            linxirabranding._remove_obsolete_modules(mkinitcpio)
            linxirabranding._enable_plymouth(mkinitcpio)

            self.assertEqual(
                mkinitcpio.read_text(encoding="utf-8"),
                "MODULES=(amdgpu)\n"
                "HOOKS=(base systemd plymouth autodetect keyboard filesystems)\n",
            )

    def test_target_plasma_layout_removes_live_installer_launcher(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            temporary_root = Path(temporary_root)
            source_root = temporary_root / "source"
            target_root = temporary_root / "target"
            source = source_root / "etc/skel/.config/plasma-layout"
            source.parent.mkdir(parents=True)
            source.write_text(
                "launchers=applications:linxira-installer.desktop,"
                "applications:org.linxira.Welcome.desktop,"
                "applications:com.shellyorg.shelly.desktop\n",
                encoding="utf-8",
            )

            relative_target = Path("etc/skel/.config/plasma-layout")
            linxirabranding._install_target_plasma_layout(
                source, target_root, relative_target
            )

            target = target_root / relative_target
            contents = target.read_text(encoding="utf-8")
            self.assertNotIn("linxira-installer.desktop", contents)
            self.assertIn("org.linxira.Welcome.desktop", contents)
            self.assertIn("com.shellyorg.shelly.desktop", contents)

    def test_run_copies_dark_kde_defaults_to_target(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn('_copy_file("/etc/skel/.config/kdeglobals", root)', source)


if __name__ == "__main__":
    unittest.main()
