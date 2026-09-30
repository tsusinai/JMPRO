# JMPRO · JM 漫画 QQ Bot

面向 QQ 群聊和私聊的中文 Bot 项目，提供漫画搜索、详情查询、排行榜、随机推荐、批量下载、PDF / ZIP 导出，以及 AI 聊天和角色切换。项目同时保留 Windows 独立 Bot 与 AstrBot 插件实现；模块化独立 Bot 位于 `jm_bot_v2/`，另有语音回复支持。

本文按仓库代码整理于 **2026-09-30**。服务器版本、账号、插件启停和公网可用性需要在实际部署时核对；历史运维记录不能替代当前运行状态。

## 目录导航

- [功能与运行方式](#功能与运行方式)
- [项目结构](#项目结构)
- [Windows 快速开始](#windows-快速开始)
- [配置说明](#配置说明)
- [QQ 命令](#qq-命令)
- [AstrBot 插件部署](#astrbot-插件部署)
- [代理与桥接](#代理与桥接)
- [数据与日常维护](#数据与日常维护)
- [测试与验证](#测试与验证)
- [常见问题](#常见问题)
- [Git 与协作](#git-与协作)
- [文档与许可](#文档与许可)

## 功能与运行方式

| 能力 | 根目录独立 Bot | 模块化独立 Bot v2 | AstrBot 插件 |
| --- | --- | --- | --- |
| 搜索 / 详情 / 排行榜 / 推荐 | 支持 | 支持 | 支持 |
| 单本 / 批量下载，PDF / ZIP 输出 | 支持 | 支持 | 支持 |
| 下载进度 / 去重 / 停止 / 缓存管理 | 支持 | 支持 | 支持 |
| AI 对话入口 | `/jm ask` | `/jm ask` | AstrBot 对话与 LLM 工具 |
| 角色选择 | `/jm role` | `/jm role` | AstrBot 人格设置 |
| 语音回复 | 未提供 v2 的语音命令 | `/jm voice`，Vocu / 硅基流动 | 由 AstrBot 或其他 TTS 插件配置 |
| 配置方式 | 源码常量 + 环境变量 + `option.yml` | `config.json` + 环境变量 + `option.yml` | AstrBot 设置 + 插件 `option.yml` |
| 入口 | `jm_bot.py` | `jm_bot_v2/main.py` | `astrbot_plugin_jmcomic/main.py` / `__init__.py` |

两种部署路线分别是：

```text
Windows 独立运行
QQ → NapCat（OneBot WS 3001 / HTTP 3002）→ 独立 Bot
                                              ├─ JMComic → 网络链路 → 图片 CDN
                                              ├─ PDF / ZIP → NapCat → QQ 文件
                                              └─ AI API / TTS API（v2）

AstrBot 插件运行
QQ → NapCat → AstrBot（OneBot 接入 3003）→ JMComic 插件
                                                ├─ /jm 命令
                                                ├─ LLM 漫画工具
                                                └─ 本机代理 + SSH 反向隧道
```

**只为同一 QQ 会话启用一个 `/jm` 处理入口**，以免旧 Bot、v2 与 AstrBot 插件同时响应。三份下载实现和文案库属于各自运行环境，修改时要明确目标，不能把同名文件直接覆盖到另一套运行时。

## 项目结构

```text
JMPRO/
├─ jm_bot.py                    # 原版独立 Bot：WS 监听与命令路由
├─ ai_chat.py                   # AI 意图分类、对话和角色
├─ download.py                  # 下载、进度、PDF / ZIP 生成
├─ messages.py                  # 中文回复文案与随机变体
├─ napcat_utils.py              # OneBot HTTP、上传、磁盘与 JSON 工具
├─ option.yml                   # 原版 JMComic 配置
├─ start.bat                    # 原版完整启动脚本
├─ jm_bot_v2/                   # 模块化独立 Bot
│  ├─ main.py / start.bat        # Python 入口 / 完整启动脚本
│  ├─ config.example.json       # 无密钥的配置示例
│  ├─ config.json               # 本机实际配置
│  ├─ option.yml                # v2 独立的 JMComic 配置
│  ├─ requirements.txt          # v2 依赖及版本记录
│  ├─ tts_voices.json           # 角色与语音音色对应表
│  ├─ bot/                     # 配置、路由、下载、聊天、TTS 等模块
│  │  └─ handlers/             # download / browse / chat / misc
│  └─ tests/test_all.py         # 独立脚本测试
├─ astrbot_plugin_jmcomic/
│  ├─ metadata.yaml            # 插件标识与版本
│  ├─ main.py / __init__.py     # 插件加载与命令 / 工具注册
│  ├─ commands.py              # /jm 命令处理
│  ├─ agent_tools.py           # LLM 工具处理
│  ├─ download.py / state.py    # 异步下载与状态
│  ├─ messages.py / utils.py    # 插件文案与辅助工具
│  ├─ personas.py / personas/  # 人格导出与模板
│  ├─ option.yml               # 插件自己的 JMComic 配置
│  └─ test_all.py              # 不依赖 AstrBot 启动的辅助测试
├─ jm_proxy.py                 # 本机 HTTP / CONNECT 代理，8888
├─ napcat_ws_bridge.py          # NapCat 消息 → AstrBot conversation API
├─ start_jm_proxy.bat           # 8888 代理 + SSH 反向隧道
├─ start_proxy_tunnel.bat       # 本机 7892 → 服务器 10808 的隧道
├─ start_proxy_tunnel_silent.vbs # 后台启动上述隧道
├─ stop_proxy_tunnel.bat        # 隧道停止脚本
├─ astrbot_start.bat            # 本机 AstrBot 启动脚本
├─ goodbyedpi/                  # Windows 网络工具与驱动
├─ test_all.py / test_domain.py # 原版辅助测试 / 联网检查
├─ docs/                       # 使用、架构、技术栈与 TTS 设计
└─ downloads/、pdfs/、zips/     # 运行时下载产物
```

`server_backup/` 是本机的服务器数据备份，包含配置、数据库和私聊数据，不是运行依赖，也不应作为分发内容。

## Windows 快速开始

### 1. 准备环境

- Windows 与可登录的 QQ / NapCat，开启 OneBot v11 正向 WebSocket 和 HTTP 服务。
- Python：v2 依赖文件记录的开发环境为 **Python 3.14**，其他版本需自行验证。
- 下载网络链路：本项目 Windows 配置使用 GoodbyeDPI `-5` 模式；驱动启动可能需要管理员权限。
- AI 聊天可选：兼容 Anthropic 协议的 API 与密钥。
- 语音回复可选：TTS API 密钥、自有音色 ID，并在 Bot 与 NapCat 的运行环境中准备 `ffmpeg`。

根目录没有统一的 `requirements.txt`。新部署可使用 v2 自带依赖文件；其中 `certifi-win32` 在文件中标记为可选证书补丁。固定版本用于记录项目环境，不表示已经验证所有 Python / Windows 组合。

### 2. 创建隔离的 Python 环境

在项目根目录运行 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\jm_bot_v2\requirements.txt
```

### 3. 准备 v2 配置

新部署且没有 `config.json` 时，从示例创建配置：

```powershell
if (!(Test-Path .\jm_bot_v2\config.json)) {
    Copy-Item .\jm_bot_v2\config.example.json .\jm_bot_v2\config.json
}
```

填写 `napcat.access_token`，使其与 NapCat 的 HTTP / WS 服务配置一致。默认地址为 `http://127.0.0.1:3002` 和 `ws://127.0.0.1:3001`。已有配置应直接编辑，避免覆盖现有密钥或阈值。

AI 配置可在当前 PowerShell 会话通过环境变量提供：

```powershell
$env:ANTHROPIC_AUTH_TOKEN = "替换为自己的密钥"
$env:ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = "替换为服务商支持的模型名"
```

URL 是项目默认配置；模型名需与实际服务商账号匹配。这些环境变量只影响当前终端及其子进程。

### 4. 启动并检查

先启动 NapCat、完成 QQ 登录并启动所需网络工具，再启动 v2：

```powershell
Set-Location .\jm_bot_v2
..\.venv\Scripts\python.exe .\main.py
```

看到 `已连接 NapCat WebSocket` 后，在测试群或私聊中发送 `/jm help`。用 `Ctrl+C` 退出。

`jm_bot_v2/start.bat` 和根目录 `start.bat` 可一键启动，但都写有特定机器的 NapCat 路径和 QQ 账号，使用前必须调整；它们还会执行 **`taskkill /f /im python.exe`，终止本机所有同名 Python 进程**，并重启 GoodbyeDPI。共享开发环境优先按上面步骤手动启动。

### 原版独立 Bot

在根目录运行 `.\.venv\Scripts\python.exe .\jm_bot.py`。原版的 NapCat token 分布在 `jm_bot.py` 与 `napcat_utils.py`，需要与实际 NapCat 配置同步；原版 AI 优先读环境变量，缺少密钥时会尝试读取 `~/.claude/settings.json`。v2 不再读取该文件，迁移后需重新配置 AI 参数。

## 配置说明

### v2：`jm_bot_v2/config.json`

配置读取使用 `utf-8-sig`，允许 UTF-8 BOM；缺失字段与 `bot/config.py` 的默认值深合并。配置在导入时加载，修改后重启 Bot。

| 配置段 | 用途 | 代码默认值 / 说明 |
| --- | --- | --- |
| `napcat` | HTTP / WS 地址与 access token | 本机 3002 / 3001，token 默认空 |
| `ai` | 密钥、兼容接口、模型 | 三个 `ANTHROPIC_*` 环境变量分别优先于对应字段 |
| `limits` | 下载冷却、查询超时与随机查询范围 | 同群 15 秒、全局 20 秒；API 20 秒 |
| `disk` | 磁盘预警与阻止下载阈值 | 500 MB / 100 MB |
| `upload_timeout` | PDF / ZIP 上传超时 | PDF 基础 600 秒、每 MB 增加 5 秒、上限 1800 秒；ZIP 600 秒 |
| `threads` | 下载 / I/O / API 线程池 | 3 / 4 / 6 |
| `tts` | 语音引擎、密钥、音色、超时 | 引擎 `vocu`；默认截取最多 300 字 |
| `antiban` | 消息与 AI 回复节流 | 出站间隔 1.2 秒；同群 AI 冷却 8 秒；全局 AI 10 条 / 分钟 |

NapCat 与 TTS 的密钥直接取配置字段，**没有与 AI 相同的环境变量覆盖机制**。节流能降低发送频率，但不能保证 QQ 账号免于平台风控。

### JMComic：三份 `option.yml`

根目录、v2 和插件分别读取自己的 `option.yml`。目前 YAML 固定域名为 `www.cdnhjk.net`、`www.cdnplaystation6.cc`，下载图片解码为 JPG，章节 / 图片并发配置为 2 / 4。域名可用性会变化，排查时以当前网络结果为准。

Windows 使用 GoodbyeDPI 时保留 `client.postman.type: requests`；项目记录 `curl_cffi` 不能按预期经过该链路。部分查询函数使用库默认客户端，修改 YAML 不一定能覆盖所有查询路径，应核对对应运行时的客户端构建代码。

PDF 使用 `img2pdf`，原版与 v2 下载实现提供手动兜底；不能仅依赖 jmcomic 2.7.x 的 `Feature.export_pdf`。插件 YAML 另有 `after_album` 的 `img2pdf` 配置。

### v2 语音

在 `config.json` 的 `tts` 段填写 `engine`（`vocu` 或 `siliconflow`）、`api_key` 与 `default_voice_id`。需要为不同角色指定音色时，编辑 `tts_voices.json` 的 `voices` 映射，键为角色编号。

开启 `/jm voice on` 后，AI 纯聊天回复走语音；搜索列表、详情、下载进度等仍为文字。合成或发送失败会回退到文字。Vocu 实现支持同步调用以及异步任务降级、音频缓存；两种引擎的密钥和音色 ID 必须对应自己的账号。

## QQ 命令

下表中的独立 Bot 包括原版与 v2；语音标为 v2 专属。

| 命令 | 用途 | 适用范围 |
| --- | --- | --- |
| `/jm help` | 主帮助 | 全部 |
| `/jm help ask`、`/jm help manage` | 分项帮助 | 独立 Bot |
| `/jm search <关键词>` | 搜索 | 全部 |
| `/jm info <ID>` | 漫画详情 | 全部 |
| `/jm rank [day\|week\|month]` | 排行榜，默认日榜 | 全部 |
| `/jm category <标签>` | 标签搜索 | 全部 |
| `/jm random` | 随机推荐 | 全部 |
| `/jm random --top` / `--best` / `--new` | 指定推荐模式 | 全部 |
| `/jm random --tag <标签>` | 指定标签 | 独立 Bot |
| `/jm random --tag:<标签>` | 指定标签，注意冒号 | 当前插件代码 |
| `/jm <ID>` | 默认 PDF 下载 | 全部，插件简写 ID 为 4～8 位 |
| `/jm download <ID> [pdf\|zip]` | 指定输出格式 | 全部 |
| `/jm download <ID1> <ID2> [pdf\|zip]` | 批量下载 | 全部 |
| `/jm queue` | 查看下载队列 / 进度 | 全部 |
| `/jm stop` | 请求停止下载 | 全部 |
| `/jm cache` | 查看缓存空间 | 全部 |
| `/jm cache clean [天数]` | 清理旧下载目录，默认 7 天 | 全部，会删除符合条件的缓存 |
| `/jm ask <内容>` | AI 对话与意图分类 | 独立 Bot；插件提示改用直接对话 |
| `/jm ask clear` | 清空当前会话聊天历史 | 独立 Bot |
| `/jm role [编号]` | 查看 / 切换会话角色 | 独立 Bot |
| `/jm voice [on\|off\|status]` | 设置 / 查询语音模式，默认查询 | v2 |
| `/jm restart` | Bot 软重启 | 独立 Bot |

原版与 v2 内置角色编号为 1～6，另有隐藏角色 0；具体角色名称以 `/jm role` 为准。AstrBot 人格模板单独由 WebUI 管理。

独立 Bot 只处理以 `/jm` 开头的消息，普通聊天需使用 `/jm ask`。AstrBot 可在正确配置对话模型与工具后，通过 @Bot 或私聊调用 `search_manga`、`get_manga_info`、`get_rank`、`random_recommend`、`download_manga` 五个工具；工具实际执行依赖 AstrBot 的模型和平台配置。

## AstrBot 插件部署

1. 准备 AstrBot 和 QQ 平台适配器。NapCat 接入通常使用 OneBot v11；`metadata.yaml` 声明 `aiocqhttp` 与 `qq_official`，文件上传能力仍需在具体适配器上验证。
2. 将 **`astrbot_plugin_jmcomic/` 整个目录**放入 AstrBot 的 `data/plugins/`，保留 `metadata.yaml`、`main.py`、`__init__.py` 和相对导入依赖。项目根目录包含其他运行时，不应整仓当作单个插件安装。
3. 在 AstrBot 实际使用的 Python 环境安装 `jmcomic`、`img2pdf`、`requests`、`certifi`。依赖要装到 AstrBot 的解释器中，系统 Python 装包不等于插件运行环境已有依赖。
4. 配置插件网络链路、OneBot 服务和需要的 AI Provider。先建立代理隧道，再加载插件。
5. 在 WebUI 启用 / 重载插件，检查加载日志，然后在测试会话使用 `/jm help` 验证路由。

服务器由 systemd 管理时，可查看：

```bash
systemctl status napcat astrbot bridge
journalctl -u astrbot --since "10 min ago" --no-pager
journalctl -u napcat -f
```

本项目已有服务器安装约定要求 AstrBot `WorkingDirectory=/home/admin`。复制部署文件包含中文名称时，先 `tar` 打包，再传输和解包。插件更新只替换相应插件代码，保留运行数据；不要把本机备份数据库直接覆盖到运行实例。

已有服务器的具体目录、服务配置和历史变更记录见 [CLAUDE.md](CLAUDE.md)。该文件含私有部署信息，服务器实况需要另行检查。

## 代理与桥接

### 本仓库插件的 8888 代理链路

```text
服务器 127.0.0.1:8888
    → SSH -R 8888:127.0.0.1:8888
    → Windows jm_proxy.py:8888
    → Windows 网络链路 / GoodbyeDPI
```

配置好 SSH 别名 `jmbot` 后，在 Windows 分别保持两个终端运行：

```powershell
python .\jm_proxy.py
```

```powershell
ssh -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -N -R 8888:127.0.0.1:8888 jmbot
```

也可使用 `start_jm_proxy.bat`。插件读取 `JM_PROXY_HOST` / `JM_PROXY_PORT`，默认 `127.0.0.1:8888`，并在模块导入时检测代理。**当前本仓库插件会在代理不可达时阻止相关操作**；建立隧道后需重载插件，不能依赖云端文档所述的另一版“动态探测并回退直连”行为。

### 10808 加速隧道脚本

`start_proxy_tunnel.bat` 映射服务器 10808 到本机代理 7892，并在连接断开后重试；本机 7892 代理必须先就绪。静默入口为 `start_proxy_tunnel_silent.vbs`。

这组脚本对应历史云端加速配置；本仓库插件默认使用 8888。若要让本仓库插件使用 10808，需要把 `JM_PROXY_PORT=10808` 设置到 **AstrBot 进程环境**并重载，且不能因此假定当前插件有直连回退。结束隧道时先停止启动脚本 / 重试循环，避免 SSH 子进程退出后再次连接。

### 群聊识图桥接

`napcat_ws_bridge.py` 监听 NapCat WS 3001，并通过 AstrBot WebUI 的 conversation API 提交消息；它不是直接把消息转发到 OneBot 3003。WS token、AstrBot 地址与登录参数在文件中配置，启动前需与目标实例一致。

桥接依赖具体 AstrBot API、登录态和图片处理配置。仅启动独立 Bot 不需要运行桥接；独立 Bot 本身也不等于拥有 AstrBot 的识图、知识库和其他插件能力。

## 数据与日常维护

| 内容 | 保存位置 / 用途 |
| --- | --- |
| 原版下载、PDF、ZIP、日志、会话 JSON | 项目根目录对应文件 / 子目录 |
| v2 下载、PDF、ZIP、日志、会话 JSON | 全部位于 `jm_bot_v2/`，与原版隔离 |
| 插件下载、PDF、ZIP | 插件目录内对应子目录；状态还使用 AstrBot KV |
| `chat_history.json` | 聊天历史 |
| `group_roles.json` | 会话角色选择 |
| `rate_limits.json` | 请求限流状态 |
| `voice_modes.json`、`tts_cache/` | v2 语音开关与缓存 |

从原版迁移 v2 时，先停止旧 Bot；若需要沿用状态，备份后把聊天历史、角色和限流 JSON 复制到 v2 目录。重新检查 `config.json` 与 `option.yml`，然后只启动 v2。下载文件不会自动迁移。

查看 `bot.log` 和 `download_errors.log` 排查失败。下载首图超时保护为 300 秒，期间也有卡死检测与切换域名逻辑；整本耗时较长不一定是进程卡死。使用 `/jm queue` 查看状态，再决定是否 `/jm stop`。清缓存前核对需要保留的文件。

## 测试与验证

现有测试是普通 Python 脚本，不要求 pytest。从根目录可执行：

```powershell
.\.venv\Scripts\python.exe .\test_all.py
.\.venv\Scripts\python.exe .\jm_bot_v2\tests\test_all.py
.\.venv\Scripts\python.exe .\astrbot_plugin_jmcomic\test_all.py
```

它们覆盖命令正则、文案、文件工具、格式化、状态和部分下载辅助逻辑；v2 还有 TTS 模拟测试。原版测试不导入 `jm_bot.py`，v2 测试不导入启动入口，插件辅助测试不要求启动 AstrBot。

根目录测试包含复制的命令正则，不能视为真实路由的完整集成验证；脚本通过也不代表 QQ 登录、模型、上传、TTS 或服务器部署已经可用。

需要实网时单独运行：

```powershell
.\.venv\Scripts\python.exe .\test_domain.py
```

真实验收顺序：QQ 登录 → OneBot 连接 → `/jm help` → 搜索 / 详情 → 自有或已授权内容的小规模下载与上传 → 可选 AI / 语音。域名检查会访问外网，下载与上传会产生文件和消息。

## 常见问题

| 现象 | 排查方法 |
| --- | --- |
| WS 连接失败或一直重连 | 等 QQ 登录完成；检查 NapCat WS 服务、端口和 token，不以 QQ 进程存在作为登录完成证据 |
| 收到两份回复 | 检查原版、v2、AstrBot 插件是否同时处理同一会话，停用重复入口 |
| AI 提示未配置密钥 | v2 检查环境变量与 `config.json.ai`；原版另有 Claude settings 回退；环境变量变更后重新启动进程 |
| 首图超时 / CDN 不通 | 检查实际网络、GoodbyeDPI `-5`、requests postman 与对应 `option.yml`，必要时运行域名检查 |
| 插件提示代理不可达 | 检查本机代理、SSH 反向端口和 AstrBot 环境变量；代理就绪后重载插件 |
| PDF 未生成 | 检查图片是否完整、`img2pdf` 是否安装在实际解释器中，以及手动兜底 / 插件 YAML 日志 |
| 下载完成但上传失败 | 检查 NapCat HTTP 鉴权、QQ 权限、目标适配器、文件路径是否能被 NapCat 进程访问 |
| 语音回退为文字 | 检查 TTS 密钥、引擎和自有音色 ID、`ffmpeg`、NapCat record 转换与 Bot 日志 |
| JSON 解码失败 | 用 UTF-8 保存；处理带 BOM 的配置时使用 `utf-8-sig`，避免手工拼接损坏 JSON |
| AstrBot 插件不加载 | 检查插件目录层级、metadata 与入口、依赖解释器，再查看加载日志 |
| 服务器文件名乱码 | 含中文路径使用 tar 打包传输；不要直接 scp 目录 |

## Git 与协作

本目录已有独立的本地 Git 仓库，主分支为 `main`。远程仓库名称、归属和可见性由维护者配置；`metadata.yaml` 的插件链接不能代替本项目实际的 Git remote。

日常先检查状态，再创建功能分支；提交时明确列出本次文件：

```powershell
git status --short --branch
git switch -c codex/功能名称
git add README.md jm_bot_v2/config.example.json .gitignore
git diff --cached --stat
git commit -m "docs: 完善项目说明与配置示例"
```

远程配置前检查 `git remote -v`。只有远程为空且目标仓库已确认时，才执行：

```powershell
git remote add origin <自己的仓库地址>
git push -u origin main
```

**目前本地历史包含实际 `config.json`、源码中的凭据、私有运维文档和 `server_backup/` 数据。直接推送会把历史一起上传。** `.gitignore` 仅防止新增未跟踪文件，不会清除已经跟踪的配置、备份或历史秘密；创建公开仓库前应使用经过脱敏的独立源码快照，并处理历史凭据。私有仓库也应明确备份与个人数据的纳入范围。

开发约定见 [AGENTS.md](AGENTS.md)：注释和用户文案使用中文，原版 / v2 / 插件边界要明确，改文案先看所属运行时的 `messages.py`。说明修改影响的运行方式及验证结果；不要把无关服务器服务、数据库、聊天数据或登录二维码混入提交。

## 文档与许可

| 文档 | 内容与适用范围 |
| --- | --- |
| [v2 README](jm_bot_v2/README.md) | 模块结构、迁移背景；其中随仓库保存私有配置的说明属于历史约定 |
| [使用说明](docs/USAGE.md) | 早期 AstrBot 使用说明，账号、密码和部分行为为历史记录 |
| [技术架构](docs/TECHNICAL.md) | 原有架构与实现说明 |
| [技术栈存档](docs/TECH_STACK.md) | 特定历史时点的部署记录，不代表实时状态 |
| [TTS 设计](docs/TTS_DESIGN.md) | 语音设计过程；当前 v2 已有 Vocu / 硅基流动实现 |
| [变更日志](CHANGELOG.md) | 项目变更记录 |
| [运维记录](CLAUDE.md) | 私有部署细节与历史操作，发布前需审查 |

仓库目前没有独立的 `LICENSE`，不能据此认定为采用某个开源许可证。第三方工具、驱动、API 与资源按各自许可和服务条款使用；漫画与音频资源由使用者自行准备并确认使用授权。
