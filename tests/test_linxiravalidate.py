import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


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
            '"linxira-chwd-detector"',
            '"linxira-hardware-driver-manager"',
            '"linxira-recovery-diagnostics"',
            '"linxira-update"',
            '"/usr/bin/linxira-component-manager"',
            '"/usr/bin/linxira-completion-agent"',
            '"/usr/bin/linxira-gaming-manager"',
            '"/usr/bin/linxira-chwd-detector"',
            '"/usr/bin/linxira-hardware-driver-manager"',
            '"/usr/bin/linxira-recovery-diagnostics"',
            '"/usr/bin/linxira-components-service"',
            '"/usr/lib/systemd/system/linxira-components.service"',
            '"linxira-components": "0.7.0-4"',
            '"linxira-hardware-driver-manager": "0.4.0-2"',
            '"/usr/bin/linxira-components-worker"',
            '"/usr/lib/systemd/system/linxira-components-worker@.service"',
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

    def test_selected_catalog_packages_are_returned_for_validation(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            catalog_path = root / "usr/share/linxira/catalog/catalog-v3.json"
            catalog_path.parent.mkdir(parents=True)
            catalog_path.write_text(json.dumps({
                "catalogVersion": 3,
                "release": "test",
                "desktops": [{
                    "id": "desktop-plasma",
                    "provider": "pacman",
                    "source": "arch",
                    "artifact": {"type": "package-group", "ids": ["plasma-meta"]},
                }],
                "applications": [],
                "components": [],
                "operations": [],
            }), encoding="utf-8")
            receipt = self.receipt(["desktop-plasma"])
            receipt["catalogSha256"] = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
            receipt["catalogRelease"] = "test"
            receipt["satisfiedItems"] = ["desktop-plasma"]
            receipt["pendingItems"] = []
            receipt["installedItems"] = ["desktop-plasma"]
            receipt["deferredItems"] = []
            receipt["itemStatuses"] = [
                {"id": "desktop-plasma", "status": "installed"}
            ]
            receipt["installedSelectedPackages"] = ["plasma-meta"]
            receipt_path = root / "var/lib/linxira/installer-selection.json"
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            self.assertEqual(
                linxiravalidate._selected_package_requirements(root), ["plasma-meta"]
            )

    def test_selected_package_validation_rejects_status_disagreement(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            catalog_path = root / "usr/share/linxira/catalog/catalog-v3.json"
            catalog_path.parent.mkdir(parents=True)
            catalog_path.write_text(json.dumps({
                "catalogVersion": 3,
                "release": "test",
                "desktops": [{
                    "id": "desktop-plasma",
                    "provider": "pacman",
                    "source": "arch",
                    "artifact": {"type": "package", "ids": ["plasma-meta"]},
                }],
            }), encoding="utf-8")
            receipt = self.receipt(["desktop-plasma"])
            receipt.update({
                "catalogSha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
                "satisfiedItems": ["desktop-plasma"],
                "pendingItems": [],
                "installedItems": [],
                "deferredItems": [],
                "itemStatuses": [{"id": "desktop-plasma", "status": "installed"}],
                "installedSelectedPackages": ["plasma-meta"],
            })
            receipt_path = root / "var/lib/linxira/installer-selection.json"
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "classifications disagree"):
                linxiravalidate._selected_package_requirements(root)

    def test_chromium_and_libreoffice_fresh_are_required_by_final_validation(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            catalog_path = root / "usr/share/linxira/catalog/catalog-v3.json"
            catalog_path.parent.mkdir(parents=True)
            catalog_path.write_text(json.dumps({
                "catalogVersion": 3,
                "release": "test",
                "desktops": [],
                "applications": [
                    {
                        "id": "chromium",
                        "provider": "pacman",
                        "source": "arch",
                        "artifact": {"type": "package", "ids": ["chromium"]},
                    },
                    {
                        "id": "libreoffice-fresh",
                        "provider": "pacman",
                        "source": "arch",
                        "artifact": {
                            "type": "package",
                            "ids": ["libreoffice-fresh"],
                        },
                    },
                ],
                "components": [],
                "operations": [],
            }), encoding="utf-8")
            selected = ["chromium", "libreoffice-fresh"]
            receipt = self.receipt(selected)
            receipt.update({
                "catalogSha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
                "satisfiedItems": selected,
                "pendingItems": [],
                "installedItems": selected,
                "deferredItems": [],
                "itemStatuses": [
                    {"id": leaf_id, "status": "installed"} for leaf_id in selected
                ],
                "installedSelectedPackages": ["chromium", "libreoffice-fresh"],
            })
            receipt["selectionDocument"]["selectedLeafIds"] = selected
            receipt_path = root / "var/lib/linxira/installer-selection.json"
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            self.assertEqual(
                linxiravalidate._selected_package_requirements(root),
                ["chromium", "libreoffice-fresh"],
            )

    def test_package_group_is_satisfied_only_when_all_sync_group_members_are_installed(self):
        group = types.SimpleNamespace(returncode=0, stdout="gcc\nmake\n")
        with mock.patch.object(linxiravalidate, "_package_installed") as installed, mock.patch.object(
            linxiravalidate.subprocess, "run", return_value=group
        ):
            installed.side_effect = lambda _root, package: package in {"gcc", "make"}
            self.assertTrue(
                linxiravalidate._package_or_group_installed("/target", "base-devel")
            )
            installed.side_effect = lambda _root, package: package == "gcc"
            self.assertFalse(
                linxiravalidate._package_or_group_installed("/target", "base-devel")
            )

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

    def test_validator_rejects_arch_branded_grub_menu(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn('GRUB_DISTRIBUTOR="Linxira OS"', source)
        self.assertIn("Advanced options for Arch Linux", source)
        self.assertIn("GRUB menu still uses Arch Linux branding", source)

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
