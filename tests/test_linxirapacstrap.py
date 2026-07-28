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

    def test_baseline_is_installed_before_selected_packages(self):
        commands = linxirapacstrap._pacstrap_commands(
            "/etc/calamares/linxira-pacman.conf",
            "/target",
            ["base", "linxira-components"],
            ["firefox"],
        )
        self.assertEqual(
            commands,
            [
                [
                    "pacstrap",
                    "-C",
                    "/etc/calamares/linxira-pacman.conf",
                    "-K",
                    "/target",
                    "base",
                    "linxira-components",
                ],
                [
                    "pacstrap",
                    "-C",
                    "/etc/calamares/linxira-pacman.conf",
                    "-K",
                    "/target",
                    "firefox",
                ],
            ],
        )
        self.assertEqual(
            len(linxirapacstrap._pacstrap_commands("config", "root", ["base"], [])),
            1,
        )
        self.assertNotIn("-M", commands[0])

    def test_plasma_default_is_satisfied_without_candidate_additions(self):
        result = self.validate(self.selection())
        self.assertEqual(result["selectedPackages"], [])
        self.assertEqual(result["satisfiedItems"], ["desktop-plasma"])

    def test_unverified_gnome_selection_fails_closed(self):
        selection = self.selection(
            {"desktop-gnome": "desktop-environments/desktop-gnome"}
        )
        with self.assertRaisesRegex(ValueError, "desktop is not installer-eligible: desktop-gnome"):
            self.validate(selection)

    def test_online_reviewed_choice_is_installed_in_target(self):
        selection = self.selection(
            {
                "chromium": "app-web/chromium",
                "desktop-plasma": "desktop-environments/desktop-plasma",
            }
        )
        result = self.validate(selection)
        self.assertEqual(result["selectedPackages"], [])
        self.assertEqual(result["onlinePackages"], ["chromium"])
        self.assertEqual(result["pendingItems"], [])
        self.assertIn("chromium", result["satisfiedItems"])

    def test_chromium_and_libreoffice_fresh_share_full_upgrade_transaction(self):
        office = next(
            item
            for item in self.catalog["applications"]
            if "libreoffice-fresh" in item.get("artifact", {}).get("ids", [])
        )
        result = self.validate(self.selection({
            "chromium": "unused",
            office["id"]: "unused",
            "desktop-plasma": "unused",
        }))
        self.assertEqual(result["onlinePackages"], ["chromium", "libreoffice-fresh"])
        self.assertEqual(result["pendingItems"], [])
        self.assertEqual(
            linxirapacstrap._online_upgrade_command(
                "/target", result["onlinePackages"], 600
            ),
            [
                "arch-chroot", "/target", "/usr/bin/timeout", "--foreground", "600",
                "/usr/bin/pacman", "-Syyu", "--needed", "--noconfirm", "chromium",
                "libreoffice-fresh",
            ],
        )

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
        self.assertIn("component-cups", result["pendingItems"])
        self.assertNotIn("cups", result["onlinePackages"])
        self.assertNotIn("component-cups", result["satisfiedItems"])

    def test_required_dependencies_are_added_before_dependents(self):
        selection = self.selection({
            "component-python-data": "cap-data-science/component-python-data",
            "desktop-plasma": "desktop-environments/desktop-plasma",
        })
        result = self.validate(selection)
        self.assertEqual(
            result["satisfiedItems"][:3],
            ["component-python", "component-python-numeric", "component-python-data"],
        )
        self.assertEqual(
            result["selectionDocument"]["userOverrides"],
            [{"id": "component-python-data", "selected": True}, {"id": "desktop-plasma", "selected": True}],
        )

    def test_review_pending_optional_component_is_deferred_not_installed(self):
        selection = self.selection({
            "component-uv": "cap-runtime/component-uv",
            "desktop-plasma": "desktop-environments/desktop-plasma",
        })
        result = self.validate(selection)
        self.assertIn("component-uv", result["pendingItems"])
        self.assertNotIn("uv", result["selectedPackages"])

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

    def test_ineligible_review_channel_selection_is_deferred(self):
        selection = self.selection(
            {
                "desktop-plasma": "desktop-environments/desktop-plasma",
                "wps-office": "app-office/wps-office",
            }
        )
        result = self.validate(selection)
        self.assertIn("wps-office", result["pendingItems"])
        self.assertEqual(result["selectedPackages"], [])

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
        self.assertEqual(receipt["installedItems"], ["desktop-plasma"])
        self.assertEqual(receipt["deferredItems"], [])
        self.assertEqual(
            receipt["itemStatuses"],
            [{"id": "desktop-plasma", "status": "installed"}],
        )
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

    def test_online_target_requires_official_config_mirror_and_keyring(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "etc/pacman.d/gnupg").mkdir(parents=True)
            (root / "etc/pacman.conf").write_text(
                "[core]\nInclude = /etc/pacman.d/mirrorlist\n"
                "[extra]\nInclude = /etc/pacman.d/mirrorlist\n",
                encoding="utf-8",
            )
            (root / "etc/pacman.d/mirrorlist").write_text(
                "Server = https://mirror.example/$repo/os/$arch\n", encoding="utf-8"
            )
            (root / "etc/pacman.d/gnupg/pubring.gpg").write_bytes(b"keyring")
            linxirapacstrap._validate_online_target(root)

            (root / "etc/pacman.d/gnupg/pubring.gpg").unlink()
            with self.assertRaisesRegex(ValueError, "keyring"):
                linxirapacstrap._validate_online_target(root)

    def test_mirror_ranking_replaces_target_list_only_with_ranked_https_servers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mirrorlist = root / "etc/pacman.d/mirrorlist"
            mirrorlist.parent.mkdir(parents=True)
            mirrorlist.write_text("Server = https://fallback.example/$repo/os/$arch\n", encoding="utf-8")

            def rank(command, _description, **_kwargs):
                Path(command[-1]).write_text(
                    "Server = https://fast.example/$repo/os/$arch\n", encoding="utf-8"
                )
                return None

            with mock.patch.object(linxirapacstrap, "_run_with_retries", side_effect=rank) as run:
                linxirapacstrap._rank_target_mirrors(root, 120)

            self.assertEqual(
                mirrorlist.read_text(encoding="utf-8"),
                "Server = https://fast.example/$repo/os/$arch\n",
            )
            command = run.call_args.args[0]
            self.assertEqual(command[:7], [
                "/usr/bin/reflector", "--protocol", "https", "--latest", "20", "--sort", "rate",
            ])
            self.assertEqual(run.call_args.kwargs["timeout_seconds"], 120)

    def test_mirror_ranking_keeps_original_list_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mirrorlist = root / "etc/pacman.d/mirrorlist"
            mirrorlist.parent.mkdir(parents=True)
            original = "Server = https://fallback.example/$repo/os/$arch\n"
            mirrorlist.write_text(original, encoding="utf-8")
            with mock.patch.object(
                linxirapacstrap, "_run_with_retries", return_value="reflector timed out"
            ):
                linxirapacstrap._rank_target_mirrors(root, 120)
            self.assertEqual(mirrorlist.read_text(encoding="utf-8"), original)

    def test_retry_error_contains_each_exit_and_command_output(self):
        with mock.patch.object(linxirapacstrap, "_run", side_effect=[1, 2]), mock.patch.object(
            linxirapacstrap.time, "sleep"
        ):
            linxirapacstrap._run.last_output = "mirror timeout"
            error = linxirapacstrap._run_with_retries(
                ["arch-chroot", "/target", "/usr/bin/pacman", "-Syyu"],
                "target transaction",
                attempts=2,
            )
        self.assertIn("attempt 1/2 exited 1: mirror timeout", error)
        self.assertIn("attempt 2/2 exited 2: mirror timeout", error)


if __name__ == "__main__":
    unittest.main()
