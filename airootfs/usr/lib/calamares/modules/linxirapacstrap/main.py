#!/usr/bin/env python3

import hashlib
import json
import os
from pathlib import Path
import queue
import re
import socket
import subprocess
import threading
import time
from urllib.parse import urlsplit

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


def _run(command, timeout_seconds=None):
    libcalamares.utils.debug("linxirapacstrap: " + " ".join(command))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines = queue.Queue()

    def read_output():
        for line in process.stdout:
            lines.put(line)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    output = []
    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    timed_out = False
    while process.poll() is None:
        try:
            line = lines.get(timeout=1)
        except queue.Empty:
            line = ""
        line = line.rstrip()
        if line:
            output.append(line)
            libcalamares.utils.debug("linxirapacstrap: " + line)
        if deadline is not None and time.monotonic() >= deadline:
            process.kill()
            timed_out = True
    reader.join()
    while not lines.empty():
        line = lines.get().rstrip()
        if line:
            output.append(line)
            libcalamares.utils.debug("linxirapacstrap: " + line)
    _run.last_output = "\n".join(output)
    if timed_out:
        _run.last_output = (
            "command timed out after " + str(timeout_seconds) + " seconds"
            + ("\n" + _run.last_output if _run.last_output else "")
        )
        libcalamares.utils.debug("linxirapacstrap: " + _run.last_output)
        return 124
    return process.returncode


_run.last_output = ""


def _run_with_retries(command, description, attempts=3, timeout_seconds=None):
    failures = []
    for attempt in range(1, attempts + 1):
        returncode = _run(command, timeout_seconds=timeout_seconds)
        if returncode == 0:
            return None
        detail = _run.last_output.strip() or "no command output"
        failures.append(f"attempt {attempt}/{attempts} exited {returncode}: {detail}")
        if attempt < attempts:
            time.sleep(attempt * 2)
    return (
        description
        + " failed after retries\ncommand: "
        + " ".join(command)
        + "\n"
        + "\n".join(failures)
    )


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


