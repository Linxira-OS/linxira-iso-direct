import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "airootfs/usr/lib/calamares/modules/linxirasession/main.py"
)
libcalamares = types.ModuleType("libcalamares")
libcalamares.globalstorage = types.SimpleNamespace(value=lambda key: None)
libcalamares.job = types.SimpleNamespace(setprogress=lambda value: None)
sys.modules["libcalamares"] = libcalamares
spec = importlib.util.spec_from_file_location("linxirasession", MODULE_PATH)
linxirasession = importlib.util.module_from_spec(spec)
spec.loader.exec_module(linxirasession)


class DesktopSessionTests(unittest.TestCase):
    @staticmethod
    def receipt(selected):
        return {
            "schemaVersion": "org.linxira.installer.selection-receipt.v1",
            "status": "installed",
            "catalogSha256": "a" * 64,
            "catalogRelease": "test",
            "selectedLeafIds": selected,
            "selectedBundleIds": ["desktop-environments"],
            "selectionDocument": {
                "schemaVersion": "org.linxira.component-selection.v1",
                "catalogSha256": "a" * 64,
                "catalogRelease": "test",
                "selectedLeafIds": selected,
                "selectedBundleIds": ["desktop-environments"],
            },
        }

    def target(self, desktop):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        receipt = root / "var/lib/linxira/installer-selection.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps(self.receipt([desktop])), encoding="utf-8")
        session = linxirasession.DESKTOP_SESSIONS[desktop]
        session_file = root / "usr/share/wayland-sessions" / session
        session_file.parent.mkdir(parents=True)
        session_file.touch()
        return temporary, root

    def test_selected_gnome_session_is_written_for_sddm(self):
        temporary, root = self.target("desktop-gnome")
        with temporary:
            session = linxirasession._selected_session(root)
            linxirasession._write_sddm_state(root, session)
            state = (root / "var/lib/sddm/state.conf").read_text(encoding="utf-8")
        self.assertEqual(session, "gnome.desktop")
        self.assertEqual(state, "[Last]\nSession=gnome.desktop\n")

    def test_selected_plasma_session_is_written_for_sddm(self):
        temporary, root = self.target("desktop-plasma")
        with temporary:
            session = linxirasession._selected_session(root)
            linxirasession._write_sddm_state(root, session)
            state = (root / "var/lib/sddm/state.conf").read_text(encoding="utf-8")
        self.assertEqual(state, "[Last]\nSession=plasma.desktop\n")

    def test_missing_or_multiple_desktops_fail_closed(self):
        for selected in ([], ["desktop-plasma", "desktop-gnome"]):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as directory:
                receipt = Path(directory) / "var/lib/linxira/installer-selection.json"
                receipt.parent.mkdir(parents=True)
                receipt.write_text(json.dumps(self.receipt(selected)), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "exactly one desktop"):
                    linxirasession._selected_session(directory)

    def test_inconsistent_nested_selection_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "var/lib/linxira/installer-selection.json"
            receipt_path.parent.mkdir(parents=True)
            receipt = self.receipt(["desktop-plasma"])
            receipt["selectionDocument"]["selectedLeafIds"] = ["desktop-gnome"]
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inconsistent"):
                linxirasession._selected_session(directory)

    def test_only_fixed_session_values_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "unsupported desktop session"):
                linxirasession._write_sddm_state(directory, "gdm.desktop")


if __name__ == "__main__":
    unittest.main()
