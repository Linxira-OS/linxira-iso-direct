import importlib.util
import json
from pathlib import Path
import re
import sys
import types
import unittest


PROFILE_ROOT = Path(__file__).parents[1]
CATALOG_ROOT = PROFILE_ROOT.parent / "linxira-catalog"
CATALOG_PATH = CATALOG_ROOT / "catalog/catalog-v2.json"
SCHEMA_PATH = CATALOG_ROOT / "schema/catalog-v2.schema.json"
CHOOSER_PATH = PROFILE_ROOT / "airootfs/etc/calamares/modules/packagechooser_components.conf"
OPTIONAL_MODULE_PATH = (
    PROFILE_ROOT / "airootfs/usr/lib/calamares/modules/linxiraoptional/main.py"
)

sys.modules.setdefault("libcalamares", types.ModuleType("libcalamares"))
spec = importlib.util.spec_from_file_location("linxiraoptional", OPTIONAL_MODULE_PATH)
linxiraoptional = importlib.util.module_from_spec(spec)
spec.loader.exec_module(linxiraoptional)


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    def test_ids_and_references_are_unique_and_valid(self):
        category_ids = [category["id"] for category in self.catalog["categories"]]
        profile_ids = [profile["id"] for profile in self.catalog["profiles"]]
        self.assertEqual(len(category_ids), len(set(category_ids)))
        self.assertEqual(len(profile_ids), len(set(profile_ids)))
        self.assertEqual(self.catalog["catalogVersion"], 2)

        source_ids = [source["id"] for source in self.catalog["sources"]]
        self.assertEqual(len(source_ids), len(set(source_ids)))

        for profile in self.catalog["profiles"]:
            self.assertEqual(profile["source"], "arch")
            self.assertIn(profile["source"], source_ids)
            self.assertTrue(profile["packages"])
            self.assertTrue(set(profile["categories"]).issubset(category_ids))
            self.assertEqual(profile["review"]["status"], "reviewed")
            self.assertIn("x86_64", profile["availability"]["architectures"])
            for package in profile["packages"]:
                self.assertRegex(package, r"^[a-z0-9@._+:-]+$")

    def test_catalog_declares_the_v2_schema(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.catalog["$schema"], "catalog-v2.schema.json")
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["catalogVersion"]["const"], 2)

    def test_installer_chooser_matches_catalog_profiles(self):
        chooser_ids = set(
            re.findall(r"^  - id: ([a-z0-9-]+)$", CHOOSER_PATH.read_text(encoding="utf-8"), re.M)
        )
        installer_ids = {
            profile["id"] for profile in self.catalog["profiles"] if profile["installer"]
        }
        self.assertEqual(chooser_ids, installer_ids)

    def test_optional_selection_is_an_allowlist(self):
        selected_ids, profiles = linxiraoptional._selected_profiles(
            self.catalog, "science,containers"
        )
        self.assertEqual(selected_ids, ["science", "containers"])
        self.assertEqual([profile["id"] for profile in profiles], selected_ids)
        with self.assertRaises(ValueError):
            linxiraoptional._selected_profiles(self.catalog, "science,--overwrite")

    def test_optional_job_downloads_without_modifying_the_base(self):
        command = linxiraoptional._download_command("/target", ["jupyterlab"])
        self.assertIn("--downloadonly", command)
        self.assertNotIn("--sysupgrade", command)
        self.assertEqual(command[-2:], ["--", "jupyterlab"])


if __name__ == "__main__":
    unittest.main()
