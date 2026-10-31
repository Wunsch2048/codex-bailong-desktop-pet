# Linux 最小验证（历史诊断记录）

日常运行请使用 `run_linux.py`，详见 [Linux 启动](LINUX.md)。下文保留验证过程和诊断命令；PyCharm 当前已切换到无时限的正式入口。

本文记录最小验证阶段，不代表当前发行包状态；当前功能与边界以 README 和 LINUX.md 为准。这是隔离探针，不是已经完成的 Linux 移植。生产入口、GUI 绘制、布局及 Windows 分支没有修改。

## 环境与隔离

基线：`a1f771f`。本次机器：CachyOS x86_64、niri 26.04、两个 1920×1080 / 100% 输出。
项目 `.venv` 使用现有 uv 管理的 CPython 3.12.14，禁用系统 site-packages；依赖均安装到该虚拟环境，未安装到系统 Python。

```sh
cd ~/forks/codex-bailong-desktop-pet
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r tools/requirements-linux-probe.txt
```

现有 `.venv` 已准备完成，不必重复创建。原 `requirements-enhanced.txt` 保持不变。

`work/linux-validation/` 保存下载、隔离状态及报告，已加入 Git 忽略。不带 `--live` 的 GUI 为演示模式：LOCALAPPDATA、APPDATA、CODEX_HOME 均隔离，每次重置演示设置，关闭真实监测和额度刷新，界面标注演示数据。带 `--live` 时读取真实 Codex 数据，桌宠自身状态仍单独隔离，详见下节。

## 素材

本次下载原项目轻量素材，按 `app/material_catalog.json` 逐个校验 32 个文件的长度与 SHA-256。素材位于隔离状态目录，不写入源码素材目录。

```sh
.venv/bin/python tools/linux_probe.py materials work/linux-validation/materials-light.zip
```

下载源：
https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/download/materials-8849481e60e0b3f2314ec6a0/bailong-light-8849481e60e0b3f2314ec6a0.zip

## IPC

```sh
.venv/bin/python tools/linux_probe.py ipc --thread <测试会话UUID> --seconds 8 --cycles 2
```

在 Codex 当前聊天的工具环境中可以省略 `--thread`，使用 CODEX_THREAD_ID；普通终端需要显式提供。默认连接 `~/.codex/ipc/ipc.sock`，支持 `--socket` 指定其他端点。探针复用生产 `LiveStatusReader._listen` 与其类型化解析器，只替换 read/write 和就绪检查。只输出阶段、时间及健康状态，不保存会话正文或标识。退出时取消订阅，`cleanup=true` 表示退出清理，不是服务端新事件。

本次两轮真实连接均收到 activity=true，最终健康状态均为 ipc_ready，证明当前会话活动状态与重新订阅可用。28 个既有压缩及等待状态单元测试通过。真实完成、停止、审批、等待输入、压缩和服务器重启恢复尚未逐项验收；主动断开重连不等价于服务端异常恢复。

## 原 GUI

```sh
.venv/bin/python tools/linux_probe.py gui --backend wayland --seconds 15
.venv/bin/python tools/linux_probe.py gui --backend xcb --seconds 15
```

自动过程：显示原人物及气泡，调用原 move/position_bubble，打开原设置页面，再返回状态页，保存控件截图和几何记录。Qt 回调异常计入结果并返回失败。`result.json` 的 errors 为空只表示探针无异常，不表示视觉和窗口行为全部合格。

人工拖动检查：

```sh
.venv/bin/python tools/linux_probe.py gui --backend wayland --manual --seconds 120
.venv/bin/python tools/linux_probe.py gui --backend xcb --manual --seconds 120
```

两种后端应依次运行，不要并行。到时自动关闭，也可从原托盘退出。手动模式不自动移动和切换面板。请不要在探针中测试安装、自启动、真实聊天密钥及更新，这些能力未做 Linux 适配。

## 本次结果与边界

- 原角色、气泡、设置页面可绘制，随包字体成功加载，轻量素材无解码错误。用户确认显示与位置基本正常，但拖动存在问题；该反馈未区分后端，不能据此单独判定 XWayland 拖动通过。
- 原生 Wayland：人物、气泡均自动成为 niri 浮动窗口。原 move 请求 `(120,-80)` 后，niri 人物实际位置仍为 `(832,425)`，气泡实际位置仍为 `(826,459)`；Qt 内部坐标已经变化。定位与气泡相对位置不合格。窗口分别居中，原布局计算无法控制实际放置。
- XWayland：Qt 记录人物 `(1300,700)→(1420,620)`，气泡 `(1294,504)→(1414,424)`。但这两类窗口未出现在 niri windows 列表，不能只凭 Qt 几何断言真实移动通过。xprop 可读到 UTILITY / OVERRIDE / NORMAL 窗口类型及 ABOVE / STAYS_ON_TOP 属性；属性存在不证明合成器兑现层级。
- 没有修改 niri 配置、窗口规则或系统 Python。测试窗口均有自动关闭期限。
- 没有 Windows 实机对照，没有验证跨平台像素一致、完整动作轨迹、透明区点击穿透、全屏恢复、跨工作区和多屏拖动。控件截图不证明合成器遮挡或点击命中正确。
- 初版探针曾调用不支持的卡片模式 normal，已修正为 auto 后重跑；最终报告使用重跑数据。

下一步应集中解决 Linux 窗口定位与拖动，先区分原生 Wayland 与 XWayland 的实际表现；不能凭本次显示成功认定移植完成，也没有据此改写 GUI 或 Windows 行为。

## 本机真实数据与 PyCharm

PyCharm 的「桌宠 Linux 验证」使用项目 Python 3.12 虚拟环境，参数已设为：

