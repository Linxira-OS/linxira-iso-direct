from pathlib import Path
import shutil
import sys
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
    def test_target_ships_os_prober_for_non_windows_fallback(self):
        target = set((PROFILE_ROOT / "target-packages.x86_64").read_text(encoding="utf-8").split())
        self.assertIn("os-prober", target)
        settings = dict(linxiraboot.GRUB_SETTINGS)
        self.assertEqual(settings["GRUB_DISABLE_OS_PROBER"], "false")

    def test_installed_grub_keeps_the_branded_menu(self):
        settings = dict(linxiraboot.GRUB_SETTINGS)
        self.assertEqual(settings["GRUB_TERMINAL_OUTPUT"], '"gfxterm"')
        self.assertEqual(settings["GRUB_THEME"], '"/boot/grub/themes/linxira/theme-24.txt"')
        self.assertEqual(settings["GRUB_BACKGROUND"], '""')
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
            original_theme = linxiraboot.GRUB_THEME_SOURCE
            linxiraboot.GRUB_SPLASH_SOURCE = source
            linxiraboot.GRUB_THEME_SOURCE = PROFILE_ROOT / "airootfs/usr/share/linxira/grub/themes/linxira"
            try:
                linxiraboot._install_grub_splash(root)
            finally:
                linxiraboot.GRUB_SPLASH_SOURCE = original
                linxiraboot.GRUB_THEME_SOURCE = original_theme
            self.assertEqual((root / "boot/grub/linxira-splash.png").read_bytes(), source.read_bytes())
            self.assertEqual((root / "usr/share/linxira/grub/splash.png").read_bytes(), source.read_bytes())
            theme_dest = root / "boot/grub/themes/linxira"
            self.assertTrue((theme_dest / "theme-24.txt").is_file())
            self.assertTrue((theme_dest / "logo.png").is_file())
            self.assertTrue((theme_dest / "fonts/linxira-ui-32.pf2").is_file())


    def test_grub_settings_pin_mainline_top_level(self):
        settings = dict(linxiraboot.GRUB_SETTINGS)
        self.assertEqual(settings["GRUB_TOP_LEVEL"], '"/boot/vmlinuz-linux"')
        self.assertEqual(settings["GRUB_DEFAULT"], "saved")
        self.assertEqual(settings["GRUB_SAVEDEFAULT"], "true")
        self.assertEqual(settings["GRUB_TIMEOUT"], "2")
        self.assertEqual(settings["GRUB_DISABLE_SUBMENU"], "true")
        self.assertIn("2880x1800", settings["GRUB_GFXMODE"])

    @unittest.skipUnless(shutil.which("grub-editenv"), "requires grub-editenv")
    def test_saved_entry_is_prepared_with_grub_editenv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "etc").mkdir()
            (root / "etc/fstab").write_text(
                "UUID=0123-4567 /boot/efi vfat umask=0077 0 2\n",
                encoding="utf-8",
            )
            linxiraboot._prepare_grub_env(root)
            env = (root / "boot/grub/grubenv").read_text(encoding="utf-8")
            self.assertIn("saved_entry=0", env)
            self.assertEqual(len(env), 1024)

    def test_theme_title_uses_image_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            theme = root / "boot/grub/themes/linxira"
            theme.mkdir(parents=True)
            (theme / "theme-32.txt").write_text(
                'title-text: "Linxira OS"\n', encoding="utf-8"
            )
            (root / "etc").mkdir()
            (root / "etc/linxira-release").write_text("2026.10.30\n", encoding="utf-8")
            linxiraboot._brand_theme_title(root)
            self.assertIn(
                'title-text: "Linxira OS 2026.10.30"',
                (theme / "theme-32.txt").read_text(encoding="utf-8"),
            )

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

class WindowsEntryTests(unittest.TestCase):
    """Windows 条目由安装期确定性生成, 不依赖 chroot 里的 os-prober。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "etc").mkdir()
        self.grub_d = self.root / "etc/grub.d"

    def write_fstab(self, entry="UUID=1234-ABCD /boot/efi vfat umask=0077 0 2"):
        (self.root / "etc/fstab").write_text(entry + "\n", encoding="utf-8")

    def make_windows_loader(self, mount="boot/efi"):
        loader = self.root / mount / "EFI/Microsoft/Boot/bootmgfw.efi"
        loader.parent.mkdir(parents=True, exist_ok=True)
        loader.write_bytes(b"MZ")

    def test_entry_is_generated_when_bootmgfw_exists(self):
        self.write_fstab()
        self.make_windows_loader()
        self.assertTrue(linxiraboot._write_windows_entry(self.root, self.grub_d))
        script = (self.grub_d / "29_linxira-windows").read_text(encoding="utf-8")
        self.assertIn("--class windows", script)
        self.assertIn("--id 'linxira-windows'", script)
        self.assertIn("--fs-uuid --set=root 1234-ABCD", script)
        self.assertIn("chainloader /EFI/Microsoft/Boot/bootmgfw.efi", script)
        self.assertIn("savedefault", script)
        if sys.platform.startswith("linux"):
            self.assertTrue((self.grub_d / "29_linxira-windows").stat().st_mode & 0o111)

    def test_efi_mountpoint_variant_is_supported(self):
        self.write_fstab("UUID=9999-FFFF /efi vfat umask=0077 0 2")
        self.make_windows_loader(mount="efi")
        self.assertTrue(linxiraboot._write_windows_entry(self.root, self.grub_d))

    def test_no_windows_loader_means_no_entry(self):
        self.write_fstab()
        self.assertFalse(linxiraboot._write_windows_entry(self.root, self.grub_d))
        self.assertFalse((self.grub_d / "29_linxira-windows").exists())

    def test_no_esp_in_fstab_means_no_entry(self):
        self.write_fstab("UUID=root-uuid / btrfs subvol=/ 0 0")
        self.make_windows_loader()
        self.assertFalse(linxiraboot._write_windows_entry(self.root, self.grub_d))

    def test_missing_fstab_is_tolerated(self):
        self.assertFalse(linxiraboot._write_windows_entry(self.root, self.grub_d))
