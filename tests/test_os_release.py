"""os-release 品牌链接门禁: 不使用我们并不拥有的域名。"""

import pathlib
import unittest


PROFILE_ROOT = pathlib.Path(__file__).parents[1]
OS_RELEASE = PROFILE_ROOT / "airootfs/etc/os-release"


class OsReleaseTests(unittest.TestCase):
    def setUp(self):
        self.text = OS_RELEASE.read_text(encoding="utf-8")

    def test_no_unowned_domain(self):
        self.assertNotIn("linxira.org", self.text)

    def test_links_point_at_the_project(self):
        for line in (
            'HOME_URL="https://github.com/Linxira-OS"',
            'DOCUMENTATION_URL="https://linxira-os.github.io"',
            'SUPPORT_URL="https://github.com/Linxira-OS"',
            'BUG_REPORT_URL="https://github.com/Linxira-OS/linxira-os/issues"',
        ):
            self.assertIn(line, self.text)

    def test_ansi_color_matches_the_brand(self):
        self.assertIn('ANSI_COLOR="38;2;20;184;166"', self.text)
