from pathlib import Path
import json
import unittest


PROFILE_ROOT = Path(__file__).parents[1]
BUILD_SCRIPT = PROFILE_ROOT / "build-direct-iso.sh"
LIVE_SESSION = PROFILE_ROOT / "airootfs/usr/local/bin/linxira-live-session"
INSTALLER_SHELL = PROFILE_ROOT / "airootfs/usr/local/bin/linxira-installer-shell"
SDDM_CONFIG = PROFILE_ROOT / "airootfs/etc/sddm.conf.d/10-linxira-live.conf"
WELCOME_SOURCE = PROFILE_ROOT.parent / "linxira-welcome"
WELCOME = WELCOME_SOURCE / "src/linxira-welcome"
WELCOME_AUTOSTART = PROFILE_ROOT / "airootfs/etc/xdg/autostart/org.linxira.Welcome.desktop"
WELCOME_I18N = WELCOME_SOURCE / "data/i18n"
CANONICAL_LOGO = PROFILE_ROOT.parent / "linxira-artwork/assets/logo/linxira-l.svg"
SCALE_LOGO = (
    PROFILE_ROOT.parent
    / "linxira-artwork/assets/concepts/reference-frame/l-scale.svg"
)
BOOT_CONFIGS = (
    PROFILE_ROOT / "grub/grub.cfg",
    PROFILE_ROOT / "grub/loopback.cfg",
    PROFILE_ROOT / "syslinux/archiso_sys-linux.cfg",
)
LIVE_PACKAGES = PROFILE_ROOT / "packages.x86_64"
TARGET_PACKAGES = PROFILE_ROOT / "target-packages.x86_64"


