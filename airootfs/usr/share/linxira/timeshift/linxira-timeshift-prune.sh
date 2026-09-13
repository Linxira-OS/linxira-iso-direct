#!/bin/sh
# Linxira OS — 快照配额修剪
# 只清理带固定描述的自家快照, timeshift 自身/用户手动建的快照不受影响:
#   "pacman transaction auto-snapshot"  保留最近 20 (更新前回滚点)
#   "boot snapshot"                     保留最近 3
#   "daily snapshot"                    保留最近 3
# "Linxira 初始快照" 永不清理 (恢复出厂点)。
# 按 Name (YYYY-MM-DD_HH-MM-SS) 字典序 = 时间序排序, 不依赖 --list 的排序方向。

prune() {
    keep="$1"
    marker="$2"
    names="$(timeshift --list 2>/dev/null | awk -v marker="$marker" '
        /^[[:space:]]*[0-9]+[[:space:]]*>/ && index($0, marker) {
            for (i = 1; i <= NF; i++) if ($i == ">") { print $(i + 1); break }
        }' | sort -r | tail -n +"$((keep + 1))")"
    for name in $names; do
        timeshift --delete --snapshot "$name" --yes >/dev/null 2>&1 || true
        printf '[linxira-timeshift] 已修剪旧快照: %s\n' "$name"
    done
}

command -v timeshift >/dev/null 2>&1 || exit 0
prune 20 "auto-snapshot"
prune 3 "boot snapshot"
prune 3 "daily snapshot"
exit 0
