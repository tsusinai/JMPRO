# AGENTS.md

JM 漫画 QQ Bot — QQ 群/私聊猫娘 Bot，支持漫画下载/搜索、AI 聊天。中文项目，注释与文案均用中文。

## 两套运行时（重要边界）

同一业务有两套并行实现，改逻辑时注意是否需要两边同步：

1. **Windows 本机独立 Bot**（本仓库根目录）：`jm_bot.py` 直连 NapCat WebSocket，处理 `/jm` 命令。依赖本机 GoodbyeDPI 翻墙访问 JMComic CDN。
2. **AstrBot 插件**（`astrbot_plugin_jmcomic/`）：部署在云服务器（`ssh jmbot`）的 AstrBot 内，运行时不需要翻墙（通过 `jm_proxy.py` + SSH 反向隧道 -R 8888 走本机代理）。

`download.py`、`messages.py` 在根目录和插件目录各有一份，分属不同运行时，勿混改。

## 目录结构

- `jm_bot.py` — 独立 Bot 入口（OneBot WS 监听 + 命令路由）
- `ai_chat.py` — `/jm ask` AI 聊天（DeepSeek API，Anthropic 兼容协议；密钥取环境变量，回退读 Claude Code settings.json）
- `download.py` — 下载 + PDF 生成 + 上传群文件（`FIRST_IMAGE_TIMEOUT=300` 超时保护）
- `messages.py` — 文案库（每类回复多变体随机选取，改文案先看这里）
- `napcat_utils.py` — 共享工具（NapCat HTTP `127.0.0.1:3002`、上传、磁盘、缓存）
- `napcat_ws_bridge.py` — 连 NapCat WS 3001 → 提交消息到 AstrBot 3003（群聊识图桥接，服务器上也跑一份 `bridge.service`）
- `jm_proxy.py` — JMComic HTTP 代理（127.0.0.1:8888），配合 `start_jm_proxy.bat` 的 SSH 反向隧道供服务器使用
- `astrbot_plugin_jmcomic/` — AstrBot 插件（`main.py`、`commands.py`、`personas.py`、`agent_tools.py`、`option.yml`、`metadata.yaml`）
- `goodbyedpi/` — JMComic CDN 翻墙工具（仅 Windows，必须用 `-5` 模式，`-6` 黑名单模式在 Win11 无效）
- `downloads/`、`pdfs/`、`zips/` — 下载产物；`bot.log` — 运行日志
- `docs/` — `TECHNICAL.md`（架构）、`TECH_STACK.md`（技术栈存档）、`USAGE.md`（使用说明）；服务器部署/服务管理详见 `CLAUDE.md`

## 启动 / 测试

```bash
# 一键启动（NapCat + GoodbyeDPI + jm_bot；会先 taskkill /f /im python.exe 防多实例）
start.bat

# 本机 AstrBot（WebUI http://localhost:6185）
astrbot_start.bat

# JM 代理 + SSH 反向隧道（供服务器下载用，窗口须保持开启）
start_jm_proxy.bat

# 测试（纯脚本，非 pytest）：不 import jm_bot.py（有副作用），只测 napcat_utils/download
python test_all.py
python test_domain.py   # CDN 域名连通性

# 依赖无 requirements.txt，装在系统 Python：jmcomic websockets requests anthropic img2pdf
```

## 关键配置与约定

- `option.yml`（插件目录）：JMComic 配置。域名手动固定为 `www.cdnhjk.net`、`www.cdnplaystation6.cc`；postman 必须用 `requests`（curl_cffi 不走 GoodbyeDPI 的 WinDivert 过滤）
- jmcomic 2.7.1 的 `Feature.export_pdf` 不可用 → 用 `img2pdf` 手动兜底
- 服务器三服务均为 systemd：`napcat`（root，3001/3002/6099）、`astrbot`（admin，6185/3003）、`bridge`；`journalctl -u <name> -f` 看日志
- QQ 重启后大概率需重新扫码（账号 1601410002），二维码：`journalctl -u napcat | grep 二维码解码URL`

## 已知坑

- 配置 JSON 带 BOM → 读写必须 `utf-8-sig`
- Windows 用户名 `a'su's` 含单引号 → shell 命令中路径要特殊处理（用双引号包裹）
- 含中文的文件/目录跨平台传输禁止直接 `scp`（编码损坏），必须 `tar` 打包后传输
- 服务器上 AstrBot 的 `WorkingDirectory` 必须是 `/home/admin`，否则报 "not a valid root directory"
- 插件加载依赖 `metadata.yaml` + `main.py`（或 `__init__.py`），缺一即失败
- 服务器端 companion 插件配置有两处重复（basic_config + 顶层），修改时需两处同步
- 服务器 NapCat 配置目录属 root，改动需 sudo；SQLite（data_v4.db）为 WAL 模式，直接改库即时生效，无需重启
