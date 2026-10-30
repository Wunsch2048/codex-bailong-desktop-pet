# niri 拖动位置保存合并（2026-10-30）

- 审核发现 `WindowLayoutsChanged` 在手动拖动及松手交接中直接调用 `save_settings()`，每次都在界面线程原子写入 JSON，交接事件还会重复写入。现由 300ms 单次计时器合并位置保存；拖动开始取消待保存任务，拖动期间不调度，松手重锚定与普通位置变化共用同一计时器。README 同步区分 niri 与 KDE 的宿主依赖。
- 新增拖动零写入、延迟保存及取消待保存任务回归；针对性 7 项和 Linux 全套 127 项测试通过，app/linux_app/tools 与三个入口编译检查通过。本轮未新增真实 niri/KDE 交互或性能采样，不能把计时器合并不再逐事件写入说成已测得帧率改善。

# Linux 第三版预览包已公开（2026-10-30）

已发布 v1.2.1-linux-preview.3，源码目标 97be8d2（运行逻辑 bcc1d70），包含上游 1.2.1 和用户确认的 Linux 功能清单。预发布附件为 AppImage、便携 tar.zst、SHA256SUMS.txt；三项远端大小及 GitHub SHA-256 与本地一致，未登录发布页与两个包下载响应均为 200，公开校验文件与本地一致后更新 README 当前入口。没有发布 Windows 包。

独立构建环境复用项目 Python 3.12 venv，未安装系统 Python 依赖。279 个载荷文件校验；两源码目录隐藏条件下，便携包/AppImage 解压运行接入真实数据、跨格式位置恢复与退出通过，直接挂载 AppImage 复验通过。两次用户手动移动干扰位置断言，确认原因后停止干预复验。素材/TLS/真实额度自检通过；Codex config/auth 和日常桌宠设置哈希未变。126 项源码回归与 Windows/Linux CI 通过。成功启动短采样单核 CPU 21.5–26.0%、RSS 207.3–217.7 MiB，不代表长期平均，未做主线程阻塞与磁盘 I/O 专项测量。新包没有 KDE、GNOME 或其他发行版实机结论。

发布证据位于 work/release-preview3 与 /tmp/bailong-preview3-validation（均不提交）；本版完整说明保存在 docs/releases/v1.2.1-linux-preview.3.md。草稿上传代理路径过慢，仅上传子进程直连重试，未改全局代理。旧预览包保留为历史回退入口。

# Linux 本轮交付检查（2026-10-29）

用户已确认随机动作、回复摘要、拖动跟随、托盘菜单首次及再次展开正常；编辑页触边返回的两个入口表现反馈为“基本上是正常了”。已授权提交、合并及推送。本轮 126 项相关回归通过，app/ 与上游 8d86342 相同；未新增 Windows/KDE 实机、长期性能或安装包验收。以下待验收和未授权描述属于历史过程，以本段为准。公开 Linux 安装包仍为 linux-preview.2，本次仅交付源码。

# niri 编辑页拖动与边缘避让：待本机验收（2026-10-29）

用户反馈固定起点偏移方案仍会在触边返回后保持错误间距，与胶囊入口表现不一致，上一轮不能视为验收通过。DragBubble 现于计算目标时暂时忽略 _editor_positioned，直接复用原 content_geometry 的角色锚点、上下翻转及屏幕边界限制，并把目标同步到真实编辑页用于松手交接；计算结束恢复编辑定位标记，不更改分离面板与 Windows app/。取消上一轮 editor_offset 状态。

回归覆盖两种初始面板位置、连续上下触边返回、再次拖动、目标区域不与角色相交以及交接位置；17 项 UI/niri/surfaces 测试通过。测试期 complete_frame 会按实际布局更新内容尺寸，断言以实际尺寸计算，不使用无效的强制 resize。真实鼠标与两个打开入口仍待人工验收。保留其他已验收修改，未提交或合并。

# Linux 托盘首次菜单布局：已通过本机验收（2026-10-29）

用户要求暂不处理隐藏角色/跨屏分离延迟，先修复托盘第一次小框、第二次空白需滚动才显示菜单的问题。原 DesktopPet 在 aboutToShow 清空并重建菜单，Linux D-Bus 实测菜单项 ID 每次全部变化，布局 revision 仍为 1、AboutToShow 返回 false。Linux 入口现于 tray.show 前填充完整菜单；ui.install 在后续 populate_tray 中使用原 build_menu 生成临时状态，只同步已有动作的文字、启用和勾选，保持原菜单树及回调身份。Windows app/ 未变。

新增回归检查动作身份、状态同步及原命令回调。实际 DBusMenu 首次 GetLayout 有完整 7 个根项及 6 个子项，连续三次 AboutToShow 后 13 个 ID 不变，证据 work/upstream-validation/tray-dbus-fixed.txt。全部 125 项 Linux 回归通过。已重启全新 tray-menu.py 实例且未调用 AboutToShow 预热；用户确认“首次、再次打开和菜单操作均正常”。先前随机动作/摘要/拖动跟随已验收的改动保留，均未提交或合并。

# 随机动作、回复摘要及拖动跟随：已通过本机验收（2026-10-29）

用户先确认随机动作和 Codex 回复摘要正常，再确认修正拖动坐标回退后的“中部跟随和边缘表现均正常”。这两项当前开发改动已完成本机 niri 人工验收；Windows app/ 未修改。当前尚未获得本轮提交、合并或推送授权，所有修改仍留在 worktree。以下调查及待验收记录为过程记录，以本段最终验收结果为准。未新增 KDE、热插拔或长期运行验收结论。

# 拖动气泡误翻到下方的修正（待验收）

