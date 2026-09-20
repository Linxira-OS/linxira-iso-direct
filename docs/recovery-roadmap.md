# Recovery 分区 · 设计路线（Pop!_OS 式）

状态：设计稿 v1（2026-09-20）。第一阶段（无需重分区的恢复层）已随 linxiraboot 落地；
分区级恢复按本设计在安装器分区模块改造时实现。

## 分层恢复体系

| 层 | 载体 | 状态 |
|---|---|---|
| L1 可引导快照 | timeshift(btrfs) + grub-btrfsd(--timeshift-auto) → GRUB 快照菜单 | ✅ 已落地 |
| L2 救援控制台 | GRUB "Linxira OS Rescue" 条目：同 root、multi-user 文本模式 | ✅ 已落地 |
| L3 恢复分区 | 独立分区装载最小修复环境（本设计） | 设计完成, 实现排期 |
| L4 Refresh Install | 保留 /home 的原地重装 | 远期 |

## L1 可引导快照（已落地）

- timeshift(btrfs) 快照经 grub-btrfsd 自动注册进 GRUB 快照子菜单；
- 升级前自动快照（pacman 钩子）+ 每日计划快照；
- 坏了直接从任意快照引导回滚。

## L2 救援控制台（已落地）

- GRUB 平铺菜单中的 "Linxira OS Rescue (text console)" 条目；
- 以 `systemd.unit=multi-user.target` 引导同一根文件系统：纯文本控制台，
  跳过图形栈/显示管理器 —— 图形会话损坏、驱动翻车、磁盘满等场景的修复入口；
- UUID 由安装期写入 /etc/grub.d/41_linxira-rescue（linxiraboot 生成），grub-mkconfig 自动携带；
- 修复工具：recovery-diagnostics（诊断/计划）+ 手工 pacman/timeshift。

## L3 恢复分区（实现排期）

Pop!_OS 的恢复分区等价物 —— **磁盘上的迷你安装器**：

### 分区布局
- 在 ESP 之后划 6GB `linxira-recovery` 分区（ext4）；
- calamares partition 模块当前不支持声明式额外分区 —— 需要自定义 partition
  模块扩展（layout 后处理）或在 users 阶段前的 shellprocess 以 sfdisk 脚本追加；
- 布局变体需覆盖 GPT/MBR、已有 Windows 双系统（ESP 复用）等场景。

### 内容与更新
- 内容 = 安装介质的活动三件套：`vmlinuz-linux`、`initramfs-linux.img`、
  `airootfs.sfs`（安装完成时从 ISO 复制，或首次联网后从 [linxira] 拉取刷新）；
- 随系统大版本更新由 linxira-update 触发刷新（可配置关闭）。

### 引导与入口
- GRUB 条目（linxiraboot 生成）：loopback 不适用（分区非镜像）——直接
  `linux (hd?,gpt?)/boot/vmlinuz-linux archisobasedir=... archiso_loop_mnt` 风格
  参数指向恢复分区，启动即进入完整安装器 live 环境；
- live 环境内置 "修复安装 / 保留 /home 重装 / 快照回滚" 引导页（Welcome 分支）。

### 收益
- 无 U 盘修复/重装/救援；
- Refresh Install 的物理载体（L4 的前置）。

### 风险
- 分区布局改动影响既有安装与双系统场景 —— 需要独立的安装器分区评审；
- 恢复分区内容与系统版本错位 —— 由 update 刷新链兜底。

## 验收场景（L3 实现后）

1. 全新安装 → 分区表出现 linxira-recovery（≥6GB）→ GRUB 出现恢复条目；
2. 引导恢复条目 → 进入 live 安装器（无需介质）；
3. 故意破坏图形栈 → 救援控制台修复 → 回到桌面；
4. 升级翻车 → GRUB 快照菜单回滚至上一个快照。
