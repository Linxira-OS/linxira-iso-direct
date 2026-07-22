import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


PROFILE_ROOT = Path(__file__).parents[1]
MODULE_PATH = PROFILE_ROOT / "airootfs/usr/lib/calamares/modules/linxirapacstrap/main.py"
CATALOG_PATH = PROFILE_ROOT.parent / "linxira-catalog/catalog/catalog-v3.json"
BASELINE = PROFILE_ROOT / "target-packages.x86_64"
CANDIDATES = PROFILE_ROOT / "offline-candidate-packages.x86_64"

libcalamares = types.ModuleType("libcalamares")
libcalamares.globalstorage = types.SimpleNamespace(value=lambda key: None)
libcalamares.job = types.SimpleNamespace(configuration={}, setprogress=lambda value: None)
libcalamares.utils = types.SimpleNamespace(debug=lambda value: None)
sys.modules["libcalamares"] = libcalamares
spec = importlib.util.spec_from_file_location("linxirapacstrap", MODULE_PATH)
linxirapacstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(linxirapacstrap)


class PacstrapSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.digest = hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest()
        cls.baseline = linxirapacstrap._manifest(BASELINE)
        cls.candidates = linxirapacstrap._manifest(CANDIDATES)
        cls.config = {"catalogPath": str(CATALOG_PATH), "selectionKey": "selection"}
        cls.leaves = {
            item["id"]: item
            for section in ("desktops", "applications", "components")
            for item in cls.catalog[section]
        }
        cls.bundles, cls.categories, cls.roles = linxirapacstrap._bundle_graph(cls.catalog)

    def selection(self, requests=None):
        requests = requests or {"desktop-plasma": "desktop-environments/desktop-plasma"}
        selected = sorted(requests)
        roots = sorted(set(self.categories) & set(self.bundles))
        bundle_ids = sorted({
            part
            for leaf_id in selected
            for root in roots
            for path in linxirapacstrap._paths_to_leaf(
                root, leaf_id, self.bundles, self.roles, self.leaves
            )
            for part in path[:-1]
        })
        document = {
            "schemaVersion": "org.linxira.installer-selection.v1",
            "catalogVersion": 3,
            "catalogSha256": self.digest,
            "catalogRelease": self.catalog["release"],
            "selectedLeafIds": selected,
            "selectedBundleIds": bundle_ids,
        }
        return document

    def validate(self, selection):
        with mock.patch.object(libcalamares.globalstorage, "value", return_value=selection):
            return linxirapacstrap._catalog_selection(
                self.config, self.baseline, self.candidates
            )

    def test_plasma_default_is_satisfied_without_candidate_additions(self):
        result = self.validate(self.selection())
        self.assertEqual(result["selectedPackages"], [])
        self.assertEqual(result["satisfiedItems"], ["desktop-plasma"])

    def test_unverified_gnome_selection_fails_closed(self):
        selection = self.selection(
            {"desktop-gnome": "desktop-environments/desktop-gnome"}
        )
        with self.assertRaisesRegex(ValueError, "not eligible: desktop-gnome"):
            self.validate(selection)

    def test_online_reviewed_choice_is_pending_not_installed(self):
        selection = self.selection(
            {
                "chromium": "app-web/chromium",
                "desktop-plasma": "desktop-environments/desktop-plasma",
            }
        )
        result = self.validate(selection)
        self.assertEqual(result["selectedPackages"], [])
        self.assertEqual(result["pendingItems"], ["chromium"])

    def test_component_selection_has_catalog_root_provenance(self):
        selection = self.selection({
            "component-cups": "cap-system/component-cups",
            "desktop-plasma": "desktop-environments/desktop-plasma",
        })
        result = self.validate(selection)
        cups = next(
            item
            for item in result["selectionDocument"]["leaves"]
            if item["id"] == "component-cups"
        )
        self.assertIn("cap-system/component-cups", cups["requestedBy"])
        self.assertIn("cap-system", result["selectionDocument"]["selectedBundleIds"])

    def test_catalog_drift_fails_closed(self):
        selection = self.selection()
        selection["catalogSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "stale"):
            self.validate(selection)

    def test_unknown_leaf_and_bundle_fail_closed(self):
        selection = self.selection()
        selection["selectedLeafIds"] = ["desktop-unknown"]
        with self.assertRaisesRegex(ValueError, "unknown selected Catalog IDs"):
            self.validate(selection)

        selection = self.selection()
        selection["selectedBundleIds"] = ["unknown-bundle"]
        with self.assertRaisesRegex(ValueError, "unknown selected Catalog bundles"):
            self.validate(selection)

    def test_exclusive_desktop_and_tampered_bundle_provenance_fail_closed(self):
        selection = self.selection(
            {
                "desktop-gnome": "desktop-environments/desktop-gnome",
                "desktop-plasma": "desktop-environments/desktop-plasma",
            }
        )
        with self.assertRaisesRegex(ValueError, "constraint"):
            self.validate(selection)

        selection = self.selection()
        selection["selectedBundleIds"] = ["app-web"]
        with self.assertRaisesRegex(ValueError, "derived selection provenance"):
            self.validate(selection)

    def test_ineligible_review_channel_selection_is_rejected(self):
        selection = self.selection(
            {
                "desktop-plasma": "desktop-environments/desktop-plasma",
                "wps-office": "app-office/wps-office",
            }
        )
        with self.assertRaisesRegex(ValueError, "not eligible: wps-office"):
            self.validate(selection)

    def test_unknown_fields_cannot_inject_packages(self):
        selection = self.selection()
        selection["directPackageTargets"] = ["gdm"]
        with self.assertRaisesRegex(ValueError, "missing or unknown fields"):
            self.validate(selection)

    def test_selection_field_types_are_exact(self):
        selection = self.selection()
        selection["selectedLeafIds"] = "desktop-plasma"
        with self.assertRaisesRegex(ValueError, "selectedLeafIds"):
            self.validate(selection)

        selection = self.selection()
        selection["catalogVersion"] = True
        with self.assertRaisesRegex(ValueError, "catalogVersion"):
            self.validate(selection)

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON key: selectedLeafIds"):
            linxirapacstrap._strict_json(
                '{"selectedLeafIds":[],"selectedLeafIds":["gdm"]}'
            )

    def test_receipt_separates_baseline_selected_and_full_provenance(self):
        selection = self.selection()
        result = self.validate(selection)
        with tempfile.TemporaryDirectory() as directory:
            linxirapacstrap._write_receipt(
                Path(directory), result, self.baseline, result["selectedPackages"]
            )
            receipt = json.loads(
                (Path(directory) / "var/lib/linxira/installer-selection.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(receipt["installedBaselinePackages"], self.baseline)
        self.assertEqual(receipt["installedSelectedPackages"], [])
        self.assertEqual(
            receipt["selectionDocument"]["schemaVersion"],
            "org.linxira.component-selection.v1",
        )
        self.assertEqual(
            receipt["selectionDocument"]["leaves"],
            [{
                "id": "desktop-plasma",
                "requestedBy": ["desktop-environments/desktop-plasma"],
                "provenance": ["optional", "user"],
            }],
        )

    def test_target_multilib_is_enabled_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "etc/pacman.conf"
            config.parent.mkdir(parents=True)
            config.write_text(
                "[core]\nInclude = /etc/pacman.d/mirrorlist\n"
                "#[multilib]\n#Include = /etc/pacman.d/mirrorlist\n",
                encoding="utf-8",
            )
            linxirapacstrap._enable_target_multilib(directory)
            linxirapacstrap._enable_target_multilib(directory)
            contents = config.read_text(encoding="utf-8")
        self.assertIn("[multilib]\nInclude = /etc/pacman.d/mirrorlist", contents)
        self.assertNotIn("#[multilib]", contents)


if __name__ == "__main__":
    unittest.main()
