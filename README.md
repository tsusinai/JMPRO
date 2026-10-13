# JMPRO — JM 漫画 QQ 智能机器人

<p align="center">
  <b>支持漫画检索、在线详情、智能推荐与 AI 角色扮演的多功能 QQ 机器人</b>
</p>

---

## 📖 项目简介

**JMPRO** 是一个专为二次元与漫画爱好者设计的 QQ 机器人项目，提供漫画关键词检索、详情浏览、全网热门榜单以及集成大语言模型（LLM）的智能对话助手。

本项目提供双运行架构支持，您可根据使用场景自由选择：
- 🌟 **QQ 官方机器人模式 (`feat/qq-official-bot` 分支)**：基于腾讯官方开放平台与 `qq-botpy` SDK，采用官方网关长连接通信，**永久免除第三方协议端的风控踢线、登录态过期与封号风险**，支持 AppID/AppSecret 免扫码部署。
- ⚡ **OneBot / NapCat 模式 (`main` 分支)**：面向私有化部署场景，直连 NapCat OneBot v11 WebSocket 或作为 AstrBot 平台插件运行。

---

## 🚀 核心功能

- 🔍 **全网漫画检索**：支持多关键词搜索、作者过滤、分类浏览，内置多 CDN 节点自动容灾与智能切源，规避网络阻断。
- 📖 **漫画详情与排行**：一键获取漫画章节、标签、作者与热度信息，支持日榜、周榜、月榜多维度榜单查询。
- 📦 **下载与格式转换**（*OneBot 独立运行版*）：支持多线程下载、断点续传、卡死检测与动态换源，自动导出高质量 PDF / ZIP 归档。
- 🤖 **AI 智能对话助手**：接入 DeepSeek / Anthropic 协议模型，具备多轮对话能力，支持漫画意图语义识别与角色扮演。
- 🎙️ **TTS 语音回复**（*OneBot 独立运行版*）：支持 CosyVoice2 / Vocu 语音合成引擎，提供拟人化语音回复。

---

## 🗂️ 分支体系与架构建议

| 分支 | 模式 | 通信协议 | 稳定性 | 推荐场景 |
| :--- | :--- | :--- | :--- | :--- |
| **`feat/qq-official-bot`** (当前分支) | **QQ 官方机器人** | QQ 开放平台 OpenAPI / Gateway (`qq-botpy`) | ⭐️⭐️⭐️⭐️⭐️ **极高**（官方通道，永不掉线，免扫码） | 生产环境、公开群聊、长期无人值守运行 |
| **`main`** | **OneBot / NapCat / AstrBot** | OneBot v11 WebSocket & HTTP | ⭐️⭐️⭐️（依赖本地 QQ 协议端，受腾讯风控机制约束） | 局域网私有群、需要发送群文件或自定义表情的场景 |

---

## 🛠️ 快速开始

### 1. 环境准备
- **Python**: 3.10 或更高版本
- **网络环境**: 访问 JMComic 资源时，Windows 环境可配合项目内置的 `goodbyedpi/` 工具开启网络加速；或通过环境变量配置 HTTP 代理。

### 2. 克隆项目与安装依赖

```bash
# 克隆代码仓库
git clone https://github.com/tsusinai/JMPRO.git
cd JMPRO

# 切换到官方机器人分支 (推荐)
git checkout feat/qq-official-bot

# 安装官方 Bot 依赖
pip install -r qq_official_bot/requirements.txt
```

---

## ⚙️ 接入与配置指引

### 方式一：运行 QQ 官方机器人 (推荐)