用户确认跟随基本正常，但气泡拖动时出现在人物下方。诊断中拖动时目标固定为第二屏原点附近 (1937,264)，松手立即恢复正常：niri 交互拖动时 tile_pos_in_workspace_view 暂缺，actual_position 返回 None，而业务坐标退回 Qt (0,0)，导致误触顶部翻转。读取布局时保存最后有效位置，业务坐标在布局暂缺期间使用该值；popup 由合成器跟随角色，松手优先读取新实际坐标。新增回归覆盖非零屏幕原点及松手更新；24 项相关测试通过。坐标缺失期间不能把缓存视为实时位置，跨边缘翻转仍须人工核对。未改 Windows，未提交合并。

# niri 拖动气泡跟随：待验收

用户已确认随机动作和 Codex 回复摘要正常，授权继续拖动气泡跟随。新增 Linux DragBubble 使用原 complete_frame 绘制当前气泡，ToolTip/xdg_popup 附着角色；create 不提升兄弟控件原生化。父表面负责连续位移，IPC 更新边缘布局，100ms 时钟仅在拖动与交接期间刷新内容。真实气泡仍在隐藏状态定位，松手 700ms 交接时保持预览可见；角色隐藏、分离或关闭时停止时钟并释放画布。Windows app/ 未改。

123 项回归通过，覆盖边缘布局、独立面板、非原生子控件及清理。真实 Wayland 自动移动对照采样中 popup 原点与原布局目标一致，无额外 subsurface、opaque-region 或退出 buffer 警告；这不是鼠标持续拖动验收，仍待用户检查跟手、屏幕边缘和松手后点击。诊断 work/upstream-validation/drag-follow.py；当前修改与已验收的随机动作/摘要修改均未提交、未合并 main。

# 随机动作与 Codex 回复摘要恢复：开发中，待验收

用户要求先开启并适配两项，确认正常后才处理拖动时气泡持续跟随。本轮仅修改 Linux launcher：新设置默认开启两项；旧入口配置通过 linux_behaviors_ready 一次性迁移，随后尊重各自保存的开关；保留声音关闭及其他交互。共用 app/ 未改，无提交、推送或合并授权。

隔离实际入口验证首次两项开启、关闭保存后重启两项仍关闭；再次开启后用于人工验收。日志 work/upstream-validation/behaviors-*.log 不记录会话内容，前后核对日常桌宠设置及 Codex config/auth 未变。新增入口迁移回归覆盖独立开关，原真实 IPC 和动作调度复用，不使用演示数据。第二项已获用户授权，当前状态见上方记录。

# Linux 合并 v1.2.1：已通过本机验收（2026-10-29）

用户已确认胶囊、右侧额度展开收起、连续点击及拖动全部正常，并授权合并本地 main。本轮同步上游 8d86342（v1.2.1），处理 README、HANDOFF 和 Source checks 冲突；app/ 保持与上游完全一致，平台修正仅由 Linux 入口安装。未授权推送或发布，公开 Linux 包仍为 v1.0.0-linux-preview.2。

Linux 补接托盘额度环、设置来源标签和 niri 顶栏提示。角色可见且与气泡同屏时使用以角色为父表面的 Wayland popup 绘制原 440/480ms 过渡，主气泡在动画期间定位，结束立即恢复真实控件；临时画布不新增任务栏条目。角色隐藏或气泡跨屏时仍保留 Tool 窗口及较慢交接，不宣称所有模式交互等同 Windows。拖动开始取消当前过渡，不残留交接画面。

原生透明画布的重要约束：不得对尚未创建的 NativeLanding 调用 winId()；这会把兄弟 content 和 TransitionCover 一并提升为原生窗口，产生绕过绘制透明度的子表面和不透明矩形。使用 create() 仅创建画布自身的句柄，测试断言内容和遮罩在创建及连续导航后始终非原生。对照时原实现产生 32 次子表面创建和 62 次非空 opaque-region 提交，修复后两项及退出缓冲警告均为 0。

验证：121 项 Linux 回归通过；150 项共享测试通过，5 项 Windows API 测试仍需 Windows 主机。前序本机检查覆盖真实 IPC/额度、设置/聊天/日报/额度对比、悬停定位及 1.0/1.4 倍缩放；最终人工验收覆盖附着气泡的显示、点击和拖动。未重建安装包、进行 KDE 或 Windows 实机验收，也未完成热插拔及长期性能验证。Qt 窗口数量和逻辑坐标检查不能替代合成器最终画面验收。

诊断脚本和日志保留于合并 worktree 的忽略目录 work/upstream-validation；main-merge-preservation 保存合并前原检出目录 .idea 的暂存及未暂存补丁，用于合并后逐字核对。测试使用原仓库 Python 3.12 虚拟环境与隔离桌宠数据，不修改系统 Python、日常桌宠或 Codex 配置。原检出目录的用户 .idea 改动不纳入合并提交。

# 2026-10-25 公开 v1.0.1 程序补丁

发布提交32026eb358f8e63866abe8a1b6d1b59c380c8b22，Release ID423359649，含最新额度对比排版、WSL接入及独立动画补丁协议。程序ZIP约74MB，程序安装桥不含动画，复用原有素材或首次仅卡片。新源重新编译101模块绑定，27项定向检查、Source checks 40193310341通过；最终冻结TLS与原生1.5x交互通过，重新整理的发布说明/部署文档随载荷校验。最终载荷由真实C#桥隔离stage-only准备并verify_ready通过，未部署覆盖本机1.0.7。包体没有重新上传人物动画。

用户明确允许仅替换该草稿三个旧附件（程序ZIP、安装器ZIP、SHA）；本地旧构建保留。Release公开且未登录下载验证成功后才更新README及快速部署公开入口，避免草稿404复发。WSL仍缺真实发行版联调，Mac PR尚未合入，不宣称支持Mac安装。构建深路径隔离缓存触发.NET260字符限制，改用接近真实用户目录长度的独立临时根验收；本机真实暂存最长184字符，不能据此保证异常长用户目录。验收缓存保留，无递归清理。

