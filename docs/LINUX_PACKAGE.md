# 白龙桌宠 Linux 便携版

v1.2.1-linux-preview.4 包含 niri 原生 Wayland 与 KDE Plasma X11/XWayland 后端，启动时自动识别。KDE 源码验收与限制详见 [KDE 说明](https://github.com/helantianshen/codex-bailong-desktop-pet/blob/main/docs/KDE.md)；本次包体实测环境为 CachyOS/niri，未做 KDE 安装包实机验收。

本构建面向 CachyOS/Arch x86_64、niri 原生 Wayland。包含 Python 3.12、Qt 与轻量素材，不需要激活虚拟环境或安装系统 Python 包。不是所有 Linux 发行版通用包。

便携包解压后执行 `./AppRun`；AppImage 先 `chmod +x 文件名.AppImage`，再执行它。也可使用 `--appimage-extract-and-run` 绕过 FUSE 挂载，但会产生临时解压开销。

宿主需要对应桌面、bubblewrap（bwrap）和本机 Codex。CLI 自动从 BAILONG_CODEX、PATH 或已知安装位置查找；其他安装位置通过 `--codex-cli /绝对路径/codex` 指定。支持 `--codex-home` 与 `--data-dir`，示例：

```sh
./AppRun --codex-cli /usr/lib/chatgpt/resources/codex
```

默认桌宠设置位于 `${XDG_DATA_HOME:-~/.local/share}/codex-bailong/BailongEnhanced`。两种包共用此位置，更新程序不覆盖设置，不包含用户会话或凭据。素材位于程序包内，程序包可只读；不要把 `--data-dir` 指向程序包或 Codex 目录。

同一数据目录不允许同时运行源码版、便携版和 AppImage。切换前从桌宠菜单退出旧实例；重复启动只会报错，不会关闭旧实例。

niri 窗口规则需放在稳定位置。将包内 `configs/bailong-linux.kdl` 复制至 `~/.config/niri/bailong-linux.kdl`，在实际加载的 niri 配置中添加该文件的绝对路径 include。已有相同规则则无需重复添加。AppImage 用户可通过 `--appimage-extract` 取得规则文件。不要 include AppImage 临时挂载目录。规则使用本机 niri 的 background-effect 扩展，其他版本需先验证兼容性；本包不会自动修改全局主题或 niri 配置。

读取真实 Codex 数据；额度查询通过 bubblewrap 只读访问原配置与认证文件。不写入 Codex 配置。设置中的“开机启动”和“随 Codex 启动”分别登记独立的 systemd 用户服务，互不依赖。启用前请把 AppImage 或便携目录放在固定位置；AppImage 登记外部文件路径，移动后需重新关闭并开启开关。已接入随 Codex 关闭与会话跳转，跳转需 xdg-utils 和 codex:// 协议处理器；聊天密钥及 Windows 更新入口尚未适配，勿使用 Windows 安装器更新此包。获取新 Linux 包后替换程序文件即可，保留用户数据目录。

素材来源与使用边界见 NOTICE.md 和 app/licenses；字体授权随 app/fonts 提供。

## 构建

构建环境独立于开发 `.venv`，所有依赖只装入仓库忽略目录：

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
  --runtime /绝对路径/runtime-x86_64
```

两个构建命令均拒绝覆盖已有目标目录。打包过程不会安装到系统或调用 Windows 构建脚本。

运行时自检使用 `./AppRun --check-runtime` 或 `./文件名.AppImage --check-runtime`，验证完整素材、TLS 上下文以及真实只读额度查询，然后退出。自检也持有状态目录锁；已有日常实例时请指定独立 `--data-dir`，不要与日常实例共享写入。

## GitHub Actions

`Source checks` 在 push、pull request 和手动触发时分别运行 Windows 与 Linux 检查。Linux 使用 Ubuntu 22.04、Python 3.12 和 offscreen Qt，执行 Linux 适配及公告/刷新测试；Windows job 保持独立。

在 Actions 中选择 `Build Linux packages` → `Run workflow`，选定分支后手动构建。工作流按素材清单下载并逐文件验证轻量素材，按锁文件验证 AppImage 工具，然后生成便携 tar.zst、AppImage 和 SHA256SUMS.txt。文件名包含源码提交的前 12 位，成功后从该次运行的 Artifacts 下载，保留 7 天；下载 AppImage 后需赋予执行权限。此工作流只保存 CI 产物，不创建或覆盖 Release。

CI 会验证归档载荷，并在源码目录外执行两种包的 `--help`。Ubuntu runner 没有真实 niri 会话与 Codex 账户，这些检查不能替代拖动、走动、面板定位及真实数据接入验收。采用 Ubuntu 22.04 构建基线也不代表已经支持 GNOME 或所有 Linux 发行版。
