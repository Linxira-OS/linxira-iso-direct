import hashlib
import importlib.util
import json
import os
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
libcalamares.utils = types.SimpleNamespace(
    debug=lambda value: None, warning=lambda value: None
)
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
        cls.base_set = set(cls.baseline)
        # 2026-08-12 产品决策: Plasma 桌面包自 baseline 拆出, 常驻 offline-candidate。
        # 默认桌面 Plasma 的离线包 = catalog 中 Plasma artifact 里不在 baseline 的部分。
        catalog = cls.catalog
        plasma_ids = next(
            d["artifact"]["ids"]
            for d in catalog["desktops"]
            if d["id"] == "desktop-plasma"
        )
        cls.plasma_packages = [p for p in plasma_ids if p not in cls.base_set]
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

    def test_plasma_default_is_offline_included_from_candidates(self):
        # 2026-08-12 产品决策: Plasma 从无条件 baseline 拆出, 桌面改由 catalog 选择驱动。
        # 默认桌面 Plasma 通过 offline-candidate 清单随镜像附带, 无网也能装。
        result = self.validate(self.selection())
        self.assertEqual(result["selectedPackages"], self.plasma_packages)
        self.assertEqual(result["satisfiedItems"], ["desktop-plasma"])

    def test_unverified_gnome_selection_fails_closed(self):
        # 2026-08-13 产品决策: 桌面选择面收窄为 KDE Plasma / 服务器(无桌面)。
        # gnome 等其余桌面移出选择面(installerVisible:false), 不再可安装期选择。
        selection = self.selection(
            {"desktop-gnome": "desktop-environments/desktop-gnome"}
        )
        with self.assertRaisesRegex(ValueError, "selectedBundleIds must not be empty|no category-root provenance"):
            self.validate(selection)

    def test_server_mode_is_a_valid_headless_selection(self):
        # 2026-08-13: 无桌面服务器模式 —— 合法选择, 不安装任何桌面包。
        selection = self.selection(
            {"desktop-server": "desktop-environments/desktop-server"}
        )
        result = self.validate(selection)
        self.assertIn("desktop-server", result["satisfiedItems"])
        self.assertEqual(result["selectedPackages"], [])

    def test_online_reviewed_choice_is_installed_in_target(self):
        selection = self.selection(
            {
                "chromium": "app-web/chromium",
                "desktop-plasma": "desktop-environments/desktop-plasma",
            }
        )
        result = self.validate(selection)
        self.assertEqual(result["selectedPackages"], self.plasma_packages)
        self.assertEqual(result["onlinePackages"], ["chromium"])
        self.assertEqual(result["pendingItems"], [])
        self.assertIn("chromium", result["satisfiedItems"])

    def test_chromium_and_libreoffice_fresh_share_online_install_transaction(self):
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
        self.assertIn("chromium", result["onlineSatisfiedLeafIds"])
        self.assertEqual(
            linxirapacstrap._online_sync_command("/target", 180),
            [
                "arch-chroot", "/target", "/usr/bin/timeout", "--foreground", "180",
                "/usr/bin/pacman", "-Syyu", "--noconfirm",
            ],
        )
        self.assertEqual(
            linxirapacstrap._online_install_command(
                "/target", result["onlinePackages"], 600
            ),
            [
                "arch-chroot", "/target", "/usr/bin/timeout", "--foreground", "600",
                "/usr/bin/pacman", "-S", "--needed", "--noconfirm", "chromium",
                "libreoffice-fresh",
            ],
        )

    def test_defer_online_items_moves_online_leaves_to_pending(self):
        result = {
            "onlinePackages": ["chromium", "libreoffice-fresh"],
            "onlineSatisfiedLeafIds": ["chromium", "libreoffice-fresh"],
            "satisfiedItems": ["desktop-plasma", "chromium", "libreoffice-fresh"],
            "pendingItems": ["component-cups"],
        }
        deferred = linxirapacstrap._defer_online_items(result)
        self.assertEqual(deferred["satisfiedItems"], ["desktop-plasma"])
        self.assertEqual(
            deferred["pendingItems"],
            ["chromium", "component-cups", "libreoffice-fresh"],
        )
        self.assertEqual(deferred["onlinePackages"], [])
        self.assertEqual(result["satisfiedItems"], ["desktop-plasma", "chromium", "libreoffice-fresh"])

    def test_defer_online_items_noop_without_online_leaves(self):
        result = {
            "onlinePackages": [],
            "onlineSatisfiedLeafIds": [],
            "satisfiedItems": ["desktop-plasma"],
            "pendingItems": [],
        }
        self.assertIsNot(linxirapacstrap._defer_online_items(result), result)
        self.assertEqual(
            linxirapacstrap._defer_online_items(result)["satisfiedItems"],
            ["desktop-plasma"],
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

    def test_input_method_follows_installer_locale(self):
        # 2026-08-13: 中文安装保留 fcitx5 组; 非中文过滤(离线闭包仍含, 不装)
        baseline = ["base", "fcitx5", "fcitx5-chinese-addons", "firefox"]
        self.assertEqual(
            linxirapacstrap._input_method_packages_for_locale(baseline, "zh_CN.UTF-8"),
            baseline,
        )
        self.assertEqual(
            linxirapacstrap._input_method_packages_for_locale(baseline, "en_US.UTF-8"),
            ["base", "firefox"],
        )
        self.assertEqual(
            linxirapacstrap._input_method_packages_for_locale(baseline, None),
            baseline,
        )

    def test_chinese_input_method_preconfigured_for_zh_locale(self):
        # 2026-08-14: zh 安装预写 /etc/environment IM 变量 + skel fcitx5 profile(默认拼音)
        import tempfile

        with tempfile.TemporaryDirectory() as root:
            linxirapacstrap._configure_chinese_input_method(root, "zh_CN.UTF-8")
            environment = os.path.join(root, "etc/environment")
            self.assertTrue(os.path.isfile(environment))
            with open(environment, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("GTK_IM_MODULE=fcitx", content)
            self.assertIn("QT_IM_MODULE=fcitx", content)
            self.assertIn("XMODIFIERS=@im=fcitx", content)
            profile = os.path.join(root, "etc/skel/.config/fcitx5/profile")
            self.assertTrue(os.path.isfile(profile))
            with open(profile, encoding="utf-8") as handle:
                self.assertIn("DefaultIM=pinyin", handle.read())

    def test_chinese_input_method_skipped_for_non_zh_locale(self):
        import tempfile

        with tempfile.TemporaryDirectory() as root:
            linxirapacstrap._configure_chinese_input_method(root, "en_US.UTF-8")
            self.assertFalse(
                os.path.exists(os.path.join(root, "etc/environment"))
            )
            self.assertFalse(
                os.path.exists(os.path.join(root, "etc/skel/.config/fcitx5/profile"))
            )

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
                "desktop-server": "desktop-environments/desktop-server",
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
        self.assertEqual(result["selectedPackages"], self.plasma_packages)

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
        self.assertEqual(
            sorted(receipt["installedSelectedPackages"]),
            sorted(self.plasma_packages),
        )
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

    def test_pending_install_queue_written_when_online_deferred(self):
        with tempfile.TemporaryDirectory() as directory:
            result = {
                "onlinePackages": [],
                "onlineSatisfiedLeafIds": ["code", "chromium"],
                "pendingItems": ["code", "chromium"],
            }
            linxirapacstrap._write_pending_install(
                Path(directory), result, str(CATALOG_PATH)
            )
            queue_path = Path(directory) / "var/lib/linxira/pending-install.json"
            self.assertTrue(queue_path.is_file())
            payload = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], "org.linxira.pending-install.v1")
            leaf_ids = [entry["leafId"] for entry in payload["pending"]]
            self.assertEqual(leaf_ids, ["chromium", "code"])
            entry = payload["pending"][0]
            self.assertEqual(entry["offlinePolicy"], "online-only")
            self.assertIsInstance(entry["name"], dict)
            self.assertIsInstance(entry["packages"], list)

    def test_pending_install_queue_removed_when_no_deferral(self):
        with tempfile.TemporaryDirectory() as directory:
            queue_path = Path(directory) / "var/lib/linxira/pending-install.json"
            queue_path.parent.mkdir(parents=True)
            queue_path.write_text('{"stale": true}\n', encoding="utf-8")
            result = {
                "onlinePackages": ["code"],
                "onlineSatisfiedLeafIds": ["code"],
            }
            linxirapacstrap._write_pending_install(
                Path(directory), result, str(CATALOG_PATH)
            )
            self.assertFalse(queue_path.exists())

    def test_target_linxira_repo_is_appended_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "etc/pacman.conf"
            config.parent.mkdir(parents=True)
            config.write_text(
                "[options]\nArchitecture = auto\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n",
                encoding="utf-8",
            )
            linxirapacstrap._enable_target_linxira_repo(Path(directory))
            contents = config.read_text(encoding="utf-8")
            self.assertIn("[linxira]", contents)
            self.assertIn("SigLevel = Required DatabaseOptional", contents)
            self.assertIn("https://linxira-os.github.io/linxira-packages/$arch", contents)
            linxirapacstrap._enable_target_linxira_repo(Path(directory))
            self.assertEqual(contents.count("[linxira]"), config.read_text(encoding="utf-8").count("[linxira]"))

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

    def _fake_mirror_connect(self, host_port, timeout):
        host, _port = host_port
        if host.startswith("bad"):
            raise OSError("connection refused")
        return mock.MagicMock()

    def test_mirror_filter_keeps_only_reachable_servers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mirrorlist = root / "etc/pacman.d/mirrorlist"
            mirrorlist.parent.mkdir(parents=True)
            mirrorlist.write_text(
                "Server = https://bad1.example/$repo/os/$arch\n"
                "Server = https://good.example/$repo/os/$arch\n"
                "Server = https://bad2.example/$repo/os/$arch\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                linxirapacstrap.socket,
                "create_connection",
                side_effect=self._fake_mirror_connect,
            ):
                count = linxirapacstrap._filter_reachable_mirrors(root, 5)
            self.assertEqual(count, 1)
            self.assertEqual(
                mirrorlist.read_text(encoding="utf-8"),
                "Server = https://good.example/$repo/os/$arch\n",
            )

    def test_mirror_filter_all_unreachable_falls_back_to_cn_mirrors(self):
        # 2026-08-13: 官方镜像池全不可达时(国内网络常见), 追加中国镜像 fallback 重测,
        # 任一可达则写回 mirrorlist, 在线软件立即安装而不是推迟到正式系统后。
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mirrorlist = root / "etc/pacman.d/mirrorlist"
            mirrorlist.parent.mkdir(parents=True)
            original = "Server = https://bad.example/$repo/os/$arch\n"
            mirrorlist.write_text(original, encoding="utf-8")
            with mock.patch.object(
                linxirapacstrap.socket,
                "create_connection",
                side_effect=self._fake_mirror_connect,
            ):
                count = linxirapacstrap._filter_reachable_mirrors(root, 5)
            self.assertEqual(count, len(linxirapacstrap.FALLBACK_MIRRORS))
            text = mirrorlist.read_text(encoding="utf-8")
            self.assertIn("mirrors.tuna.tsinghua.edu.cn", text)
            self.assertNotIn("bad.example", text)

    def test_mirror_filter_all_unreachable_including_fallback_keeps_original_list(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mirrorlist = root / "etc/pacman.d/mirrorlist"
            mirrorlist.parent.mkdir(parents=True)
            original = "Server = https://bad.example/$repo/os/$arch\n"
            mirrorlist.write_text(original, encoding="utf-8")

            def refuse_everything(host_port, timeout):
                raise OSError("connection refused")

            with mock.patch.object(
                linxirapacstrap.socket,
                "create_connection",
                side_effect=refuse_everything,
            ):
                count = linxirapacstrap._filter_reachable_mirrors(root, 5)
            self.assertEqual(count, 0)
            self.assertEqual(mirrorlist.read_text(encoding="utf-8"), original)

    def test_mirror_filter_all_reachable_keeps_list_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mirrorlist = root / "etc/pacman.d/mirrorlist"
            mirrorlist.parent.mkdir(parents=True)
            original = (
                "Server = https://good1.example/$repo/os/$arch\n"
                "Server = https://good2.example/$repo/os/$arch\n"
            )
            mirrorlist.write_text(original, encoding="utf-8")
            with mock.patch.object(
                linxirapacstrap.socket,
                "create_connection",
                side_effect=self._fake_mirror_connect,
            ):
                count = linxirapacstrap._filter_reachable_mirrors(root, 5)
            self.assertEqual(count, 2)
            self.assertEqual(mirrorlist.read_text(encoding="utf-8"), original)

    def test_run_defers_online_packages_when_database_sync_fails(self):
        result = {
            "selectionDocument": {"selectedLeafIds": ["desktop-plasma", "chromium"]},
            "selectedPackages": [],
            "onlinePackages": ["chromium"],
            "onlineSatisfiedLeafIds": ["chromium"],
            "satisfiedItems": ["desktop-plasma", "chromium"],
            "pendingItems": [],
            "catalogSha256": self.digest,
            "catalogRelease": self.catalog["release"],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pacman_conf = root / "pacman.conf"
            pacman_conf.write_text("[options]\n", encoding="utf-8")
            repository = root / "repo"
            repository.mkdir()
            config = {
                "pacmanConfig": str(pacman_conf),
                "repositoryPath": str(repository),
                "packageManifest": str(BASELINE),
                "candidateManifest": str(CANDIDATES),
            }
            with mock.patch.object(linxirapacstrap.os.path, "ismount", return_value=True), \
                 mock.patch.object(linxirapacstrap, "_catalog_selection", return_value=result), \
                 mock.patch.object(linxirapacstrap, "_pacstrap_commands", return_value=[]), \
                 mock.patch.object(linxirapacstrap, "_enable_target_multilib"), \
                 mock.patch.object(linxirapacstrap, "_enable_target_linxira_repo"), \
                 mock.patch.object(linxirapacstrap, "_rank_target_mirrors"), \
                 mock.patch.object(linxirapacstrap, "_filter_reachable_mirrors", return_value=1), \
                 mock.patch.object(linxirapacstrap, "_validate_online_target"), \
                 mock.patch.object(
                     linxirapacstrap, "_online_sync_command", return_value=["pacman", "-Sy"]
                 ), \
                 mock.patch.object(
                     linxirapacstrap, "_run_with_retries", return_value="sync timed out"
                 ), \
                 mock.patch.object(linxirapacstrap, "_write_receipt") as receipt, \
                 mock.patch.object(linxirapacstrap, "_write_pending_install") as pending:
                libcalamares.job.configuration = config
                libcalamares.globalstorage.value = lambda key: (
                    str(root) if key == "rootMountPoint" else None
                )
                error = linxirapacstrap.run()
            self.assertIsNone(error)
            deferred = receipt.call_args.args[1]
            self.assertIn("chromium", deferred["pendingItems"])
            self.assertNotIn("chromium", deferred["satisfiedItems"])
            self.assertEqual(deferred["onlinePackages"], [])
            self.assertEqual(receipt.call_args.args[3], [])
            pending.assert_called_once()

    def test_retry_error_contains_each_exit_and_command_output(self):
        with mock.patch.object(linxirapacstrap, "_run", side_effect=[1, 2]), mock.patch.object(
            linxirapacstrap.time, "sleep"
        ):
            linxirapacstrap._run.last_output = "mirror timeout"
            error = linxirapacstrap._run_with_retries(
                ["arch-chroot", "/target", "/usr/bin/pacman", "-Sy"],
                "target transaction",
                attempts=2,
            )
        self.assertIn("attempt 1/2 exited 1: mirror timeout", error)
        self.assertIn("attempt 2/2 exited 2: mirror timeout", error)


if __name__ == "__main__":
    unittest.main()