公开后验收补充：匿名 GET Range 对六个附件均返回 206，GitHub Source checks 40193310341 成功。旧公开 v1.0.0 更新器通过实际发现流程识别到 v1.0.1 program，大小与 SHA-256 均匹配。WSL Issue #6 原评论已改为正式发布链接且保持开放；不宣称本机完成真实 WSL 发行版联调。发布链接：https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/tag/v1.0.1。发布既有草稿时务必显式设置 tag_name；CDN HEAD 曾短暂误报404，匿名 GET Range 和内容摘要才验证了真实下载。

# 2026-10-25 公开 1.0.1 发布准备

本轮用户授权上传程序补丁并回复 WSL Issue #6，不授权关闭它。开发机没有 WSL，不能宣称真实发行版联调完成。本地安装继续保持 1.0.6。

旧公开 1.0.0 在 API 限流备用流程中必须找到 windows-x64.zip 的 SHA 行，才继续选择 program.zip。仅发布 program.* 会阻断该类用户更新。1.0.1 增加不含动画的 C# 程序安装桥，嵌入同一已校验程序包，保留该旧下载名；README 首装固定指向此新版桥，未来纯动画 Latest 不影响首次安装。安装准备只写受管新暂存目录，交给原事务安装器保留设置与回退。已用真实编译桥做首次卡片准备、素材复用、篡改、摘要、越界与大小写冲突检查，全部通过，未部署到本机。

本次采用全新构建目录，Qt 先计算裁剪清单再跳过复制，无批量删除。额外资料和动画不重新上传。公开编译号、标签、描述统一 1.0.1；程序版本和素材更新有效版本分别显示。

# 项目交接要点

## Linux 退出联动与会话跳转（2026-10-29）

- codex_watch.install 替换原 codex_startup.desktop_sessions，live.start 启动原两秒 codex_timer；沿用后台扫描、ExitGate 见过启动后连续三次缺席和设置变化重置规则，不修改 Windows app/。开关关闭时原轮询立即返回，不扫描进程。仅关闭 Codex 窗口而桌面主进程仍在时不会退出。
- live.open_codex 经原 CodexNavigation 工作线程调用 xdg-mime/xdg-open，任务链接沿用原 UUID 校验；打开主界面用 codex://launch。本机注册为 chatgpt.desktop，当前安装包解析器确认 launch/threads 路由。无协议注册或派发失败直接报错；不修改系统关联，不启动浏览器回退，不直接确认已读。两个 open_codex 导入引用都须替换，退出上下文后恢复。
- 冻结包向宿主派发时沿用 host_environment 恢复 LD_LIBRARY_PATH，并清除桌宠 Qt 插件目录、QML 路径和后端选择，防止 KDE 外部工具使用打包 Qt。此分支仅做环境模拟回归，未重新打包。
- 用户确认独立真实数据诊断实例的任务名跳转和“打开 Codex”均正常。另一独立实例经真实检测器过滤合成桌面 PID，测试进程退出后 4.16 秒正常关闭（退出码 0）、释放锁并保留设置，未关闭真实 Codex。117 项回归、actionlint、编译和 diff 检查通过；未做 KDE 实机或冻结包验收。证据 work/linux-codex-integration/，诊断数据不纳入提交，尚未发布安装包。

## Linux preview.2 发布验证（2026-10-25）

- 本轮重新通过 108 项回归、actionlint 和 279 个归档载荷 SHA256；源码目录用 bwrap 隐藏后，便携版与 AppImage 解压模式真实 IPC/额度/Token、位置保存恢复及正常退出通过，普通 FUSE 挂载也通过。Codex config/auth 与日常设置哈希保持不变。
- 打包监听实测使用外部 AppImage 路径创建独立 GUI 服务，手动退出不反复拉起；临时服务已清理。PyInstaller 的 Qt 运行钩子会预载 QtCore，不能将源码的无 Qt 结论套到冻结包；冻结监听没有 QtGui/QtWidgets 映射，5 秒采样单核 CPU 2.2%、RSS 44.0 MiB。
- 三种包体运行的两秒短采样单核 CPU 27.5–30.5%、RSS 226.7–363.3 MiB，包含启动与动画，非长期平均或性能对照。压缩健康为 degraded，不声称完整压缩行为通过。未做 KDE 包体、其他发行版、重新登录或 Windows 人工验收。证据 work/linux-build/preview2-*，源码外验收位于当前聊天 work/preview2。

## Linux 随 Codex 启动（2026-10-25）

- linux_app/codex_watch.py 复用原 LaunchGate，按当前用户 Electron 主进程的 PID/创建时间识别会话，排除 CLI 和 --type 子进程；live.py 的桌面存在检测共用此实现。--watch-codex 在 Qt 初始化及素材准备前进入监听，仅两秒扫描进程，不加载 Qt。未知权限状态不当作 Codex 退出。
- 独立 bailong-codex-watch.service 通过原设置页开关立即启停；触发的 GUI 使用 systemd-run 创建 bailong-codex-pet.service，避免停止监听时被同一 cgroup 杀死。普通开机启动仍只登记、不立即启动，原 app/Windows 逻辑未变；随 Codex 关闭尚未接入。
- Autostart 管理器支持独立单元和监听参数，启用失败恢复原文件与登记状态。调用宿主 systemctl/systemd-run 前恢复 PyInstaller LD_LIBRARY_PATH。临时服务通过 D-Bus 传参，仅美元变量需转义，不能套用 unit 文本的百分号转义；真实 systemd 合成路径验证通过。
- 108 项回归、actionlint 及 diff 检查通过。独立数据目录实测真实 Codex 启动触发、手动关闭不重拉起、关闭监听保留 GUI；监听进程未映射 Qt，5 秒短采样单核 CPU 1.2%、RSS 18.3 MiB。测试服务已清理，日常开关未开启；未退出用户 Codex、未重新登录及打包验收。证据 work/linux-autostart/watch-integration.log。

## Linux systemd 自启动（2026-10-25）

