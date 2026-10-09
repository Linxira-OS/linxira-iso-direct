# linxira-iso-direct · Agent 开发规范

> **档位:S(治理与发布核心)**
> 本仓职责:ISO 构建仓 —— archiso live profile / Calamares 安装器配置 / 目标包清单 / ISO 构建。
> 通用条款一律见工作区总纲 `f:\Linxira-OS\AGENTS.md` 与发布规范 `linxira-os/docs/RELEASE_STANDARD.md`,
> 本文件不复述。冲突时以本文件为准。

## 职责与边界
- 归属:`owns: [live-profile, installer-configuration, target-manifests, iso-build]`,lifecycle `active`。
- 本仓只负责"构建一张 ISO"的 profile 与包装脚本;自研包的 PKGBUILD 在 `packages` 仓,**不要在此重定义包**。
- Discover 有意排除;Package Center 是目录应用安装器,Shelly 用于已审核推荐。
- 已落地的恢复层设计见 `docs/recovery-roadmap.md`(L3 恢复分区为设计稿)。

## 目录布局
- `profiledef.sh` —— archiso profile(iso_name/label、`bootmodes=(bios.syslinux uefi.grub)`、
  squashfs xz、`file_permissions` 白名单)。
- `build-direct-iso.sh` —— 构建包装脚本:校验各 `--*-package` 身份与关键路径,复制 profile 到临时目录,
  建 `linxira-local`(仅构建期)与 `linxira-offline`(嵌入 `/opt/linxira/offline-repo`)两个仓库,调 `mkarchiso`。
- 包清单:`packages.x86_64` / `target-packages.x86_64` / `target-packages-minimal.x86_64` /
  `offline-candidate-packages.x86_64` / `bootstrap_packages`。
- `pacman.conf`(构建环境 `SigLevel = Never`)、`profile-symlinks.list`(Windows 上无法可靠保存的符号链接,构建时重建)。
- `airootfs/`、`efiboot/`、`grub/`、`syslinux/` —— live 文件系统与各引导器。
- `scripts/`:`fetch-linxira-packages.sh`、`validate-calamares-config.sh`、`test-initramfs-target.sh`、
  `archive-src.sh`、`calamares-probe.sh`、`calamares-probe-outer.sh`、`wait-and-verify-r14.sh`。
- `tests/` —— Python unittest(pacstrap / bootloader / catalog / live-session 等);`docs/`。

## 构建与校验
```bash
# 从官方 [linxira] 仓库可复现地拉取自研包闭包,再构建
./scripts/fetch-linxira-packages.sh --output ./.linxira-packages
./build-direct-iso.sh --shelly-package ./.linxira-packages/shelly-*.pkg.tar.zst \
  --calamares-package ./.linxira-packages/calamares-*.pkg.tar.zst \
  --artwork-package ./.linxira-packages/linxira-artwork-*.pkg.tar.zst ... --output ./out
# 无 root 校验 Calamares 配置
bash scripts/validate-calamares-config.sh <calamares.pkg.tar.zst> <linxira-artwork.pkg.tar.zst> <rootless-arch-root>
# 测试(与 CI ci.yml 一致)
pip install pyyaml
PYTHONPATH=src python -m unittest discover -s tests -v
```
- 完整 `--*-package` 参数清单(约 18 个)见 `build-direct-iso.sh --help` 与 README;`...` 处省略的以实际脚本为准。
- 构建机要求(README「Build-machine requirements」):mirrorlist 用阿里云;`mkarchiso` 的 xorriso 需在原生参数区加 `-s 5G`。
- CI(`.github/workflows/ci.yml`)会 checkout `linxira-catalog`/`linxira-package-center`/`linxira-component-manager`/
  `linxira-config-hub`/`linxira-welcome`/`linxira-artwork` 等兄弟仓后跑测试。

## 发布与签名
- 镜像必须使用 Linxira 密钥签名的包与仓库元数据;构建期 `linxira-local` 仓库仅接受未签名开发包,且在生成
  SquashFS 前从 live pacman 配置移除。
- 产物 ISO 落到工作区 `f:\Linxira-OS\iso-release\`。
- 当前仍是**测试镜像**(r17 / 2026-09-30),未过验收门不得称正式版 —— 见发布规范 §1。

## 禁区
- 构建期不得复制同级工作树源码(README 明确:live 与 target 都经 pacman 安装 Linxira 拥有的文件)。
- 安装后目标系统必须移除 offline 仓库引用与 `/opt/linxira/offline-repo`(回收约 2.2 GB)。
- 目标/离线包闭包必须完整,否则离线安装失败(offline pacman.conf 无网络回退)。
- 不要为缩小体积牺牲离线安装能力;`linux` + `linux-lts` + 两个 `-headers` 必须常装。
- 分支名以 `git rev-parse --abbrev-ref HEAD` 为准,勿盲目推错分支。

## 关联文档
- `README.md`(含逐版本要点)、`docs/recovery-roadmap.md`、`.github/workflows/ci.yml`。
- 工作区总纲;发布规范;`packages/docs/AGENT-GUIDELINES.md`;`linxira-packages/README.md`。