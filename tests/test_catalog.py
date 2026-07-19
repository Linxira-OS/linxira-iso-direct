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
DESKTOP_CHOOSER_PATH = PROFILE_ROOT / "airootfs/etc/calamares/modules/packagechooser_desktop.conf"
APPLICATION_CHOOSER_PATH = PROFILE_ROOT / "airootfs/etc/calamares/modules/packagechooser_applications.conf"
SETTINGS_PATH = PROFILE_ROOT / "airootfs/etc/calamares/settings.conf"
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
        application_ids = [application["id"] for application in self.catalog["applications"]]
        profile_ids = [profile["id"] for profile in self.catalog["profiles"]]
        desktop_ids = [desktop["id"] for desktop in self.catalog["desktopBundles"]]
        self.assertEqual(len(category_ids), len(set(category_ids)))
        self.assertEqual(len(application_ids), len(set(application_ids)))
        self.assertEqual(len(profile_ids), len(set(profile_ids)))
        self.assertEqual(len(desktop_ids), len(set(desktop_ids)))
        self.assertEqual(self.catalog["catalogVersion"], 2)

        source_ids = [source["id"] for source in self.catalog["sources"]]
        self.assertEqual(len(source_ids), len(set(source_ids)))
        sources = {source["id"]: source for source in self.catalog["sources"]}
        self.assertEqual(sources["conda-forge"]["kind"], "conda")
        self.assertEqual(sources["bioconda"]["trust"], "verified-third-party")

        for application in self.catalog["applications"]:
            self.assertIn(application["source"], source_ids)
            self.assertTrue(application["packages"])
            self.assertTrue(set(application["categories"]).issubset(category_ids))
            self.assertIn(application["review"]["status"], {"reviewed", "needs-vm-test", "source-review"})
            self.assertIn("x86_64", application["availability"]["architectures"])
            for package in application["packages"]:
                self.assertRegex(package, r"^[a-z0-9@._+:-]+$")

        for profile in self.catalog["profiles"]:
            self.assertEqual(profile["source"], "arch")
            self.assertIn(profile["source"], source_ids)
            self.assertTrue(profile["packages"])
            self.assertTrue(set(profile["categories"]).issubset(category_ids))
            self.assertEqual(profile["review"]["status"], "reviewed")
            self.assertIn("x86_64", profile["availability"]["architectures"])
            for package in profile["packages"]:
                self.assertRegex(package, r"^[a-z0-9@._+:-]+$")
        for desktop in self.catalog["desktopBundles"]:
            self.assertIn(desktop["desktopType"], {"desktop", "compositor", "window-manager"})
            self.assertIn(desktop["support"], {"stable", "candidate"})
            self.assertTrue(desktop["packages"])
            for package in desktop["packages"]:
                self.assertRegex(package, r"^[a-z0-9@._+:-]+$")

        for profile in self.catalog["profiles"]:
            for application_id in profile.get("applications", []):
                self.assertIn(application_id, application_ids)

    def test_catalog_declares_the_v2_schema(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.catalog["$schema"], "catalog-v2.schema.json")
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["catalogVersion"]["const"], 2)
        self.assertIn("applications", schema["required"])

    def test_installer_chooser_matches_catalog_profiles(self):
        chooser_ids = set(
            re.findall(r"^  - id: ([a-z0-9-]+)$", CHOOSER_PATH.read_text(encoding="utf-8"), re.M)
        )
        installer_ids = {
            profile["id"] for profile in self.catalog["profiles"] if profile["installer"]
        }
        self.assertEqual(chooser_ids, installer_ids)

    def test_desktop_chooser_matches_catalog_bundles(self):
        chooser_ids = set(
            re.findall(r"^  - id: ([a-z0-9-]+)$", DESKTOP_CHOOSER_PATH.read_text(encoding="utf-8"), re.M)
        )
        self.assertEqual(chooser_ids, {desktop["id"] for desktop in self.catalog["desktopBundles"]})

    def test_application_chooser_matches_catalog_applications(self):
        chooser_ids = set(
            re.findall(
                r"^  - id: ([a-z0-9-]+)$",
                APPLICATION_CHOOSER_PATH.read_text(encoding="utf-8"),
                re.M,
            )
        )
        installer_ids = {
            application["id"]
            for application in self.catalog["applications"]
            if application["installer"]
        }
        self.assertEqual(chooser_ids, installer_ids)

    def test_application_chooser_is_in_the_install_sequence(self):
        settings = SETTINGS_PATH.read_text(encoding="utf-8")
        self.assertIn("config: packagechooser_applications.conf", settings)
        self.assertIn("- packagechooser@applications", settings)

    def test_optional_selection_is_an_allowlist(self):
        selected_ids, profiles = linxiraoptional._selected_profiles(
            self.catalog, "science,containers"
        )
        self.assertEqual(selected_ids, ["science", "containers"])
        self.assertEqual([profile["id"] for profile in profiles], selected_ids)
        with self.assertRaises(ValueError):
            linxiraoptional._selected_profiles(self.catalog, "science,--overwrite")

    def test_application_selection_is_an_allowlist(self):
        selected_ids, applications = linxiraoptional._selected_applications(
            self.catalog, "haruna,vlc"
        )
        self.assertEqual(selected_ids, ["haruna", "vlc"])
        self.assertEqual([application["id"] for application in applications], selected_ids)
        with self.assertRaises(ValueError):
            linxiraoptional._selected_applications(self.catalog, "haruna,--overwrite")

    def test_desktop_selection_is_single_and_allowlisted(self):
        desktop_id, desktop = linxiraoptional._selected_desktop(self.catalog, "kde-plasma")
        self.assertEqual(desktop_id, "kde-plasma")
        self.assertEqual(desktop["session"], "plasma")
        with self.assertRaises(ValueError):
            linxiraoptional._selected_desktop(self.catalog, "kde-plasma,gnome")
        with self.assertRaises(ValueError):
            linxiraoptional._selected_desktop(self.catalog, "--overwrite")

    def test_desktop_chooser_defers_required_selection_to_transaction_validation(self):
        config = DESKTOP_CHOOSER_PATH.read_text(encoding="utf-8")
        self.assertIn("mode: optionalmultiple", config)
        self.assertIn("method: legacy", config)
        self.assertNotIn("mode: required", config)

    def test_vlc_requires_an_explicit_post_install_choice(self):
        media = next(profile for profile in self.catalog["profiles"] if profile["id"] == "media-playback")
        self.assertEqual(media["packages"], ["vlc"])
        self.assertFalse(media["installer"])
        self.assertFalse(media["presentation"]["recommended"])

    def test_kde_media_defaults_keep_haruna_and_separate_vlc(self):
        applications = {application["id"]: application for application in self.catalog["applications"]}
        self.assertTrue(applications["haruna"]["presentation"]["defaultSelected"])
        self.assertFalse(applications["vlc"]["presentation"]["defaultSelected"])
        self.assertTrue(applications["haruna"]["presentation"]["recommended"])
        self.assertFalse(applications["vlc"]["presentation"]["recommended"])

    def test_optional_job_installs_selected_packages_in_one_transaction(self):
        command = linxiraoptional._install_command("/target", ["jupyterlab"])
        self.assertNotIn("--downloadonly", command)
        self.assertIn("--refresh", command)
        self.assertNotIn("--sysupgrade", command)
        self.assertEqual(command[-2:], ["--", "jupyterlab"])


if __name__ == "__main__":
    unittest.main()