- linux_app/autostart.py 只替换 Linux 进程内 desktop、desktop_services、desktop_settings 的已导入启动函数，Windows app/ 源码不变。服务采用 graphical-session.target 的 WantedBy/After/PartOf，正常退出不重启；开关只 enable/disable，不用 --now。没有默认开启日常自启动，也没有启用 linger。
- 源码必须保留虚拟环境 sys.executable 的路径，不能 resolve 为系统 Python。AppImage 只在 frozen 且当前可执行文件位于 APPDIR 时采用经检查的外部 APPIMAGE；不存在则报错，不能登记临时路径。ExecStart 对引号、反斜线、百分号和美元符号分别转义，保留数据路径和 Codex 参数，桌面每次登录自动识别。
- 手工同名服务不覆盖，写入原子替换，启用失败恢复原文件与登记状态。systemctl 调用仅发生在设置读取/应用时，无后台轮询，每次等待上限 5 秒。服务操作仍在原同步设置流程中；没有做 UI 卡顿性能保证。
- 临时 bailong-autostart-validation.service 已在真实 systemd 用户管理器完成启用、ExecStart 特殊字符验证、执行和禁用，并删除该测试文件。Type=simple 的 start 返回不等于子进程已经写完测试结果，验证需等待结果文件。未注销登录验收，未新打包 AppImage。

## niri 人物输入区域（2026-10-25）

- `linux_app/wayland_input.py` 仅由 niri 入口安装，使用 QWindow mask 设置 Wayland 输入区域，不设置 QWidget mask；阈值位图从 KDE 实现提取到 input_shape.py，KDE 行为保持。Qt 6.9.2 Wayland 将空 mask 解释为整窗输入，空帧必须使用窗口外的非空矩形，不能传空 QRegion。输入区域随 surface commit 生效，设置后补一次绘制；同帧缓存防止形成持续重绘循环。
- 输入范围使用 Wayland 逻辑坐标；按住/原生拖动时保留整窗输入，确保原 niri 的 Leave/Enter 松手交接不会因人物姿态变化而失效。隐藏时不计算，计时器只在绘制后单次触发。窗口句柄、帧、翻转、大小和按住状态变化会更新区域。
- 95 项本地回归和 actionlint 通过，8 秒原生协议采样确认 set_input_region、无解码错误并正常退出。用户验收透明角落穿透、人物点击拖动、松手动画和气泡恢复均正常。独立诊断实例 10 秒短采样单核 CPU 28.6%、RSS 274.8 MiB，含动画及人工交互，不代表长期平均或性能对照。未改 app/Windows 入口；未重新打包，未完整验收分数缩放和跨屏热插拔。诊断日志在忽略目录 work/linux-validation/input-*。
- PR 跟进自动化 kde-pr 已删除，automation.toml 已不存在；先前暂停调用虽返回成功，但后续复核文件仍标 ACTIVE，不能只凭更新响应宣称已停用。

## PR #1 review 修复（2026-10-25）

- 维护者指出无条件把 Codex CLI 挂到 /tmp/bailong-codex 会破坏相邻文件查找。包装器现在始终在原路径执行；未被遮蔽的安装不重定位，CODEX_HOME 内的顶层安装子树（如 packages/）整体只读挂回原位置，保留脚本、模块与资源；/tmp 内的完整安装同理。根层 config/auth 仍只读，运行时文件仍只存在于临时 home。直接位于被遮蔽根目录的单个启动器明确拒绝，不猜测或绕过依赖。
- KDE 原 createAlphaMask 的阈值为 128，与 DesktopPet.alpha_hit 的 12 不同。现在提取 Alpha8，通过 Pillow 的 C 层查表按 alpha >= 12 打包为 LSB 位图，仅修改 ShapeInput；不裁切视觉边缘，不在 GUI 做逐像素 Python 循环。niri 目前没有逐像素输入区域，不能称它已遵循这一阈值，本次不顺带修改 niri。
- 修复后重新验证 190 项（Linux 适配/公告刷新 93 项）；新增合成相邻 helper/资源、配置/认证只读、运行时文件不外泄、alpha 11/12/127/128 及全部 alpha、四档 DPR 与水平翻转回归。真实 CLI 素材/TLS/额度自检重新通过。512px 位图转换 100 次微基准中位 0.383ms、最大 0.585ms，不代表整个 GUI 帧耗时。
- 本轮重新核对 9 组实际 Qt/X11 坐标、物理输入区和关闭置顶状态，无回调异常；21.22 秒含抓图及新索引的采样中 CPU 耗时 12.11 秒、末端 RSS 329.8 MiB，不是闲置平均，也未做同负载性能对照。记录在忽略目录 work/kde-review-validation。初始提交人工鼠标确认与本轮自动/原生验证分别记录；不声称重新做过 niri/Windows 人工验收或 KDE 打包验收。下面的初始提交记录保留当时结果，不能替代本轮 review 修复验证。

## KDE 适配与独立桌面入口（2026-10-25）

