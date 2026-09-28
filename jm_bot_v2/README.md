# JM Bot v2 — 重构版独立 Bot

由根目录 `jm_bot.py`（1661 行单体）+ `download.py` + `ai_chat.py` + `napcat_utils.py` 重构而来的模块化版本。
**产物自包含**：在本目录下独立运行，产物（downloads/pdfs/zips/bot.log/状态 JSON）也落在本目录，与旧版完全隔离；根目录旧代码未改动。

## 启动 / 测试

```bash
start.bat              # NapCat + GoodbyeDPI + 本 Bot（含多实例防护）
python main.py         # 仅启动 Bot（需 NapCat 与 GoodbyeDPI 已就绪）
python tests/test_all.py   # 单元测试（不连网、不触发下载）
```

依赖安装：`pip install -r requirements.txt`

## 模块结构

```
main.py            入口：日志初始化 + asyncio 启动
config.json        全部可调项（端口/token/冷却/磁盘阈值/上传超时/线程池）
bot/
  config.py        配置加载与路径常量（敏感项不再散落源码）
  runner.py        WebSocket 主循环（连接/重连/消息过滤）
  router.py        命令正则表 + 顺序分发（ask clear 先于 ask、/jm <ID> 兜底）
  handlers/
    download.py    download/批量/stop/queue/cache/cache clean + 进度通知
    browse.py      search/info/rank/category/random + ask 的数据动作
    chat.py        ask/ask clear/role
    misc.py        help/restart（软重启）
  napcat.py        NapCat OneBot HTTP API（底层）
  messaging.py     消息发送门面（统一注入角色口吻 + 发送节流）
  antiban.py       风控节流：出站消息全局最小间隔 + AI 回复限频（同群冷却/每分钟上限）
  tts.py           TTS（vocu 主引擎：同步直出→免费计划自动降级异步；siliconflow 备选）
  roles.py         7 人设角色系统 + group_roles.json
  ai_chat.py       /jm ask（意图分类 → 执行 → 猫娘回复）+ chat_history.json
  jm_client.py     JMComic 客户端单例 + CDN 域名扩展 + 查询域逻辑
  downloader.py    下载核心（进度回调/取消/卡死检测/PDF|ZIP/CLI 入口）
  state.py         共享运行状态（下载去重/进度/冷却，原全局变量收拢）
  runtime.py       线程池（download/io/api）+ 超时包装
  fsutils.py       磁盘/日志轮转/JSON 原子写
  messages.py      文案库（与旧版一致）
tests/test_all.py  单元测试（正则直测 router 真代码）
```

## 与旧版的行为差异（仅授权的小幅清理）

1. **配置集中**：NapCat token、端口、各类超时/冷却阈值全部进入 `config.json`（原来硬编码在 `jm_bot.py:82`、`napcat_utils.py:21`、`napcat_ws_bridge.py:21`）。
2. **AI Key 来源**：环境变量 `ANTHROPIC_AUTH_TOKEN/ANTHROPIC_BASE_URL/ANTHROPIC_DEFAULT_HAIKU_MODEL` 优先，回退 `config.json` 的 `ai` 段；**不再回退读取 `~/.claude/settings.json`**。
3. 其余命令行为、文案、限流参数、下载重试/卡死检测逻辑逐行等价；`/jm` 命令格式不变。

## 迁移注意事项

- `config.json` 内含 NapCat access_token（本机私有项目随仓库保存；若开源需先移除并改用环境变量）。
- 群角色 `group_roles.json`、聊天历史 `chat_history.json`、限流 `rate_limits.json` 若需沿用旧数据，从根目录复制到本目录即可（格式未变）。
- `option.yml` 与根目录同名文件一致（CDN 域名固定 + requests postman 走 GoodbyeDPI），改域名记得两处同步或以本目录为准。
- CLI 下载保留：`python -m bot.downloader <ID> [--group <群号>]`。
- 原 `start.bat` 仍在根目录指向旧代码；切换到 v2 后建议改用本目录 `start.bat`。
