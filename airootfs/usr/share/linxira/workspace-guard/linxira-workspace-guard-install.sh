#!/usr/bin/env bash
# 默认同盘: 守护仓库放在系统盘的 /var/lib/linxira/guard, root-only。
# 不创建分区, 不修改分区表, 不碰第二块盘/Windows/数据盘。
# 独立盘是可选的人工操作, 不在安装器里自动处理。

set -uo pipefail

CONF=/etc/linxira/workspace-guard.conf
STORE=/var/lib/linxira/guard
log() { printf '[workspace-guard] %s\n' "$1"; }

main() {
    if [[ -f $CONF ]]; then
        log "configuration already present; keeping the existing store"
    else
        install -d -m 700 /etc/linxira
        ( umask 177 && printf '[guard]\nstore = %s\nschedule = *:0/30\nkeep_scheduled = 24\nkeep_manual = 10\n' \
            "$STORE" > "$CONF" )
        chmod 600 "$CONF"
        log "same-disk store configured: ${STORE}"
    fi

    if command -v linxira-config >/dev/null 2>&1; then
        linxira-config workspace-guard adopt-installer || log "adopt-installer reported a problem"
    else
        log "linxira-config is not installed yet; store will be adopted after first boot"
    fi
    exit 0
}

main "$@"
