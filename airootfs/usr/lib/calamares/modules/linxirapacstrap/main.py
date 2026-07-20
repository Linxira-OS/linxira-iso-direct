#!/usr/bin/env python3

import os
import hashlib
import json
from pathlib import Path
import subprocess

import libcalamares


def pretty_name():
    return "Install Linxira OS packages"


def _run(command):
    libcalamares.utils.debug("linxirapacstrap: " + " ".join(command))
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
            libcalamares.utils.debug("linxirapacstrap: " + line)
    return process.wait()


def _microcode_package():
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as cpuinfo:
            contents = cpuinfo.read()
    except OSError:
        return None
    if "GenuineIntel" in contents:
        return "intel-ucode"
    if "AuthenticAMD" in contents:
        return "amd-ucode"
    return None


def _catalog_selection(config, packages):
    selection = libcalamares.globalstorage.value(config.get("selectionKey", "linxiraSoftwareSelection"))
    if not selection:
        return {"selectedLeafIds": [], "selectedBundleIds": [], "satisfiedItems": [], "pendingItems": []}
    if not isinstance(selection, dict) or selection.get("catalogVersion") != 3:
        raise ValueError("invalid Catalog v3 selection")

    catalog_path = Path(config.get("catalogPath", "/usr/share/linxira/catalog/catalog-v3.json"))
    raw = catalog_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if selection.get("catalogSha256") != digest:
        raise ValueError("Catalog v3 selection is stale")
    catalog = json.loads(raw)
    leaves = {
        item["id"]: item
        for section in ("applications", "components")
        for item in catalog.get(section, [])
    }
    selected = sorted(set(selection.get("selectedLeafIds", [])))
    unknown = sorted(set(selected) - set(leaves))
    if unknown:
        raise ValueError("unknown selected Catalog IDs: " + ", ".join(unknown))

    satisfied = []
    pending = []
    for leaf_id in selected:
        leaf = leaves[leaf_id]
        availability = leaf.get("availability", {})
        review = leaf.get("review", {})
        if (
            leaf.get("provider") not in {"pacman", None}
            or leaf.get("source") not in {"arch", None}
            or availability.get("status") != "available"
            or availability.get("channel") != "default"
            or review.get("status") != "reviewed"
        ):
            raise ValueError("selected Catalog item is not eligible: " + leaf_id)
        artifact = leaf.get("artifact", {})
        targets = artifact.get("ids", []) if artifact.get("type") in {"package", "package-group"} else []
        if availability.get("offlinePolicy") == "included":
            missing = sorted(set(targets) - set(packages))
            if missing:
                raise ValueError("offline Catalog item is absent from the fixed manifest: " + ", ".join(missing))
            satisfied.append(leaf_id)
        else:
            pending.append(leaf_id)
    return {
        "selectedLeafIds": selected,
        "selectedBundleIds": sorted(set(selection.get("selectedBundleIds", []))),
        "satisfiedItems": satisfied,
        "pendingItems": pending,
        "catalogSha256": digest,
        "catalogRelease": catalog.get("release"),
    }


def _write_receipt(root, selection, packages):
    receipt_path = Path(root) / "var/lib/linxira/installer-selection.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schemaVersion": "org.linxira.installer.selection-receipt.v1",
        "catalogVersion": 3,
        "catalogSha256": selection.get("catalogSha256"),
        "catalogRelease": selection.get("catalogRelease"),
        "selectedLeafIds": selection.get("selectedLeafIds", []),
        "selectedBundleIds": selection.get("selectedBundleIds", []),
        "satisfiedItems": selection.get("satisfiedItems", []),
        "pendingItems": selection.get("pendingItems", []),
        "installedBaselinePackages": packages,
        "status": "installed",
    }
    temporary = receipt_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(receipt_path)


def run():
    root = libcalamares.globalstorage.value("rootMountPoint")
    config = libcalamares.job.configuration or {}
    pacman_config = config.get("pacmanConfig")
    repository = config.get("repositoryPath")
    manifest = config.get("packageManifest")

    if not root or not os.path.ismount(root):
        return "Target is not mounted", "The target root mount is unavailable."
    if not pacman_config or not os.path.isfile(pacman_config):
        return "Offline configuration is missing", str(pacman_config)
    if not repository or not os.path.isdir(repository):
        return "Offline repository is missing", str(repository)
    if not manifest or not os.path.isfile(manifest):
        return "Target package list is missing", str(manifest)

    with open(manifest, encoding="utf-8") as package_file:
        packages = [
            line.strip()
            for line in package_file
            if line.strip() and not line.lstrip().startswith("#")
        ]
    if not packages:
        return "Target package list is empty", str(manifest)

    microcode = _microcode_package()
    if microcode:
        packages.append(microcode)

    try:
        selection = _catalog_selection(config, packages)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return "Software selection is invalid", str(error)

    command = ["pacstrap", "-C", pacman_config, "-K", "-M", root] + packages
    if _run(command) != 0:
        return "Package installation failed", "pacstrap did not complete successfully."

    try:
        _write_receipt(root, selection, packages)
    except OSError as error:
        return "Installer receipt could not be written", str(error)

    libcalamares.job.setprogress(1.0)
    return None
