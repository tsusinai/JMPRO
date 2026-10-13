# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

JM 漫画 QQ Bot — QQ 群/私聊 AI 猫娘 Bot。基于 AstrBot v4.28.2 + 插件。支持漫画下载/搜索、B站视频解析、AI聊天、图片识图、知识库。

> 2026-09-28 已从 v4.26.6 升级至 v4.28.2（uv tool 安装，备份 ~/astrbot_backup_v4.26.6_20260928_1830.tar.gz）。QQ 号风控后服务器切换到 QQ 官方 bot 通道（qq_official），aiocqhttp/NapCat 通道已禁用；jm 漫画功能由 Windows 本机独立 Bot（根目录 / jm_bot_v2）承担，服务器 jm 相关插件已停用。

## 架构 (2026-07-17)

**服务器** (云服务器 2核4G, Linux):
```
QQ Linux(3.2.31) → NapCat Shell(v4.18.28, LD_PRELOAD) → AstrBot v4.28.2 (:6185, :3003)
  ├─ WS Server(3001) → napcat_ws_bridge.py (群聊识图)
  ├─ HTTP Server(3002) ← AstrBot 发送消息
  └─ WebUI(6099) — NapCat 管理界面

systemd 持久化: napcat.service → astrbot.service → bridge.service

> 2026-09-28: AstrBot 升级 v4.26.6→v4.28.2（备份 ~/astrbot_backup_v4.26.6_20260928_1830.tar.gz）；
> NapCat 升级 v4.18.9→v4.18.28（备份 ~/napcat_backup_v4.18.28_pre，配置备份 ~/napcat_config_backup_20260928.tar.gz）。
> QQ 换新号 **2143388598**（旧号 1601410002 风控弃用；快速登录列表仅剩旧号，新号依赖 QQ 本地登录态自动登录，重启后若掉线需扫码）。
> aiocqhttp 桥接已重新启用（此前 qq_official 通道期间 aiocqhttp 曾 enable:false），NapCat → 3003 连接正常，群消息实时流入。
> NapCat WebUI v4.18.28 登录 API 变化：POST /api/auth/login body 为 {hash: SHA256(token+".napcat"), totpCode:""}，返回 data.Credential；QR 接口 GetQQLoginQRcode 返回解码 URL 而非图片。
```

**Windows 本机**: GoodbyeDPI / 本地代理 (127.0.0.1:7892), 开发/测试
  - `start_proxy_tunnel.bat`: 一键建立 SSH 反向代理隧道 (`10808` -> `127.0.0.1:7892`)，为云端 JMComic 加速
  - `start_proxy_tunnel_silent.vbs`: 后台静默启动隧道
  - `stop_proxy_tunnel.bat`: 停止反向代理隧道

### JMComic 网络加速机制 (2026-09-28)
- 服务器端 `astrbot_plugin_jmcomic` 支持**动态自适应代理**：
  - 自动探测 `127.0.0.1:10808`（5秒防抖缓存）；
  - 若连通：自动将 `JmOption` 注入本地隧道代理，漫画搜索/详情/下载全走本机代理加速；
  - 若未连通/本机关机：无缝自动回退到原生直连，不阻断正常服务。

### 高松灯 (Tomori) 专属音色 TTS 接入 (2026-09-28)
- **音色模型**: 硅基流动 `FunAudioLLM/CosyVoice2-0.5B`，克隆音色 URI 为 `speech:tomori_v2:d9c9i8lsssvc73dqeta0:nlfkvwsaxnqotkhsvvld`（上传时必须带 Prompt Text 台词文本对齐）。
- **AstrBot 配置**:
  - Provider: `siliconflow/tomori_tts` (`type: "openai_tts_api"`)
  - 全局配置: `provider_tts_settings.enable = true`, `dual_output = true` (双轨发送文字+语音), `trigger_probability = 1.0`。
- **系统依赖**: 服务器通过 RPM Fusion 安装了 `ffmpeg 4.4.8`，用于将 TTS 生成的 wav 转换为 NapCat/QQ 所需的 silk 富媒体格式。

## SSH 连接

```bash
# 本机 ~/.ssh/config:
# Host jmbot
#     HostName <server_ip>
#     User admin
#     IdentityFile ~/.ssh/id_ed25519
#     ServerAliveInterval 60

ssh jmbot  # 操作服务器
```

密钥路径: `~/.ssh/id_ed25519` (ed25519)

## 启动 / 服务管理

所有服务使用 **systemd** 管理，配置文件在 `/etc/systemd/system/`:

