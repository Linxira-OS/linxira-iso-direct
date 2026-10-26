"""GRUB 主题门禁: 对象类型、字号变体、两处资源一致。"""

import pathlib
import unittest


PROFILE_ROOT = pathlib.Path(__file__).parents[1]
THEME_DIR = PROFILE_ROOT / "grub/themes/linxira"
SHIPPED_DIR = PROFILE_ROOT / "airootfs/usr/share/linxira/grub/themes/linxira"

OBJECT_TYPES = {
    "boot_menu",
    "label",
    "progress_bar",
    "circular_progress",
    "image",
    "vbox",
    "hbox",
    "canvas",
}
SIZES = (20, 24, 32, 40, 48)


class GrubThemeTests(unittest.TestCase):
    def test_every_size_variant_is_valid(self):
        for size in SIZES:
            path = THEME_DIR / f"theme-{size}.txt"
            self.assertTrue(path.is_file(), path.name)
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                line = line.strip()
                if not line.startswith("+"):
                    continue
                kind = line[1:].strip().split()[0].rstrip("{").strip()
                self.assertIn(kind, OBJECT_TYPES, f"{path.name}: {line}")
            self.assertIn('desktop-image: "background.png"', text)
            self.assertIn(f'item_font = "DejaVu Sans Mono Regular {size}"', text)
            self.assertIn('id = "__timeout__"', text)

    def test_background_and_fonts_exist(self):
        self.assertTrue((THEME_DIR / "background.png").is_file())
        for size in SIZES:
            self.assertTrue((THEME_DIR / f"fonts/linxira-ui-{size}.pf2").is_file())
            self.assertTrue((THEME_DIR / f"fonts/linxira-ui-bold-{size}.pf2").is_file())

    def test_selector_has_no_arithmetic(self):
        # GRUB 脚本不支持 $(( )); 只用简单比较。
        cfg = (PROFILE_ROOT / "grub/grub.cfg").read_text(encoding="utf-8")
        self.assertIn("gfxheight", cfg)
        self.assertIn("theme-$ui.txt", cfg)
        self.assertNotIn("$((gfx", cfg)
        module = (PROFILE_ROOT / "airootfs/usr/lib/calamares/modules/linxiraboot/main.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("_write_theme_selector", module)
        self.assertIn("theme-$ui.txt", module)
        self.assertNotIn("$((gfx", module)

    def test_installed_copy_matches_the_iso_theme(self):
        iso_files = sorted(p.name for p in THEME_DIR.rglob("*") if p.is_file())
        shipped_files = sorted(p.name for p in SHIPPED_DIR.rglob("*") if p.is_file())
        self.assertEqual(iso_files, shipped_files)
        for name in iso_files:
            iso = next(THEME_DIR.rglob(name))
            shipped = next(SHIPPED_DIR.rglob(name))
            self.assertEqual(iso.read_bytes(), shipped.read_bytes(), name)
