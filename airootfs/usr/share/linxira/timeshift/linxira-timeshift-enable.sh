#!/bin/sh
# Linxira OS — Timeshift + GRUB 快照菜单一键启用
# 安装期由 calamares shellprocess@linxira-timeshift 调用;
# 运行期由 linxira-config timeshift enable 调用。幂等: 重复执行安全。

DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK_NAME="linxira-timeshift-autosnap.hook"

log()  { printf '[linxira-timeshift] %s\n' "$*"; }

# 快照位置不能留空: Timeshift 不会替用户选盘, 空 UUID 只会让创建静默失败。
# 从目标系统 fstab 取根 btrfs UUID; 加密根再从 crypttab 取外层 LUKS UUID。
bind_timeshift_location() {
    conf=/etc/timeshift/timeshift.json
    [ -f "$conf" ] && [ -f /etc/fstab ] || return 0

    root_spec=$(awk '$2 == "/" { print $1; exit }' /etc/fstab)
    root_type=$(awk '$2 == "/" { print $3; exit }' /etc/fstab)
    [ "$root_type" = "btrfs" ] || return 0

    case "$root_spec" in
        UUID=*) root_uuid=${root_spec#UUID=} ;;
        /dev/*) root_uuid=$(blkid -s UUID -o value "$root_spec" 2>/dev/null) ;;
        *) root_uuid="" ;;
    esac
    [ -n "$root_uuid" ] || return 0

    parent_uuid=""
    if [ -f /etc/crypttab ]; then
        parent_uuid=$(awk '$3 == "luks" && $2 ~ /^UUID=/ { print substr($2, 6); exit }' /etc/crypttab)
    fi

    sed -i 's|"backup_device_uuid"[[:space:]]*:[[:space:]]*"[^"]*"|"backup_device_uuid": "'"$root_uuid"'"|' "$conf"
    sed -i 's|"parent_device_uuid"[[:space:]]*:[[:space:]]*"[^"]*"|"parent_device_uuid": "'"$parent_uuid"'"|' "$conf"
    log "快照位置已绑定: $root_uuid${parent_uuid:+ (LUKS $parent_uuid)}"
}

# 1. 应用默认配置 (btrfs 模式, 每日 3 份 + 启动 3 份)
if [ -f "$DIR/timeshift.json" ]; then
    mkdir -p /etc/timeshift
    cp -f "$DIR/timeshift.json" /etc/timeshift/timeshift.json
    bind_timeshift_location
    log "timeshift 配置已应用 (btrfs 模式, 每日 3 + 启动 3)"
else
    log "警告: 未找到配置模板 $DIR/timeshift.json, 保留现有 timeshift 配置"
fi

# 2. pacman 事务前自动快照钩子
#    钩子内部自带守卫: 未启用时静默跳过, 快照失败不阻塞 pacman 事务
if [ -f "$DIR/$HOOK_NAME" ]; then
    mkdir -p /etc/pacman.d/hooks
    cp -f "$DIR/$HOOK_NAME" "/etc/pacman.d/hooks/$HOOK_NAME"
    log "更新前自动快照钩子已安装 (/etc/pacman.d/hooks)"
fi

# 3. grub-btrfsd 使用 timeshift 自动探测 (timeshift >= 22.06 快照目录含随机 PID)
if [ -x /usr/bin/grub-btrfsd ] && [ -f /usr/lib/systemd/system/grub-btrfsd.service ]; then
    mkdir -p /etc/systemd/system/grub-btrfsd.service.d
    {
        printf '%s\n' '[Service]'
        printf '%s\n' 'ExecStart='
        printf '%s\n' 'ExecStart=/usr/bin/grub-btrfsd --syslog --timeshift-auto'
    } > /etc/systemd/system/grub-btrfsd.service.d/linxira-timeshift.conf
    systemctl daemon-reload 2>/dev/null || true
    systemctl enable grub-btrfsd.service 2>/dev/null || true
    if [ "$(ps -p 1 -o comm= 2>/dev/null)" = "systemd" ]; then
        systemctl start grub-btrfsd.service 2>/dev/null || true
    fi
    log "grub-btrfsd 已启用 (timeshift 自动探测)"
fi

# 4. 引导只读快照所需 initramfs 钩子 (新增时重建 initramfs; 安装期已由 linxiraboot 处理)
if [ -f /usr/lib/initcpio/hooks/grub-btrfs-overlayfs ] && [ -f /etc/mkinitcpio.conf ]; then
    if ! grep -qE '^HOOKS=\(.*grub-btrfs-overlayfs' /etc/mkinitcpio.conf; then
        sed -i 's/^HOOKS=(\(.*\))/HOOKS=(\1 grub-btrfs-overlayfs)/' /etc/mkinitcpio.conf
        mkinitcpio -P 2>/dev/null || true
        log "grub-btrfs-overlayfs 已加入 HOOKS, initramfs 已重建"
    fi
fi

# 5. 初始快照 (btrfs CoW 秒级; 失败必须显式记录, 不能假装启用)
initial_failed=0
if command -v timeshift >/dev/null 2>&1; then
    existing="$(timeshift --list 2>/dev/null | grep -cE '^[[:space:]]*[0-9]+[[:space:]]+>' || true)"
    if [ "${existing:-0}" != "0" ]; then
        log "已存在快照 ($existing 个), 跳过初始快照"
    else
        if timeshift --create --comments "Linxira 初始快照" --tags O >/dev/null 2>&1 \
            && timeshift --list 2>/dev/null | grep -q "Linxira 初始快照"; then
            log "初始快照已创建"
        else
            log "错误: 初始快照创建失败, 快照功能未启用 (检查位置: timeshift --list)"
            initial_failed=1
        fi
    fi
fi

# 6. systemd 双保险定时器 (不依赖 timeshift 自建 cron; 当日已有同类快照则跳过)
if [ -d /etc/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
    cat > /etc/systemd/system/linxira-timeshift-boot.service <<'EOF'
[Unit]
Description=Linxira OS boot snapshot (Timeshift B)

[Service]
Type=oneshot
ExecStart=/bin/sh -c '/bin/sh /usr/share/linxira/timeshift/linxira-timeshift-prune.sh || true; l=$$(/usr/bin/timeshift --list 2>/dev/null); d=$$(date +%F); echo "$$l" | grep -q "$${d}.*boot snapshot" || /usr/bin/timeshift --create --comments "boot snapshot" --tags B; /bin/sh /usr/share/linxira/timeshift/linxira-timeshift-prune.sh || true'
EOF
    cat > /etc/systemd/system/linxira-timeshift-boot.timer <<'EOF'
[Unit]
Description=Linxira OS boot snapshot timer

[Timer]
OnBootSec=3min
Unit=linxira-timeshift-boot.service

[Install]
WantedBy=timers.target
EOF
    cat > /etc/systemd/system/linxira-timeshift-daily.service <<'EOF'
[Unit]
Description=Linxira OS daily snapshot (Timeshift D)

[Service]
Type=oneshot
ExecStart=/bin/sh -c '/bin/sh /usr/share/linxira/timeshift/linxira-timeshift-prune.sh || true; l=$$(/usr/bin/timeshift --list 2>/dev/null); d=$$(date +%F); echo "$$l" | grep -q "$${d}.*daily snapshot" || /usr/bin/timeshift --create --comments "daily snapshot" --tags D; /bin/sh /usr/share/linxira/timeshift/linxira-timeshift-prune.sh || true'
EOF
    cat > /etc/systemd/system/linxira-timeshift-daily.timer <<'EOF'
[Unit]
Description=Linxira OS daily snapshot timer

[Timer]
OnCalendar=daily
Persistent=true
Unit=linxira-timeshift-daily.service

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload 2>/dev/null || true
    systemctl enable linxira-timeshift-boot.timer linxira-timeshift-daily.timer 2>/dev/null || true
    if [ "$(ps -p 1 -o comm= 2>/dev/null)" = "systemd" ]; then
        systemctl start linxira-timeshift-boot.timer linxira-timeshift-daily.timer 2>/dev/null || true
    fi
    log "systemd 定时器已启用 (开机 3min + 每日, 双保险之一)"
fi

# 7. timeshift 自建 cron (双保险之二): 跑一次让 app 按 json 同步 cron 条目, 失败无碍
timeshift --list >/dev/null 2>&1 || true

# 8. 重生成 grub.cfg, 快照子菜单 (41_snapshots-btrfs, 由 grub-btrfs 包提供)
if [ -x /usr/bin/grub-mkconfig ] && [ -d /boot/grub ]; then
    grub-mkconfig -o /boot/grub/grub.cfg >/dev/null 2>&1 \
        && log "GRUB 快照菜单已生成" \
        || log "警告: grub-mkconfig 失败, 快照菜单将由 grub-btrfsd 首次触发时生成"
fi

# 9. 配额修剪 (O 保留 20, B/D 保留 3; 初始快照永不清理)
if [ -x "$DIR/linxira-timeshift-prune.sh" ]; then
    sh "$DIR/linxira-timeshift-prune.sh" || true
fi

exit "$initial_failed"