def _derive_selection(
    catalog,
    selected_ids,
    submitted_bundle_ids,
    digest,
    leaves,
    *,
    user_selected_ids=None,
):
    bundles, categories, roles = _bundle_graph(catalog)
    roots = sorted(set(categories) & set(bundles))
    leaf_entries = []
    derived_bundles = set()
    user_selected = set(selected_ids) if user_selected_ids is None else set(user_selected_ids)
    for leaf_id in selected_ids:
        paths = sorted({
            "/".join(path)
            for root in roots
            for path in _paths_to_leaf(root, leaf_id, bundles, roles, leaves)
        })
        if not paths:
            raise ValueError("selected Catalog leaf has no category-root provenance: " + leaf_id)
        provenance = set()
        if leaf_id in user_selected:
            provenance.add("user")
        for path in paths:
            parts = path.split("/")
            derived_bundles.update(parts[:-1])
            provenance.add(roles[parts[-2]][leaf_id])
        leaf_entries.append({
            "id": leaf_id,
            "requestedBy": paths,
            "provenance": sorted(provenance),
        })
    if submitted_bundle_ids is not None and submitted_bundle_ids != sorted(derived_bundles):
        raise ValueError("selectedBundleIds do not match Catalog-derived selection provenance")
    selected = set(selected_ids)
    return {
        "schemaVersion": SELECTION_SCHEMA,
        "catalogSha256": digest,
        "catalogRelease": catalog["release"],
        "selectedLeafIds": selected_ids,
        "selectedBundleIds": sorted(derived_bundles),
        "leaves": leaf_entries,
        "userOverrides": [
            {"id": leaf_id, "selected": True}
            for leaf_id in selected_ids
            if leaf_id in user_selected
        ],
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


def _installer_eligible(leaf):
    availability = leaf.get("availability", {})
    artifact = leaf.get("artifact", {})
    license_info = leaf.get("license", {})
    return (
        leaf.get("provider") == "pacman"
        and leaf.get("source") == "arch"
        and availability.get("status") == "available"
        and availability.get("channel") == "default"
        and "x86_64" in availability.get("architectures", [])
        and leaf.get("review", {}).get("status") == "reviewed"
        and artifact.get("type") in {"package", "package-group"}
        and license_info.get("requiresAcceptance") is not True
    )


def _required_bundle_leaf_ids(bundle_id, leaves, bundles, roles, visiting=None):
    visiting = set() if visiting is None else visiting
    if bundle_id in visiting:
        raise ValueError("Catalog bundle cycle detected at " + bundle_id)
    visiting.add(bundle_id)
    required = set()
    for child_id, role in roles.get(bundle_id, {}).items():
        if role != "required":
            continue
        if child_id in leaves:
            required.add(child_id)
        elif child_id in bundles:
            required.update(
                _required_bundle_leaf_ids(child_id, leaves, bundles, roles, visiting)
            )
    visiting.remove(bundle_id)
    return required


def _direct_required_leaf_ids(leaf_id, leaves, bundles, roles, nodes):
    required = set()
    for dependency_id in leaves[leaf_id].get("requires", []):
        if dependency_id in leaves:
            required.add(dependency_id)
        elif dependency_id in bundles:
            required.update(
                _required_bundle_leaf_ids(dependency_id, leaves, bundles, roles)
            )
        elif dependency_id not in nodes:
            raise ValueError(
                "Catalog leaf references an unknown required dependency: "
                + leaf_id
                + " -> "
                + dependency_id
            )
    return required


def _expand_required_leaf_ids(selected_ids, leaves, bundles, roles, nodes):
    ordered = []
    expanded = set()
    visiting = []

    def visit(leaf_id):
        if leaf_id in expanded:
            return
        if leaf_id in visiting:
            cycle = " -> ".join([*visiting[visiting.index(leaf_id):], leaf_id])
            raise ValueError("Catalog requires cycle detected: " + cycle)
        visiting.append(leaf_id)
        for dependency_id in sorted(
            _direct_required_leaf_ids(leaf_id, leaves, bundles, roles, nodes)
        ):
            visit(dependency_id)
        visiting.pop()
        expanded.add(leaf_id)
        ordered.append(leaf_id)

    for leaf_id in selected_ids:
        visit(leaf_id)
    return sorted(expanded), ordered


def _validate_selection_document(selection, leaves, bundles, roles):
    _validate_provenance(selection, leaves, bundles, roles)
    _validate_overrides(selection, leaves)
    _validate_constraint_types(selection["constraintResults"])
    if not all(result["valid"] for result in selection["constraintResults"]):
        raise ValueError("selection violates a Catalog category constraint")


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
    nodes = {
        item["id"]: item
        for section in ("desktops", "applications", "components", "bundles", "operations")
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

    submitted_selection = _derive_selection(
        catalog, selected_ids, selected_bundles, digest, leaves
    )
    _validate_selection_document(submitted_selection, leaves, bundles, roles)

    expanded_ids, ordered_ids = _expand_required_leaf_ids(
        selected_ids, leaves, bundles, roles, nodes
    )
    selection = _derive_selection(
        catalog,
        expanded_ids,
        None,
        digest,
        leaves,
        user_selected_ids=selected_ids,
    )
    _validate_selection_document(selection, leaves, bundles, roles)
    desktop_ids = set(categories.get("desktop-environments", {}).get("children", []))
    if len(set(expanded_ids) & desktop_ids) != 1:
        raise ValueError("selection must contain exactly one desktop")

    available_packages = set(baseline_packages) | set(candidate_packages)
    baseline_package_set = set(baseline_packages)
    offline_package_set = set()
    offline_packages = []
    online_package_set = set()
    online_packages = []
    online_satisfied = []
    satisfied = []
    pending = []
    pending_set = set()
    for leaf_id in ordered_ids:
        leaf = leaves[leaf_id]
        availability = leaf.get("availability", {})
        artifact = leaf.get("artifact", {})
        dependencies = _direct_required_leaf_ids(leaf_id, leaves, bundles, roles, nodes)
        operation_dependencies = {
            dependency_id
            for dependency_id in leaf.get("requires", [])
            if isinstance(nodes.get(dependency_id), dict)
            and nodes[dependency_id].get("kind") == "operation"
        }
        if dependencies & pending_set:
            pending.append(leaf_id)
            pending_set.add(leaf_id)
            continue
        if operation_dependencies:
            pending.append(leaf_id)
            pending_set.add(leaf_id)
            continue
        if not _installer_eligible(leaf):
            if leaf.get("kind") == "desktop":
                raise ValueError("selected desktop is not installer-eligible: " + leaf_id)
            pending.append(leaf_id)
            pending_set.add(leaf_id)
            continue
        offline_policy = availability.get("offlinePolicy")
        if offline_policy == "included":
            targets = artifact.get("ids", [])
            missing = sorted(set(targets) - available_packages)
            if missing:
                raise ValueError(
                    "included Catalog artifact is absent from fixed manifests: "
                    + ", ".join(missing)
                )
            for target in targets:
                if target not in baseline_package_set and target not in offline_package_set:
                    offline_package_set.add(target)
                    offline_packages.append(target)
            satisfied.append(leaf_id)
        elif offline_policy in {"online-only", "defer-with-consent"}:
            for target in artifact.get("ids", []):
                if target not in online_package_set:
                    online_package_set.add(target)
                    online_packages.append(target)
            satisfied.append(leaf_id)
            online_satisfied.append(leaf_id)
        else:
            pending.append(leaf_id)
            pending_set.add(leaf_id)

    return {
        "selectionDocument": selection,
        "selectedPackages": offline_packages,
        "onlinePackages": online_packages,
        "onlineSatisfiedLeafIds": online_satisfied,
        "satisfiedItems": satisfied,
        "pendingItems": pending,
        "catalogSha256": digest,
        "catalogRelease": catalog["release"],
    }


def _write_receipt(root, result, baseline_packages, selected_packages):
    receipt_path = Path(root) / "var/lib/linxira/installer-selection.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    selection = result["selectionDocument"]
    satisfied = set(result["satisfiedItems"])
    receipt = {
        "schemaVersion": "org.linxira.installer.selection-receipt.v1",
        "catalogVersion": 3,
        "catalogSha256": result["catalogSha256"],
        "catalogRelease": result["catalogRelease"],
        "selectedLeafIds": selection["selectedLeafIds"],
        "selectedBundleIds": selection["selectedBundleIds"],
        "satisfiedItems": result["satisfiedItems"],
        "pendingItems": result["pendingItems"],
        "installedItems": result["satisfiedItems"],
        "deferredItems": result["pendingItems"],
        "itemStatuses": [
            {
                "id": leaf_id,
                "status": (
                    "installed"
                    if leaf_id in satisfied
                    else "explicitly-deferred"
                ),
            }
            for leaf_id in selection["selectedLeafIds"]
        ],
        "selectionDocument": selection,
        "installedBaselinePackages": baseline_packages,
        "installedSelectedPackages": selected_packages,
        "status": "installed",
    }
    temporary = receipt_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(receipt_path)


def _enable_target_multilib(root):
    config_path = Path(root) / "etc/pacman.conf"
    contents = config_path.read_text(encoding="utf-8")
    disabled = "#[multilib]\n#Include = /etc/pacman.d/mirrorlist"
    enabled = "[multilib]\nInclude = /etc/pacman.d/mirrorlist"
    if disabled in contents:
        if contents.count(disabled) != 1:
            raise ValueError("target pacman configuration has ambiguous multilib sections")
        config_path.write_text(contents.replace(disabled, enabled), encoding="utf-8")
    elif enabled not in contents:
        raise ValueError("target pacman configuration has no recognized multilib section")


def _pacstrap_command(pacman_config, root, packages):
    return [
        "pacstrap",
        "-C",
        pacman_config,
        "-K",
        root,
        *packages,
    ]


def _pacstrap_commands(pacman_config, root, baseline_packages, selected_packages):
    commands = [_pacstrap_command(pacman_config, root, baseline_packages)]
    if selected_packages:
        commands.append(_pacstrap_command(pacman_config, root, selected_packages))
    return commands


def _online_sync_command(root, timeout_seconds):
    return [
        "arch-chroot",
        root,
        "/usr/bin/timeout",
        "--foreground",
        str(timeout_seconds),
        "/usr/bin/pacman",
        "-Sy",
        "--noconfirm",
    ]


def _online_install_command(root, packages, timeout_seconds):
    return [
        "arch-chroot",
        root,
        "/usr/bin/timeout",
        "--foreground",
        str(timeout_seconds),
        "/usr/bin/pacman",
        "-S",
        "--needed",
        "--noconfirm",
        *packages,
    ]


def _validate_online_target(root):
    root_path = Path(root)
    config_path = root_path / "etc/pacman.conf"
    mirrorlist_path = root_path / "etc/pacman.d/mirrorlist"
    keyring_path = root_path / "etc/pacman.d/gnupg/pubring.gpg"
    config = config_path.read_text(encoding="utf-8")
    mirrorlist = mirrorlist_path.read_text(encoding="utf-8")
    if "linxira-offline" in config:
        raise ValueError("target pacman configuration retains the offline repository")
    for repository in ("core", "extra"):
        if not re.search(rf"(?m)^\[{re.escape(repository)}\]\s*$", config):
            raise ValueError("target pacman configuration is missing official repository: " + repository)
    if not re.search(r"(?m)^\s*Server\s*=\s*\S+", mirrorlist):
        raise ValueError("target pacman mirrorlist has no enabled server")
    if not keyring_path.is_file() or keyring_path.stat().st_size == 0:
        raise ValueError("target pacman keyring is not initialized")


def _rank_target_mirrors(root, timeout_seconds):
    mirrorlist = Path(root) / "etc/pacman.d/mirrorlist"
    ranked = mirrorlist.with_name("mirrorlist.linxira-ranked")
    original = mirrorlist.read_bytes()
    ranked.unlink(missing_ok=True)
    error = _run_with_retries(
        [
            "/usr/bin/reflector",
            "--protocol",
            "https",
            "--latest",
            "20",
            "--sort",
            "rate",
            "--save",
            str(ranked),
        ],
        "official mirror ranking",
        attempts=1,
        timeout_seconds=timeout_seconds,
    )
    try:
        contents = ranked.read_text(encoding="utf-8")
    except OSError:
        contents = ""
    if error or not re.search(r"(?m)^\s*Server\s*=\s*https://\S+", contents):
        ranked.unlink(missing_ok=True)
        mirrorlist.write_bytes(original)
        libcalamares.utils.debug(
            "linxirapacstrap: mirror ranking failed; retaining the original mirrorlist"
        )
        return
    ranked.replace(mirrorlist)
    libcalamares.utils.debug("linxirapacstrap: target mirrorlist ranked with reflector")


def _reachable_mirror_servers(mirrorlist_text, connect_timeout=8, maximum=8):
    servers = re.findall(r"(?m)^\s*Server\s*=\s*(\S+)", mirrorlist_text)
    reachable = []
    for server in servers:
        parts = urlsplit(server)
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if not host:
            continue
        try:
            with socket.create_connection((host, port), timeout=connect_timeout):
                pass
            reachable.append(server)
        except OSError:
            libcalamares.utils.debug("linxirapacstrap: mirror unreachable: " + server)
        if len(reachable) >= maximum:
            break
    return reachable


def _filter_reachable_mirrors(root, connect_timeout=8, maximum=8):
    mirrorlist = Path(root) / "etc/pacman.d/mirrorlist"
    original = mirrorlist.read_bytes()
    text = original.decode("utf-8", errors="replace")
    servers = re.findall(r"(?m)^\s*Server\s*=\s*(\S+)", text)
    if not servers:
        return 0
    reachable = _reachable_mirror_servers(text, connect_timeout, maximum)
    if not reachable:
        libcalamares.utils.debug("linxirapacstrap: no reachable mirror; leaving the list untouched")
        return 0
    if len(reachable) == len(servers):
        return len(reachable)
    mirrorlist.write_text(
        "\n".join("Server = " + server for server in reachable) + "\n",
        encoding="utf-8",
    )
    libcalamares.utils.debug(
        "linxirapacstrap: filtered mirrorlist to %d reachable server(s)" % len(reachable)
    )
    return len(reachable)


def _defer_online_items(result):
    result = dict(result)
    deferred = set(result.get("onlineSatisfiedLeafIds", []))
    if not deferred:
        return result
    result["satisfiedItems"] = [
        item for item in result["satisfiedItems"] if item not in deferred
    ]
    result["pendingItems"] = sorted(set(result["pendingItems"]) | deferred)
    result["onlinePackages"] = []
    return result


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
        retry_count = config.get("retryCount", 3)
        if type(retry_count) is not int or not 1 <= retry_count <= 5:
            raise ValueError("retryCount must be an integer from 1 through 5")
        mirror_rank_timeout = config.get("mirrorRankTimeoutSeconds", 120)
        if type(mirror_rank_timeout) is not int or not 30 <= mirror_rank_timeout <= 300:
            raise ValueError("mirrorRankTimeoutSeconds must be an integer from 30 through 300")
        online_transaction_timeout = config.get("onlineTransactionTimeoutSeconds", 600)
        if type(online_transaction_timeout) is not int or not 300 <= online_transaction_timeout <= 1800:
            raise ValueError(
                "onlineTransactionTimeoutSeconds must be an integer from 300 through 1800"
            )
        online_transaction_attempts = config.get("onlineTransactionAttempts", 1)
        if type(online_transaction_attempts) is not int or not 1 <= online_transaction_attempts <= 2:
            raise ValueError("onlineTransactionAttempts must be an integer from 1 through 2")
        online_sync_timeout = config.get("onlineSyncTimeoutSeconds", 180)
        if type(online_sync_timeout) is not int or not 60 <= online_sync_timeout <= 600:
            raise ValueError("onlineSyncTimeoutSeconds must be an integer from 60 through 600")
        online_sync_attempts = config.get("onlineSyncAttempts", 2)
        if type(online_sync_attempts) is not int or not 1 <= online_sync_attempts <= 3:
            raise ValueError("onlineSyncAttempts must be an integer from 1 through 3")
        online_connect_timeout = config.get("onlineConnectTimeoutSeconds", 8)
        if type(online_connect_timeout) is not int or not 2 <= online_connect_timeout <= 30:
            raise ValueError(
                "onlineConnectTimeoutSeconds must be an integer from 2 through 30"
            )
    except (OSError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        return "Software selection is invalid", str(error)

    selected_packages = result["selectedPackages"]
    for command in _pacstrap_commands(
        pacman_config, root, baseline_packages, selected_packages
    ):
        error = _run_with_retries(command, "offline pacstrap", retry_count)
        if error:
            return "Package installation failed", error

    try:
        _enable_target_multilib(root)
        if result["onlinePackages"]:
            _validate_online_target(root)
    except (OSError, ValueError) as error:
        return "Target configuration could not be finalized", str(error)

    if result["onlinePackages"]:
        _rank_target_mirrors(root, mirror_rank_timeout)
        reachable = _filter_reachable_mirrors(root, online_connect_timeout)
        if not reachable:
            libcalamares.utils.warning(
                "linxirapacstrap: no reachable official mirror; deferring online packages"
            )
            result = _defer_online_items(result)
        else:
            try:
                _validate_online_target(root)
            except (OSError, ValueError) as error:
                libcalamares.utils.warning(
                    "linxirapacstrap: online target validation failed; deferring online packages: "
                    + str(error)
                )
                result = _defer_online_items(result)
            else:
                sync_error = _run_with_retries(
                    _online_sync_command(root, online_sync_timeout),
                    "official repository database synchronization",
                    online_sync_attempts,
                    timeout_seconds=online_sync_timeout,
                )
                if sync_error:
                    libcalamares.utils.warning(
                        "linxirapacstrap: database synchronization failed; deferring online packages: "
                        + sync_error
                    )
                    result = _defer_online_items(result)
                else:
                    command = _online_install_command(
                        root, result["onlinePackages"], online_transaction_timeout
                    )
                    error = _run_with_retries(
                        command,
                        "target official repository package installation",
                        online_transaction_attempts,
                        timeout_seconds=online_transaction_timeout,
                    )
                    if error:
                        libcalamares.utils.warning(
                            "linxirapacstrap: online package installation failed; deferring online packages: "
                            + error
                        )
                        result = _defer_online_items(result)

    try:
        _write_receipt(
            root,
            result,
            baseline_packages,
            selected_packages + result["onlinePackages"],
        )
    except OSError as error:
        return "Target configuration could not be finalized", str(error)

    libcalamares.job.setprogress(1.0)
    return None
