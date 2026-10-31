# KDE Plasma 运行说明

本分支在 [helantianshen 的 Linux/niri 适配](https://github.com/helantianshen/codex-bailong-desktop-pet/tree/3144a6769b1590f4e2665077d907b92bb7d4c4d7)上增加 KDE 支持。KDE 最初适配的 Windows 基线为 v1.0.0，linux-preview.2 起包含 KDE 后端；早期 linux-preview.1 下载包只支持 niri。按[上游 Linux issue 的审阅建议](https://github.com/Wunsch2048/codex-bailong-desktop-pet/issues/2#issuecomment-6392931998)隔离平台代码、说明实机环境与功能边界。

当前源码同步上游 1.3.0，合并前修复和待验项目见 [HANDOFF](../HANDOFF.md)。程序需手动更新，维护页只提供兼容动画更新和 Linux 下载入口；已保存的行为开关不因升级被开启。当前公开包仍为 v1.2.1-linux-preview.4，基于上游 v1.2.1；以下 KDE 实机记录来自此前适配，新版完整交互尚未在 KDE 复验，详见 [发布说明](releases/v1.2.1-linux-preview.4.md)。

## 启动

支持 KDE Plasma 的 X11 会话，以及启用了 XWayland 的 Wayland 会话。KDE 使用 Qt 的 xcb 后端，使原有窗口定位、人物拖动、走动和面板布局能沿用全局坐标；这不是原生 Wayland layer-shell 实现。不需要安装 niri，也不需要修改 KWin 或 niri 规则。

系统需要 Python 3.12、bubblewrap（`bwrap`）、X11/XWayland、libX11、libXext 和 Qt xcb 运行库。所有命令在仓库根目录执行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-linux.txt
```

Git 不保存动画。首次运行先下载[原项目轻量素材](https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/download/v1.3.0/bailong-desktop-pet-1.3.0-animation-light.zip)，然后导入：

```sh
.venv/bin/python tools/linux_probe.py materials /绝对路径/bailong-desktop-pet-1.3.0-animation-light.zip
.venv/bin/python run_kde.py
```

导入逐项核对素材当前清单中的 45 个文件及 SHA-256。已有有效素材和配置会继续使用；源码入口会复用已验证素材。

KDE 的专用入口固定使用 KDE 后端；niri 单独使用 `run_niri.py`，不受继承的其他桌面环境标记影响。两个入口只调用共享的 Linux 生命周期和数据服务，不复制业务代码，且不能用 `--desktop` 切换成另一个桌面。原 `run_linux.py` 保留自动识别和 `--desktop kde/niri`，兼容已有启动配置。

可明确指定数据源：

```sh
.venv/bin/python run_kde.py --codex-home ~/.codex --codex-cli /绝对路径/codex
```

CLI 优先使用 `--codex-cli`，其次是 `BAILONG_CODEX`、PATH 中的 `codex`，最后尝试 `/usr/lib/chatgpt/resources/codex`。桌宠设置和统计默认写入 `${XDG_DATA_HOME:-~/.local/share}/codex-bailong/BailongEnhanced`；`--data-dir` 可以隔离测试实例。同一数据目录不能重复启动。托盘/右键菜单、Ctrl+C 或 SIGTERM 可正常退出。

## 窗口与数据

- KDE 使用原 Qt 拖动与布局路径；niri 继续使用原生 Wayland 和自己的 IPC 适配，不会加载 KDE 鼠标命中逻辑。
- 人物的鼠标命中通过 X Shape 的输入区域处理，沿用 Windows `DesktopPet.alpha_hit()` 的 `alpha >= 12` 阈值，半透明可点击边缘保留，视觉透明边缘不裁切；“鼠标穿透”可关闭整个人物的鼠标输入。niri 源码入口的对应输入区域适配见 [Linux 说明](LINUX.md#niri-透明区域点击穿透)。
- 命中区域按屏幕物理像素生成，并跟随帧、翻转、缩放及原生窗口重建更新。关闭置顶后继续尊重该设置。
- 会话、Token、额度和公告沿用真实本机来源。额度查询使用原只读 bubblewrap 沙箱；CLI 安装在 CODEX_HOME 内也能执行，不开放配置写入。
- 不把现有 Windows 更新包当成 Linux 更新包使用。

CLI 始终在其原路径执行，未被遮蔽的安装保持原样；若 CLI 位于 CODEX_HOME 内，则将其所在的顶层安装子树（如 `packages/`，包括相邻脚本、模块、资源）只读挂回原位置。安装的完整依赖须在该子树内或其他未遮蔽的系统路径；CODEX_HOME 根目录仍是私有可写运行空间，根层 config/auth 单独只读挂载。`/tmp` 内的临时安装也按完整子目录保留原路径。直接放在 CODEX_HOME 或 `/tmp` 根目录的独立启动器会明确拒绝，请将完整安装放进子目录或外部；不会把单个文件重定位到 `/tmp/bailong-codex`。

## 历史 KDE 验证记录（不含当前 1.3.0 源码）

本机环境为 Evernight Vista 44.0.1（Fedora 44 衍生）、x86_64、KDE Plasma / KWin 6.7.5、Wayland 会话、Qt xcb 经 XWayland 显示、200% 缩放；Python 3.12.15、PySide6 / Qt 6.9.2。已核对实际 X11 窗口坐标与物理尺寸，覆盖人物程序化移动、设置/聊天页、日报、分离面板、胶囊往返、人物 1.0/1.4 倍大小及关闭置顶；已观察真实额度、Token 和 IPC 健康状态。素材和 TLS 自检入口（已有日常实例时指定独立数据目录）：

```sh
.venv/bin/python run_kde.py --check-runtime --data-dir /绝对路径/独立桌宠数据目录
```

适配回归（不需动画）：

```sh
.venv/bin/python tools/check_source.py test_linux_entrypoints test_linux_launcher test_linux_backends test_linux_kde \
  test_linux_readonly test_linux_placement test_linux_surfaces test_linux_walk \
  test_linux_niri test_reset_watch test_reset_recovery test_reset_presentation test_refresh_flow
```

此前 KDE review 修复时运行了 190 项回归（当时适配组为 93 项），并完成 app/linux_app/tools 与三个 Linux 入口的编译检查。新增测试覆盖原路径相邻脚本/资源、沙箱内外完整安装目录、配置与认证不可写、运行时文件不外泄，以及全部 256 种 alpha、四档缩放和水平翻转。真实 CLI 素材/TLS/额度自检重新通过。

用户曾在初始提交用真实鼠标确认人物拖动、松手后的气泡跟随及透明区域点击正常；该人工反馈不冒充本轮阈值修复后的重复验收。本轮另重跑实际 Qt/X11 窗口与输入区域采样，未重复人工鼠标或打包验收。niri 本轮只做入口与适配单元回归，未在 niri 实机重复验收；Windows `app/` 和构建脚本未修改，也未声称完成 Windows 实机回归。

按上游 issue 的核心功能清单，本轮结果如下；“未验收”与“未实现”分别列出：

| 功能 | 复现或验收步骤 | 本轮 KDE 结果 |
| --- | --- | --- |
| 透明窗口和输入 | 启动后检查原画透明边缘，点击人物透明区域的下层窗口 | 实机显示、原生输入区及用户鼠标验收通过 |
| 拖动与松手 | 拖动人物后松手，检查气泡位置及持续动作 | 用户实机确认正常 |
| 自主移动 | 开启自由走动、关闭禁止移动，在无高优先级任务的待机边界观察 | 保留原 Qt 路径；程序化原生移动和相关回归通过，随机自主触发未专项实机验收 |
| Codex 状态、额度、Token | 本机登录 Codex，执行任务，检查连接健康及真实数据 | 实际 IPC、额度、Token 和公告接通；完整完成/等待/中断/压缩转换未逐项实机验收 |
| 完成提醒与确认 | Codex 任务结束后检查未读常驻、点击确认及真实已读清除 | 既有去重/已读回归通过，完整用户流程和系统通知未专项实机验收 |
| 会话跳转 | 点击会话名进入对应 Codex 聊天 | 当前源码已接入桌面 codex:// 协议处理器；niri 人工通过，KDE 尚待实机验收；preview.2 包不含此功能 |
| 视频全屏让位 | 真实浏览器/播放器进入全屏，核对未读优先和手动置顶设置 | Linux 未接入 Windows 视频检测/让位服务；未实现，不把保留的设置开关视为支持 |
| 数据存储 | 重启或切换入口，检查设置；只读沙箱内尝试写入合成配置和运行时文件 | XDG 独立目录、单实例锁、状态复用和配置只读验证通过；提交与测试夹具不含真实数据 |
| 更新、安装管理 | 检查维护页与 Linux 程序分发方式 | Windows 安装/回退和应用内更新未适配；源码按上述步骤运行，不使用 Windows 更新包 |

未覆盖实际多屏热插拔、其他系统缩放或长期稳定性。声音、聊天密钥等原 Linux 预览版边界仍然存在；自启动现已接入 Linux systemd，见 LINUX.md。聊天页面可打开，不代表联网聊天及密钥保存已通过验收。KDE 便携包/AppImage 本轮没有构建或安装验收；原 Linux 构建步骤保留在 [LINUX_PACKAGE.md](LINUX_PACKAGE.md)，不能沿用旧 niri 包结论。
