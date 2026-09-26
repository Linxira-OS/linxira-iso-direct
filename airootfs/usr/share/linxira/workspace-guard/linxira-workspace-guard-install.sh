#!/usr/bin/env bash
# 装机阶段建立工作区守护: 在非系统盘上建 ext4 分区 + 写配置 + 交给 adopt-installer。
#
# 为什么不用 partition 模块: 当前 calamares 的 partition 模块只读它认识的键,
# 自定义段会被静默忽略。装机时没有 TTY, 也无法让用户选盘, 所以这里按固定策略执行:
# 第一块"不是系统盘且剩余空间够"的整盘, 64 GiB, 少于 32 GiB 就不建。
#
# 任何一步失败都不阻塞安装 —— 守护是加分项, 不是装机的前提。
set -uo pipefail

STORE_UUID_KEY=store_uuid
GUARD_LABEL=linxira-guard
GUARD_SIZE_GIB=64
MIN_SIZE_GIB=32
MIN_FREE_GIB=40
CONF=/etc/linxira/workspace-guard.conf
STORE_PATH=/var/lib/linxira/guard
log() { printf '[workspace-guard] %s\n' "$1"; }
skip() { log "SKIP: $1"; exit 0; }

# 目标系统根所在的那块盘, 不能在上面追加分区。
root_source=$(findmnt -n -o SOURCE / 2>/dev/null || true)
[[ -n "$root_source" ]] || skip "cannot read the installed root source"
root_disk=$(lsblk -nrpo PKNAME "$root_source" 2>/dev/null | head -1)
[[ -n "$root_disk" ]] && root_disk="/dev/$root_disk" || root_disk=""

pick_disk() {
    local name type size
    while read -r name type size; do
        [[ $type == disk ]] || continue
        [[ -n "$root_disk" && "/dev/$name" == "$root_disk" ]] && continue
        [[ $size =~ ^[0-9]+$ ]] || continue
        (( size / 1024 / 1024 / 1024 >= MIN_FREE_GIB )) || continue
        printf '/dev/%s\n' "$name"
        return 0
    done < <(lsblk -drno NAME,TYPE,SIZE 2>/dev/null)
    return 1
}

write_config() {
    local uuid=$1
    install -d -m 700 /etc/linxira
    ( umask 177 && printf '[guard]\n%s = %s\nstore = %s\nschedule = *:0/30\nkeep_scheduled = 24\nkeep_manual = 10\n' \
        "$STORE_UUID_KEY" "$uuid" "$STORE_PATH" > "$CONF" )
    chmod 600 "$CONF"
}

main() {
    if [[ -f $CONF ]]; then
        log "configuration already present; keeping the existing store"
    else
        local disk
        if ! disk=$(pick_disk); then
            skip "no secondary disk with ${MIN_FREE_GIB} GiB free; workspace guard stays off"
        fi
        log "creating a ${GUARD_SIZE_GIB} GiB ext4 partition on ${disk}"
        local partitions sector_size size_mib
        partitions=$(lsblk -nrpo NAME "$disk" 2>/dev/null | tail -n +2 | wc -l)
        sector_size=$(blockdev --getss "$disk" 2>/dev/null || echo 512)
        size_mib=$((GUARD_SIZE_GIB * 1024))
        if ! sfdisk --no-reread --append --force "$disk" <<< ",${size_mib}MiB,L"; then
            skip "sfdisk refused to extend ${disk}; workspace guard stays off"
        fi
        partprobe "$disk" 2>/dev/null || partx -u "$disk" >/dev/null 2>&1 || true
        udevadm settle >/dev/null 2>&1 || true
        local part_number=$((partitions + 1)) created
        created=$(partx --show --partno "$part_number" "$disk" 2>/dev/null | tail -1)
        [[ -n $created ]] || created="${disk}${part_number}"
        [[ -b $created ]] || skip "the new partition ${created} did not appear; workspace guard stays off"
        log "formatting ${created} (sector size ${sector_size})"
        if ! mkfs.ext4 -q -L "$GUARD_LABEL" "$created"; then
            skip "mkfs.ext4 failed on ${created}; the partition is left untouched for inspection"
        fi
        # 守护盘不写进 fstab: 开机不挂载, 没有 root 就够不着快照。
        if grep -qF "$created" /etc/fstab 2>/dev/null; then
            cp /etc/fstab /etc/fstab.linxira-guard.bak
            sed -i "\\|[[:space:]]${created}[[:space:]]|d" /etc/fstab
            log "removed the guard entry from /etc/fstab (backup: /etc/fstab.linxira-guard.bak)"
        fi
        local uuid
        uuid=$(blkid -s UUID -o value "$created" 2>/dev/null || true)
        [[ -n $uuid ]] || skip "could not read the UUID of ${created}; workspace guard stays off"
        write_config "$uuid"
        log "wrote ${CONF} (0600, root) for ${created} (${uuid})"
    fi

    if command -v linxira-config >/dev/null 2>&1; then
        linxira-config workspace-guard adopt-installer || log "adopt-installer reported a problem; guard may be off"
    else
        log "linxira-config is not installed yet; run 'linxira-config workspace-guard enable' after first boot"
    fi
    exit 0
}

main "$@"
