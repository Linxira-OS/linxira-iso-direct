#!/usr/bin/env python3

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import libcalamares


INPUT_SCHEMA = "org.linxira.installer-selection.v1"
INPUT_FIELDS = {
    "schemaVersion",
    "catalogVersion",
    "catalogSha256",
    "catalogRelease",
    "selectedLeafIds",
    "selectedBundleIds",
}
SELECTION_SCHEMA = "org.linxira.component-selection.v1"
STABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
PROVENANCE = {"required", "recommended", "optional", "user"}


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


def _reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key: " + key)
        value[key] = item
    return value


def _strict_json(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(value, object_pairs_hook=_reject_duplicate_keys)


def _string_array(value, field, *, nonempty=False):
    if not isinstance(value, list) or not all(
        isinstance(item, str) and STABLE_ID.fullmatch(item) for item in value
    ):
        raise ValueError(field + " must be an array of stable IDs")
    if value != sorted(set(value)):
        raise ValueError(field + " must be de-duplicated and stably sorted")
    if nonempty and not value:
        raise ValueError(field + " must not be empty")
    return value


def _manifest(path):
    packages = [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not packages:
        raise ValueError("package manifest is empty: " + str(path))
    if len(packages) != len(set(packages)):
        raise ValueError("package manifest contains duplicate targets: " + str(path))
    return packages


def _bundle_graph(catalog):
    bundles = {item["id"]: item for item in catalog.get("bundles", [])}
    categories = {item["id"]: item for item in catalog.get("categories", [])}
    roles = {}
    for bundle_id, bundle in bundles.items():
        children = {}
        for role in ("required", "recommended", "optional"):
            for child in bundle["children"][role]:
                children[child] = role
        roles[bundle_id] = children
    return bundles, categories, roles


def _descendant_leaves(node_id, bundles, roles, leaves, visiting=None):
    if node_id in leaves:
        return {node_id}
    if node_id not in bundles:
        return set()
    visiting = set() if visiting is None else visiting
    if node_id in visiting:
        raise ValueError("Catalog bundle cycle detected at " + node_id)
    visiting.add(node_id)
    descendants = set()
    for child in roles[node_id]:
        descendants.update(_descendant_leaves(child, bundles, roles, leaves, visiting))
    visiting.remove(node_id)
    return descendants


def _expected_constraints(catalog, selected, bundles, categories, roles, leaves):
    results = []
    for bundle_id, bundle in bundles.items():
        policy = bundle["selection"]["mode"]
        maximum = None
        if bundle_id in categories:
            policy = categories[bundle_id]["selection"]["mode"]
            maximum = categories[bundle_id]["selection"].get("maxSelected")
        if policy == "exclusive":
            maximum = 1
        count = sum(
            bool(selected & _descendant_leaves(child, bundles, roles, leaves))
            for child in roles[bundle_id]
        )
        results.append(
            {
                "bundleId": bundle_id,
                "policy": policy,
                "selectedCount": count,
                "maxSelected": maximum,
                "valid": maximum is None or count <= maximum,
            }
        )
    return sorted(results, key=lambda item: item["bundleId"])


def _paths_to_leaf(node_id, target, bundles, roles, leaves, visiting=None):
    if node_id in leaves:
        return [[node_id]] if node_id == target else []
    if node_id not in bundles:
        return []
    visiting = set() if visiting is None else visiting
    if node_id in visiting:
        raise ValueError("Catalog bundle cycle detected at " + node_id)
    visiting.add(node_id)
    paths = []
    for child in roles[node_id]:
        for suffix in _paths_to_leaf(child, target, bundles, roles, leaves, visiting):
            paths.append([node_id, *suffix])
    visiting.remove(node_id)
    return paths


def _derive_selection(catalog, selected_ids, submitted_bundle_ids, digest, leaves):
    bundles, categories, roles = _bundle_graph(catalog)
    roots = sorted(set(categories) & set(bundles))
    leaf_entries = []
    derived_bundles = set()
    for leaf_id in selected_ids:
        paths = sorted({
            "/".join(path)
            for root in roots
            for path in _paths_to_leaf(root, leaf_id, bundles, roles, leaves)
        })
        if not paths:
            raise ValueError("selected Catalog leaf has no category-root provenance: " + leaf_id)
        provenance = {"user"}
        for path in paths:
            parts = path.split("/")
            derived_bundles.update(parts[:-1])
            provenance.add(roles[parts[-2]][leaf_id])
        leaf_entries.append({
            "id": leaf_id,
            "requestedBy": paths,
            "provenance": sorted(provenance),
        })
    if submitted_bundle_ids != sorted(derived_bundles):
        raise ValueError("selectedBundleIds do not match Catalog-derived selection provenance")
    selected = set(selected_ids)
    return {
        "schemaVersion": SELECTION_SCHEMA,
        "catalogSha256": digest,
        "catalogRelease": catalog["release"],
        "selectedLeafIds": selected_ids,
        "selectedBundleIds": sorted(derived_bundles),
        "leaves": leaf_entries,
        "userOverrides": [{"id": leaf_id, "selected": True} for leaf_id in selected_ids],
        "constraintResults": _expected_constraints(
            catalog, selected, bundles, categories, roles, leaves
        ),
        "providerRequirements": sorted({leaves[item]["provider"] for item in selected_ids}),
        "sourceRequirements": sorted({leaves[item]["source"] for item in selected_ids}),
    }


def _validate_provenance(selection, leaves, bundles, roles):
    submitted = selection["leaves"]
    if not isinstance(submitted, list):
        raise ValueError("leaves must be an array")
    submitted_ids = []
    active_bundles = set()
    for index, item in enumerate(submitted):
        if not isinstance(item, dict) or set(item) != {"id", "requestedBy", "provenance"}:
            raise ValueError(f"leaves[{index}] has missing or unknown fields")
        leaf_id = item["id"]
        if leaf_id not in leaves or leaf_id in submitted_ids:
            raise ValueError(f"leaves[{index}] has an unknown or duplicate leaf ID")
        requested_by = item["requestedBy"]
        provenance = item["provenance"]
        if not isinstance(requested_by, list) or requested_by != sorted(set(requested_by)) or not requested_by:
            raise ValueError(f"leaves[{index}].requestedBy must be a sorted unique string array")
        if (
            not isinstance(provenance, list)
            or provenance != sorted(set(provenance))
            or not provenance
            or set(provenance) - PROVENANCE
        ):
            raise ValueError(f"leaves[{index}].provenance is invalid")
        path_roles = set()
        for path in requested_by:
            if not isinstance(path, str):
                raise ValueError(f"leaves[{index}] has a non-string provenance path")
            parts = path.split("/")
            if len(parts) < 2 or parts[-1] != leaf_id or any(not STABLE_ID.fullmatch(part) for part in parts):
                raise ValueError("invalid selection provenance path: " + path)
            for parent, child in zip(parts, parts[1:]):
                if parent not in roles or child not in roles[parent]:
                    raise ValueError("selection provenance path is not in the Catalog: " + path)
                active_bundles.add(parent)
                if child == leaf_id:
                    path_roles.add(roles[parent][child])
        if not path_roles.issubset(set(provenance)):
            raise ValueError("selection provenance roles do not match Catalog paths for " + leaf_id)
        submitted_ids.append(leaf_id)
    if submitted_ids != selection["selectedLeafIds"]:
        raise ValueError("leaves must exactly match selectedLeafIds in stable order")
    if active_bundles != set(selection["selectedBundleIds"]):
        raise ValueError("selectedBundleIds do not match selection provenance paths")


def _validate_overrides(selection, leaves):
    overrides = selection["userOverrides"]
    if not isinstance(overrides, list):
        raise ValueError("userOverrides must be an array")
    ids = []
    for index, item in enumerate(overrides):
        if not isinstance(item, dict) or set(item) != {"id", "selected"}:
            raise ValueError(f"userOverrides[{index}] must contain exactly id and selected")
        if item["id"] not in leaves or not isinstance(item["selected"], bool):
            raise ValueError(f"userOverrides[{index}] is invalid")
        ids.append(item["id"])
    if ids != sorted(set(ids)):
        raise ValueError("userOverrides must be unique and stably sorted")


def _validate_constraint_types(value):
    fields = {"bundleId", "policy", "selectedCount", "maxSelected", "valid"}
    if not isinstance(value, list):
        raise ValueError("constraintResults must be an array")
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError(f"constraintResults[{index}] has missing or unknown fields")
        maximum = item["maxSelected"]
        if (
            not isinstance(item["bundleId"], str)
            or not STABLE_ID.fullmatch(item["bundleId"])
            or not isinstance(item["policy"], str)
            or type(item["selectedCount"]) is not int
            or item["selectedCount"] < 0
            or (maximum is not None and (type(maximum) is not int or maximum < 1))
            or not isinstance(item["valid"], bool)
        ):
            raise ValueError(f"constraintResults[{index}] has invalid field types")


def _catalog_selection(config, baseline_packages, candidate_packages):
    submitted = libcalamares.globalstorage.value(
        config.get("selectionKey", "linxiraSoftwareSelection")
    )
    if isinstance(submitted, str):
        submitted = _strict_json(submitted)
    if not isinstance(submitted, dict) or set(submitted) != INPUT_FIELDS:
        raise ValueError("selection document has missing or unknown fields")
    if submitted["schemaVersion"] != INPUT_SCHEMA:
        raise ValueError("unsupported selection document schemaVersion")
    if submitted["catalogVersion"] != 3 or isinstance(submitted["catalogVersion"], bool):
        raise ValueError("unsupported selection catalogVersion")
    if (
        not isinstance(submitted["catalogSha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", submitted["catalogSha256"])
        or not isinstance(submitted["catalogRelease"], str)
    ):
        raise ValueError("selection catalog identity has invalid field types")

    catalog_path = Path(config.get("catalogPath", "/usr/share/linxira/catalog/catalog-v3.json"))
    raw = catalog_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    catalog = _strict_json(raw)
    if catalog.get("catalogVersion") != 3:
        raise ValueError("invalid Catalog v3 document")
    if submitted["catalogSha256"] != digest:
        raise ValueError("Catalog v3 selection is stale")
    if submitted["catalogRelease"] != catalog.get("release"):
        raise ValueError("selection catalog release is stale")

    leaves = {
        item["id"]: item
        for section in ("desktops", "applications", "components")
        for item in catalog.get(section, [])
    }
    selected_ids = _string_array(submitted["selectedLeafIds"], "selectedLeafIds", nonempty=True)
    selected_bundles = _string_array(submitted["selectedBundleIds"], "selectedBundleIds", nonempty=True)
    bundles, categories, roles = _bundle_graph(catalog)
    unknown_leaves = sorted(set(selected_ids) - set(leaves))
    unknown_bundles = sorted(set(selected_bundles) - set(bundles))
    if unknown_leaves:
        raise ValueError("unknown selected Catalog IDs: " + ", ".join(unknown_leaves))
    if unknown_bundles:
        raise ValueError("unknown selected Catalog bundles: " + ", ".join(unknown_bundles))

    selection = _derive_selection(catalog, selected_ids, selected_bundles, digest, leaves)
    _validate_provenance(selection, leaves, bundles, roles)
    _validate_overrides(selection, leaves)
    _validate_constraint_types(selection["constraintResults"])
    expected_constraints = selection["constraintResults"]
    if not all(result["valid"] for result in expected_constraints):
        raise ValueError("selection violates a Catalog category constraint")
    desktop_ids = set(categories.get("desktop-environments", {}).get("children", []))
    if len(set(selected_ids) & desktop_ids) != 1:
        raise ValueError("selection must contain exactly one desktop")

    available_packages = set(baseline_packages) | set(candidate_packages)
    selected_packages = set()
    satisfied = []
    pending = []
    for leaf_id in selected_ids:
        leaf = leaves[leaf_id]
        availability = leaf.get("availability", {})
        artifact = leaf.get("artifact", {})
        if (
            leaf.get("provider") != "pacman"
            or leaf.get("source") != "arch"
            or availability.get("status") != "available"
            or availability.get("channel") != "default"
            or "x86_64" not in availability.get("architectures", [])
            or leaf.get("review", {}).get("status") != "reviewed"
            or artifact.get("type") not in {"package", "package-group"}
        ):
            raise ValueError("selected Catalog item is not eligible: " + leaf_id)
        if availability.get("offlinePolicy") == "included":
            targets = artifact.get("ids", [])
            missing = sorted(set(targets) - available_packages)
            if missing:
                raise ValueError(
                    "included Catalog artifact is absent from fixed manifests: "
                    + ", ".join(missing)
                )
            selected_packages.update(set(targets) - set(baseline_packages))
            satisfied.append(leaf_id)
        else:
            pending.append(leaf_id)

    return {
        "selectionDocument": selection,
        "selectedPackages": sorted(selected_packages),
        "satisfiedItems": satisfied,
        "pendingItems": pending,
        "catalogSha256": digest,
        "catalogRelease": catalog["release"],
    }


def _write_receipt(root, result, baseline_packages, selected_packages):
    receipt_path = Path(root) / "var/lib/linxira/installer-selection.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    selection = result["selectionDocument"]
    receipt = {
        "schemaVersion": "org.linxira.installer.selection-receipt.v1",
        "catalogVersion": 3,
        "catalogSha256": result["catalogSha256"],
        "catalogRelease": result["catalogRelease"],
        "selectedLeafIds": selection["selectedLeafIds"],
        "selectedBundleIds": selection["selectedBundleIds"],
        "satisfiedItems": result["satisfiedItems"],
        "pendingItems": result["pendingItems"],
        "selectionDocument": selection,
        "installedBaselinePackages": baseline_packages,
        "installedSelectedPackages": selected_packages,
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
    candidate_manifest = config.get("candidateManifest")

    if not root or not os.path.ismount(root):
        return "Target is not mounted", "The target root mount is unavailable."
    if not pacman_config or not os.path.isfile(pacman_config):
        return "Offline configuration is missing", str(pacman_config)
    if not repository or not os.path.isdir(repository):
        return "Offline repository is missing", str(repository)
    if not manifest or not os.path.isfile(manifest):
        return "Target package list is missing", str(manifest)
    if not candidate_manifest or not os.path.isfile(candidate_manifest):
        return "Offline candidate package list is missing", str(candidate_manifest)

    try:
        baseline_packages = _manifest(manifest)
        candidate_packages = _manifest(candidate_manifest)
        microcode = _microcode_package()
        if microcode:
            baseline_packages.append(microcode)
        result = _catalog_selection(config, baseline_packages, candidate_packages)
    except (OSError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        return "Software selection is invalid", str(error)

    selected_packages = result["selectedPackages"]
    command = ["pacstrap", "-C", pacman_config, "-K", "-M", root]
    command.extend(baseline_packages)
    command.extend(selected_packages)
    if _run(command) != 0:
        return "Package installation failed", "pacstrap did not complete successfully."

    try:
        _write_receipt(root, result, baseline_packages, selected_packages)
    except OSError as error:
        return "Installer receipt could not be written", str(error)

    libcalamares.job.setprogress(1.0)
    return None