- KDE 变更基于 helantianshen/main 的 `3144a67`（v1.0.0 + Linux/niri 基线），只提交源码适配，未制作或发布安装包。
- 按上游 issue #2 的隔离与验收建议整理：niri 使用独立 `run_niri.py`，KDE 使用独立 `run_kde.py`；两者固定自己的桌面，共享 Linux 生命周期。`run_linux.py` 保留自动选择和 `--desktop kde/niri` 兼容入口。Qt 在后端选定后才导入，不要把 Qt 原生 Wayland 的虚拟坐标当作 KDE 实际窗口位置。
- `linux_app/kde.py` 使用 X Shape 的 ShapeInput 区域实现透明像素鼠标穿透，不调用 QWidget.setMask 裁切视觉透明边缘。按 DPR 生成物理像素位图，原画、变换与人物大小保持。单次事件计时器在绘制后合并更新，隐藏/同帧不重复上传。
- Qt 6.9.2 切换置顶时可能重建 QWindow，而 QWidget.winId() 仍返回旧 ID；必须使用 windowHandle().winId() 操作 X11 资源。初轮探针因旧 ID 误报 BadWindow；改正后原生坐标、尺寸、置顶状态和命中区均已重新核对。
- 初始提交曾把 CODEX_HOME 内的 CLI 单文件重定位到沙箱 /tmp/bailong-codex；该实现会破坏相邻运行依赖，已被上面的 review 修复替换，不得恢复。config/auth 只读及运行时隔离继续保留。
- 桌面进程识别不再根据 CLI 父目录猜 ChatGPT 路径，而是确认同名 Electron 主程序旁的 resources/app.asar 并排除 --type 子进程，允许 CLI 与桌面程序分开安装。
- 新建 Python 3.12.15 / PySide6 6.9.2 虚拟环境，32 个轻量素材文件逐项 SHA-256 核对。185 项回归及 app/linux_app/tools 和三个 Linux 入口编译检查通过；真实额度、Token、IPC 与公告已接通。Evernight Vista 44.0.1（Fedora 44 衍生）、x86_64、Plasma / KWin 6.7.5 Wayland、200% 缩放下实际 X11 坐标与 Qt 目标匹配，覆盖程序化移动、设置/聊天、日报、分离、胶囊往返、人物 1.0/1.4 倍及取消置顶。
- 用户人工确认真实鼠标拖动、松手后的气泡跟随和透明区域点击正常。XTest 在本会话未送达角色，不能用注入替代该反馈；其他缩放、热插拔、多屏、长期运行和真实全屏播放器未验收。原 Linux 预览版的其他功能边界仍保留。
- 原生切换探针的 21.63 秒采样包含多次控件抓图，进程 CPU 耗时 9.15 秒、末端 RSS 276.2 MiB；日常实例另一次 8 秒短采样为单核 CPU 17.9%、末端 RSS 349.1 MiB。这些不是长期平均、性能优化对照或显示帧率。诊断、截图和数据均在忽略目录 work/kde-validation，日常实例使用 XDG 数据目录，未修改桌面全局规则。
- 运行与验证入口见 docs/KDE.md，其中按 issue 清单逐项区分已验证、未专项验收和未实现。会话跳转、视频全屏让位、Windows 更新/安装管理未适配，不把保留的 UI 入口视为 Linux 支持。KDE 日常启动 `.venv/bin/python run_kde.py`；已有日常实例时先从托盘退出，不要为重复启动删除有效锁。

## 既有基线与历史记录

## 上游 Windows 历史记录

## 本地 v1.0.6：WSL Codex 接入（2026-10-25，已实装）

当前安装 1.0.6-20261025-185208，回退 1.0.5-20261025-173521，用户数据备份 deployment-backups/20261025-185208-db12376f。精确备份见 本地实装/v1.0.6-deployment.json。设置、高清偏好和 connection-paths.json 逐项无变化，当前仍 Windows 来源、HD；实际 EXE 哈希与最终构建相同。132 项定向/Windows 回归，其中20项WSL；发布副本不依赖原始动画的20项WSL检查通过。101 个冻结模块、离线 TLS、冻结 Windows 1×/1.5×交互通过。5秒整进程采样0.266 CPU秒/秒、228.7MB工作集，含HD与业务，不作前后性能对照或动画单项结论。未打包或上传，GitHub稳定版仍v1.0.0。

Issue #6（https://github.com/Wunsch2048/codex-bailong-desktop-pet/issues/6）要求导入 WSL 中的 Codex 和 CLI。本轮增加设置→Codex→连接路径→Windows/WSL来源选择、后台枚举、Linux用户/数据目录/CLI验证；发行版枚举不启动Linux，明确验证会启动所选发行版。Linux CLI由固定login-sh包装和独立位置参数启动，加载Linux环境/代理及NVM路径；不把用户字符串拼进shell代码，不复制Windows登录文件，不把Windows CODEX_HOME传给Linux。支持常见VS Code Server CLI路径和手动绝对Linux路径。Windows共享可读性也是保存前提，Linux版本命令成功不能冒充UNC可读。

WSL文件通过 \\wsl$\发行版\路径读取，启动阶段不resolve UNC；数据目录大小写保留。Token来源键、完成提醒和本机重置证据按发行版/数据目录隔离，不把旧Windows统计迁入WSL。配置保存后当前进程保持原来源，重启才采用新来源。运行状态查询短缓存；CLI执行前刷新检查。发行版停止时不扫描UNC，不回退到Windows账户，手动Token刷新也完成失败事件，不无限忙碌。

WSL模式不连接Windows桌面实时管道、不读Windows/跨平台SQLite已读证据；状态依赖JSONL日志，完成手动确认。会话跳转用所选Linux CLI在Windows Terminal/独立终端resume有效会话ID。Windows桌面关闭不能触发WSL来源退出；启动联动标签明确为Windows桌面端，WSL进程启动/退出联动未实现。路径验证和连接检测的退出等待改为finished信号，避免GUI线程wait数秒。

本机未安装WSL：wsl.exe管理命令和界面检测均得到未安装/无发行版提示，没有安装或启动测试发行版。不能声称真实WSL登录、UNC读取、Linux CLI RPC已经实机验收通过。只有隔离传输/路径/IPC防串源用例与Windows界面/冻结程序验证；保留Issue #6，未回复或关闭。入口和边界见发布副本 docs/WSL.md，证据 WSL接入检查/界面检查.json、WSL设置界面.png、本地实装/v1.0.6-verification.json。设置截图仅本地验收，可能含原桌宠叠层，未经检查不要上传。

本轮WSL是同一活动回合的追加需求，沿用用户对本轮测试与构建暂存清理的许可；实际使用全新build/local-1.0.6-final及release/local-1.0.6-final。实装禁用递归清理，旧版本和备份全部保留。下一活动回合不得沿用该清理许可。

