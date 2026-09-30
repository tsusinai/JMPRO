# JM Bot v2

> 面向 QQ 群聊与私聊的模块化 JM 漫画 Bot

[![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![OneBot](https://img.shields.io/badge/QQ-OneBot%20v11-12B7F5)](https://onebot.dev/)
[![License](https://img.shields.io/badge/license-not%20specified-lightgrey)](#许可与使用边界)

JM Bot v2 将 JMComic 搜索、推荐、详情、下载、PDF/ZIP 导出、AI 对话、角色口吻、TTS 和风控节流拆成独立模块，运行产物全部留在 `jm_bot_v2/` 内。仓库只发布 v2 实现，不包含旧版单体 Bot、AstrBot 插件、服务器备份或私有运维配置。

## 能做什么

| 模块 | 能力 |
| --- | --- |
| 漫画浏览 | 关键词搜索、漫画详情、日/周/月排行、分类筛选、随机推荐 |
| 下载交付 | 单本或批量下载，生成 PDF / ZIP，进度通知，重复任务去重 |
| 任务控制 | 查看队列、停止任务、查看磁盘占用、按天数清理旧缓存 |
| AI 对话 | `/jm ask` 意图分类、漫画工具调用、会话历史和上下文压缩 |
| 角色系统 | 7 种角色口吻，按群保存角色选择 |
| 语音 | v2 的 `/jm voice` 开关，Vocu 主引擎、硅基流动备选、缓存和文字回退 |
| 稳定性 | WebSocket 自动重连、API 超时、下载卡死检测、消息节流和 AI 限频 |

## 运行结构

```text
QQ
 │
 └─ NapCat / OneBot v11
       ├─ HTTP 127.0.0.1:3002   ← 发消息、上传文件
       └─ WS   127.0.0.1:3001   → bot/runner.py
                                      │
                                      ├─ router.py       命令匹配
                                      ├─ handlers/       浏览、下载、聊天、杂项
                                      ├─ downloader.py   JMComic 下载与进度
                                      ├─ ai_chat.py      Anthropic 兼容 API
                                      └─ tts.py          Vocu / 硅基流动
```

Bot 只接收以 `/jm` 开头的消息。漫画数据来自 JMComic，AI 和 TTS 是可选的外部服务；没有配置密钥时，下载和浏览功能仍可独立工作。

## 快速开始

### 环境

- Windows 10/11
- Python 3.14（其他版本需要自行验证）
- 已运行并登录的 NapCat，启用 OneBot v11 HTTP/WS
- 可访问 JMComic CDN 的网络环境；需要时自行准备 GoodbyeDPI 或其他代理
- 可选：Anthropic 兼容 AI API、Vocu/硅基流动 TTS API、ffmpeg

### 安装

```powershell
cd jm_bot_v2
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.json config.json
```

编辑 `config.json`，至少确认 `napcat.http_url`、`napcat.ws_url` 和 `napcat.access_token` 与本机 NapCat 一致。`config.json` 已被 `.gitignore` 忽略，永远不要把真实 token 或 API key 写进提交。

### 启动

```powershell
cd jm_bot_v2
.\.venv\Scripts\python.exe main.py
```

或双击 `jm_bot_v2/start.bat`。脚本只启动 v2，不会终止系统中其他 Python 进程，也不写入固定用户路径。启动日志出现 `已连接 NapCat WebSocket` 后，在测试群发送 `/jm help`。

AI 配置也可以通过环境变量覆盖 `config.json` 中的对应字段：

```powershell
$env:ANTHROPIC_AUTH_TOKEN = "你的 API Key"
$env:ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = "服务商支持的模型名"
```

### 语音配置

在 `config.json` 的 `tts` 段填写引擎和密钥，在 `tts_voices.json` 中把 `YOUR_VOCU_VOICE_ID` 换成自己的音色 ID。安装并确保 `ffmpeg` 在 PATH 中，然后使用：

```text
/jm voice on       开启本群 AI 语音
/jm voice off      关闭本群 AI 语音
/jm voice status   查看当前状态
```

语音只作用于 AI 纯聊天回复；搜索、详情、排行、下载进度和错误消息保持文字。合成或发送失败会自动回退文字。

## 命令

| 命令 | 说明 |
| --- | --- |
| `/jm help` | 查看帮助 |
| `/jm search <关键词>` | 搜索漫画 |
| `/jm info <ID>` | 查看详情 |
| `/jm rank [day\|week\|month]` | 查看排行榜，默认日榜 |
| `/jm category <标签>` | 按标签筛选 |
| `/jm random` | 随机推荐 |
| `/jm random --top` / `--best` / `--new` | 指定推荐模式 |
| `/jm random --tag <标签>` | 按标签随机推荐 |
| `/jm <ID>` | 下载并生成 PDF（兼容简写） |
| `/jm download <ID> [pdf\|zip]` | 指定输出格式 |
| `/jm download <ID1> <ID2> [pdf\|zip]` | 批量下载 |
| `/jm queue` | 查看队列和进度 |
| `/jm stop` | 停止下载 |
| `/jm cache` | 查看缓存占用 |
| `/jm cache clean [天数]` | 清理旧缓存，默认 7 天 |
| `/jm ask <内容>` | AI 对话和意图执行 |
| `/jm ask clear` | 清除当前会话历史 |
| `/jm role [编号]` | 查看或切换角色 |
| `/jm voice [on\|off\|status]` | 设置或查看语音模式 |
| `/jm restart` | 请求 Bot 软重启 |

AI 对话需要模型服务可用；下载、上传还需要 NapCat HTTP 权限和足够磁盘空间。

## 目录

```text
jm_bot_v2/
├─ main.py                 # 入口、日志与退出清理
├─ config.example.json     # 脱敏配置模板
├─ config.json             # 本机配置（忽略，不提交）
├─ option.yml              # JMComic 域名、超时与并发
├─ requirements.txt        # Python 依赖
├─ start.bat               # 安全的 Windows 启动脚本
├─ tts_voices.json         # 音色占位配置
├─ bot/
│  ├─ config.py            # 配置和运行目录
│  ├─ runner.py            # WS 连接、重连、消息过滤
│  ├─ router.py            # `/jm` 命令路由
│  ├─ handlers/            # browse / chat / download / misc
│  ├─ jm_client.py         # JMComic 客户端
│  ├─ downloader.py        # 下载、进度、PDF/ZIP
│  ├─ napcat.py             # OneBot HTTP API
│  ├─ messaging.py         # 角色口吻、语音和发送门面
│  ├─ ai_chat.py           # 意图分类和对话
│  ├─ tts.py                # TTS 引擎与音频缓存
│  ├─ roles.py              # 角色与群角色持久化
│  ├─ antiban.py            # 出站与 AI 节流
│  └─ fsutils.py            # JSON、磁盘、日志工具
└─ tests/test_all.py       # 无网络的脚本测试
```

## 配置重点

| 配置段 | 作用 | 默认重点 |
| --- | --- | --- |
| `napcat` | OneBot HTTP/WS | `3002` / `3001` |
| `ai` | Anthropic 兼容 API | DeepSeek 地址与模型占位 |
| `limits` | 查询、冷却和随机推荐 | 同群 15 秒、全局 20 秒 |
| `disk` | 磁盘预警 | 500 MB 预警、100 MB 临界 |
| `upload_timeout` | 文件上传 | PDF 最长 1800 秒 |
| `threads` | 下载 / I/O / API 线程池 | 3 / 4 / 6 |
| `tts` | 引擎、音色和超时 | 默认 Vocu，最多 300 字 |
| `antiban` | 发送和 AI 限频 | 1.2 秒发送间隔、10 条/分钟 |

`option.yml` 使用 `requests` postman，域名固定值只是当前配置记录，不保证长期可用。PDF 由 `img2pdf` 生成，下载器保留超时、卡死检测和域名切换逻辑。

## 测试

测试脚本不启动 WebSocket、不调用真实 AI/TTS，也不会导入 Bot 主循环：

```powershell
cd jm_bot_v2
python tests/test_all.py
```

联网检查需要单独在项目外完成；真实验收建议依次验证 NapCat 登录、WS 连接、`/jm help`、搜索、详情、小规模下载和文件上传。测试通过不代表外部 API、QQ 登录或 CDN 当前可用。

## 排错

- **WS 不连接**：确认 NapCat 已登录、端口和 access token 一致。
- **没有回复**：确认只启动一个 v2 实例，并检查 `bot.log`。
- **首图超时**：检查网络链路、`option.yml` 域名和证书；首图保护为 300 秒。
- **PDF/ZIP 上传失败**：检查 NapCat HTTP 鉴权、文件权限、QQ 群文件权限和磁盘空间。
- **AI 不可用**：检查 `ANTHROPIC_*` 环境变量或 `config.json.ai`，重启进程后再试。
- **语音回退文字**：检查 TTS key、音色 ID、ffmpeg 和 `tts_cache/`。
- **中文配置读取失败**：配置文件按 UTF-8/UTF-8-SIG 保存，不要手工破坏 JSON。

## Git 与安全

提交前检查：

```powershell
git status --short
git diff --check
git diff -- . ':(exclude)config.json'
```

不要提交 `config.json`、真实 API key、NapCat token、QQ 登录二维码、聊天历史、下载产物或音频缓存。仓库只发布 v2 代码和脱敏文档；漫画内容、音频和第三方服务按使用者自己的授权与服务条款处理。

## 许可与使用边界

本仓库当前没有声明独立开源许可证。JMComic、NapCat、GoodbyeDPI、OneBot、AI/TTS 服务及其依赖分别遵循各自许可证和服务条款。请仅对拥有合法访问或使用权的内容执行搜索、下载、存储和群文件上传。