| 服务 | 用户 | 端口 | 开机自启 | 自动重启 |
|------|------|------|---------|---------|
| `napcat.service` | root | 3001, 3002, 6099 | ✅ | ✅ |
| `astrbot.service` | admin | 6185, 3003 | ✅ | ✅ |
| `bridge.service` | admin | — | ✅ | ✅ |

```bash
# 日常管理
systemctl status napcat astrbot bridge   # 查看状态
systemctl restart napcat                  # 重启 (需重新扫码QQ!)
systemctl stop napcat                     # 停止
journalctl -u napcat -f                   # 实时日志
journalctl -u astrbot --since "10 min ago"

# 开机自启已启用 (systemctl enable)
# 崩溃自动重启已配置 (Restart=always)
```

### NapCat 服务详情

```ini
# /etc/systemd/system/napcat.service
[Service]
Type=simple
User=root
WorkingDirectory=/home/admin/.astrbot/data
ExecStartPre=/usr/bin/bash -c "pgrep -x Xvfb >/dev/null || (Xvfb :1 -screen 0 1280x720x16 +extension GLX +render > /dev/null 2>&1 & sleep 2)"
ExecStart=/usr/bin/bash -c "export DISPLAY=:1 && ./launcher.sh"
Environment=DISPLAY=:1
Environment=NAPCAT_QUICK_ACCOUNT=2143388598
KillMode=control-group
TimeoutStopSec=15
LimitNOFILE=65535
Restart=always
RestartSec=10
```

> **内存与稳定性保护 (2026-09-28)**：
> - 服务器 2G 内存无 Swap 导致此前频繁触发系统内核 OOM-Killer（强杀 QQ 与 AstrBot）。已配置 **2GB Swapfile** 并持久化（`/swapfile`，`vm.swappiness=10`）。
> - NapCat 配置自动快速登录：`launcher.sh` 增加 `-q 2143388598`，`napcat.service` 注入 `NAPCAT_QUICK_ACCOUNT=2143388598`，`webui.json` 固化 `"autoLoginAccount": "2143388598"`，并在 `onebot11_2143388598.json` 中禁用了无效的 8080 Webhook 上报，防止重启后卡在等待扫码。

### AstrBot 服务详情

```ini
# /etc/systemd/system/astrbot.service
[Service]
Type=simple
User=admin
WorkingDirectory=/home/admin    # 关键! 必须在 $HOME 下启动
ExecStartPre=rm -f ~/data && ln -sf ~/.astrbot/data ~/data
ExecStart=/home/admin/.local/bin/astrbot run
Restart=always
RestartSec=5
```

### Bridge 服务详情

```ini
# /etc/systemd/system/bridge.service
[Service]
Type=simple
User=admin
ExecStart=/usr/bin/python3 /home/admin/napcat_ws_bridge.py
Restart=always
RestartSec=10
```

### QQ 扫码登录

QQ 重启后需要扫码登录（登录态有时会缓存，有时需要重新扫）:

```bash
# 1. 导出二维码到本机
ssh jmbot "base64 /home/admin/.astrbot/data/napcat/cache/qrcode.png" > qr.b64 && base64 -d qr.b64 > qr.png

# 2. 或直接从日志获取 URL
journalctl -u napcat --no-pager | grep "二维码解码URL"
```

扫码账号: **2143388598**（2026-09-28 起启用；旧号 1601410002 已弃用）

### 端口一览

| 端口 | 绑定 | 服务 | 用途 |
|------|------|------|------|
| 3001 | 127.0.0.1 | NapCat | OneBot WS Server (桥接) |
| 3002 | 127.0.0.1 | NapCat | OneBot HTTP Server |
| 3003 | 127.0.0.1 | AstrBot | OneBot WS Server (NapCat 连此端口) |
| 6185 | 0.0.0.0 | AstrBot | WebUI 仪表盘 |
| 6099 | 0.0.0.0 | NapCat | NapCat WebUI |

### WebUI 访问

- AstrBot: http://<server_ip>:6185 (账密详见服务器配置)
- NapCat: http://<server_ip>:6099 (WebUI token 详见配置)

## 人格系统

### 7 个人格 (已迁移至服务器)

存储在 `data_v4.db` 的 `personas` 表中，通过 AstrBot WebUI → 人格设定 管理:

| Persona ID | 名称 | 自称 | 称呼用户 |
|-----------|------|------|---------|
| `jm_catgirl` | 色色猫娘 (默认) | 本喵 | 主人 |
| `jm_gou_da_fa` | 郭大发 | 我 | 你 |
| `jm_tsundere` | 傲娇大小姐 | 本小姐 | 庶民/杂鱼 |
| `jm_succubus` | 邪魅魅魔 | 妾身 | 契约者/小羊羔 |
| `jm_oneesan` | 温柔大姐姐 | 姐姐 | 小可爱/宝贝 |
| `jm_yandere` | 病娇 | 私 | Darling |
| `jm_gyaru` | 反差痴女 | 人家 | 哥哥 |