公开协议迁移门禁：下一正式程序版需先交付支持独立动画的更新器，并更新一次安装基包及README固定入口；否则未来Latest为纯动画时新用户从v1.0.0旧安装基包无法更新。之后日常程序改动再只发程序补丁，不重传不变动画。公开编号实时承接上一GitHub稳定版；本地1.0.6不能直接充当公开序号。维护页当前显示程序编译版本，更新卡显示含动画补丁的整体版本；首个独立动画公开前需把维护页标签明确为“程序版本”以免混淆。发布副本源码已同步但未提交/推送，app/version.py仍保留公开1.0.0。

## 本地 v1.0.5：动画补丁与额度对比（2026-10-25，已实装）

当前安装 1.0.5-20261025-173521，回退 1.0.4-20261025-134339，备份 deployment-backups/20261025-173520-7d2a1164。设置和素材偏好逐项无变化，继续 HD；104 项定向检查、100 个冻结模块、离线 TLS、冻结 EXE 原生 1×/1.5× 交互通过。实际安装 EXE 与最终构建相同。程序下载/素材更新在后台，进度限频 120ms，启动读取一次动画覆盖；本机 5 秒整进程采样 0.147 CPU 秒/秒、217.5MB 工作集，包含 HD 和业务，不代表动画单项耗时或显示帧率。未制作公开安装包或上传，GitHub 仍 v1.0.0。

动画补丁现支持稳定 Release 独立发现、API 受限备用下载通道、描述和 ZIP/文件完整 SHA、最低程序版本、按当前画质下载、动作边界提交、仅卡片不下载不显示人物、素材页回退。新目录和一个原子 JSON 指针交接，旧资源保留。回退不能降低程序号；之后程序更新保留独立动画覆盖，除非程序携带更新版本的动画目录。同批程序与动画构建校验目录一致。动画元数据在更新器尚不识别的公开 v1.0.0 上不能生效，下一公开版须先交付新程序更新器；不要误说旧客户端已支持。真实 GitHub 动画补丁尚未发布，网络发布路径以隔离包/传输夹具验证。构建入口 build_animation_update.py；发布规则见 GitHub 副本 docs/PATCH_RELEASES.md。主动移除动画的清单含当前/上次补丁与捆绑素材，路径去重；本机未执行真实素材删除。

额度对比的推测是首次记录与末次记录之间 Token 增量 / 已观察百分比下降，至少 5 个百分点；历史可比要求下降至少20、至少3个不同读数、主模型占比≥70%、输入输出完整，以及同套餐/主模型/相近任务构成/重置类型。面板增加5/20门槛，覆盖不足提示拆为还需多少百分点、读数和模型等缺失条件。只读7个本机周期均可算出推测，当前8个百分点、主模型约55%，不满足可比。查询约100ms，属于后台 SQL 计算而非帧率。

概览缩水原因：scroll.show() 早于追加类比卡片，ShowToParent 尚未处理就测 heightForWidth，473px错算384px；现先完成全部内容再挂入滚动区并显示，避免计时器补救。1×/1.5× Windows 实际桌面连续帧尺寸稳定；268/420/560宽度定向检查通过。截图采集包含自身开销，不能把其采样间隔当显示帧率。更新缓存被其他操作移除时先捕获枚举异常。证据 本地实装/v1.0.5-verification.json、补丁与额度对比修复/桌面切页对照.png。

构建最终目录 release/local-1.0.5-final/BailongEnhanced；用户允许本轮测试与构建暂存清理，清理限本次 build/local-1.0.5-final 和 release/local-1.0.5-final，不覆盖下一轮授权。正式实装禁止递归清理，旧版本和用户备份保留。发布副本已同步待发布源代码但未提交/推送，内嵌公开号仍为1.0.0，下一公开号须实时读取 GitHub 再计算。

## 补丁统一编号与名称（2026-10-25，规则落盘）

程序和动画补丁共用 GitHub 公开序列；任一类单独发布均推进一位，同批发布共用同一版本。示例：程序补丁包 1.0.1 → 动画补丁包 1.0.2 → 程序补丁包 1.0.3 与动画补丁包 1.0.3 同批发布。第二、三段满十进位；本地开发号继续独立。GitHub Release 标题和附件 label 使用上述易读名称，下载文件名保留兼容格式；素材内容 ID 只用于校验。

实现边界：当前程序更新器只识别程序包和完整安装包，动画资源下载仍通过素材设置及内容 ID；本次只确立命名和公开编号规则，没有实现动画单独稳定 Release 的自动发现/安装，也没有修改已公开 v1.0.0。后续真正发布动画补丁前，必须补齐该路由及 API 限流备用通道，不能把动画附件单独放入 Latest 就宣称能够推送，否则旧客户端会显示缺少安装包。同步发布时只创建一个公开 Release。程序更新界面源文案改为版本化“程序补丁包”，未构建实装。

开始改动前先读 `AGENTS.md`，再读本文件，随后核对当前源码和版本对应的验收记录。不要把旧版验证结果当作新版结果。

- 当前公开基线 v1.0.0；发布副本另有未提交的本地改动。完整 Windows 包和程序更新包按同一源码构建；高清素材是独立、按内容哈希校验的资源。
- 状态来自 IPC 与本机日志。IPC 已终止的回合可能在稍后才读到同回合日志；已关闭回合不能被重新打开，新回合要用不同的回合编号进入。
- `父UUID_分支UUID.jsonl` 可能是用户编辑消息后形成的同一对话日志分支：若元数据归属父会话且首个回合是根用户操作，要用父会话 ID 显示和跳转。真实代理子会话可能有相似文件名，应凭自身元数据或代理归属判断。没有回合编号的完成提醒无法自动确认，恢复时清理，也不应再次创建。
- 旧 Token 历史库被锁或暂时不可读时保留迁移待重试状态。只有确认迁移完成或旧库确实无需迁移后，才能写入来源标记；旧库原文件不移动。
- 卡片、人物与日报的形变要检查实际窗口交接。截图覆盖层和原生控件重复布局会产生闪烁或震颤；不能仅凭定时器数值推断桌面帧率。
- 人物自动移动以手动放置点为中心，默认仅水平。自动位置保存不能反过来更新活动中心。
- 高 DPI 下绘制、点击、拖动必须共用坐标换算。状态图标静置卡顿曾来自粗粒度计时和主线程重复磁盘扫描；缓存只作显示提示，启用素材前仍完整校验。
- 发布前确认 GitHub 副本与本地源版本一致，完整包、程序包和校验清单全部准备好再公开。不要把运行时数据库、账号凭据、日志或角色动画写入 Git 历史。
- 公开版本只按 GitHub 上一稳定版进位；本机 v1.0.4 与公开 v1.0.0 分离。仅卡片发布用仓库内 tools/pyinstaller_keep_files.py，不能依赖本机未跟踪的 本地实装 辅助脚本。构建输出要使用全新路径；完整包、程序更新包、仅卡片包和独立轻量资源分别验 SHA 后再发布。

