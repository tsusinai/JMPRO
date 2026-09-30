# JM Bot v2 开发说明

完整的用户安装和命令文档位于仓库根目录 [README.md](../README.md)，设计与运行细节位于 [docs/V2.md](../docs/V2.md)。本文件只记录 v2 目录内部的开发约定。

## 入口与模块

```text
main.py                  日志初始化、ffmpeg 检查、asyncio 入口
config.example.json      脱敏配置模板
config.json              本机配置，已被 .gitignore 忽略
option.yml               JMComic 客户端配置
bot/config.py            配置深合并、路径和运行常量
bot/runner.py            NapCat WebSocket 连接、重连和消息过滤
bot/router.py            `/jm` 正则路由，具体命令交给 handlers/
bot/handlers/browse.py   搜索、详情、排行、分类、随机推荐
bot/handlers/download.py 下载、队列、取消、缓存和进度
bot/handlers/chat.py     AI 对话、历史清理和角色切换
bot/handlers/misc.py     帮助、软重启和语音模式
bot/downloader.py        同步 jmcomic 的异步包装、PDF/ZIP 和卡死保护
bot/jm_client.py         JMComic 查询客户端
bot/napcat.py             OneBot HTTP 调用和文件上传
bot/messaging.py          角色口吻、节流、文字/语音发送
bot/ai_chat.py            意图分类、工具动作和对话回复
bot/tts.py                Vocu / 硅基流动、缓存和文字回退
bot/roles.py              角色模板与群角色持久化
bot/antiban.py            全局发送节流和 AI 限频
bot/fsutils.py            JSON 原子写、磁盘检查和日志轮转
tests/test_all.py         不连网的脚本测试
```

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.json config.json
.\.venv\Scripts\python.exe tests/test_all.py
```

测试不会启动 WebSocket，也不会调用真实 AI、TTS 或下载服务。修改路由、文件工具、状态、TTS 时，应优先补充同目录的脚本测试；需要真实验收时再单独启动 NapCat 和 Bot。

## 配置边界

- `config.json` 只保存在本机，不进入 Git；配置读取兼容 UTF-8 BOM。
- AI 优先使用 `ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL`、`ANTHROPIC_DEFAULT_HAIKU_MODEL` 环境变量，缺失项再读取 `config.json.ai`。
- NapCat token、TTS key 和音色 ID 从本地配置读取。`tts_voices.json` 中的音色值应替换为个人占位符，不要提交真实账号资源。
- 下载、PDF、ZIP、日志、历史 JSON、TTS 缓存都由 `bot/config.py` 定位在 v2 目录下。

## 修改约定

1. 所有用户可见文案使用中文，并集中维护在 `bot/messages.py`。
2. 命令匹配顺序在 `bot/router.py` 中有意设计；新增规则时同步添加正向和反向测试。
3. 下载函数运行在工作线程中，不能阻塞 asyncio 事件循环；进度通过现有回调通道发送。
4. 数据类回复保持文字，只有 AI 纯聊天在语音模式下调用 TTS；合成失败必须回退文字。
5. 修改超时、限流和磁盘阈值时，更新根 README 的配置表和对应测试。