默认人格: `jm_catgirl` (在 `cmd_config.json` → `provider_settings.default_personality`)

### 人格迁移流程

```bash
# 1. 从本地导出
cat JMPRO/astrbot_plugin_jmcomic/personas/_all_personas.json

# 2. 上传到服务器
scp _all_personas.json jmbot:/tmp/

# 3. 导入数据库
python3 -c "
import sqlite3, json
db = sqlite3.connect('/home/admin/.astrbot/data/data_v4.db')
personas = json.load(open('/tmp/all_personas.json'))
for i, p in enumerate(personas):
    db.execute('INSERT INTO personas (created_at, updated_at, persona_id, system_prompt, begin_dialogs, sort_order) VALUES (datetime(), datetime(), ?, ?, ?, ?)',
        (p['persona_id'], p['system_prompt'], json.dumps(p['begin_dialogs'], ensure_ascii=False), i))
db.commit()
"

# 4. 设置默认人格
# 修改 cmd_config.json: provider_settings.default_personality = "jm_catgirl"
```

## 知识库

### 存储位置

`/home/admin/.astrbot/data/knowledge_base/`:

```
knowledge_base/
├── kb.db                          # SQLite 主库 (嵌入向量)
├── anime_games.md                 # 动漫游戏知识 (19KB)
├── bilibili_memes.md              # B站梗知识 (9.5KB)
├── 30a25586-62a7-4a72-9508-76ef4fbd6727/  # 角色扮演知识库
│   ├── doc.db                     # 文档嵌入
│   ├── files/
│   └── medias/
├── 78132e0e-299c-43f5-98aa-1cd3c7dd8139/  # (空)
├── 79854340-a074-447c-b762-089a5118a5a9/  # (空)
└── af110e7e-409b-49cd-8ec0-a740bb6ee17d/  # (含 doc.db)
    ├── doc.db
    ├── files/
    └── medias/
```

### 嵌入模型

- Provider: `siliconflow/bge-m3` (免费)
- API: `https://api.siliconflow.cn/v1`
- 模型: `BAAI/bge-m3`

### 知识库迁移流程

```bash
# 知识库文件直接用 scp -r 传输 (无中文路径问题)
scp -r knowledge_base/* jmbot:/home/admin/.astrbot/data/knowledge_base/
```

⚠️ 包含中文名的文件/目录必须用 **tar 打包**传输，否则编码会损坏！

## 插件系统

### 插件清单 (2026-09-28 实测)

QQ 风控换号后插件已大幅精简，**当前启用**：

| 插件 | 说明 |
|------|------|
| astrbot_plugin_AstrNa | 系统优化 |
| astrbot_plugin_changsha_travel | 长沙旅游 |
| astrbot_plugin_exa_web_search | Exa 联网搜索（未配 API Key） |
| astrbot_plugin_polite_silence | 骚扰拒答 |
| builtin_commands / astrbot | 内置 |

**已停用**（在 `data/plugins/disabled_plugins/`，QQ 风控后停用，jm 功能改由 Windows 本机独立 Bot 承担）：jmcomic、private_companion、memory_companion、smart_imagechat_hub、Bilibili-Full-Featured、bilibili、biliread、fund、STEmbedding。

### 插件页面 (Plugin Pages)

部分插件自带 WebUI 面板（在插件详情页可打开）:

| 插件 | 页面目录 | 页面名 |
|------|---------|--------|
| memory_companion | `pages/记忆面板/` | 记忆面板 |
| private_companion | `pages/陪伴面板/` | 陪伴面板 |
| smart_imagechat_hub | `pages/image-center-page/` | image-center-page |

**⚠️ 迁移注意事项**: 插件 pages 目录含中文名，直接从 Windows scp 会导致编码损坏（文件名变 `??????`）。
必须用 tar 打包传输:

```bash
# 正确做法
cd ~/.astrbot/data/plugins
tar -cvf /tmp/plugin_pages.tar \
  astrbot_plugin_memory_companion/pages \
  astrbot_plugin_private_companion/pages \
  astrbot_plugin_smart_imagechat_hub/pages
scp /tmp/plugin_pages.tar jmbot:/tmp/
ssh jmbot "cd /home/admin/.astrbot/data/plugins && sudo tar -xvf /tmp/plugin_pages.tar"

# ❌ 错误做法: 直接 scp -r 包含中文的目录
```