1. 前往 [QQ 开放平台 (q.qq.com)](https://q.qq.com/) 注册个人开发者并创建机器人。
2. 在机器人详情页「开发设置」中获取 **AppID** 与 **AppSecret**。
3. 复制配置模板并填入凭证：
   ```bash
   cp qq_official_bot/config.example.yaml qq_official_bot/config.yaml
   ```
4. 编辑 `qq_official_bot/config.yaml`：
   ```yaml
   appid: "你的AppID"
   secret: "你的AppSecret"
   sandbox: false       # 测试期间可设置为 true

   ai:
     enabled: true
     api_key: "你的DeepSeek或Anthropic_API_Key"
   ```
5. 启动机器人：
   ```bash
   # Windows 双击运行 qq_official_bot/start.bat，或命令行执行：
   python -m qq_official_bot.main
   ```

---

### 方式二：运行 OneBot 独立 Bot (`main` 分支)

1. 复制配置文件模板：
   ```bash
   cp config.example.json config.json
   cp .env.example .env
   ```
2. 在 `config.json` 或 `.env` 中配置 NapCat 连接地址与 AI Key：
   ```json
   {
     "napcat": {
       "http_url": "http://127.0.0.1:3002",
       "ws_url": "ws://127.0.0.1:3001",
       "access_token": "your_token"
     },
     "ai": {
       "api_key": "your_deepseek_api_key"
     }
   }
   ```
3. 运行启动脚本：
   ```bash
   # Windows 本机一键启动 (包含 GoodbyeDPI 与 Bot)
   start.bat
   ```

---

## 🔒 API 管理与安全规范

为防止私有 API 密钥与敏感数据外泄，本项目严格遵循以下安全约定：

1. **零密钥入库**：真实配置文件（`config.json`、`qq_official_bot/config.yaml`、`.env`）均已加入 `.gitignore`，**严禁提交包含真实 Token 的配置文件到 Git 仓库**。
2. **环境变量优先**：所有模块均支持通过环境变量直接注入密钥：
   - `QQ_BOT_APP_ID`: QQ 开放平台 AppID
   - `QQ_BOT_APP_SECRET`: QQ 开放平台 AppSecret
   - `ANTHROPIC_AUTH_TOKEN`: DeepSeek / Claude 模型 API Key
   - `NAPCAT_ACCESS_TOKEN`: OneBot 通信 Token
   - `VOCU_TTS_API_KEY`: 语音合成 API Key
3. **本地数据隔离**：所有漫画切片文件（`downloads/`）、PDF 归档（`pdfs/`）、日志（`*.log`）均已被 Git 彻底忽略，执行 Git 提交时不会同步任何本地媒体与个人浏览数据。

---

## 💬 常用指令清单

在 QQ 群内 **@机器人** 或在私聊窗口中发送：

| 指令 | 示例 | 功能说明 |
| :--- | :--- | :--- |
| `/jm search <关键词>` | `/jm search 东方` | 检索相关漫画作品列表 |
| `/jm <作品ID>` | `/jm 1448061` | 查询作品详情（作者、章节数、标签） |
| `/jm rank [日榜/周榜]` | `/jm rank 周榜` | 获取全站热门排行榜 TOP 5 |
| `/jm random` | `/jm random` | 随机发现并推荐一部作品 |
| `/jm ask <内容>` | `/jm ask 推荐一部纯爱漫画` | 召唤 AI 助手进行对话 |
| `/jm help` | `/jm help` | 显示帮助菜单与指令列表 |

*注：在 OneBot 模式下，额外支持 `/jm download <ID> [pdf/zip]` 批量下载与群文件上传。*

---

## 📂 项目结构

```text
JMPRO/
├── qq_official_bot/            # 🌟 QQ 官方机器人适配层 (qq-botpy)
│   ├── config.py               # 官方 Bot 配置读取 (YAML & 环境变量)
│   ├── client.py               # 网关客户端 (监听群@与私聊消息)
│   ├── router.py               # 命令路由分发与结果排版
│   ├── main.py                 # 入口启动脚本
│   ├── start.bat               # Windows 一键启动脚本
│   └── requirements.txt        # 官方模块依赖清单
├── jm_bot_v2/                  # ⚡ OneBot 独立 Bot 模块化实现
│   ├── bot/                    # 核心库 (下载器/AI/角色系统/流控)
│   └── config.example.json     # 独立版配置示例模板
├── astrbot_plugin_jmcomic/     # 🔌 AstrBot 平台插件实现
├── docs/                       # 架构设计与技术栈文档
├── goodbyedpi/                 # Windows CDN 翻墙加速组件
├── option.yml                  # JMComic 核心爬虫策略配置
├── .env.example                # 环境变量配置模板
├── config.example.json         # 集中配置文件模板
└── README.md                   # 项目使用与说明文档
```

---

## ⚠️ 免责声明

1. 本项目仅供 Python 异步网络编程与机器人 SDK 开发的技术交流与学习研究使用。
2. 漫画版权归原作者及相关平台所有，请勿将本项目用于任何商业营利行为。
3. 请合理控制请求频率，遵守当地法律法规与各开放平台服务协议。
