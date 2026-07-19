#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess

import libcalamares


CATALOG_PATH = Path("/usr/share/linxira/catalog/catalog-v2.json")
SELECTION_KEY = "packagechooser_components"
APPLICATION_SELECTION_KEY = "packagechooser_applications"
DESKTOP_SELECTION_KEY = "packagechooser_desktop"


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


def _selected_applications(catalog, selection):
    applications = {
        application["id"]: application
        for application in catalog.get("applications", [])
        if application.get("installer")
        and application.get("source") == "arch"
        and application.get("review", {}).get("status") == "reviewed"
    }
    selected_ids = [item for item in selection.split(",") if item]
    unknown = sorted(set(selected_ids) - applications.keys())
    if unknown:
        raise ValueError("Unknown application selection: " + ", ".join(unknown))
    return selected_ids, [applications[item] for item in selected_ids]


def _selected_desktop(catalog, selection):
    bundles = {bundle["id"]: bundle for bundle in catalog.get("desktopBundles", [])}
    selected_ids = [item for item in selection.split(",") if item]
    if len(selected_ids) != 1:
        raise ValueError("Choose exactly one desktop bundle")
    selected_id = selected_ids[0]
    if selected_id not in bundles:
        raise ValueError("Unknown desktop selection: " + selected_id)
    return selected_id, bundles[selected_id]


def _install_command(root, packages):
    return [
        "arch-chroot",
        root,
        "pacman",
        "--sync",
        "--refresh",
        "--needed",
        "--noconfirm",
        "--",
    ] + packages


def run():
    root = libcalamares.globalstorage.value("rootMountPoint")
    if not root or not os.path.ismount(root):
        return "Target is not mounted", "The target root mount is unavailable."

    selection = libcalamares.globalstorage.value(SELECTION_KEY) or ""
    receipt = {
        "catalogVersion": 2,
        "desktop": None,
        "profiles": [],
        "applications": [],
        "packages": [],
        "status": "none",
    }
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        desktop_id, desktop = _selected_desktop(
            catalog, libcalamares.globalstorage.value(DESKTOP_SELECTION_KEY) or ""
        )
        selected_ids, selected_profiles = _selected_profiles(catalog, selection)
        selected_app_ids, selected_applications = _selected_applications(
            catalog,
            libcalamares.globalstorage.value(APPLICATION_SELECTION_KEY) or "",
        )
        packages = sorted(
            {package for package in desktop["packages"]}
            | {package for profile in selected_profiles for package in profile["packages"]}
            | {
                package
                for application in selected_applications
                for package in application["packages"]
            }
        )
        receipt.update(
            {
                "desktop": desktop_id,
                "profiles": selected_ids,
                "applications": selected_app_ids,
                "packages": packages,
            }
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        receipt.update({"status": "catalog-error", "message": str(error)})
        _write_receipt(root, receipt)
        libcalamares.utils.warning("linxiraoptional: " + str(error))
        libcalamares.job.setprogress(1.0)
        return "Invalid software selection", str(error)

    if not packages:
        _write_receipt(root, receipt)
        libcalamares.job.setprogress(1.0)
        return None

    exit_code = _run(_install_command(root, packages))
    receipt["status"] = "installed" if exit_code == 0 else "deferred"
    if exit_code:
        receipt["message"] = (
            "The selected desktop or components could not be installed. The base "
            "system is complete; retry the same receipt after first boot."
        )
        libcalamares.utils.warning("linxiraoptional: package installation deferred")
    else:
        receipt["message"] = "Selected desktop and components were installed during setup."
    _write_receipt(root, receipt)
    libcalamares.job.setprogress(1.0)
    return None