### 插件详情页排查

如果插件详情页打不开:
1. 检查 `journalctl -u astrbot -f` 有无错误
2. 检查损坏的插件目录: `ls -la /home/admin/.astrbot/data/plugins/*/metadata.yaml`
3. 检查 pages 目录权限: `find /home/admin/.astrbot/data/plugins/*/pages -ls`
4. 重启 AstrBot: `systemctl restart astrbot`

## 模型分工

| 场景 | Provider ID | 说明 |
|------|-------------|------|
| 主 LLM (文本) | deepseek/deepseek-v4-pro | 对话/工具调用 |
| 识图/Vision (所有) | xiaomi/mimo-v2.5 | 图片理解 |
| 嵌入/知识库 | siliconflow/bge-m3 | 免费 embedding |
| 生图 | 百炼 wanx2.1-t2i-turbo | 图片生成 |
| 语音合成 (TTS) | siliconflow/tomori_tts | FunAudioLLM/CosyVoice2-0.5B (高松灯专属音色克隆) |

### 语音与人设指令规范 (2026-09-28)
- **人设风格与口头禅**：
  - 彻底删除语气词“喵”、“喵~”、“喵呜”及自称“本喵”（改为“我”）；
  - 加入口头禅：“我操了老铁”，在日常闲聊、惊叹、吐槽时自然带出；
  - 影响范围涵盖：`data_v4.db.personas`、`astrbot_plugin_private_companion_config.json` 及 `astrbot_plugin_jmcomic/agent_tools.py`。
- **三种语音回复模式与指令**：
  - 由 `astrbot_plugin_tts_switch` 插件接管，支持单群/单会话独立持久化配置：
    - `1` / `/tts 1` / `/语音 1`：**仅语音**（回复仅发送语音，不附带文字）；
    - `2` / `/tts 2` / `/语音 2`：**仅文字**（回复仅发送文字，不合成语音）；
    - `3` / `/tts 3` / `/语音 3`：**两种都有**（双轨输出，既发文字又发语音）；
    - `/tts global on/off`：全局 TTS 总开关控制。

## 核心配置文件

| 文件 | 位置 | 用途 |
|------|------|------|
| `cmd_config.json` | `~/.astrbot/data/` | 全局: providers, personality, timeout |
| `private_companion_config.json` | `~/.astrbot/data/config/` | 陪伴: 人设, 识图, 主动私聊, 模型 |
| `memory_companion_config.json` | `~/.astrbot/data/config/` | 记忆: 捕获/检索/图谱/衰减 |
| `onebot11_1601410002.json` | `napcat/config/` | OneBot WS/HTTP 端口 |
| `napcat_protocol_1601410002.json` | `napcat/config/` | 协议启用开关 |
| `option.yml` | `plugins/astrbot_plugin_jmcomic/` | JMComic CDN + img2pdf |
| `napcat_ws_bridge.py` | `/home/admin/` | 群聊识图桥接 |

## 关键配置阈值

| 配置 | 值 |
|------|-----|
| tool_call_timeout | 600s |
| max_agent_step | 5 |
| hard_limit | 120s窗口, 8条 |
| 主动私聊 | idle=10min, interval=10min |
| 免打扰 | 02:00-08:00 |
| 猫娘人设 | 软甜风格, 叫主人, 1-2句 |
| private_image_timeout | 60s, wait 90s |
| MiMo降权 | 60s |

## 服务器目录结构

```
/home/admin/
├── .astrbot/
│   ├── astrbot.lock
│   └── data/
│       ├── cmd_config.json           # 主配置
│       ├── data_v4.db                # SQLite (人格/偏好/对话/会话)
│       ├── config/                   # 插件 JSON 配置
│       ├── plugins/                  # 11 个插件目录
│       ├── plugin_data/              # 插件运行时数据
│       ├── knowledge_base/           # 知识库 (kb.db + 集合)
│       ├── logs/                     # 日志
│       ├── temp/                     # 临时文件
│       └── napcat/                   # NapCat Shell
│           ├── config/               # OneBot + 协议配置
│           ├── cache/qrcode.png      # QQ 扫码登录
│           ├── napcat.mjs            # NapCat 主程序
│           └── launcher.sh           # QQ + NapCat 启动脚本
├── data -> .astrbot/data             # 软链接 (AstrBot 需要)
├── napcat_ws_bridge.py              # 群聊识图桥接
└── .local/bin/astrbot               # AstrBot CLI
```

## 已知问题

