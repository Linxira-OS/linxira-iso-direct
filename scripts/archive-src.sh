#!/usr/bin/env bash
# Archive the ISO build source tree with git archive.
#
# This is THE canonical way to produce a source tarball for the builder:
#   scripts/archive-src.sh <output.tar.gz>
#
# git archive packs exactly the tracked files (including dot-directories
# such as airootfs/etc/skel/.config), so a tarball produced here is
# byte-identical on any machine and any checkout of the same commit.
# Do NOT replace this with an ad-hoc find/walk/tar loop: a naive
# `os.walk` + `startswith('.')` filter silently drops hidden dirs and
# breaks reproducible builds (this exact bug shipped r13 without the
# dark Plasma defaults).
set -euo pipefail

output="${1:-build-src.tar.gz}"
commit="${2:-HEAD}"

git archive --format=tar.gz --prefix="linxira-iso-direct/" -o "$output" "$commit"

# Sanity: the archive must contain the skel dark-theme defaults.
missing="$(tar -tzf "$output" 2>/dev/null | grep -c 'skel/.config/kdeglobals' || true)"
if [ "$missing" -lt 1 ]; then
    printf 'ERROR: archive is missing airootfs/etc/skel/.config/kdeglobals\n' >&2
    exit 1
fi

printf 'OK: %s (from %s)\n' "$output" "$commit"
