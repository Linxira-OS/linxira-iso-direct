#!/usr/bin/env bash
set -euo pipefail

sed -i '/^\[linxira-local\]$/,/^$/d' /etc/pacman.conf
plymouth-set-default-theme linxira
mkinitcpio -p linux

# ---- 发布证据: 第三方声明 + 源码提供(2026-10-24)----
# GPL/AGPL 二进制随镜像分发 => 三件套必须存在(见 docs/RELEASE_STANDARD.md)
python3 /usr/local/bin/linxira-generate-notices.py --root / \
  --version "$(cat /etc/linxira-release 2>/dev/null || true)"
for evidence in THIRD-PARTY-NOTICES.md SOURCE-OFFER license-manifest.json; do
  test -s "/usr/share/doc/linxira/$evidence" \
    || { echo "错误: 缺少发布证据 $evidence" >&2; exit 1; }
done
