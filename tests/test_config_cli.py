from pathlib import Path
import unittest


PROFILE_ROOT = Path(__file__).parents[1]
CONFIG_CLI = PROFILE_ROOT.parent / "linxira-config-hub/cli/linxira-config"
PACKAGE_CENTER = PROFILE_ROOT.parent / "linxira-package-center/src/linxira-package-center"


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
        self.assertIn("catalog-v2.json", script)
        self.assertIn(".applications[]", script)
        live_packages = (PROFILE_ROOT / "packages.x86_64").read_text(encoding="utf-8")
        target_packages = (PROFILE_ROOT / "target-packages.x86_64").read_text(encoding="utf-8")
        self.assertIn("kdialog\n", live_packages)
        self.assertIn("kdialog\n", target_packages)
        self.assertIn("pkexec", script)
        self.assertIn("pkexec \"$COMPONENTS_CLI\" apply", script)
        self.assertIn("--application", script)
        self.assertNotIn("CONFIG_CLI", script)

    def test_package_center_selects_individual_applications_by_category(self):
        script = PACKAGE_CENTER.read_text(encoding="utf-8")
        self.assertIn(".applications[]", script)
        self.assertIn(".categories", script)
        self.assertIn(".installer == true", script)
        self.assertIn(".review.status == \"reviewed\"", script)

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

    def test_build_injects_brand_policy_into_live_and_target(self):
        build = (PROFILE_ROOT / "build-direct-iso.sh").read_text(encoding="utf-8")
        branding = (PROFILE_ROOT / "airootfs/usr/lib/calamares/modules/linxirabranding/main.py").read_text(encoding="utf-8")
        self.assertIn("usr/share/doc/linxira-artwork/TRADEMARKS.md", build)
        self.assertIn('"/usr/share/doc/linxira-artwork/TRADEMARKS.md"', branding)


if __name__ == "__main__":
    unittest.main()
