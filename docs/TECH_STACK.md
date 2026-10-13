# JM Bot 技术栈存档

> 存档日期: 2026-07-18
> 背景: QQ 号 1601410002 因长期在服务器（阿里云机房 IP）运行被腾讯风险管控。
> 本文档记录被风控时点的完整技术栈，供后续换号 / 换平台 / 重建时参考。

## 分层总览

```
┌─────────────────────────────────────────────────┐
│ 5. JM 下载链路（平台无关，可复用）                  │
│    jmcomic → 代理隧道 → GoodbyeDPI → JM CDN      │
├─────────────────────────────────────────────────┤
│ 4. AI 模型层（平台无关，可复用）                    │
│    DeepSeek / MiMo / bge-m3 / wanx               │
├─────────────────────────────────────────────────┤
│ 3. Bot 框架层（平台无关，可复用）                   │
│    AstrBot + 11 插件 + 人格 + 知识库              │
├─────────────────────────────────────────────────┤
│ 2. QQ 接入层 ⚠️ 风控受灾区（与 QQ 强耦合）          │
│    QQ Linux + NapCat + OneBot v11                │
├─────────────────────────────────────────────────┤
│ 1. 基础设施层                                     │
│    阿里云 ECS + systemd + SSH                    │
└─────────────────────────────────────────────────┘
```

## 1. 基础设施层

| 组件 | 版本/配置 | 位置 |
|------|----------|------|
| 云服务器 ECS | 2核4G, Linux | `<server_host>` |
| Python | 3.12 (uv 管理) | `/home/admin/.local/share/uv/tools/astrbot/` |
| systemd | napcat / astrbot / bridge 三服务 + qq-watchdog.timer | `/etc/systemd/system/` |
| SSH | ed25519 密钥, `ssh jmbot` 直连 | `~/.ssh/config` |
| Windows 本机 | 开发环境 + GoodbyeDPI + JM 代理 | 本地工作目录 |

### systemd 服务

| 服务 | 用户 | 端口 | 说明 |
|------|------|------|------|
| napcat.service | root | 3001, 3002, 6099 | Xvfb :1 + QQ + NapCat |
| astrbot.service | admin | 6185, 3003 | WorkingDirectory 必须为 /home/admin |
| bridge.service | admin | — | napcat_ws_bridge.py 群聊识图 |
| qq-watchdog.timer | — | — | 每 5 分钟检测 retcode=1200 自动重启 |

## 2. QQ 接入层 ⚠️（风控重灾区）

| 组件 | 版本 | 说明 |
|------|------|------|
| QQ Linux | 3.2.31 (Electron) | `/opt/QQ/`, Xvfb :1 虚拟显示 |
| NapCat Shell | v4.17.52（从 4.18.9 降级避风控） | LD_PRELOAD 注入, 备份在 `napcat_backup_v4.18.9/` |
| OneBot v11 | WS Server 3001 / HTTP 3002 / WS Client → 3003 | 协议层 |
| napcat_ws_bridge.py | 自研 | 群聊识图桥接 (WS 3001 → 处理 → HTTP 3002) |
| qq_watchdog.sh | 自研 | retcode=1200 冻结检测 |

### 风控链条分析

```
阿里云机房 IP 段（腾讯已标记数据中心 IP）
  + 7×24 小时在线不间断
  + NapCat 协议模拟登录（非官方客户端特征）
  + 异地登录（号主常用地 ≠ 杭州机房）
    → 设备/环境风控评分累积
    → 前兆: retcode=1200 内核冻结、登录态频繁失效要求扫码
    → 最终: 账号风险管控（2026-07-18）
```

### 若换号继续，防风控要点

- 新号先在常用设备正常使用养号数周
- 避免机房 IP：住宅代理 / 家庭宽带内网穿透部署
- 降低消息频率，避免瞬时大量发送
- NapCat 保持低版本（社区反馈新版 QQ 3.25+ 风控更激进）

## 3. Bot 框架层（平台无关，可复用）

| 组件 | 版本 | 说明 |
|------|------|------|
| AstrBot | v4.26.6 | 核心框架, WebUI :6185, 支持多平台适配器 |
| 数据库 | data_v4.db (SQLite, WAL) | 人格 / 偏好 / 对话 / 会话 |
| 知识库 | kb.db + anime_games.md (19KB) + bilibili_memes.md (9.5KB) + 4 集合 | bge-m3 嵌入 |

### 插件清单 (11 个)

| 插件 | 版本 | 功能 |
|------|------|------|
| private_companion | 5.9.10 | 陪伴 / 生图 / 识图 / 主动私聊, 有"陪伴面板" |
| memory_companion | 1.6.0 | 长期记忆 / 知识图谱, 有"记忆面板" |
| jmcomic | 1.0.0 | 漫画下载/搜索/推荐 (5 LLM Tools + /jm 命令) |
| smart_imagechat_hub | 2.8.6 | 表情包 / 智能图片对话, 有 image-center-page |
| Bilibili-Full-Featured | 1.2.0 | B站全能解析 |
| bilibili (旧) | 1.6.4 | BV 解析关, mini-app 开 |
| biliread | 1.2.0 | B站视频理解 |
| polite_silence | 1.1.0 | 骚扰拒答 |
| AstrNa | 1.4.6 | 系统优化 |
| fund | 1.0.0 | 基金查询 |
| STEmbedding | 1.2.4 | 本地嵌入模型（备用） |

