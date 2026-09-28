# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

JM 漫画 QQ Bot — QQ 群/私聊 AI 猫娘 Bot。基于 AstrBot v4.26.6 + 11 插件。支持漫画下载/搜索、B站视频解析、AI聊天、图片识图、知识库。

## 架构 (2026-07-17)

**服务器** (118.31.184.221, 阿里云 2核4G, Anolis OS 8 / Alibaba Cloud Linux 3):
```
QQ Linux(3.2.31) → NapCat Shell(v4.18.9, LD_PRELOAD) → AstrBot v4.26.6 (:6185, :3003)
  ├─ WS Server(3001) → napcat_ws_bridge.py (群聊识图)
  ├─ HTTP Server(3002) ← AstrBot 发送消息
  └─ WebUI(6099) — NapCat 管理界面

systemd 持久化: napcat.service → astrbot.service → bridge.service
```

**Windows 本机**: GoodbyeDPI (JMComic CDN 翻墙), 开发/测试

## SSH 连接

```bash
# 本机 ~/.ssh/config:
# Host jmbot
#     HostName 118.31.184.221
#     User admin
#     IdentityFile ~/.ssh/id_ed25519
#     ServerAliveInterval 60

ssh jmbot  # Claude Code 操作服务器
```

密钥路径: `C:\Users\a'su's\.ssh\id_ed25519` (ed25519, 2026-07-17 创建)

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
ExecStartPre=pkill -9 qq Xvfb; sleep 1
ExecStartPre=Xvfb :1 -screen 0 1280x720x16 +extension GLX +render
ExecStart=bash -c 'export DISPLAY=:1 && ./launcher.sh'
Restart=always
RestartSec=10
```

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

扫码账号: **1601410002**（注意不要扫错！）

### 端口一览

| 端口 | 绑定 | 服务 | 用途 |
|------|------|------|------|
| 3001 | 127.0.0.1 | NapCat | OneBot WS Server (桥接) |
| 3002 | 127.0.0.1 | NapCat | OneBot HTTP Server |
| 3003 | 127.0.0.1 | AstrBot | OneBot WS Server (NapCat 连此端口) |
| 6185 | 0.0.0.0 | AstrBot | WebUI 仪表盘 |
| 6099 | 0.0.0.0 | NapCat | NapCat WebUI |

### WebUI 访问

- AstrBot: http://118.31.184.221:6185 (astrbot / Jm123456)
- NapCat: http://118.31.184.221:6099 (token: e6fe235a1c03)

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

### 插件清单 (2026-07-17)

| 插件 | 版本 | 状态 | 说明 |
|------|------|------|------|
| private_companion | 5.9.10 | ✅ | 陪伴/生图/识图/主动私聊 |
| memory_companion | 1.6.0 | ✅ | 长期记忆/知识图谱 |
| jmcomic | 1.0.0 | ✅ | 漫画下载/搜索/推荐 |
| smart_imagechat_hub | 2.8.6 | ✅ | 表情包/智能图片对话 |
| Bilibili-Full-Featured | 1.2.0 | ✅ | B站全能解析 |
| bilibili (旧) | 1.6.4 | ✅ | BV关, mini-app开 |
| polite_silence | 1.1.0 | ✅ | 骚扰拒答 |
| STEmbedding | 1.2.4 | 备用 | 本地嵌入模型 |
| AstrNa | 1.4.6 | ✅ | 系统优化 |
| fund | 1.0.0 | ✅ | 基金查询 |
| biliread | 1.2.0 | ✅ | B站视频理解 |
| iris_chat_memory | — | ❌ 已删 | 已迁移到 memory_companion |

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
