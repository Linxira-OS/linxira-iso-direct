#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess

import libcalamares


CATALOG_PATH = Path("/usr/share/linxira/catalog/catalog-v2.json")
SELECTION_KEY = "packagechooser_components"


def pretty_name():
    return "Prepare optional Linxira components"


def _write_receipt(root, receipt):
    receipt_path = Path(root) / "var/lib/linxira/installer-selection.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = receipt_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(receipt_path)


def _run(command):
    libcalamares.utils.debug("linxiraoptional: " + " ".join(command))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    for line in process.stdout:
        line = line.rstrip()
        if line:
            libcalamares.utils.debug("linxiraoptional: " + line)
    return process.wait()


def _selected_profiles(catalog, selection):
    profiles = {
        profile["id"]: profile
        for profile in catalog["profiles"]
        if profile.get("installer") and profile.get("source") == "arch"
    }
    selected_ids = [item for item in selection.split(",") if item]
    unknown = sorted(set(selected_ids) - profiles.keys())
    if unknown:
        raise ValueError("Unknown component selection: " + ", ".join(unknown))
    return selected_ids, [profiles[item] for item in selected_ids]


def _download_command(root, packages):
    return [
        "arch-chroot",
        root,
        "pacman",
        "--sync",
        "--refresh",
        "--downloadonly",
        "--needed",
        "--noconfirm",
        "--",
    ] + packages


def run():
    root = libcalamares.globalstorage.value("rootMountPoint")
    if not root or not os.path.ismount(root):
        return "Target is not mounted", "The target root mount is unavailable."

    selection = libcalamares.globalstorage.value(SELECTION_KEY) or ""
    receipt = {"catalogVersion": 2, "profiles": [], "packages": [], "status": "none"}
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        selected_ids, selected_profiles = _selected_profiles(catalog, selection)
        packages = sorted(
            {package for profile in selected_profiles for package in profile["packages"]}
        )
        receipt.update({"profiles": selected_ids, "packages": packages})
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        receipt.update({"status": "catalog-error", "message": str(error)})
        _write_receipt(root, receipt)
        libcalamares.utils.warning("linxiraoptional: " + str(error))
        libcalamares.job.setprogress(1.0)
        return None

    if not packages:
        _write_receipt(root, receipt)
        libcalamares.job.setprogress(1.0)
        return None

    exit_code = _run(_download_command(root, packages))
    receipt["status"] = "downloaded" if exit_code == 0 else "deferred"
    if exit_code:
        receipt["message"] = (
            "The package download was unavailable. The base system is complete; "
            "the selected profiles can be downloaded after first boot."
        )
        libcalamares.utils.warning("linxiraoptional: package download deferred")
    else:
        receipt["message"] = (
            "Packages are cached but not installed. Complete the selected profiles "
            "after first boot with linxira-config."
        )
    _write_receipt(root, receipt)
    libcalamares.job.setprogress(1.0)
    return None
