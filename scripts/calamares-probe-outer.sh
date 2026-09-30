M=/root/iso-build/isocheck/m
mount --bind /proc $M/proc 2>/dev/null
mount --bind /dev $M/dev 2>/dev/null
mount --bind /sys $M/sys 2>/dev/null
cp /etc/resolv.conf $M/etc/resolv.conf 2>/dev/null
tr -d '\r' < /mnt/f/Linxira-OS/linxira-iso-direct/scripts/calamares-probe.sh > $M/tmp/probe.sh
chmod +x $M/tmp/probe.sh
chroot $M /tmp/probe.sh
umount $M/proc $M/dev $M/sys 2>/dev/null
true
