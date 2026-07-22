import json
from pathlib import Path
import unittest


PROFILE_ROOT = Path(__file__).parents[1]
CATALOG_ROOT = PROFILE_ROOT.parent / "linxira-catalog"
CATALOG_PATH = CATALOG_ROOT / "catalog/catalog-v3.json"
SCHEMA_PATH = CATALOG_ROOT / "schema/catalog-v3.schema.json"
SETTINGS_PATH = PROFILE_ROOT / "airootfs/etc/calamares/settings.conf"
MODULES_PATH = PROFILE_ROOT / "airootfs/etc/calamares/modules"
LOCAL_MODULES_PATH = PROFILE_ROOT / "airootfs/usr/lib/calamares/modules"
TARGET_PACKAGES = PROFILE_ROOT / "target-packages.x86_64"
CANDIDATE_PACKAGES = PROFILE_ROOT / "offline-candidate-packages.x86_64"


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_catalog_v3_is_the_canonical_post_install_contract(self):
        self.assertEqual(self.catalog["catalogVersion"], 3)
        self.assertEqual(self.catalog["$schema"], "catalog-v3.schema.json")
        self.assertEqual(
            self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
        )
        self.assertEqual(self.schema["properties"]["catalogVersion"]["const"], 3)

    def test_installer_has_no_legacy_flat_software_choosers(self):
        settings = SETTINGS_PATH.read_text(encoding="utf-8")
        for name in ("desktop", "components", "applications"):
            self.assertNotIn(f"packagechooser@{name}", settings)
            self.assertFalse((MODULES_PATH / f"packagechooser_{name}.conf").exists())
        self.assertNotIn("module: packagechooser", settings)

    def test_installer_has_no_unfrozen_optional_package_transaction(self):
        settings = SETTINGS_PATH.read_text(encoding="utf-8")
        self.assertNotIn("linxiraoptional", settings)
        self.assertFalse((LOCAL_MODULES_PATH / "linxiraoptional/main.py").exists())
        self.assertFalse((LOCAL_MODULES_PATH / "linxiraoptional/module.desc").exists())

    def test_installer_declares_the_native_catalog_viewmodule(self):
        settings = SETTINGS_PATH.read_text(encoding="utf-8")
        self.assertIn("- linxirasoftware", settings)
        self.assertEqual(
            (MODULES_PATH / "linxirasoftware.conf").read_text(encoding="utf-8").splitlines()[1],
            'catalogPath: "/usr/share/linxira/catalog/catalog-v3.json"',
        )

    def test_installer_uses_fixed_plasma_and_v3_post_install_surfaces(self):
        packages = set(TARGET_PACKAGES.read_text(encoding="utf-8").splitlines())
        self.assertTrue(
            {
                "plasma-desktop",
                "linxira-catalog",
                "linxira-package-center",
                "linxira-component-manager",
            }.issubset(packages)
        )

    def test_offline_candidates_are_separate_and_exactly_gnome(self):
        baseline = set(TARGET_PACKAGES.read_text(encoding="utf-8").splitlines())
        candidates = CANDIDATE_PACKAGES.read_text(encoding="utf-8").splitlines()
        gnome = next(item for item in self.catalog["desktops"] if item["id"] == "desktop-gnome")
        self.assertEqual(candidates, gnome["artifact"]["ids"])
        self.assertTrue(set(candidates).isdisjoint(baseline))

        build = (PROFILE_ROOT / "build-direct-iso.sh").read_text(encoding="utf-8")
        self.assertIn('target_packages+=("${candidate_packages[@]}")', build)
        pacstrap = (LOCAL_MODULES_PATH / "linxirapacstrap/main.py").read_text(encoding="utf-8")
        self.assertIn('command.extend(selected_packages)', pacstrap)
        self.assertNotIn('selection["directPackageTargets"]', pacstrap)

    def test_shared_desktop_plumbing_is_in_live_and_target(self):
        live = set((PROFILE_ROOT / "packages.x86_64").read_text(encoding="utf-8").splitlines())
        target = set(TARGET_PACKAGES.read_text(encoding="utf-8").splitlines())
        shared = {"wireplumber", "xdg-desktop-portal", "xdg-desktop-portal-kde"}
        self.assertTrue(shared.issubset(live))
        self.assertTrue(shared.issubset(target))

    def test_firefox_default_is_part_of_the_fixed_offline_baseline(self):
        packages = set(TARGET_PACKAGES.read_text(encoding="utf-8").splitlines())
        selected = [
            item["id"]
            for item in self.catalog["applications"]
            if item["presentation"]["defaultSelected"]
        ]
        self.assertEqual(selected, ["firefox"])
        self.assertIn("firefox", packages)


if __name__ == "__main__":
    unittest.main()
