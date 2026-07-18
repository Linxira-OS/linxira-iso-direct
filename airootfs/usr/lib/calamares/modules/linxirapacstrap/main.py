#!/usr/bin/env python3

import os
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

    command = ["pacstrap", "-C", pacman_config, "-K", "-M", root] + packages
    if _run(command) != 0:
        return "Package installation failed", "pacstrap did not complete successfully."

    libcalamares.job.setprogress(1.0)
    return None
