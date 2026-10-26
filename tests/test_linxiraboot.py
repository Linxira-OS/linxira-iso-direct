from pathlib import Path
import tempfile
import unittest


PROFILE_ROOT = Path(__file__).parents[1]
MODULE_PATH = PROFILE_ROOT / "airootfs/usr/lib/calamares/modules/linxiraboot/main.py"

libcalamares = __import__("types").ModuleType("libcalamares")
libcalamares.globalstorage = __import__("types").SimpleNamespace(value=lambda key: None)
libcalamares.job = __import__("types").SimpleNamespace(setprogress=lambda v: None)
libcalamares.utils = __import__("types").SimpleNamespace(
    debug=lambda v: None, warning=lambda v: None
)
import sys
sys.modules["libcalamares"] = libcalamares
spec = __import__("importlib.util", fromlist=["util"]).spec_from_file_location(
    "linxiraboot", MODULE_PATH
)
linxiraboot = __import__("importlib.util", fromlist=["util"]).module_from_spec(spec)
spec.loader.exec_module(linxiraboot)


class BootMenuTests(unittest.TestCase):
    def test_installed_grub_keeps_the_branded_menu(self):
        settings = dict(linxiraboot.GRUB_SETTINGS)
        self.assertEqual(settings["GRUB_TERMINAL_OUTPUT"], '"gfxterm"')
        self.assertEqual(settings["GRUB_BACKGROUND"], '"/boot/grub/linxira-splash.png"')
        self.assertIn("GRUB_COLOR_HIGHLIGHT", settings)

    def test_grub_splash_is_copied_into_the_target(self):
        source = PROFILE_ROOT / "airootfs/usr/share/linxira/grub/splash.png"
        self.assertTrue(source.is_file(), "live image must ship the GRUB splash")
        self.assertEqual(
            source.read_bytes(),
            (PROFILE_ROOT / "grub/splash.png").read_bytes(),
            "ISO menu and installed menu must use the same splash",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = linxiraboot.GRUB_SPLASH_SOURCE
            linxiraboot.GRUB_SPLASH_SOURCE = source
            try:
                linxiraboot._install_grub_splash(root)
            finally:
                linxiraboot.GRUB_SPLASH_SOURCE = original
            self.assertEqual((root / "boot/grub/linxira-splash.png").read_bytes(), source.read_bytes())
            self.assertEqual((root / "usr/share/linxira/grub/splash.png").read_bytes(), source.read_bytes())


    def test_grub_settings_pin_mainline_top_level(self):
        settings = dict(linxiraboot.GRUB_SETTINGS)
        self.assertEqual(settings["GRUB_TOP_LEVEL"], '"/boot/vmlinuz-linux"')
        self.assertEqual(settings["GRUB_DEFAULT"], "0")
        self.assertEqual(settings["GRUB_DISABLE_SUBMENU"], "true")

    def test_rescue_entry_generated_from_fstab_uuid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "etc").mkdir()
            (root / "etc/fstab").write_text(
                "# /dev/sda2\n"
                "UUID=33f1e33a-e5e1-4676-a72c-67407ab050a2 / btrfs "
                "rw,noatime,compress=zstd:3,subvol=@ 0 0\n"
                "UUID=abcd-ef01 /boot vfat rw 0 2\n",
                encoding="utf-8",
            )
            grub_d = root / "etc/grub.d"
            self.assertTrue(linxiraboot._write_rescue_entry(root, grub_d))
            script = (grub_d / "41_linxira-rescue").read_text(encoding="utf-8")
        self.assertIn("menuentry 'Linxira OS Rescue (text console)'", script)
        self.assertIn("root=UUID=33f1e33a-e5e1-4676-a72c-67407ab050a2", script)
        self.assertIn("rootflags=subvol=@", script)
        self.assertIn("systemd.unit=multi-user.target", script)
        self.assertIn("/@/boot/vmlinuz-linux", script)
        self.assertIn("/@/boot/initramfs-linux.img", script)

    def test_rescue_entry_skipped_when_fstab_unparseable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "etc").mkdir()
            (root / "etc/fstab").write_text(
                "# only comments here\n", encoding="utf-8"
            )
            grub_d = root / "etc/grub.d"
            self.assertFalse(linxiraboot._write_rescue_entry(root, grub_d))
            self.assertFalse((grub_d / "41_linxira-rescue").exists())


if __name__ == "__main__":
    unittest.main()
