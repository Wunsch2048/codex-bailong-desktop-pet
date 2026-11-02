# 白龙桌宠 Linux 便携版

本文对应 **v1.4.2-linux-preview.5**，程序基于上游 1.4.2，包含 KDE 动画换帧命中区域修复和 niri 卡片绘制、拖动定位修复。程序内显示的版本为 `1.4.2`；`linux-preview.5` 标识第五次 Linux 预览交付。功能、验证范围与限制见[本版说明](https://github.com/helantianshen/codex-bailong-desktop-pet/blob/main/docs/releases/v1.4.2-linux-preview.5.md)。

包内提供 niri 原生 Wayland 与 KDE Plasma X11/XWayland 后端，启动时自动识别，也可指定 `--desktop niri` 或 `--desktop kde`。KDE 维护者已完成合并修复后的实机测试；本次新包在 CachyOS/niri 验证，维护者反馈不等同于新包的 KDE 安装验收。KDE 的环境要求见 [KDE 说明](https://github.com/helantianshen/codex-bailong-desktop-pet/blob/main/docs/KDE.md)。

本版在 CachyOS x86_64 本机构建并验收，面向已更新的 CachyOS/Arch 系统。包内运行库要求 **glibc 2.44 或更高版本**；可用 `getconf GNU_LIBC_VERSION` 检查宿主版本。包含 Python 3.12、Qt 与完整轻量素材（45 个文件、35 个动作，含独立走路动画），不需要激活虚拟环境或安装系统 Python 包。其他发行版仍须验证运行库兼容性。

便携包解压后执行 `./AppRun`；AppImage 先 `chmod +x 文件名.AppImage`，再执行它。也可使用 `--appimage-extract-and-run` 绕过 FUSE 挂载，但会产生临时解压开销。

宿主需要对应桌面、bubblewrap（bwrap）和本机 Codex。CLI 自动从 BAILONG_CODEX、PATH 或已知安装位置查找；其他安装位置通过 `--codex-cli /绝对路径/codex` 指定。支持 `--codex-home` 与 `--data-dir`，示例：

```sh
./AppRun --codex-cli /usr/lib/chatgpt/resources/codex
```

默认桌宠设置位于 `${XDG_DATA_HOME:-~/.local/share}/codex-bailong/BailongEnhanced`。两种包共用此位置，更新程序不覆盖设置，不包含用户会话或凭据。素材位于程序包内，程序包可只读；不要把 `--data-dir` 指向程序包或 Codex 目录。

同一数据目录不允许同时运行源码版、便携版和 AppImage。切换前从桌宠菜单退出旧实例；重复启动只会报错，不会关闭旧实例。

niri 窗口规则需放在稳定位置。将包内 `configs/bailong-linux.kdl` 复制至 `~/.config/niri/bailong-linux.kdl`，在实际加载的 niri 配置中添加该文件的绝对路径 include。已有相同规则则无需重复添加。AppImage 用户可通过 `--appimage-extract` 取得规则文件。不要 include AppImage 临时挂载目录。规则使用本机 niri 的 background-effect 扩展，其他版本需先验证兼容性；本包不会自动修改全局主题或 niri 配置。

读取真实 Codex 数据；额度查询通过 bubblewrap 只读访问原配置与认证文件。不写入 Codex 配置。设置中的“开机启动”和“随 Codex 启动”分别登记独立的 systemd 用户服务，互不依赖。启用前请把 AppImage 或便携目录放在固定位置；AppImage 登记外部文件路径，移动后需重新关闭并开启开关。已接入随 Codex 关闭与会话跳转，跳转需 xdg-utils 和 codex:// 协议处理器。

Linux 程序通过手动替换 AppImage 或便携目录更新，保留用户数据目录。维护页只提供 Linux 下载入口和兼容动画更新，动画继续校验最低程序版本与 SHA-256；Windows 程序安装、目录迁移和历史版本清理不可用。升级保留随机动作、回复摘要、自主走动、画质及人物可见性等已有选择。聊天密钥安全保存和完整联网聊天仍未适配，声音保持关闭。

素材来源与使用边界见 NOTICE.md 和 app/licenses；字体授权随 app/fonts 提供。

## 构建

构建环境独立于开发 `.venv`，所有依赖只装入仓库忽略目录。先检查 `command -v ldd`，确保打包器使用宿主系统工具；自定义工具链中的 `ldd` 可能漏识别 Qt 运行库。如本机工具链覆盖了系统工具，可仅为构建命令设置 `PATH=/usr/bin:/bin`，不修改全局 PATH。本版公开交付沿用本机构建与上传流程；下方 CI 构建用于独立验证，其产物不等同于本版 Release 附件。

```sh
uv venv --python 3.12 work/linux-build/venv
uv pip install --python work/linux-build/venv/bin/python -r tools/requirements-linux-build.txt
work/linux-build/venv/bin/python tools/build_linux.py \
  --destination work/linux-build/build-new \
  --materials /绝对路径/已校验的轻量素材目录
```

素材目录直接包含 `素材清单.json`；构建前按 `app/material_catalog.json` 核对全部 SHA256。构建工具及 AppImage runtime 的下载地址和校验值固定在 `tools/appimage-tools.lock.json`。下载并验证后传入：

```sh
work/linux-build/venv/bin/python tools/package_linux.py \
  --bundle work/linux-build/build-new/dist/bailong-linux \
  --destination work/linux-build/packages-new \
  --appimagetool /绝对路径/appimagetool-x86_64.AppImage \
  --runtime /绝对路径/runtime-x86_64 \
  --name Bailong-1.4.2-linux-preview.5-x86_64
```

两个构建命令均拒绝覆盖已有目标目录。打包过程不会安装到系统或调用 Windows 构建脚本。

运行时自检使用 `./AppRun --check-runtime` 或 `./文件名.AppImage --check-runtime`，验证完整素材、TLS 上下文以及真实只读额度查询，然后退出。自检也持有状态目录锁；已有日常实例时请指定独立 `--data-dir`，不要与日常实例共享写入。

## GitHub Actions

`Source checks` 在 push、pull request 和手动触发时分别运行 Windows 与 Linux 检查。Linux 使用 Ubuntu 22.04、Python 3.12 和 offscreen Qt，执行 Linux 适配及公告/刷新测试；Windows job 保持独立。

在 Actions 中选择 `Build Linux packages` → `Run workflow`，选定分支后手动构建。工作流按素材清单下载并逐文件验证轻量素材，按锁文件验证 AppImage 工具，然后生成便携 tar.zst、AppImage 和 SHA256SUMS.txt。文件名包含源码提交的前 12 位，成功后从该次运行的 Artifacts 下载，保留 7 天；下载 AppImage 后需赋予执行权限。此工作流只保存 CI 产物，不创建或覆盖 Release。

CI 会验证归档载荷，在源码目录外执行两种包的 `--help`，并用 Xvfb 和空 Codex 目录检查冻结程序的 xcb 窗口启动与正常退出。Ubuntu runner 没有真实 niri 会话与 Codex 账户，这些检查不能替代拖动、走动、面板定位及真实数据接入验收。CI 的 Ubuntu 22.04 产物还需在目标发行版检查外部程序启动及证书路径；不能只凭构建成功就作为跨发行版交付。
