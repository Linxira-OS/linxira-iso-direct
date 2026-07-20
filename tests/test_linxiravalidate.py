import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "airootfs/usr/lib/calamares/modules/linxiravalidate/main.py"
)
sys.modules.setdefault("libcalamares", types.ModuleType("libcalamares"))
spec = importlib.util.spec_from_file_location("linxiravalidate", MODULE_PATH)
linxiravalidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(linxiravalidate)


class InstalledSystemValidationTests(unittest.TestCase):
    def test_validator_requires_component_manager_and_catalog_v3(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        for value in (
            '"linxira-component-manager"',
            '"/usr/bin/linxira-component-manager"',
            '"/usr/share/applications/org.linxira.ComponentManager.desktop"',
            '"/usr/share/linxira/catalog/catalog-v3.json"',
            '"/usr/share/linxira/catalog/catalog-v3.schema.json"',
        ):
            self.assertIn(value, source)

    def test_obsolete_initcpio_module_spellings_are_found_in_all_config_locations(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            main_config = root / "etc/mkinitcpio.conf"
            drop_in = root / "etc/mkinitcpio.conf.d/graphics.conf"
            preset = root / "etc/mkinitcpio.d/linux.preset"
            main_config.parent.mkdir(parents=True)
            drop_in.parent.mkdir(parents=True)
            preset.parent.mkdir(parents=True)
            main_config.write_text("MODULES=(crc32c-intel)\n", encoding="utf-8")
            drop_in.write_text("MODULES=(crc32c_intel)\n", encoding="utf-8")
            preset.write_text("ALL_kver=/boot/vmlinuz-linux\n", encoding="utf-8")

            self.assertEqual(
                linxiravalidate._obsolete_initcpio_configs(root),
                [
                    "/etc/mkinitcpio.conf",
                    "/etc/mkinitcpio.conf.d/graphics.conf",
                ],
            )

    def test_supported_crc32c_module_is_not_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            config = Path(temporary_root) / "etc/mkinitcpio.conf"
            config.parent.mkdir(parents=True)
            config.write_text("MODULES=(amdgpu crc32c)\n", encoding="utf-8")

            self.assertEqual(
                linxiravalidate._obsolete_initcpio_configs(temporary_root), []
            )


if __name__ == "__main__":
    unittest.main()
