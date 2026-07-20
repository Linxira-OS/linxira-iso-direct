import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


MODULE_PATH = (
    Path(__file__).parents[1]
    / "airootfs/usr/lib/calamares/modules/linxirapacstrap/main.py"
)
libcalamares = types.ModuleType("libcalamares")
libcalamares.globalstorage = types.SimpleNamespace(value=lambda key: None)
libcalamares.job = types.SimpleNamespace(configuration={}, setprogress=lambda value: None)
libcalamares.utils = types.SimpleNamespace(debug=lambda value: None)
sys.modules["libcalamares"] = libcalamares
spec = importlib.util.spec_from_file_location("linxirapacstrap", MODULE_PATH)
linxirapacstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(linxirapacstrap)


class PacstrapSelectionTests(unittest.TestCase):
    def setUp(self):
        self.catalog_path = Path(__file__).parents[2] / "linxira-catalog/catalog/catalog-v3.json"
        self.catalog = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        self.digest = __import__("hashlib").sha256(self.catalog_path.read_bytes()).hexdigest()
        self.selection = {
            "catalogVersion": 3,
            "catalogRelease": self.catalog["release"],
            "catalogSha256": self.digest,
            "selectedLeafIds": ["firefox"],
            "selectedBundleIds": ["app-web"],
        }

    def test_included_firefox_is_satisfied_by_fixed_manifest(self):
        config = {
            "catalogPath": str(self.catalog_path),
            "selectionKey": "linxiraSoftwareSelection",
        }
        with mock.patch.object(
            libcalamares.globalstorage, "value", return_value=self.selection
        ):
            result = linxirapacstrap._catalog_selection(config, ["firefox"])
        self.assertEqual(result["satisfiedItems"], ["firefox"])
        self.assertEqual(result["pendingItems"], [])

    def test_online_choice_is_recorded_pending_without_new_pacman_target(self):
        selection = dict(self.selection)
        selection["selectedLeafIds"] = ["chromium"]
        config = {"catalogPath": str(self.catalog_path), "selectionKey": "key"}
        with mock.patch.object(libcalamares.globalstorage, "value", return_value=selection):
            result = linxirapacstrap._catalog_selection(config, ["firefox"])
        self.assertEqual(result["satisfiedItems"], [])
        self.assertEqual(result["pendingItems"], ["chromium"])

    def test_catalog_drift_fails_closed(self):
        selection = dict(self.selection)
        selection["catalogSha256"] = "0" * 64
        config = {"catalogPath": str(self.catalog_path), "selectionKey": "key"}
        with mock.patch.object(libcalamares.globalstorage, "value", return_value=selection):
            with self.assertRaisesRegex(ValueError, "stale"):
                linxirapacstrap._catalog_selection(config, ["firefox"])

    def test_receipt_is_written_inside_target(self):
        with tempfile.TemporaryDirectory() as directory:
            linxirapacstrap._write_receipt(Path(directory), self.selection, ["firefox"])
            receipt = json.loads(
                (Path(directory) / "var/lib/linxira/installer-selection.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(receipt["schemaVersion"], "org.linxira.installer.selection-receipt.v1")
        self.assertEqual(receipt["installedBaselinePackages"], ["firefox"])


if __name__ == "__main__":
    unittest.main()
