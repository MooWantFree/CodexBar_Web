# 使用与统计说明

[返回 README](../README.md)

## 统计与价格规则

API 等价金额属于估算, 不是订阅账单. 当前调用统计尚未按账号区分.

### Fast 档位与倍率

API Fast 倍率采用 CodexBar 的硬编码表方式维护, 与订阅 Credits 倍率分开.
Fast 档位同时读取会话 JSONL 的 `thread_settings_applied` 设置与 `logs_2.sqlite` 请求 trace.
逐轮请求的明确档位优先于会话设置, 会话设置优先于 trace 缺失推断; 两种来源分别保存,
trace 不存在、暂时不可读或已被清理时仍使用已保存证据. 设置按轮次生效并随增量扫描保存;
即使设置事件晚于 `task_started`, 首条有效用量出现前仍会更新当前轮次的档位.
子会话不会继承复制的父会话设置. 升级后自动重解析可用日志并修复旧 trace ID 的引号,
保留已采集用量和价格快照.
GPT-6 Sol 按[官方模型定价](https://developers.openai.com/api/docs/models/gpt-6-sol)使用 2×.
GPT-6 Luna 按[官方模型定价](https://developers.openai.com/api/docs/models/gpt-6-luna)使用 2×.
旧快照缺失的已知 Fast 倍率会在读取时补齐, 保留当时的 Token 单价、日期和手工覆盖.

### 自动定价与价格快照

新 OpenAI 模型的 Standard 单价从 models.dev 的 OpenAI 目录自动读取. 扫描后检查价格,
后台每 15 分钟检查一次; 有效目录缓存 24 小时, 未知模型或刷新失败按 15 分钟冷却重试.
Fast 倍率尚未收录时, 按 CodexBar 使用 Standard 基价暂估, 金额显示黄色并在 hover 中说明
尚未包含 Fast 加价. 完全无价时保留 Token 和未知标记, 不借用其他供应商的同名模型价格.
新模型的旧快照缺价时使用首次取得的价格回填并标为估算, 后续涨价不改变该回填金额.
手工覆盖保留明确的未知或数字倍率; 账号额度外推只使用已确认的价格.

### 账号额度采样

服务启动后自动读取账号额度, 此后每 65 秒采样一次; 关闭浏览器页面后仍继续记录, 页面打开时也会自动更新.
提前重置需要两次间隔至少 60 秒的一致读数确认, 通常几分钟内出现在“重置日期”中, 重置时刻仍标为推算.
自动识别需要本地服务持续运行、Codex 已登录且额度查询成功; 服务停止期间未采集的历史无法完整还原.

## 托盘与后台运行

在仓库根目录运行:

```sh
uv sync --locked
uv run codex-token-report --tray
```

默认打开 `http://127.0.0.1:8765`. 加上 `--port 18765` 可指定端口;
加上 `--no-browser` 可仅启动服务与托盘, 启动时不打开网页:

```sh
uv run codex-token-report --tray --no-browser
```

托盘菜单提供“打开网页”和“退出”. Windows 双击图标打开网页、右键显示菜单;
macOS 点击菜单栏图标显示菜单; Linux 按桌面环境的原生方式显示菜单.
关闭网页后服务仍继续采集, 选择“退出”会停止服务并等待正在进行的工作结束.
日志保存在应用数据目录的 `tray.log`（自动轮转）.

Windows 若希望使用不创建控制台窗口的 Python 运行服务, 可从 PowerShell 启动:

```powershell
uv run pythonw -m codex_token_report.cli --tray
```

macOS / Linux 若希望关闭终端后继续运行, 可从图形桌面的终端启动:

```sh
nohup uv run codex-token-report --tray --no-browser >/dev/null 2>&1 &
```

Linux 需在图形桌面会话中运行, 并安装 GTK 3 和 AppIndicator / Ayatana AppIndicator
的系统库及 GI introspection 数据. 虚拟环境中还需 PyGObject; 先按
[PyGObject 官方安装说明](https://pygobject.gnome.org/getting_started.html)准备发行版所需的构建依赖,
再运行:

```sh
uv sync --locked --extra tray-linux
uv run --extra tray-linux codex-token-report --tray
```

后续启动（包括 `nohup` 后的 `uv run`）也需保留 `--extra tray-linux`, 避免 uv 同步时移除可选依赖.
GNOME 等桌面可能还需启用托盘扩展; 具体限制见
[pystray 后端说明](https://pystray.readthedocs.io/en/latest/usage.html#supported-backends).
仅支持默认点击、不支持菜单的 Xorg 后端会明确报错, 避免缺少“退出”入口.
无图形桌面或托盘不可用时, 可运行 `uv run codex-token-report` 使用普通网页模式.
当前原生托盘交互已在 Windows 验证; macOS / Linux 仍需对应桌面环境实机验证.

## 日志目录与数据保存

首次启动扫描所选 Codex 目录中的 `sessions`、`archived_sessions` 和 `logs_2.sqlite`.
默认读取环境变量 `CODEX_HOME`, 未设置时使用当前用户主目录下的 `.codex`: Windows
为 `$env:USERPROFILE\.codex`, macOS / Linux 为 `~/.codex`. 通过 `--codex-home` 可以覆盖.

也可在网页“设置”中选择含 `sessions`、`archived_sessions` 或 `logs_2.sqlite` 的 Codex
主目录. 目录必须已存在且可读; 点击“保存并扫描”后立即切换并扫描, 已有统计和历史继续保留.
目录设置随统计数据库持久保存, 后续启动与 `--scan-only` 默认继续使用.
显式 `--codex-home` 优先于保存的设置; 未保存时才读取 `CODEX_HOME` 或默认目录.

统计数据库默认位于 Windows 的 `$env:LOCALAPPDATA\CodexTokenReport\usage.sqlite3`,
macOS / Linux 为 `~/.local/share/codex-token-report/usage.sqlite3`. 可通过 `--data-dir`
或 `CODEX_TOKEN_REPORT_DATA_DIR` 指定持久数据目录; 不要把它放进将被清空的日志目录.

### 扫描耗时

扫描跳过未变化的 JSONL, 对追加内容增量读取. 档位按现有证据重新计算, 仅写入分类、
证据来源或计价模型发生变化的记录; 后到的 trace 和覆盖区间仍可修正历史分类.

`--scan-only`、`POST /api/scan` 的结果及报表中的 `last_scan` 包含 `duration_seconds`
和 `timings_seconds`. 分阶段字段为 `discovery`（文件发现与检查点读取）、`session_files`
（日志读取及入库）、`priority_trace`、`classify_service_tiers`、`price_snapshots` 和
`session_titles`. 耗时使用单调时钟, 包含价格快照和会话标题处理; 不包含等待扫描锁、
保存耗时记录本身、后续在线价格刷新或前端报表刷新. `finished_at` 在这些扫描阶段完成后记录.

## 指定 Codex CLI

实时额度查询需要可用的 Codex CLI 和 ChatGPT 登录. macOS / Linux 需确保 `codex`
在当前终端的 `PATH` 中; 也可指定可执行文件:

```sh
export CODEX_TOKEN_REPORT_CODEX_BIN="/path/to/codex"
```

Windows PowerShell 对应设置:

```powershell
$env:CODEX_TOKEN_REPORT_CODEX_BIN = "C:\path\to\codex.exe"
```

## 更多命令

只更新本地统计数据库, 不启动网页:

```powershell
uv run codex-token-report --scan-only
```

指定 Codex 目录和数据目录（Windows / PowerShell）:

```powershell
uv run codex-token-report `
  --codex-home "$env:USERPROFILE\.codex" `
  --data-dir "$env:LOCALAPPDATA\CodexTokenReport"
```

macOS / Linux 对应命令:

```sh
uv run codex-token-report --codex-home "$HOME/.codex" --data-dir "$HOME/.local/share/codex-token-report"
```

## 可选桌面窗口

桌面窗口使用 pywebview, 与浏览器和托盘模式分别启动. macOS / Linux 未实测.

```sh
uv sync --locked --extra desktop
uv run --extra desktop codex-token-report-desktop
```

## 前端构建与更新

仓库已包含前端构建产物, 正常启动不需要 Node.js. 如果更新或修改了 `frontend/` 中的前端源码,
需要安装 Node.js 20 或更新版本, 并在仓库根目录重新安装前端依赖、编译前端（Windows / macOS / Linux 均适用）:

```powershell
npm --prefix frontend ci
npm --prefix frontend run build
```

构建产物会更新到 `src/codex_token_report/static/webui/`. 更新代码后, 关闭旧服务,
在仓库根目录重新启动, 然后刷新浏览器页面:

```powershell
uv run codex-token-report
```

后端不会自动重载; 若页面与运行中的后端版本不匹配, 统计区会明确提示重启.

## 开发与测试

```powershell
uv sync --locked --extra dev
uv run --extra dev ruff check src tests scripts
uv run --extra dev pytest
```

WebUI 使用 React, 源码位于 `frontend/`, 按页面、共享组件、数据请求和翻译模块拆分.
生产构建随 Python 包分发, 正常启动不需要 Node.js. 修改前端需安装 Node.js 20 或更新版本:

```powershell
cd frontend
npm ci
npm test
npm run build
```

热更新开发和扩展方式见 [前端开发说明](../frontend/README.md).
