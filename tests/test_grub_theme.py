"""GRUB 主题语法门禁: 未支持的对象类型会让 gfxmenu 直接报错。"""

import pathlib
import unittest


PROFILE_ROOT = pathlib.Path(__file__).parents[1]
THEME = PROFILE_ROOT / "grub/themes/linxira/theme.txt"
SHIPPED = PROFILE_ROOT / "airootfs/usr/share/linxira/grub/themes/linxira/theme.txt"

# grub-core/gfxmenu/theme_loader.c 支持的对象类型
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


class GrubThemeTests(unittest.TestCase):
    def setUp(self):
        self.text = THEME.read_text(encoding="utf-8")

    def test_only_supported_object_types_are_used(self):
        offenders = []
        for line in self.text.splitlines():
            line = line.strip()
            if not line.startswith("+"):
                continue
            kind = line[1:].strip().split()[0].rstrip("{").strip()
            if kind not in OBJECT_TYPES:
                offenders.append(line)
        self.assertEqual(offenders, [], "unsupported theme objects cause gfxmenu errors")

    def test_timeout_uses_the_reserved_label_id(self):
        self.assertIn('id = "__timeout__"', self.text)

    def test_desktop_image_exists(self):
        image = THEME.parent / "background.png"
        self.assertTrue(image.is_file())
        self.assertIn("desktop-image: \"background.png\"", self.text)

    def test_installed_copy_matches_the_iso_theme(self):
        self.assertEqual(THEME.read_bytes(), SHIPPED.read_bytes())
