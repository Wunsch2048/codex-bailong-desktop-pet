# Codex&GPT桌宠数据中心 | 你桌面的龙娘小助手

在桌面查看 Codex 任务状态、完成提醒、账户额度和 Token 用量，也可以让白龙陪你一起工作。支持仅卡片使用，人物动画按需下载。

**[Windows 首次安装](https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/download/v1.8.1/bailong-desktop-pet-1.8.1-setup.exe)** | **[程序更新](https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/latest)** | [Linux 预览版](#linux--niri--kde) | [macOS 社区版](#macos)

Windows 当前公开版 **v1.8.1**。在线安装器直接获取最新累计程序；已有用户可在“设置 → 维护 → 软件更新”升级，无需逐个安装旧补丁。升级保留设置、统计和已下载素材。

![白龙桌宠封面](docs/media/cover.png)

## 最近更新

### v1.8.1

- **实时速率**　修复短回合结束太快、速率还没显示就被清掉的问题。最后一次有效速率最多保留 5 秒，悬停可看到「刚刚输出」。
- **胶囊**　刷新状态和额度时原位更新，减少胶囊闪烁。
- **顶部避让**　屏幕上方空间不够时，正常卡片按原尺寸移动，避免移位时文字和数字短暂变模糊。

[查看 v1.8.1 完整更新与下载](https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/tag/v1.8.1)

### v1.8.0

- **卡片**　正常卡片和大卡片采用右侧略宽的双栏排版，统一间距、对齐与圆角。Codex 字标换成清晰的矢量字形，会话切换仍在任务区。数据面板各页随主卡片展开、收起，文字和图表一起移动。时间筛选加入切换动画，修复靠近屏幕顶部时展开大卡片导致整组下移的问题。
- **个性化**　桌宠、卡片和数据面板可一起置顶、正常显示或置底。新增仅在 Codex 位于前台时显示的开关。人物和卡片可分别调整大小，也可按原有比例联动；拖动滑块即时预览，也可输入精确数值。整理设置分区与右键、托盘菜单，主题预览更快。
- **图表**　24 小时图和日报按小时显示实际输出速率，长回合无需等结束就能看到已有采样。采样不足的时段留空，悬停仍可看完成回合的均速和中位数。正常卡片的 7 天图按模型分色，全部范围与数据面板统一柱数和合并规则。模型页新增速率曲线、单日峰值和日均用量，点选模型时图表不会突然收缩。
- **历史与成本**　模型、额度和成本可用日历查看历史。模型日历会标出所选模型有用量的日期，额度日历按实际重置周期选取。成本新增「日」，日报点成本会直接打开对应日期。常用时间范围切换更快，第一次整理历史时显示进度。修复日历灰底和图例异常。
- **额度与浮窗**　周额度早期显示黄色「观察中」，累计观察至少 15 个百分点且估算稳定后才显示参考百分比。额度对比与实时的浮窗宽度跟随正常卡片，内容按重点分层。修复托盘浮窗灰块和图表悬停文字重叠。估算说明与官方 Credits 价表移到额度页三点菜单，支持整页滚动和查看历史价表。
- **聊天与状态**　聊天页统一进入「聊天设置」，服务连接、回复风格和历史选项分开，修复展开选项时的闪烁。补齐发消息给其他聊天、等待协作、查看图片及其数量等短状态。短状态会停留片刻，等待其他聊天不会误计为「待操作」。
- **动画下载**　网络中断后再次下载可从已保留进度继续，完成后校验再启用。临时文件被占用时会有限重试，失败会标明阶段并保留原始原因。也修复了 Windows 长路径关闭时可能出现的暂存文件写入问题。
- **Windows 兼容**　修复自动收起和状态刷新可能抢走前台焦点的问题。主动打开聊天和设置仍可输入。远程控制或显示比例变化后，临时贴边的人物可恢复完整显示。安装包移除了用不到的图片解码组件，体积更小。
- **平台路径**　合入 [#28](https://github.com/Wunsch2048/codex-bailong-desktop-pet/pull/28) 的源码改进，明确区分各平台的数据目录，避免在 macOS 上把残留的 WSL 路径当成 Codex 数据目录。感谢 @Kki1ds 的贡献。
## 主要功能

- **任务联动**：查看思考、编辑、命令执行等状态，接收完成提醒，点击会话名跳转。
- **额度与统计**：额度环、重置倒计时、Token 柱线图、实时速率、日报和项目成本估算。
- **桌宠与卡片**：胶囊、正常卡片和大卡片切换；35 个动作、贴边收纳、四种走动方式及八套主题。
- **日常使用**：托盘找回、全屏让位、集成闲聊、连接诊断、应用内更新和版本回退。

<details>
<summary>查看界面与动效</summary>

![状态卡片](docs/media/update-1.4.0/status-bailong.png)

| 胶囊展开 | 日报展开与收回 |
| --- | --- |
| ![胶囊展开](docs/report/assets/胶囊展开正常.gif) | ![日报动效](docs/report/assets/日报展开收回.gif) |

配图使用合成示例数据，历史界面与当前版本可能略有区别。

</details>

[完整功能与使用说明](docs/使用说明.md) | [全部版本记录](docs/releases)

## 安装与连接

1. 运行顶部的 Windows 在线安装器，无需 Python 或管理员权限。
2. 在本机安装并登录 Codex，发送一次消息，桌宠会自动发现本机数据。
3. 需要人物时，在设置的素材页下载轻量或高清动画；只用卡片可以跳过。
4. 没有数据时，打开“设置 → Codex → 检测连接与额度”。

仅支持 Windows x64。离线安装、程序位置和数据目录见[快速部署](docs/快速部署说明.txt)；WSL 用户见 [WSL 接入](docs/WSL.md)。闲聊需要自行配置模型服务。

Token 与速率统计覆盖本机可读取的记录；项目成本是 API 等价估算，不是订阅实际扣费。更多口径见[使用说明](docs/使用说明.md#数据和能力的范围)。

## 其他平台

### Linux / niri / KDE

Linux 适配源码已合入主分支，预览包由 [helantianshen](https://github.com/helantianshen/codex-bailong-desktop-pet#linux--niri--kde) 社区维护。当前预览 **v1.4.2-linux-preview.5** 面向 CachyOS/Arch x86_64，要求 **glibc ≥ 2.44**；支持 niri 原生 Wayland 与 KDE Plasma X11/XWayland，不代表覆盖所有发行版。

[下载预览包](https://github.com/helantianshen/codex-bailong-desktop-pet/releases/tag/v1.4.2-linux-preview.5) | [Linux 运行说明](docs/LINUX.md) | [KDE 说明](docs/KDE.md) | [包体与限制](docs/LINUX_PACKAGE.md)

### macOS

[Kki1ds 社区版](https://github.com/Kki1ds/codex-bailong-desktop-pet)提供 Apple Silicon DMG，未公证、无应用内更新。[下载与安装说明](https://github.com/Kki1ds/codex-bailong-desktop-pet/releases)以维护者仓库为准。

社区包由对应作者测试和发布，平台问题请前往对应仓库反馈；Windows 安装器和程序补丁不适用于 Linux 或 macOS。

## 安全反馈

微软已完成对提交的 **1.2.1 样本**的复核并移除该样本检测。结论限于该文件；其他版本、文件及卡巴斯基反馈仍需分别核查。[详细进展与处理建议](docs/安全反馈.md)

<details>
<summary>微软复核结果（已脱敏）</summary>

<img src="docs/media/security/defender-1.2.1-review-redacted.png" alt="微软对1.2.1提交样本的复核结果，敏感字段已遮挡" width="560">

用户提供的截图已脱敏并整理版面，邮箱、提交编号和精确提交时间已遮挡。判定文字已对照原图核对。

</details>

## 文档与反馈

[使用说明](docs/使用说明.md) | [开发与构建](docs/DEVELOPMENT.md) | [维护规范](docs/维护规范验证入口.md) | [迭代历史](docs/迭代历史.txt) · [旧版专项记录](docs/archive) | [提交问题](https://github.com/Wunsch2048/codex-bailong-desktop-pet/issues/new/choose)

反馈请附版本、系统缩放和复现步骤，并去掉截图、日志中的私密信息。

## 来源与许可

基于 [jingh12312-rgb/bailong-desktop-pet](https://github.com/jingh12312-rgb/bailong-desktop-pet) 改造。角色形象、原有动作及基础程序来自原项目，增强内容见版本记录。

本项目未统一采用 MIT 许可。发布者获得的公开再分发授权不自动授予访问者商业使用或再分发权；详见 [NOTICE](NOTICE.md)、[原素材说明](docs/upstream/ASSETS.md)及各依赖许可证。

本项目为独立第三方程序，与 OpenAI、Codex 官方无隶属关系。