class LiveSessionTests(unittest.TestCase):
    def test_live_session_only_starts_plasma(self):
        script = LIVE_SESSION.read_text(encoding="utf-8")
        self.assertIn("plasma-dbus-run-session-if-needed", script)
        self.assertIn("startplasma-wayland", script)
        self.assertNotIn("sleep", script)
        self.assertNotIn("linxira-installer-shell", script)
        self.assertNotIn("linxira.mode", script)
        self.assertNotIn("kwin_wayland --xwayland --exit-with-session", script)

    def test_boot_menu_has_one_live_entry_and_no_mode_switch(self):
        for path in BOOT_CONFIGS:
            config = path.read_text(encoding="utf-8")
            self.assertIn("Start Linxira OS", config)
            self.assertNotIn("linxira.mode", config)
            self.assertNotIn("Try Linxira OS", config)

    def test_media_and_vpn_apps_follow_the_preinstall_policy(self):
        live_packages = set(LIVE_PACKAGES.read_text(encoding="utf-8").splitlines())
        target_packages = set(TARGET_PACKAGES.read_text(encoding="utf-8").splitlines())
        self.assertTrue({"openconnect", "stoken", "haruna"}.isdisjoint(live_packages))
        self.assertIn("gwenview", target_packages)
        self.assertTrue({"haruna", "vlc"}.isdisjoint(target_packages))
        mimeapps = (PROFILE_ROOT / "airootfs/etc/xdg/mimeapps.list").read_text(encoding="utf-8")
        self.assertNotIn("haruna", mimeapps.lower())

    def test_global_mime_policy_only_sets_firefox_web_handlers(self):
        mimeapps = (PROFILE_ROOT / "airootfs/etc/xdg/mimeapps.list").read_text(encoding="utf-8")
        for desktop in ("org.kde", "dolphin", "kate", "okular", "gwenview", "ark"):
            self.assertNotIn(desktop, mimeapps.lower())
        self.assertIn("x-scheme-handler/http=firefox.desktop", mimeapps)
        self.assertIn("x-scheme-handler/https=firefox.desktop", mimeapps)
        self.assertIn("text/html=firefox.desktop", mimeapps)

    def test_grub_loads_png_support_before_the_background(self):
        config = BOOT_CONFIGS[0].read_text(encoding="utf-8")
        self.assertLess(config.index("insmod png"), config.index("background_image"))
        self.assertIn('loadfont "/boot/grub/fonts/unicode.pf2"', config)
        self.assertIn('background_image "/boot/grub/splash.png"', config)

    def test_build_includes_the_grub_font_required_by_gfxterm(self):
        script = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("/usr/share/grub/unicode.pf2", script)
        self.assertIn('grub/fonts/unicode.pf2', script)

    def test_welcome_autostarts_without_starting_calamares(self):
        desktop = WELCOME_AUTOSTART.read_text(encoding="utf-8")
        self.assertIn("Exec=/usr/bin/linxira-welcome --autostart", desktop)
        self.assertNotIn("calamares", desktop.lower())
        self.assertNotIn("OnlyShowIn=KDE", desktop)

    def test_welcome_has_fixed_launchers_and_no_privileged_shell(self):
        script = WELCOME.read_text(encoding="utf-8")
        self.assertIn('"installer": (LIVE_INSTALLER, [])', script)
        self.assertIn("QProcess.startDetached(executable, arguments)", script)
        for forbidden in ("shell=True", "bash -c", "sudo", "pkexec"):
            self.assertNotIn(forbidden, script)

    def test_welcome_translations_have_a_complete_base_and_allow_fallback(self):
        translations = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(WELCOME_I18N.glob("*.json"))
        ]
        self.assertEqual(len(translations), 9)
        base_keys = {
            "home", "status", "help", "install", "open_software",
            "open_components", "open_config", "open_settings", "health",
            "first_completion", "docs", "website", "wiki", "github",
        }
        for translation in translations:
            self.assertTrue(base_keys.issubset(translation))
        simplified_chinese = json.loads((WELCOME_I18N / "zh_CN.json").read_text(encoding="utf-8"))
        for key in ("home", "status", "help", "open_config", "open_components"):
            self.assertIn(key, simplified_chinese)

    def test_welcome_only_routes_to_fixed_product_surfaces(self):
        script = WELCOME.read_text(encoding="utf-8")
        self.assertIn('"package_center": ("/usr/bin/linxira-package-center", [])', script)
        self.assertIn('"component_manager": ("/usr/bin/linxira-component-manager", [])', script)
        self.assertIn('"config": ("/usr/bin/konsole"', script)
        self.assertNotIn('"mirrors":', script)
        self.assertNotIn('"miniforge":', script)
        self.assertNotIn('self.catalog.get("applications", [])', script)

    def test_scale_l_is_the_canonical_logo(self):
        canonical = CANONICAL_LOGO.read_text(encoding="utf-8")
        scale = SCALE_LOGO.read_text(encoding="utf-8")
        for geometry in (
            'fill="#20B8B0" d="M112 64H224V336H448V448H112Z"',
            'stroke="#F36F5D"',
        ):
            self.assertIn(geometry, canonical)
            self.assertIn(geometry, scale)

    def test_default_desktop_uses_dark_kde_settings(self):
        kdeglobals = (PROFILE_ROOT / "airootfs/etc/skel/.config/kdeglobals").read_text(encoding="utf-8")
        self.assertIn("ColorScheme=BreezeDark", kdeglobals)
        self.assertIn("LookAndFeelPackage=org.kde.breezedark.desktop", kdeglobals)
        desktop = (PROFILE_ROOT / "airootfs/etc/skel/.config/plasma-org.kde.plasma.desktop-appletsrc").read_text(encoding="utf-8")
        self.assertIn("Image=/usr/share/wallpapers/LinxiraOS/contents/images/current.svg", desktop)
        tmpfiles = (PROFILE_ROOT / "airootfs/usr/lib/tmpfiles.d/linxira-live-tmpfiles.conf").read_text(encoding="utf-8")
        self.assertIn("/home/installer/.config/kdeglobals", tmpfiles)

    def test_live_session_does_not_lock_or_suspend_on_idle(self):
        tmpfiles = (PROFILE_ROOT / "airootfs/usr/lib/tmpfiles.d/linxira-live-tmpfiles.conf").read_text(encoding="utf-8")
        lock_config = (PROFILE_ROOT / "airootfs/usr/share/linxira/live/kscreenlockerrc").read_text(encoding="utf-8")
        power_config = (PROFILE_ROOT / "airootfs/usr/share/linxira/live/powermanagementprofilesrc").read_text(encoding="utf-8")
        self.assertIn("/home/installer/.config/kscreenlockerrc", tmpfiles)
        self.assertIn("/home/installer/.config/powermanagementprofilesrc", tmpfiles)
        self.assertIn("Autolock=false", lock_config)
        self.assertIn("LockOnResume=false", lock_config)
        self.assertIn("noScreenManagement=true", power_config)
        self.assertIn("noSuspend=true", power_config)
        self.assertIn("lockBeforeTurnOff=0", power_config)

    def test_offline_repository_uses_a_build_scoped_cache(self):
        script = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('package_cache=$(mktemp -d "${build_parent}/.linxira-target-package-cache.XXXXXX")', script)
        self.assertNotIn("LINXIRA_PACKAGE_CACHE", script)

    def test_failed_session_does_not_autologin_forever(self):
        config = SDDM_CONFIG.read_text(encoding="utf-8")
        self.assertIn("Relogin=false", config)
        self.assertNotIn("Relogin=true", config)

    def test_sddm_is_the_only_display_manager_owner(self):
        links = (PROFILE_ROOT / "profile-symlinks.list").read_text(encoding="utf-8")
        self.assertIn(
            "airootfs/etc/systemd/system/display-manager.service|/usr/lib/systemd/system/sddm.service",
            links,
        )
        self.assertNotIn("gdm.service", links)
        displaymanager = (PROFILE_ROOT / "airootfs/etc/calamares/modules/displaymanager.conf").read_text(encoding="utf-8")
        self.assertIn("displaymanagers: [ sddm ]", displaymanager)
        self.assertNotIn("gdm", displaymanager)

    def test_gnome_wallpaper_defaults_have_an_explicit_tested_deferral(self):
        readme = (PROFILE_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("GNOME wallpaper gsettings are intentionally deferred", readme)
        self.assertFalse(any((PROFILE_ROOT / "airootfs").rglob("*gsettings*")))

    def test_installer_failure_is_visible_and_logged(self):
        script = INSTALLER_SHELL.read_text(encoding="utf-8")
        self.assertIn("/tmp/linxira-installer.log", script)
        self.assertIn("konsole --fullscreen --hold", script)
        self.assertIn("pkexec /usr/bin/calamares", script)
        self.assertNotIn("is-active polkit.service", script)
        self.assertIn("if (( status != 0 ))", script)

    def test_calamares_sequence_has_valid_indentation(self):
        settings = (PROFILE_ROOT / "airootfs/etc/calamares/settings.conf").read_text(encoding="utf-8")
        self.assertIn(
            "      - keyboard\n      - partition\n      - linxirasoftware\n      - users\n      - summary",
            settings,
        )
        self.assertNotIn("       - partition", settings)
        self.assertNotIn("packagechooser@", settings)
        self.assertIn("linxirasoftware", settings)
        self.assertIn("      - displaymanager\n      - linxirasession\n", settings)

    def test_initramfs_jobs_are_ordered_and_consolefont_is_removed(self):
        settings = (PROFILE_ROOT / "airootfs/etc/calamares/settings.conf").read_text(encoding="utf-8")
        initcpiocfg = (
            PROFILE_ROOT / "airootfs/etc/calamares/modules/initcpiocfg.conf"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "      - initcpiocfg\n      - linxirabranding\n      - initcpio",
            settings,
        )
        self.assertIn("  remove:\n    - consolefont\n", initcpiocfg)

    def test_target_manifest_excludes_live_installer_packages(self):
        target_packages = set(TARGET_PACKAGES.read_text(encoding="utf-8").splitlines())
        self.assertNotIn("calamares", target_packages)
        self.assertNotIn("archiso", target_packages)

    def test_system_software_is_package_owned_in_live_and_target(self):
        live_packages = set(LIVE_PACKAGES.read_text(encoding="utf-8").splitlines())
        target_packages = set(TARGET_PACKAGES.read_text(encoding="utf-8").splitlines())
        artifact_contracts = {
            "catalog_package": "linxira-catalog",
            "component_manager_package": "linxira-component-manager",
            "components_package": "linxira-components",
            "config_hub_package": "linxira-config-hub",
            "package_center_package": "linxira-package-center",
            "welcome_package": "linxira-welcome",
        }
        system_packages = set(artifact_contracts.values())
        self.assertTrue(system_packages.issubset(live_packages))
        self.assertTrue(system_packages.issubset(target_packages))
        build = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('profile_dir}/../linxira-', build)
        for variable, package in artifact_contracts.items():
            self.assertIn(
                f'validate_package_artifact "${variable}" {package}', build
            )

    def test_initramfs_integration_covers_both_kernels(self):
        script = (
            PROFILE_ROOT / "scripts/test-initramfs-target.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("base btrfs-progs linux linux-lts", script)
        self.assertIn('mkfs.btrfs -q -f "$filesystem_image"', script)
        self.assertIn('mount -o loop "$filesystem_image" "$target"', script)
        self.assertIn('test -s "$target/etc/mkinitcpio.d/linux.preset"', script)
        self.assertIn('test -s "$target/etc/mkinitcpio.d/linux-lts.preset"', script)
        self.assertIn('arch-chroot "$target" mkinitcpio -P', script)
        self.assertIn("grep -q '^==> ERROR:'", script)
        self.assertIn('test -s "$target/boot/initramfs-linux.img"', script)
        self.assertIn('test -s "$target/boot/initramfs-linux-lts.img"', script)

    def test_target_validator_rejects_live_only_paths(self):
        validator = (
            PROFILE_ROOT
            / "airootfs/usr/lib/calamares/modules/linxiravalidate/main.py"
        ).read_text(encoding="utf-8")
        for path in (
            "/etc/calamares",
            "/etc/sddm.conf.d/10-linxira-live.conf",
            "/etc/polkit-1/rules.d/49-linxira-installer.rules",
            "/usr/local/bin/linxira-installer-shell",
            "/usr/local/bin/linxira-live-session",
        ):
            self.assertIn(path, validator)

        self.assertIn("/boot/initramfs-linux.img", validator)
        self.assertIn("/boot/initramfs-linux-lts.img", validator)
        self.assertIn("crc32c(?:-|_)intel", validator)


if __name__ == "__main__":
    unittest.main()
