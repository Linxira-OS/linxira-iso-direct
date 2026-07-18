from pathlib import Path
import unittest


PROFILE_ROOT = Path(__file__).parents[1]
CONFIG_CLI = PROFILE_ROOT.parent / "linxira-config-hub/cli/linxira-config"


class ConfigCliTests(unittest.TestCase):
    def test_cli_consumes_catalog_v2(self):
        script = CONFIG_CLI.read_text(encoding="utf-8")
        self.assertIn("catalog-v2.json", script)
        self.assertIn(".catalogVersion == 2", script)
        self.assertNotIn("catalog-v1.json", script)

    def test_bio_alias_maps_to_the_reviewed_profile(self):
        script = CONFIG_CLI.read_text(encoding="utf-8")
        self.assertIn("bio) install_catalog_profile bioinformatics", script)

    def test_system_info_reports_only_official_kernel_names(self):
        script = CONFIG_CLI.read_text(encoding="utf-8")
        self.assertIn("/^linux(-lts|-zen|-hardened)?$/", script)
        self.assertNotIn("linux-cachyos|linux-linxira", script)


if __name__ == "__main__":
    unittest.main()