- **记忆插件库损坏已重建（2026-09-28）**：memory_companion"我会牢牢记住你"主库 evidence 列乱码 + 库文件物理损坏（malformed，历史 Windows→服务器迁移遗留），按用户指示删库重建（插件自动 init）。旧库备份：`/home/admin/mc_backup_20260928.db` + 插件目录 3 个 before-memory-atom-v2 备份。教训：跨平台迁移 SQLite 库文件必须 tar 打包

- **插件面板 HTML 打不开（v4.28+）**：插件页面改为 JWT asset_token 鉴权（`/api/plugin/page/content/<plugin>/<page>/`，401 = 缺 token）。升级/重启后旧会话失效会导致面板加载失败，**重新登录 WebUI 即恢复**（前端重新拿 entry config 里的 asset_token）。private_companion v6.5.6"我会永远陪着你"陪伴面板曾遇到（2026-09-28，重登自愈）

- GoodbyeDPI 需 Windows 保持运行 (JMComic CDN翻墙)
- jmcomic 2.7.1 Feature.export_pdf 不工作 → 手动 img2pdf 兜底
- 群聊识图依赖桥接稳定性
- NapCat 不支持 QQ 3.2.31 PacketBackend (用 LD_PRELOAD/Frida 模式)
- JMComic 下载功能仅在 Windows 侧可用 (需 DPI)
- **中文文件/目录跨平台传输编码损坏** — 必须用 tar 打包
- **插件 pages 目录编码问题** — 已有 3 个插件修复 (2026-07-17)
- QQ 重启后大概率需要重新扫码登录 (登录态缓存不稳定)
- NapCat OneBot 端口不是 QQ 启动后立即就绪 — 需等 QQ 登录完成

## 修改注意事项

- **jmcomic 插件已恢复启用（2026-09-28）**：从 disabled_plugins 移回。uv 升级重建 venv 后插件依赖丢失需重装：`~/.local/bin/uv pip install --python ~/.local/share/uv/tools/astrbot/bin/python jmcomic img2pdf -i https://pypi.tuna.tsinghua.edu.cn/simple`。实测该服务器**可直连 JM API 与图片 CDN**（搜索/单图下载均通，无需 GoodbyeDPI/隧道）；整本下载耗时数分钟属正常，插件有进度通知。风控注意：色色内容从机房 IP 高频发送有风险，已在群聊插话限额内平衡

- **群聊插话已开启（2026-09-28）**：private_companion 配置 `enable_group_interjection=True`（原为 False，闲聊从不搭话的主因）、插话最小间隔 6→3 分钟、关系插话额度放宽（窗口 10min/3 次、每人日 12、群日 60），插话反馈学习开。备份：`/home/admin/companion_config_backup_20260928.json`。配置修改必须同步顶层+`group_interject_config`+`basic_config` 三处重复键。嫌插话频繁调大 `group_interject_min_interval_minutes`，嫌少调小

- jm_bot_v2 已内置风控节流（bot/antiban.py）：出站消息全局最小间隔 1.2s（messaging 层）、AI 聊天同群冷却 8s + 全局 10 条/分钟；阈值在 jm_bot_v2/config.json "antiban" 段。旧号因机房 IP 被风控，新号 2143388598 使用需保持节流 + 低频养号（避免频繁重启 napcat、避免色色内容高频直发）

- companion 配置有两处重复 (basic_config + 顶层), 用 replace_all 确保同步
- JSON 配置文件带 BOM, Python 读写需 `utf-8-sig`
- 用户名 `a'su's` 含单引号, shell 命令中路径需特殊处理
- NapCat 配置目录属于 root (`/home/admin/.astrbot/data/napcat/`), 修改需 sudo
- AstrBot 服务 `WorkingDirectory` 必须在 `/home/admin`, 否则报 "not a valid root directory"
- 插件详情页依赖 `metadata.yaml` + `main.py`/`__init__.py`, 缺少任何一个都会导致加载失败
- 数据库直接操作后无需重启即可生效 (SQLite WAL 模式)

## 会话记录 (2026-07-17)

### 完成事项
1. ✅ SSH 密钥配置 + `~/.ssh/config` (ssh jmbot 直连)
2. ✅ systemd 持久化 (napcat/astrbot/bridge 三服务, 开机自启)
3. ✅ 7 个人格迁移至服务器 (data_v4.db.personas)
4. ✅ 知识库迁移 (kb.db + 2 个 .md + 4 个集合目录)
5. ✅ 插件详情页修复 (3 个插件的 pages 中文目录编码损坏 → tar 重传)
6. ✅ 删除损坏的 iris_chat_memory 插件目录
7. ✅ NapCat OneBot 协议启用 (napcat_protocol 配置 enable: true)
8. ✅ CLAUDE.md 完整文档更新
