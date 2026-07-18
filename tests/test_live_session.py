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
WELCOME_AUTOSTART = (
    WELCOME_SOURCE / "data/autostart/org.linxira.Welcome.desktop"
)
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

    def test_welcome_has_fixed_launchers_and_no_privileged_shell(self):
        script = WELCOME.read_text(encoding="utf-8")
        self.assertIn('"installer": (LIVE_INSTALLER, [])', script)
        self.assertIn("QProcess.startDetached(executable, arguments)", script)
        for forbidden in ("shell=True", "bash -c", "sudo", "pkexec"):
            self.assertNotIn(forbidden, script)

    def test_welcome_translations_share_one_complete_key_set(self):
        translations = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(WELCOME_I18N.glob("*.json"))
        ]
        self.assertEqual(len(translations), 9)
        expected_keys = set(translations[0])
        self.assertGreaterEqual(len(expected_keys), 40)
        for translation in translations[1:]:
            self.assertEqual(set(translation), expected_keys)

    def test_scale_l_is_the_canonical_logo(self):
        canonical = CANONICAL_LOGO.read_text(encoding="utf-8")
        scale = SCALE_LOGO.read_text(encoding="utf-8")
        for geometry in (
            'fill="#20B8B0" d="M112 64H224V336H448V448H112Z"',
            'stroke="#F36F5D"',
        ):
            self.assertIn(geometry, canonical)
            self.assertIn(geometry, scale)

    def test_failed_session_does_not_autologin_forever(self):
        config = SDDM_CONFIG.read_text(encoding="utf-8")
        self.assertIn("Relogin=false", config)
        self.assertNotIn("Relogin=true", config)

    def test_installer_failure_is_visible_and_logged(self):
        script = INSTALLER_SHELL.read_text(encoding="utf-8")
        self.assertIn("/tmp/linxira-installer.log", script)
        self.assertIn("konsole --fullscreen --hold", script)
        self.assertIn("pkexec /usr/bin/calamares", script)
        self.assertNotIn("is-active polkit.service", script)
        self.assertIn("if (( status != 0 ))", script)


if __name__ == "__main__":
    unittest.main()
