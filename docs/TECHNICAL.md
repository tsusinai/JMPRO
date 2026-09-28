# JM 猫娘 Bot — 技术文档

## 架构

```
QQ 消息 → NapCat WS Server (3001) → NapCat WS Client → AstrBot aiocqhttp (3003)
                                                            │
                              ┌──────────────────────────────┤
                              │                              │
                         Agent Pipeline                 /jm Command
                              │                              │
                    ┌─────────┼─────────┐                   │
                    │         │         │                   │
              LLM Provider  Persona   Tools             commands.py
              (DeepSeek)   (猫娘)      │                   │
                                       │              download.py
                          ┌────────────┤              messages.py
                          │            │
                    JM Tools (5)   Iris Memory (6)
                    search_manga   save_memory
                    get_manga_info search_memory
                    get_rank       correct_memory
                    random_recommend save_knowledge
                    download_manga search_knowledge_graph
                                   get_profile
```

## 插件清单

| 插件 | 版本 | 用途 |
|------|------|------|
| `astrbot` (内置) | 4.26.6 | AstrBot 核心、命令系统 |
| `astrbot_plugin_jmcomic` | 1.0.0 | JM 漫画工具（5 LLM Tools + /jm 命令） |
| `astrbot_plugin_private_companion` | 5.9.10 | 陪伴编排（状态、日程、主动消息、图片生成） |
| `astrbot_plugin_iris_chat_memory` | 0.2.0 | 三层记忆（L1 缓冲 / L2 FAISS 向量 / L3 知识图谱） |
| `astrbot_plugin_polite_silence` | 1.1.0 | 拒绝骚扰用户 |
| `astrbot_plugin_smart_imagechat_hub` | 2.8.6 | 智能图片对话/发表情 |

## 目录结构

```
~\.astrbot\
├── astrbot.lock                          # 进程锁
├── data\
│   ├── cmd_config.json                   # 主配置
│   ├── data_v4.db                        # SQLite 数据库（人格、偏好、对话）
│   ├── config\                           # 插件配置
│   ├── plugins\
│   │   ├── astrbot_plugin_jmcomic\       # JM 漫画插件
│   │   ├── astrbot_plugin_private_companion\
│   │   ├── astrbot_plugin_iris_chat_memory\
│   │   ├── astrbot_plugin_polite_silence\
│   │   └── astrbot_plugin_smart_imagechat_hub\
│   ├── plugin_data\                      # 插件数据
│   ├── knowledge_base\                   # 知识库
│   ├── logs\                             # 日志
│   └── temp\                             # 临时文件
└── ...
```

## 关键配置

### cmd_config.json 关键项

```json
{
  "platform": [{
    "type": "aiocqhttp",
    "name": "闲置QQ",
    "id": "onebot",
    "enable": true,
    "ws_reverse_host": "127.0.0.1",
    "ws_reverse_port": 3003,
    "ws_reverse_token": "O~3GVdp9kwlCH.Zg"
  }],
  "wake_prefix": ["/", ""],
  "admins_id": ["astrbot", "3263123370"],
  "provider_settings": {
    "max_agent_step": 5,
    "default_personality": "default"
  },
  "timezone": "Asia/Shanghai"
}
```

### NapCat WebSocket 配置

NapCat 关键配置 (`onebot11_1601410002.json`)：
```json
{
  "network": {
    "websocketServers": [{
      "host": "127.0.0.1", "port": 3001
    }],
    "httpServers": [{
      "host": "127.0.0.1", "port": 3002, "token": "O~3GVdp9kwlCH.Zg"
    }],
    "websocketClients": [{
      "url": "ws://127.0.0.1:3003/ws/",
      "token": "O~3GVdp9kwlCH.Zg"
    }]
  }
}
```

### AI 提供商

```json
{
  "provider": [{
    "type": "openai_compatible",
    "name": "DeepSeek",
    "base_url": "https://api.deepseek.com/anthropic",
    "api_key": "<API_KEY>",
    "model": "deepseek-chat"
  }]
}
```

## JM 插件内部结构

```
astrbot_plugin_jmcomic/
├── __init__.py      # Star 入口，/jm 命令路由 + 5 LLM Tools
├── download.py       # 异步下载引擎（asyncio.to_thread + ProgressDownloader）
├── agent_tools.py    # LLM Tool 实现（猫娘口吻返回值）
├── commands.py       # /jm 子命令处理器
├── messages.py       # 文案系统（M() 随机变体 / M_single() 固定）
├── state.py          # 速率限制 / 下载队列 / 进度追踪
├── utils.py          # 工具函数（format_size / get_dir_info 等）
├── personas.py       # 7 个猫娘人设配置
├── option.yml        # jmcomic 库配置（CDN 域名、线程数等）
├── metadata.yaml     # AstrBot 插件元数据
├── main.py           # 插件入口点
├── personas/         # 人设 JSON 导出文件
└── test_all.py       # 83 项测试
```

### LLM Tools (5 个)

| Tool | 参数 | 说明 |
|------|------|------|
| `search_manga` | query: str | 搜索漫画（jmcomic API） |
| `get_manga_info` | album_id: str | 漫画详情 |
| `get_rank` | period: str = "day" | 排行榜 |
| `random_recommend` | tag: str = "" | 随机推荐 |
| `download_manga` | album_id: str | 下载 + 上传群文件 |

### 下载流程

```
download_manga(event, album_id)
  └─ download_single(album_id, fmt="pdf")
       └─ asyncio.to_thread(_run)
            ├─ jmcomic.create_option_by_file(option.yml)
            ├─ Feature.export_pdf() — 设置 PDF 输出
            ├─ option.build_jm_client().get_album_detail() — 元数据
            ├─ jmcomic.download_album() — 下载图片（ProgressDownloader）
            │    ├─ before_image: 0.1s 请求间隔（threading.local）
            │    ├─ before_image: 20s 卡死检测 → CDN 切换
            │    └─ after_image: 进度回调
            ├─ 统计下载文件
            └─ 定位 PDF 路径
  └─ _upload_to_group() — NapCat HTTP API 上传群文件
```

### 兼容性处理

jmcomic 2.7.1 返回值类型变化：
- `search_site()` 返回 dict/tuple/对象 → `_get_id()` / `_get_name()` / `_get_author()` 兼容
- `get_album_detail()` → JmAlbumDetail 对象 → `getattr()` 取值
- `photo_count` 不存在 → 用 `len(episode_list)` 替代
- logger 冲突 → 独立 handler，关闭 propagate

## 启动脚本

`astrbot_start.bat`：
1. 杀旧 astrbot.exe
2. 删除 `astrbot.lock`
3. 启动 `astrbot run`（WebUI 端口 6185）

NapCat 需提前启动（端口 3001/3002）。

## AstrBot Python 环境

- 路径：`C:\Users\a'su's\AppData\Roaming\uv\tools\astrbot\`
- Python：3.12.13（uv 管理）
- pip 安装：`<astrbot_venv>\Scripts\python.exe -m pip install <pkg>`
- 已手动安装：jmcomic 2.7.1、img2pdf、pikepdf
