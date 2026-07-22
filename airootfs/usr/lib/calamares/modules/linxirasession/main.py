#!/usr/bin/env python3

import json
import os
from pathlib import Path

import libcalamares


DESKTOP_SESSIONS = {
    "desktop-gnome": "gnome.desktop",
    "desktop-plasma": "plasma.desktop",
}


def pretty_name():
    return "Configure the default desktop session"


def _reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key: " + key)
        value[key] = item
    return value


def _selected_session(root):
    receipt_path = Path(root) / "var/lib/linxira/installer-selection.json"
    receipt = json.loads(
        receipt_path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    selection = receipt.get("selectionDocument")
    if (
        receipt.get("schemaVersion") != "org.linxira.installer.selection-receipt.v1"
        or receipt.get("status") != "installed"
        or not isinstance(selection, dict)
        or selection.get("schemaVersion") != "org.linxira.component-selection.v1"
        or selection.get("catalogSha256") != receipt.get("catalogSha256")
        or selection.get("catalogRelease") != receipt.get("catalogRelease")
        or selection.get("selectedLeafIds") != receipt.get("selectedLeafIds")
        or selection.get("selectedBundleIds") != receipt.get("selectedBundleIds")
    ):
        raise ValueError("installer receipt provenance is missing or inconsistent")
    selected = set(selection["selectedLeafIds"]) & set(DESKTOP_SESSIONS)
    if len(selected) != 1:
        raise ValueError("installer receipt must select exactly one desktop")
    return DESKTOP_SESSIONS[selected.pop()]


def _write_sddm_state(root, session):
    if session not in set(DESKTOP_SESSIONS.values()):
        raise ValueError("unsupported desktop session")
    session_path = Path(root) / "usr/share/wayland-sessions" / session
    if not session_path.is_file():
        raise ValueError("selected session file is missing: " + session)
    state_path = Path(root) / "var/lib/sddm/state.conf"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("[Last]\nSession=" + session + "\n", encoding="utf-8")


def run():
    root = libcalamares.globalstorage.value("rootMountPoint")
    if not root or not os.path.ismount(root):
        return "Target is not mounted", "The target root mount is unavailable."
    try:
        _write_sddm_state(root, _selected_session(root))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return "Default desktop session could not be configured", str(error)
    libcalamares.job.setprogress(1.0)
    return None
