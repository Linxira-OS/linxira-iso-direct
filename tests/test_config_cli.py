from pathlib import Path
import unittest


PROFILE_ROOT = Path(__file__).parents[1]
CONFIG_CLI = PROFILE_ROOT.parent / "linxira-config-hub/cli/linxira-config"
PACKAGE_CENTER = PROFILE_ROOT.parent / "linxira-package-center/src/linxira-package-center"
COMPONENT_MANAGER = PROFILE_ROOT.parent / "linxira-component-manager/src/linxira_component_manager/backend.py"


class ConfigCliTests(unittest.TestCase):
    def test_cli_consumes_catalog_v3(self):
        script = CONFIG_CLI.read_text(encoding="utf-8")
        self.assertIn("catalog-v3.json", script)
        self.assertIn("catalog <kind>", script)
        self.assertNotIn("catalog-v1.json", script)

    def test_cli_does_not_install_catalog_profiles(self):
        script = CONFIG_CLI.read_text(encoding="utf-8")
        self.assertNotIn("install_catalog_profile", script)
        self.assertNotIn("install_catalog_applications", script)

    def test_system_info_reports_only_official_kernel_names(self):
        script = CONFIG_CLI.read_text(encoding="utf-8")
        self.assertIn("/^linux(-lts|-zen|-hardened)?$/", script)
        self.assertNotIn("linux-cachyos|linux-linxira", script)

    def test_privileged_network_and_service_inputs_are_validated(self):
        script = CONFIG_CLI.read_text(encoding="utf-8")
        self.assertIn("validate_port", script)
        self.assertIn("validate_dns_server", script)
        self.assertIn("target_user", script)
        self.assertIn("PKEXEC_UID", script)
        self.assertIn('sudo -u "$user" env HOME="$home"', script)

    def test_unverified_remote_desktop_actions_fail_closed(self):
        script = CONFIG_CLI.read_text(encoding="utf-8")
        self.assertIn("xrdp is not present in Linxira's signed repositories", script)
        self.assertIn("a per-user TigerVNC session and firewall policy must be implemented first", script)
        self.assertNotIn("pacman -S --noconfirm xrdp", script)

    def test_package_center_owns_the_catalog_install_transaction(self):
        script = PACKAGE_CENTER.read_text(encoding="utf-8")
        self.assertIn("catalog-v3.json", script)
        self.assertIn("QTreeWidget", script)
        self.assertIn("pkexec", script)
        self.assertIn('self.pkexec, self.components_cli, "apply"', script)
        self.assertIn('command.extend(("--selection", str(selection_path)))', script)
        self.assertIn("PartiallyChecked", script)
        self.assertNotIn("CONFIG_CLI", script)

    def test_package_center_selects_individual_applications_by_category(self):
        script = PACKAGE_CENTER.read_text(encoding="utf-8")
        self.assertIn('category.get("surface") != "applications"', script)
        self.assertIn('review_status != "reviewed"', script)
        self.assertIn('channel == "optional-review"', script)
        self.assertIn("maxSelected", script)

    def test_both_v3_uis_bind_apply_to_the_same_catalog(self):
        package_center = PACKAGE_CENTER.read_text(encoding="utf-8")
        component_manager = COMPONENT_MANAGER.read_text(encoding="utf-8")
        self.assertIn('"--catalog", str(self.catalog_path)', package_center)
        self.assertIn('"--catalog",\n            str(transaction.catalog_path)', component_manager)

    def test_config_cli_defers_software_installation_to_package_center(self):
        script = CONFIG_CLI.read_text(encoding="utf-8")
        self.assertIn("Software installation is owned by Linxira Package Center", script)
        self.assertNotIn("Install (post-install packages)", script)

    def test_runtime_status_reports_nix_and_unresolved_wise(self):
        script = CONFIG_CLI.read_text(encoding="utf-8")
        self.assertIn("runtime_status", script)
        self.assertIn("nix", script)
        self.assertIn("unresolved", script)
        self.assertIn("wise", script)

    def test_build_validates_packaged_brand_policy(self):
        build = (PROFILE_ROOT / "build-direct-iso.sh").read_text(encoding="utf-8")
        branding = (PROFILE_ROOT / "airootfs/usr/lib/calamares/modules/linxirabranding/main.py").read_text(encoding="utf-8")
        self.assertIn("usr/share/doc/linxira-artwork/TRADEMARKS.md", build)
        self.assertNotIn('"/usr/share/doc/linxira-artwork/TRADEMARKS.md"', branding)

    def test_build_requires_native_installer_tree_plugin(self):
        build = (PROFILE_ROOT / "build-direct-iso.sh").read_text(encoding="utf-8")
        self.assertIn(
            "usr/lib/calamares/modules/linxirasoftware/libcalamares_viewmodule_linxirasoftware.so",
            build,
        )
        self.assertIn("usr/lib/calamares/modules/linxirasoftware/module.desc", build)


if __name__ == "__main__":
    unittest.main()
