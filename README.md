# Codex&GPT桌宠数据中心 | 你桌面的龙娘小助手

![文章海报](docs/media/cover.png)

一只陪你使用 Codex 的白龙桌宠：在桌面查看任务状态、接收完成提醒、追踪账户额度和 Token 用量。基于 [jingh12312-rgb/bailong-desktop-pet](https://github.com/jingh12312-rgb/bailong-desktop-pet) 持续改造，源码已合并上游 Windows **v1.2.1**，本 fork 提供 **Linux/niri、KDE 预览版 v1.2.1-linux-preview.4**。

**[Linux 下载](https://github.com/helantianshen/codex-bailong-desktop-pet/releases/tag/v1.2.1-linux-preview.4)** · [Windows 上游下载](https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/latest) · [快速部署](docs/快速部署说明.txt) · [全部新增功能](docs/新增功能说明.txt) · [开发说明](docs/DEVELOPMENT.md) · [迭代历史](docs/迭代历史.txt)

## Linux / niri / KDE

本分支在 Linux/niri 适配基础上增加 **KDE Plasma X11 / XWayland 源码运行支持**。不同桌面使用独立入口，共享原界面和数据逻辑：

| 环境 | 源码入口 | 窗口后端 |
| --- | --- | --- |
| Windows | `python app/enhanced.py` | 原 Windows 入口 |
| niri | `.venv/bin/python run_niri.py` | 原生 Wayland + niri IPC |
| KDE Plasma | `.venv/bin/python run_kde.py` | X11 / XWayland |

原 `run_linux.py` 保留为自动识别桌面的兼容入口。准备依赖、素材和查看验证边界见 [KDE 运行说明](docs/KDE.md)及 [Linux 启动说明](docs/LINUX.md)。当前预览包包含 niri 与 KDE 后端。Linux 适配仍位于独立入口，`app/` 与 Windows 构建脚本沿用上游实现。

本 fork 的 Linux 预览版面向 **CachyOS/Arch x86_64 + niri 原生 Wayland**，不宣称兼容所有 Linux 发行版。Windows 入口、组件样式及原动画素材保持不变。

| 下载格式 | 启动方式 |
| --- | --- |
| [AppImage](https://github.com/helantianshen/codex-bailong-desktop-pet/releases/download/v1.2.1-linux-preview.4/Bailong-1.2.1-linux-preview.4-x86_64.AppImage) | 赋予执行权限后运行 |
| [便携包 tar.zst](https://github.com/helantianshen/codex-bailong-desktop-pet/releases/download/v1.2.1-linux-preview.4/Bailong-1.2.1-linux-preview.4-x86_64.tar.zst) | 解压后运行目录内的 `AppRun` |
| [SHA256 校验值](https://github.com/helantianshen/codex-bailong-desktop-pet/releases/download/v1.2.1-linux-preview.4/SHA256SUMS.txt) | 在下载目录执行 `sha256sum -c SHA256SUMS.txt`，需要对应文件都已下载 |

两种包均包含 Python 3.12、Qt 及轻量人物素材，每个约 680 MiB，不需要安装 Python 包。宿主需要 bubblewrap（`bwrap`）和本机 Codex；仅 niri 后端需要 niri，KDE 后端需要 X11/XWayland。

```sh
chmod +x Bailong-1.2.1-linux-preview.4-x86_64.AppImage
./Bailong-1.2.1-linux-preview.4-x86_64.AppImage
```

当前包会先检查 `BAILONG_CODEX` 和 PATH，也可通过 `--codex-cli /绝对路径/codex` 指定。首次配置 niri 时，按[使用说明](docs/LINUX_PACKAGE.md)将包内窗口规则复制到稳定配置路径并 include；规则包含本机 niri 的 `background-effect` 扩展，其他构建需验证兼容性。KDE 不使用这些规则。

默认设置和统计索引保存在 `~/.local/share/codex-bailong/BailongEnhanced`（支持 `XDG_DATA_HOME`）。源码版、便携版和 AppImage 共用该位置，切换前退出旧实例；更新程序不覆盖位置与偏好。额度查询只读访问 Codex 配置，包内不包含账户、会话、个人设置或凭据。

已接入真实额度、Token、任务 IPC 和重置公告；已适配 niri 拖动、自由走动、显示器与位置记忆、分离气泡、设置/聊天面板定位、Token 日报、展开收起和人物缩放。本机验证覆盖脱离源码启动、真实数据、跨格式位置恢复及正常退出。

**当前边界**：当前预览版已恢复随机动作和 Codex 回复摘要，首次升级开启一次，之后保留用户开关；声音仍由入口关闭。声音播放、聊天密钥保存、甩出惯性及 Windows 更新安装流程尚未适配，部分界面入口仍保留，请勿将其视为 Linux 可用功能。分离面板等复杂交互已进行初步人工验收，不等于全套跨屏、高 DPI 或长期稳定性验收；置顶及系统通知仍需跨桌面验收。niri/KDE 人物输入区域已采用 `alpha >= 12`，“开机启动”和“随 Codex 启动”已接入独立 systemd 用户服务，使用步骤见 [Linux 说明](docs/LINUX.md#登录图形桌面后自启动)。两个启动开关相互独立。不要使用 Windows 更新包更新 Linux 版。

**本版新增**：已接入上游 v1.2.1 界面，补齐 niri 拖动期间气泡跟随、设置页边缘避让，并修复托盘首次展开菜单不完整。已接入“随 Codex 关闭”和会话跳转。退出沿用连续三次确认规则；会话链接交由已注册的 `codex://` 协议处理器打开，需 `xdg-utils`。点击任务名不提前清除未读提醒，详见 [Linux 说明](docs/LINUX.md#随-codex-关闭与会话跳转)。完整的已实现功能、限制和未适配项目见 [本版发布说明](docs/releases/v1.2.1-linux-preview.4.md)。

源码已同步上游 **v1.2.1** 的卡片过渡、悬停提示、额度变化阈值与额度对比、显示缩放恢复等改进。Linux 补接托盘额度环和 niri 提示窗口定位；托盘文字由桌面原生提示显示，外观随桌面主题。Windows 的 WSL 来源、程序迁移和更新安装流程不适用于 Linux。上述改动已进入当前预览包，具体范围见 [本次适配说明](docs/LINUX.md)。

开发启动：创建独立 Python 3.12 虚拟环境并安装 `requirements-linux.txt`，然后执行 `.venv/bin/python run_linux.py`。素材准备及 PyCharm 配置见 [Linux 启动说明](docs/LINUX.md)，打包方法见[使用与构建说明](docs/LINUX_PACKAGE.md)，本次发布范围见[Linux 预览版说明](docs/releases/v1.2.1-linux-preview.4.md)。

## 上游 Windows 更新记录

以下安装器与补丁仅适用于 Windows。Linux 的下载版本及适配范围见上方说明。macOS 预览版见 [Kki1ds 社区仓库](https://github.com/Kki1ds/codex-bailong-desktop-pet)。

### v1.2.1 程序补丁

- 改善远控或屏幕缩放恢复后的角色清晰度，避免放大后仍使用低分辨率动画帧。
- 顶栏按钮和托盘额度使用自定义悬停气泡，延迟显示、不抢焦点，数据面板不会遮挡按钮提示。
- 正常卡片与详情中的共有模块连续移动，保留图表进度；修复多会话文字在过渡途中消失。
- 减少重复快照绘制和隐藏页面的布局准备，保留原有防闪烁交接与高清素材。
- 升级后的自启与 Codex 联动入口使用标准 Windows 快捷方式。旧安装器未更新，杀软反馈仍需进一步核实。

[下载累计程序补丁 1.2.1](https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/tag/v1.2.1) | [完整更新说明](docs/releases/v1.2.1.md)

已有用户可在软件内更新，只需最新一份累计程序补丁，不重传动画。首次安装继续使用顶部有效的 1.1.0 安装器，安装后更新程序。

![卡片展开与收回](docs/media/card-transition-1.2.1.gif)

动图使用隔离合成数据，不作为屏幕帧率证明。

### v1.2.0 程序补丁（历史）

- 新增可自定义的额度涨跌提醒，默认下降 10%、上涨 15%；周额度角标显示实际变化。
- 修复程序目录迁移就绪回执不一致，以及重启后误拆额度周期、观察量和推测总量重新开始。
- 托盘使用无数字额度环，升级继承常驻选择；可选同屏游戏或视频全屏时只留托盘。
- 改善正常卡片与大卡片的首帧交接，Windows 设置历史托盘列表仍可能缓存残留。

[下载累计程序补丁 1.2.0](https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/tag/v1.2.0) | [完整更新说明](docs/releases/v1.2.0.md)

已有用户可直接在软件内更新；首次安装继续使用页面顶部的 1.1.0 安装器，安装后更新。不重复下载动画素材。

![卡片切换演示](docs/media/card-transition-1.2.0.gif)

动图使用隔离演示数据，不作为屏幕帧率证明。

### v1.1.1 程序补丁（历史）

- 修复长时间未打开后展开卡片、数据面板和胶囊展开正常卡片时的提前露帧。
- 修复自动台词和点击台词被会话状态覆盖，并保留未读完成提醒。
- 这是累计程序补丁，不含动画素材。

[查看 v1.1.1 发布说明](docs/releases/v1.1.1.md)

### v1.1.0 程序补丁

- 首次安装可选程序目录，已有程序和已下载动画可分别迁移，升级与启动入口沿用新位置。
- 修复重启后日志恢复误报“记录受限”、画质配置结构异常导致启动失败，以及孤立额度回升导致整轮暂停估算。
- 改善久未打开卡片及内部切页时的跳闪，工作三球的最外层旋转调整为 2.5 倍，内部动作节拍不变。

这是累计程序补丁，只需最新一份，无需逐个安装旧补丁；已有有效动画继续复用。详见[完整更新说明](docs/releases/v1.1.0.md)。

| 工作状态动效 | 数据面板切换 |
| --- | --- |
| ![三球工作状态](docs/media/status-orbit-1.1.0.gif) | ![数据面板切换](docs/media/data-pages-1.1.0.gif) |

动图为原生矢量合成时间及隔离窗口演示，不作为屏幕帧率证明。

### v1.0.1 程序补丁（历史）

- 额度对比按用量、总量变化和历史图分区，区分 5 个百分点估算门槛与 20 个百分点对比条件，完整规则按需展开。
- 新增 [WSL Codex 接入](docs/WSL.md)，支持 Linux 日志、Token 与 CLI 额度查询；真实 WSL 实机验证仍待反馈。
- 补齐程序与动画补丁的独立更新流程，修复额度对比切回概览时面板变短。

[该历史版更新说明](docs/releases/v1.0.1.md)。当前安装请使用页面顶部的最新入口。

![额度对比新排版](docs/media/quota-compare-1.0.1.png)

### v1.0.0 更新

- 加入历史额度周期对比，显示周期已用 Token 与按剩余额度推测的总量，并区分套餐切换和数据不足。
- 桌宠自主移动衔接落地动画，水平范围可到屏幕两侧，减少在中间停留。
- 优化设置控件、数据面板导航与窗口过渡，改善按钮描边和展开闪烁。
- 支持仅安装卡片；动画可单独下载、启用或移除。
- 提供完整 Windows 安装包、应用内程序更新包、仅卡片安装包和独立轻量动画资源。

完整变化与安装方式见 [v1.0.0 更新说明](docs/releases/v1.0.0.md)。主仓库提供 Windows x64 版本；Linux 社区版和 macOS 移植信息见上方入口。

## 桌面上可以做什么

下表介绍上游 Windows 完整功能；Linux 的已适配范围和限制见 [Linux / niri / KDE](#linux--niri--kde)。

| 功能 | 实际表现 |
| --- | --- |
| Codex 实时状态 | 思考、编辑文件、运行命令、等待输入或审批、压缩上下文及完成；最多同时显示两个会话，更多会话轮换展示 |
| 不容易错过的完成提醒 | 完成后感叹号轻晃，再静止保留；点击确认或在 Codex 实际查看回复后消除；子会话不会重复冒充主会话提醒 |
| 会话跳转 | 点击气泡里的会话名，直接进入对应 Codex 对话 |
| 胶囊与卡片 | 闲置自动缩小，也可保持小胶囊；点击展开正常卡片，详情、聊天和设置集成在面板内 |
| 仅卡片安装 | 可不下载人物动画；之后可单独下载轻量或高清素材，也可移除动画保留卡片 |
| 额度与重置 | 真实账户提供的 5 小时和周剩余额度、重置倒计时；胶囊显示一个开口弧额度圆 |
| Token 统计 | 全部、30 天、7 天柱状图；点击今日 Token 查看 24 小时曲线 |
| 独立日报 | 累计与昨日指标分组、昨日小时曲线、按模型筛选；27 本书的等量比较使用累计 Token 与真实文本计数估算 |
| 额外重置公告 | 接入 Codex Resets 公告；网站公告与账户实际重置分别显示 |
| 龙娘互动 | 25 段动作，含新增五段工作和五段互动；工作动作持续跟随稳定的 Codex 状态并自然收尾，自动动作静音 |
| 全屏让位 | 可选视频让位，或同屏游戏/视频全屏时只留托盘；后者不会因完成提醒抢回显示，离开全屏恢复原偏好 |
| 应用内更新 | 设置 → 维护 → 软件更新；自动只检查，手动下载安装，支持暂停续传与SHA-256校验 |
| 日常使用 | 登录自启、托盘找回、连接诊断、自定义角色、集成闲聊、一键安装升级与回退 |

### 实际界面与动效

| 胶囊展开正常面板 | 日报展开与收回 |
| --- | --- |
| ![胶囊展开](docs/report/assets/胶囊展开正常.gif) | ![日报动效](docs/report/assets/日报展开收回.gif) |

历史变化见[迭代历史](docs/迭代历史.txt)和[版本记录](docs/releases)。其中旧版包名与界面属于当时版本，安装请使用页面顶部的当前公开版本入口。

## 安装与首次连接

1. 从 [v1.1.0 发布页](https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/tag/v1.1.0) 下载 `windows-x64.zip` 程序安装器，完整解压后运行其中的“一键部署.exe”；安装后在软件内更新到最新版本。
2. 安装器为当前 Windows 用户安装、校验并启动，无需 Python 或管理员权限。
3. 在本机安装并登录 Codex，发送一次消息。桌宠会自动发现本机数据，通常不需要重启 Codex。
4. 若没有数据，在“设置 → Codex → 检测连接与额度”检查各项能力；支持手动指定连接路径。

适用 **Windows x64**。新电脑必须使用自己的 Codex 登录；闲聊需要自行配置模型服务和密钥。新安装默认开启登录自启，可在设置关闭；升级保留原偏好。

安装目录：`%LOCALAPPDATA%\Programs\BailongEnhanced`。设置、聊天和统计目录：`%LOCALAPPDATA%\BailongEnhanced`。升级保留用户数据，安装管理提供回退及卸载入口。

## 数据和能力的范围

- 额度来自本机登录的 Codex 账户，不代表 ChatGPT 网页全部模型的额度；未知数据不会当作 0%。
- Token 图表只覆盖本机可读取的 Codex 日志，不能汇总其他电脑或未记录的消耗。缓存输入可能包含在总量中，不等于计费金额。
- Codex Resets 是第三方公告来源，公告不代表你的账户已落实重置。
- 会话状态、已读及压缩识别依赖 Codex 本机文件和实时通道；Codex 更新可能影响兼容性。
- Firefox + B 站有真实全屏播放验证；其他浏览器和播放器依赖系统可访问性与窗口识别，尚未逐一实测。普通网页 F11 不应触发让位。
- 原视频让位模式保留未读完成提醒优先；同屏游戏/视频隐藏模式只留托盘，完成提醒不会抢回人物或面板。手动关闭置顶后，提醒不会自动打开置顶。
- 已有桌面移动和原动作播放；新的自然交替行走、飞行动画尚未作为完成品装入。
- 本地统计读取本机数据；额度、公告、闲聊分别访问相应服务。安装包不携带开发者的登录、API 密钥、会话记录或 Token 数据库。

## 开发、报告与反馈

- [从源码运行与构建](docs/DEVELOPMENT.md)：Python 3.12、PySide6、角色素材准备、验证和打包。
- [通俗开发报告](docs/report/index.html)：下载仓库后用浏览器打开，可离线查看配图和 GIF；GitHub 页面展示 HTML 源码。
- [新增功能说明](docs/新增功能说明.txt) 和 [完整迭代历史](docs/迭代历史.txt)：当前能力与已被替换方案分别记录。
- 遇到问题请 [提交 Issue](https://github.com/Wunsch2048/codex-bailong-desktop-pet/issues/new/choose)，附版本、系统缩放、操作步骤；请先去掉截图和日志里的私密信息。

## 来源与许可

原项目：[jingh12312-rgb/bailong-desktop-pet](https://github.com/jingh12312-rgb/bailong-desktop-pet)，本地改造基线为 v0.3.3，已合入上游 v0.4.1 的十段新动作。角色形象、原有动作及基础程序来自原项目；本仓库记录其上的界面、Codex 联动、数据统计、交互和部署增强。

发布者已确认取得本次源码、角色素材和安装包公开再分发授权。这不自动授予访问者商业使用、再分发或其他许可。原项目未随基线提供统一代码 LICENSE；本仓库不擅自将整项目标为 MIT。详见 [来源与授权说明](NOTICE.md)、保留的 [原素材说明](docs/upstream/ASSETS.md) 及各依赖许可证。

本项目是独立第三方桌面程序，与 OpenAI、Codex 官方无隶属关系。