## Linux 隔离最小验证（2026-10-25）

- `tools/linux_probe.py` 复用原 GUI 与 IPC 解析器；运行方法及证据边界见 `docs/LINUX_VALIDATION.md`。Python 3.12 虚拟环境在 `.venv`，状态和素材在 Git 忽略的 `work/linux-validation`。
- 原生 Wayland 下 Qt 的 `move()` 可改变应用内部坐标，而 niri 实际窗口位置不变；不能用 QWidget.geometry() 单独验证桌宠移动和气泡定位。
- XWayland 的工具窗口未出现在本机 niri windows 列表；Qt 坐标变化及 ABOVE 属性均不足以证明实际定位、层级和拖动通过。用户确认显示基本正常但拖动异常，尚未区分后端验收。
- IPC 两次订阅收到真实工作中状态，28 项既有状态解析测试通过；真实完成/审批/压缩及 Windows 无回归仍未验收。


### Linux 探针真实数据接入（2026-10-25）

PyCharm 配置已启用 `--live`。Linux 专用适配集中在 tools/linux_live.py 与 tools/linux_codex_readonly，未修改 app 生产模块。实际使用 Unix IPC、会话日志、只读 SQLite 和沙箱化的账户额度 RPC；桌宠状态在 work/linux-validation/state-live，演示状态独立。bwrap 使用临时 Codex home 加只读 config/auth 挂载；仅根目录只读会使当前 CLI 初始化失败，因此必须为运行时数据库保留临时可写空间。不得降级为无沙箱查询。

40 秒 offscreen 测试确认 IPC、额度查询和 Token 统计可用，28 个既有测试通过；保护文件前后内容一致。会话额度会按原规则覆盖较旧接口额度，界面来源不一定一直显示接口。GTK color-mix 来自系统 GTK 3 CSS，探针只清空本进程主题桥接，Qt 仍为 Fusion。需用户停止旧 PyCharm 实例后重启；拖动、完整状态转换和跨平台视觉一致性仍待验收。详情见 docs/LINUX_VALIDATION.md。


### niri 原生拖动与透明画布（2026-10-25）

用户人工确认最终一轮拖动、持续拎起动画、松手后气泡定位正常，矩形边框消失。PyCharm 改为 `gui --backend wayland --niri --live --manual --seconds 3600`，适配仅在 tools/linux_niri.py，未编辑 app 生产源码。XWayland 诊断抓到虚拟全局坐标反馈累加；原生移动采用 startSystemMove，气泡依据 niri WindowLayoutsChanged 的实际坐标定位。MoveFloatingWindow 的 SetFixed 基于工作区原点，不能直接传 Qt/IPC 的屏幕坐标；当前使用实际坐标差 AdjustFixed。

Qt 6.9 原生移动会发送模拟松手，不能据此结束动画；当前忽略该事件，等待 Leave 后 Enter。气泡不能 hide/show 重新映射，否则 niri 会先居中；使用 QGraphicsOpacityEffect 仅隐藏绘制，松手定位后等待本机弹簧动画约 700ms 恢复。33 个针对性测试通过；原 test_native_interactions 的 3 失败、1 错误未解决且未纳入通过数，该测试没有加载适配且含缺失素材。新代码、现有 Windows 入口和实际 Windows 回归验收需区分。

为去除透明画布矩形阴影，在本机 ~/.config/niri/__custom__.kdl 末尾添加仓库 configs/niri-probe.kdl 的 include，仅作用于 app-id bailong-linux-probe。备份在 work/linux-validation/niri-custom-before.kdl，niri validate 通过；未改 GTK 主题、Codex 配置或系统 Python。后续移植重点：分离气泡、其他面板、跨屏及位置持久化；本次人工确认不覆盖这些路径。


### Linux 持续运行入口（2026-10-25）

新增根目录 run_linux.py，装配入口为 linux_app/launcher.py，无演示数据、截图采样或自动退出计时。原 tools/linux_live.py、tools/linux_niri.py、tools/linux_codex_readonly 移至 linux_app/live.py、linux_app/niri.py、linux_app/codex_readonly；验证脚本和测试共用这些模块，运行时平台替换使用可恢复的上下文管理器，未修改 app 生产源码。requirements-linux.txt 为共享依赖源，原验证依赖文件引用它。

PyCharm 配置文件为 .run/Bailong Linux.run.xml，名称「桌宠 Linux」，使用项目 Python 3.12 .venv，启动 run_linux.py，无参数。niri 现有规则扩展为同时匹配正式 bailong-linux 与原 bailong-linux-probe，无新增全局主题改动。

默认自身状态位于 XDG_DATA_HOME/codex-bailong/BailongEnhanced（本机 ~/.local/share/codex-bailong/BailongEnhanced）。首次仅迁移验证阶段的设置和已校验素材，后续保留设置/素材选择；凭据不复制，Codex 数据源仍只读，额度程序仍使用 bwrap。QLockFile 使用零过期时间防止长期运行后误判；同目录重复启动已拒绝。SIGINT/SIGTERM 关闭窗口及工作线程并释放目录锁。

