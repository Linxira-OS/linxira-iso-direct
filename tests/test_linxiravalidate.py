import importlib.util
import json
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
    @staticmethod
    def receipt(selected):
        return {
            "schemaVersion": "org.linxira.installer.selection-receipt.v1",
            "status": "installed",
            "catalogSha256": "a" * 64,
            "catalogRelease": "test",
            "selectedLeafIds": selected,
            "selectedBundleIds": ["desktop-environments"],
            "selectionDocument": {
                "schemaVersion": "org.linxira.component-selection.v1",
                "catalogSha256": "a" * 64,
                "catalogRelease": "test",
                "selectedLeafIds": selected,
                "selectedBundleIds": ["desktop-environments"],
            },
        }

    def test_validator_requires_component_manager_and_catalog_v3(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        for value in (
            '"linxira-component-manager"',
            '"linxira-completion-agent"',
            '"linxira-gaming-manager"',
            '"linxira-recovery-diagnostics"',
            '"linxira-update"',
            '"/usr/bin/linxira-component-manager"',
            '"/usr/bin/linxira-completion-agent"',
            '"/usr/bin/linxira-gaming-manager"',
            '"/usr/bin/linxira-recovery-diagnostics"',
            '"/usr/bin/linxira-components-service"',
            '"/usr/lib/systemd/system/linxira-components.service"',
            '"/usr/bin/linxira-update"',
            '"/etc/xdg/autostart/org.linxira.Completion.desktop"',
            '"/usr/share/applications/org.linxira.ComponentManager.desktop"',
            '"/usr/share/linxira/catalog/catalog-v3.json"',
            '"/usr/share/linxira/catalog/catalog-v3.schema.json"',
        ):
            self.assertIn(value, source)

    def test_validator_requires_installer_selection_receipt(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn('"/var/lib/linxira/installer-selection.json"', source)

    def test_gnome_receipt_adds_session_portal_and_keyring_requirements(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            receipt = Path(temporary_root) / "var/lib/linxira/installer-selection.json"
            receipt.parent.mkdir(parents=True)
            receipt.write_text(
                json.dumps(self.receipt(["desktop-gnome"])),
                encoding="utf-8",
            )
            desktop, session, packages = linxiravalidate._selection_requirements(temporary_root)
        self.assertEqual(desktop, "desktop-gnome")
        self.assertEqual(session, "gnome.desktop")
        self.assertIn("gnome-keyring", packages)
        self.assertIn("xdg-desktop-portal-gnome", packages)
        self.assertIn("xdg-desktop-portal-gtk", packages)

    def test_validator_rejects_inconsistent_nested_selection(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            receipt_path = Path(temporary_root) / "var/lib/linxira/installer-selection.json"
            receipt_path.parent.mkdir(parents=True)
            receipt = self.receipt(["desktop-plasma"])
            receipt["selectionDocument"]["selectedBundleIds"] = ["app-web"]
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inconsistent"):
                linxiravalidate._selection_requirements(temporary_root)

    def test_validator_enforces_sddm_and_shared_portal_plumbing(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        for value in (
            '"wireplumber"',
            '"xdg-desktop-portal"',
            '"xdg-desktop-portal-kde"',
            '"gdm"',
            '"/usr/lib/systemd/system/sddm.service"',
            '"plasma.desktop"',
            '"gnome.desktop"',
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
