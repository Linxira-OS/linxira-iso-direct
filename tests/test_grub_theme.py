"""GRUB 主题门禁: 对象类型、变体完整性、两处资源一致。"""

import pathlib
import re
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
ASPECTS = ("16x9", "16x10", "21x9")
SIZES = (24, 32, 40, 48)


class GrubThemeTests(unittest.TestCase):
    def test_every_variant_exists_and_uses_supported_objects(self):
        for aspect in ASPECTS:
            for size in SIZES:
                path = THEME_DIR / f"theme-{aspect}-{size}.txt"
                self.assertTrue(path.is_file(), path.name)
                text = path.read_text(encoding="utf-8")
                for line in text.splitlines():
                    line = line.strip()
                    if not line.startswith("+"):
                        continue
                    kind = line[1:].strip().split()[0].rstrip("{").strip()
                    self.assertIn(kind, OBJECT_TYPES, f"{path.name}: {line}")
                self.assertIn(f'desktop-image: "bg-{aspect}.png"', text)
                self.assertIn(f'font = "DejaVu Sans Mono {size}"', text)
                self.assertIn('id = "__timeout__"', text)

    def test_backgrounds_and_fonts_exist(self):
        for aspect in ASPECTS:
            self.assertTrue((THEME_DIR / f"bg-{aspect}.png").is_file())
        for size in SIZES:
            self.assertTrue((THEME_DIR / f"fonts/linxira-ui-{size}.pf2").is_file())

    def test_selector_picks_by_height_and_aspect(self):
        cfg = (PROFILE_ROOT / "grub/grub.cfg").read_text(encoding="utf-8")
        for marker in ("gfxheight", "gfxwidth", "theme-${aspect}-${ui}.txt"):
            self.assertIn(marker, cfg)
        module = (PROFILE_ROOT / "airootfs/usr/lib/calamares/modules/linxiraboot/main.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("_write_theme_selector", module)
        self.assertIn("theme-${aspect}-${ui}.txt", module)

    def test_installed_copy_matches_the_iso_theme(self):
        iso_files = sorted(p.name for p in THEME_DIR.rglob("*") if p.is_file())
        shipped_files = sorted(p.name for p in SHIPPED_DIR.rglob("*") if p.is_file())
        self.assertEqual(iso_files, shipped_files)
        for name in iso_files:
            iso = next(THEME_DIR.rglob(name))
            shipped = next(SHIPPED_DIR.rglob(name))
            self.assertEqual(iso.read_bytes(), shipped.read_bytes(), name)
