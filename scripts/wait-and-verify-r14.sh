#!/bin/bash
# r14 (WSL 构建) 完成等待 + 盘内验证 + 哈希
set -e
for i in $(seq 1 60); do
    pgrep -f build-direct-iso >/dev/null || break
    sleep 30
done
if pgrep -f build-direct-iso >/dev/null; then
    echo "STILL RUNNING after 30min"
    exit 1
fi
echo "=== INFO Done 次数 ==="
grep -c "INFO: Done" ~/iso-build/build-wsl-iso.log
echo "=== 日志尾 ==="
tail -3 ~/iso-build/build-wsl-iso.log | cut -c1-160
ls -lh ~/iso-build/linxira-iso-direct/out/
echo "=== 盘内验证 ==="
rm -rf /tmp/isocheck && mkdir -p /tmp/isocheck
xorriso -osirrox on -indev ~/iso-build/linxira-iso-direct/out/linxira-2026.09.29-x86_64.iso \
    -extract /linxira/x86_64/airootfs.sfs /tmp/isocheck/r14.sfs 2>&1 | tail -1
mkdir -p /tmp/isocheck/m
if mount /tmp/isocheck/r14.sfs /tmp/isocheck/m 2>/dev/null; then
    ls -l /tmp/isocheck/m/usr/local/bin/linxira-install-cleanup
    grep -E "dontChroot|command:" /tmp/isocheck/m/etc/calamares/modules/shellprocess_linxira-cleanup.conf
    grep initialPartitioningChoice /tmp/isocheck/m/etc/calamares/modules/partition.conf
    umount /tmp/isocheck/m
else
    echo "(squashfs 直挂不可用, 跳过模式检查 — unsquashfs 兜底)"
    unsquashfs -d /tmp/isocheck/m /tmp/isocheck/r14.sfs >/dev/null 2>&1
    ls -l /tmp/isocheck/m/usr/local/bin/linxira-install-cleanup
    grep -E "dontChroot|command:" /tmp/isocheck/m/etc/calamares/modules/shellprocess_linxira-cleanup.conf
    grep initialPartitioningChoice /tmp/isocheck/m/etc/calamares/modules/partition.conf
fi
echo "=== sha256 ==="
cd ~/iso-build/linxira-iso-direct/out && sha256sum linxira-2026.09.29-x86_64.iso