36 个针对性测试通过，实际正式入口验证额度、Token、IPC 均正常，SIGTERM 退出码 0、目录锁已释放。config.toml/auth.json/gtk.css 内容保持一致。未做整小时耐久测试，时限移除依据正式入口没有生命周期计时器。一次启动后 10 秒采样 CPU 约占单核 20.6%，早期 RSS 约 259 MiB，包含角色动画与实时监测，不能视为长期平均或性能优化结论。其他既有移植边界保留，详见 docs/LINUX.md。


### niri 自主走动（2026-10-25）

Linux 正式入口不再强制 wandering=False；首次升级开启并写 linux_wandering_ready 标记，之后保留用户暂停状态。仅 linux_app/niri.py 适配 DesktopPet 的 Python 坐标读写与 start/stop_walk，原移动路径、范围、速度、随机调度和动画选择仍使用 app 原实现，app 源码未修改。

actual_position 将 niri 输出内位置加上当前 QScreen 逻辑原点；走动请求保留最新目标，33ms 计时器仅在有移动时运行，等布局变化确认后才提交下一增量，1500ms 无确认则停止本次走动。鼠标按下通过原 stop_walk 路径清除目标与计时器，原生拖动结束后待实际布局恢复再更新 wander_home。气泡沿用现有布局订阅跟随。

用户确认会走动，询问被拖走姿态；已核实原素材没有 moveAnimations，原 start_walk 回退 dragAnimation，未更改素材/动画。两分钟采样含 walk/drag/landing/idle，气泡布局误差中位数0、最大2逻辑像素、异步连接采样峰值1；另一真实 niri 窗口测试在走动中注入鼠标按下后位置保持不变，超出边界目标被约束到完整画布内。41项针对性测试通过；跨屏、不同缩放和所有输入设备尚未完整人工验收。详情与重现证据在 docs/LINUX.md、忽略目录 work/linux-validation/walk-result.json 和 walk-contract.json。

### Linux/niri 位置持久化

新增 linux_app/placement.py，仅在 Linux 适配安装期间替换保存和恢复入口。Windows 初始化时会调用 save_settings，而 Wayland 窗口此时只有占位坐标，因此必须保留原 screen_position，等 niri 确认布局后再更新。输出名称从 WorkspacesChanged 映射取得，不能依赖跨屏时可能滞后的 QWidget.screen。恢复按显示器、输出内坐标分两阶段确认，气泡跨工作区也须先确认再计算相对增量。位置锁不阻止恢复；缺失输出回退首个 Qt 屏幕。45 项针对性测试通过，双屏、真实重启、位置锁与缺失输出配置在独立状态目录实测通过，证据 work/linux-validation/placement-*.json。未改 app 目录或 Windows 入口，也未证明全部 Windows 专属功能已移植。

### Linux 重置公告卡片一直查询中

正式入口遗留 refresh_reset_feed 空替换且没有创建 ResetThread，导致 reset_snapshot 永久为 None。已去掉空替换并在 launcher.create_pet 连接原 ResetThread 的 ready、failed、diagnostic、busy、completed 信号后启动，原关闭流程负责停止线程。无须改 app 或 Windows 入口。52 项公告、刷新与启动相关测试通过；独立状态目录的真实 GUI 启动实测公告接口 0.79 秒返回 available/ok，卡片状态 empty、文案「暂无安排」，证据 work/linux-validation/reset-result.json。公告为第三方公开信息，不是本机账户额度到账保证。

### Linux 面板几何桥接

linux_app/surfaces.py 仅替换 CompactBubble、DailyReport、NativeLanding 的几何读写，保留原逻辑目标与原画布动画，niri 布局确认后提交下一次增量。日报窗口透明度使用 QGraphicsOpacityEffect，因为 Wayland 原生 windowOpacity 不受支持。DesktopPet.geometry 同步实际布局；缩放位移在 apply_settings 结束后提交，避免被关闭走动时的 stop_walk 清除。分离气泡采用 startSystemMove，模拟松手与实际结束分开处理。原 app 目录无改动。

原生窗口阶段检查见忽略目录 work/linux-validation/surface_check.py、surfaces-result.json、surface-check.log，稳定位置误差 0–1 逻辑像素，设置/聊天抓图已检查；位置恢复回归通过。21 项 Linux 测试通过；原 55 项面板测试中两项 test_bubble_resize 锚点测试失败（该次运行没有安装 Linux 适配），日志 gui-unit.log。动画闪跳、分离拖动及多屏交互仍需用户人工验收，不可写成全部视觉一致性已证明。测试进程均已退出。

### Linux 便携包及 AppImage

独立构建环境为 work/linux-build/venv（Python 3.12.14），固定依赖 tools/requirements-linux-build.txt；构建 tools/build_linux.py 使用 PyInstaller onedir 平铺布局，resources ROOT 在冻结后取可执行文件父目录。包内只包含已逐项 SHA256 校验的轻量素材，不从验证 state 或日常设置生成发布配置。tools/package_linux.py 从同一目录生成 tar.zst 与 AppImage；官方工具和运行时 SHA 固定在 tools/appimage-tools.lock.json。包内资源只读，用户数据目录沿用原 Linux 默认位置。

运行时 --check-runtime 完整校验素材、初始化 TLS、查询真实额度。宿主 Codex 查询前恢复 LD_LIBRARY_PATH_ORIG；退出信号处理器仅设置标记，由 Qt 定时器执行关闭，避免信号重入 Qt notify 时崩溃。严格测试沙箱须 --dev-bind /dev /dev，否则 /dev/null 权限错误会导致误判额度查询失败。AppImage 在用户命名空间可能不能执行 FUSE 挂载，因此分别测试正常挂载和 --appimage-extract-and-run。

本机 niri 的桌宠规则已原样复制到 ~/.config/niri/bailong-linux.kdl，仅替换 __custom__.kdl 中该条 include，niri validate 通过，原文件备份 work/linux-build/niri-custom-before.kdl。源码可移走而不影响规则。Windows app 目录未改动，未提交或推送。
