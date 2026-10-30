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
            self.assertIn('desktop-color: "#000000"', text)
            self.assertNotIn("desktop-image", text)
            self.assertIn(f'item_font = "DejaVu Sans Mono Regular {size}"', text)
            self.assertIn(f'selected_item_font = "DejaVu Sans Mono Bold {size}"', text)
            self.assertIn('file = "logo.png"', text)
            self.assertIn('id = "__timeout__"', text)
            self.assertIn('menu_pixmap_style = "menu_*.png"', text)

    def test_small_vm_modes_fit_without_scrolling(self):
        import re

        text = (THEME_DIR / "theme-20.txt").read_text(encoding="utf-8")
        item_height = int(re.search(r"item_height = (\d+)", text).group(1))
        self.assertIn("height = 52%", text)
        for height in (480, 600, 768):
            with self.subTest(height=height):
                # 6 个菜单项必须放得进 52% 的屏高
                self.assertLessEqual(item_height * 6, int(height * 0.52))
                # 提示行/倒计时仍在屏内
                self.assertLess(0.82 * height, height)

    def test_menu_is_centered_and_has_a_frame(self):
        for size in SIZES:
            text = (THEME_DIR / f"theme-{size}.txt").read_text(encoding="utf-8")
            self.assertIn("left = 20%", text)
            self.assertIn("width = 60%", text)
            self.assertIn("top = 24%", text)
            self.assertIn("height = 52%", text)
            self.assertIn('menu_pixmap_style = "menu_*.png"', text)

    def test_logo_keeps_two_to_one_aspect_ratio(self):
        import re

        for size in SIZES:
            text = (THEME_DIR / f"theme-{size}.txt").read_text(encoding="utf-8")
            logo = text.split("+ image {", 1)[1]
            width = int(re.search(r"width = (\d+)", logo).group(1))
            height = int(re.search(r"height = (\d+)", logo).group(1))
            self.assertEqual(width, height * 2, f"theme-{size} logo stretched")
            self.assertNotIn("%", re.search(r"width = .*", logo).group(0))

    def test_logo_fits_common_resolutions(self):
        import re

        def theme_size(height):
            if height > 2000:
                return 48
            if height > 1400:
                return 40
            if height > 1000:
                return 32
            if height > 700:
                return 24
            return 20

        for width, height in (
            (640, 480), (800, 600), (1024, 768), (1280, 800),
            (1366, 768), (1600, 900), (1680, 1050), (1920, 1080),
            (1920, 1200), (2560, 1080), (2560, 1440), (3440, 1440),
            (3840, 2160),
        ):
            with self.subTest(resolution=f"{width}x{height}"):
                text = (THEME_DIR / f"theme-{theme_size(height)}.txt").read_text(
                    encoding="utf-8"
                )
                logo = text.split("+ image {", 1)[1]
                logo_width = int(re.search(r"width = (\d+)", logo).group(1))
                logo_height = int(re.search(r"height = (\d+)", logo).group(1))
                self.assertLessEqual(0.80 * width + logo_width, width)
                self.assertLessEqual(0.85 * height + logo_height, height)

    def test_logo_and_fonts_exist(self):
        self.assertTrue((THEME_DIR / "logo.png").is_file())
        for name in (
            "menu_nw.png", "menu_n.png", "menu_ne.png",
            "menu_w.png", "menu_c.png", "menu_e.png",
            "menu_sw.png", "menu_s.png", "menu_se.png",
        ):
            self.assertTrue((THEME_DIR / name).is_file(), name)
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