```sh
.venv/bin/python tools/linux_probe.py gui --backend wayland --niri --live --manual --seconds 3600
```

停止旧实例后重新运行才会采用新参数。当前仍为有一小时时限的验证入口。省略 `--live` 可运行演示模式。默认数据源为 `CODEX_HOME` 或 `~/.codex`，可用 `--codex-home` 指定；CLI 默认为本机 `/usr/lib/chatgpt/resources/codex`，可用 `--codex-cli` 指定。

- 活动状态：连接真实 Unix IPC socket，沿用原状态解析器，断线后重连。
- Token 与会话：读取原始会话日志和只读 SQLite；索引、设置、额度记录等仅写入 `work/linux-validation/state-live/BailongEnhanced`。首轮索引需要等待。真实模式不自动保存界面截图。
- 账户额度：原 RPC 查询经 `linux_app/codex_readonly` 启动，需要已有的 `bwrap`。整个根文件系统只读，真实 `config.toml` 和 `auth.json` 只读挂载，查询程序的 Codex 目录及 `/tmp` 为临时挂载。凭据存储方式仅通过子进程参数设为 file，避免访问系统密钥存储，不写回配置。沙箱不可用时查询失败，不回退到无隔离执行。登录刷新若需要保存凭据，也会被阻止。
- 原项目优先采用时间更新的会话额度，因此界面来源可由“接口”变为“会话记录”；查询失败时保留旧值并提示。这里保持原业务规则，接入真实数据不代表不同统计口径一定相同。
- 已验证素材以硬链接复用，真实模式与演示模式的设置和统计缓存独立。Windows 生产源码未改。

本次 40 秒 offscreen 集成验证：无 Qt 回调异常，IPC 为 `ipc_ready`，额度查询健康状态为 available/ok，Token 统计可用。28 个既有压缩/等待测试通过。沙箱写入测试确认配置及认证写入被拒绝，运行时文件只存在于临时挂载；真实配置、认证文件与全局 GTK CSS 的测试前后 SHA-256 一致。尚未逐项验收实际完成、审批、重启恢复与所有面板统计口径；拖动问题仍未修复。

## GTK 主题警告

本机继承 `QT_QPA_PLATFORMTHEME=gtk3`，GTK 3 解析 `~/.config/gtk-3.0/gtk.css` 第 158、224 行时不支持 `color-mix`。探针仅在创建 QApplication 前清空本进程的 `QT_QPA_PLATFORMTHEME`，不编辑全局主题。独立对照验证两种设置下 Qt 样式均为 Fusion，清空后上述警告消失；offscreen 后端的 raise/propagateSizeHints 提示与 GTK 警告无关。


## niri 原生拖动适配

PyCharm 当前使用 `--backend wayland --niri --live`。`--niri` 仅允许 Linux、原生 Wayland 和有效 NIRI_SOCKET 环境。XWayland 模式保留为对照，不承担修复后的拖动路径。

人工坐标记录确认 XWayland 拖动时：鼠标窗口内坐标几乎不变，Qt 虚拟窗口位置却反复累加，最终产生跳动。niri 模式超过原 8 像素阈值后使用 QWindow.startSystemMove，让合成器移动真实浮动窗口；普通单击、双击仍沿用原入口。拖动期间保留原拎起动画、隐藏附着气泡；原生交互结束后恢复落地动画与气泡。原生移动不使用原来的抛掷速度估计。

气泡通过 niri 事件流读取桌宠实际位置，保留原居中、8 像素间距、边缘约束及上下翻转规则。移动使用相对实际位置的增量，避免 niri 绝对移动相对工作区而 Qt 可用区域未扣除面板时的额外偏移。订阅和移动均使用异步 QLocalSocket；只操作本进程已识别的窗口，拖动代码不修改 niri 配置、全局主题或 app 生产源码。透明画布的合成器外观由下述独立窗口规则处理。

33 个布局、原生拖动分支、模拟松手回归、压缩和等待状态测试通过。额外运行原有 test_native_interactions 时出现 3 个失败、1 个错误（该套件未加载 Linux 适配，含缺失素材错误），不将其报告为通过。Linux 原生窗口位置仍不能由 QWidget.pos 推断，人工与自动验证均以 niri 布局为准。其他设置面板、分离气泡拖动、跨屏与位置持久化尚未完成专项验收。


最终人工验收：用户确认拖动跟手、持续拎起动画、松手后气泡恢复正常，矩形边框消失。Qt 6.9 的 startSystemMove 会调用 handleEndDrag 并发送模拟 MouseButtonRelease；适配忽略该事件，使用指针离开后重新进入判定原生移动结束，回归测试覆盖这一顺序。气泡使用绘制透明度隐藏，保持原生窗口映射，避免重新映射时在屏幕中央闪现；松手后等待本机 niri 弹簧位移动画约 700 毫秒再恢复显示。该等待值针对本机验证，调整合成器动画后需要重新验收。

本机 `~/.config/niri/__custom__.kdl` 末尾增加了一条 include，加载仓库 `configs/niri-probe.kdl`。规则只匹配 `^bailong-linux-probe$`，设为浮动并关闭合成器阴影、边框、焦点框、圆角裁切、背景模糊，保留原窗口 alpha；其他应用与 GTK 主题不变。`niri validate` 通过。修改前备份位于忽略目录 `work/linux-validation/niri-custom-before.kdl`；回退仅需删除末尾新增的 include 与对应注释，不要覆盖用户后续配置改动。当前规则含本机 niri 的 background-effect 扩展，其他发行版需按其 niri 版本适配。

Qt 行为依据：https://github.com/qt/qtwayland/blob/6.9/src/client/qwaylandwindow.cpp （startSystemMove）及同目录 qwaylandinputdevice.cpp （handleEndDrag）。