### 人格系统 (7 个, data_v4.db → personas 表)

| Persona ID | 名称 | 自称 | 称呼用户 |
|-----------|------|------|---------|
| jm_catgirl | 色色猫娘 (默认) | 本喵 | 主人 |
| jm_gou_da_fa | 郭大发 | 我 | 你 |
| jm_tsundere | 傲娇大小姐 | 本小姐 | 庶民/杂鱼 |
| jm_succubus | 邪魅魅魔 | 妾身 | 契约者/小羊羔 |
| jm_oneesan | 温柔大姐姐 | 姐姐 | 小可爱/宝贝 |
| jm_yandere | 病娇 | 私 | Darling |
| jm_gyaru | 反差痴女 | 人家 | 哥哥 |

本地源文件: `astrbot_plugin_jmcomic/personas/_all_personas.json`

## 4. AI 模型层（平台无关，可复用）

| 场景 | Provider / 模型 | 说明 |
|------|----------------|------|
| 主 LLM (文本/工具调用) | deepseek/deepseek-v4-pro | — |
| 识图 Vision | xiaomi/mimo-v2.5 | 降权 60s |
| 嵌入/知识库 | siliconflow/bge-m3 | 免费, api.siliconflow.cn |
| 生图 | 百炼 wanx2.1-t2i-turbo | — |

### 关键阈值

| 配置 | 值 |
|------|-----|
| tool_call_timeout | 600s |
| max_agent_step | 5 |
| hard_limit | 120s 窗口 / 8 条 |
| 主动私聊 | idle=10min, interval=10min |
| 免打扰 | 02:00–08:00 |
| private_image_timeout | 60s, wait 90s |

## 5. JM 下载链路（平台无关，可复用）

```
服务器 jmcomic 库 → HTTP_PROXY(127.0.0.1:8888) → SSH 反向隧道
  → Windows jm_proxy.py → GoodbyeDPI → JMComic CDN
```

| 组件 | 说明 |
|------|------|
| jmcomic | 2.7.1, curl_cffi, 超时 15s, Feature.export_pdf 失效 → img2pdf 兜底 |
| jm_proxy.py | Windows 侧 HTTP 多线程代理 (127.0.0.1:8888) |
| SSH 反向隧道 | `ssh -R 8888:127.0.0.1:8888 -N jmbot` |
| start_jm_proxy.bat | 一键启动代理 + 隧道 |
| GoodbyeDPI | 黑名单模式 `-5`, 绕过 GFW DPI |
| 环境变量 | JM_PROXY_HOST / JM_PROXY_PORT 可覆盖 |

局限: Windows 关机则 JM 功能不可用（返回明确错误, 不挂死）。替代方案: 服务器装 Clash 订阅。

## 核心配置文件索引

| 文件 | 位置 | 用途 |
|------|------|------|
| cmd_config.json | `~/.astrbot/data/` | providers / personality / timeout |
| private_companion_config.json | `~/.astrbot/data/config/` | 陪伴插件 |
| memory_companion_config.json | `~/.astrbot/data/config/` | 记忆插件 |
| onebot11_1601410002.json | `napcat/config/` | OneBot 端口 (root 权限) |
| napcat_protocol_1601410002.json | `napcat/config/` | 协议开关 (root 权限) |
| option.yml | `plugins/astrbot_plugin_jmcomic/` | JMComic 配置 |

## 迁移可复用性结论

**风控只影响第 2 层（QQ 接入层）。** 以下资产全部与 QQ 解耦，换号/换平台零迁移成本:

- AstrBot 框架 + 全部 11 个插件（基于 AstrBot 事件 API, 不感知平台）
- 7 个人格 (data_v4.db) + 知识库 (kb.db)
- 全部模型 Provider 配置
- JM 下载链路

**换平台选项** (AstrBot 原生适配器): Telegram / Discord / 微信个人号 / 企微 / 钉钉 / QQ 官方机器人 API (qq-botpy, 但仅频道+群限权)。换平台只需在 WebUI 新增 platform 适配器, 删除 aiocqhttp 配置即可。

**换 QQ 号**: 仅需改 `onebot11_<新QQ号>.json` + `napcat_protocol_<新QQ号>.json` 文件名与内容, 重新扫码。

## 已知坑速查

1. 中文文件跨平台传输必须 tar 打包（scp 直传文件名损坏）
2. AstrBot systemd WorkingDirectory 必须为 /home/admin
3. NapCat 配置目录属 root, 修改需 sudo
4. JSON 配置带 BOM, Python 用 utf-8-sig 读写
5. 用户名 `a'su's` 含单引号, shell 路径需转义
6. 插件详情页依赖 metadata.yaml + main.py/__init__.py
7. SQLite WAL 模式, 直接改库无需重启
8. NapCat v4.17.52 要求 QQ ≥ 3.2.23
