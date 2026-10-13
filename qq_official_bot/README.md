# QQ 官方机器人接入指南 (qq-botpy)

本项目采用腾讯官方开放平台 Python SDK [`qq-botpy`](https://github.com/tencent-connect/botpy) 构建，彻底解决第三方协议端（如 NapCat/LLOneBot 等）容易遭遇的腾讯安全中心风控踢线与登录态失效问题。

---

## 🌟 核心优势

- ✅ **官方认证合规**：走腾讯官方开放平台网关通信，无需挂机 QQ 客户端，永不被风控踢线。
- ✅ **免扫码维护**：使用 `AppID` + `AppSecret` 永久凭据连接，服务重启秒级自愈。
- ✅ **安全稳定**：原生支持 QQ 群 `@机器人` 被动交互以及单聊 (C2C) 私信会话。

---

## 📋 接入准备步骤

### 1. 注册 QQ 开放平台开发者
1. 访问 [QQ 开放平台 (q.qq.com)](https://q.qq.com/) 并使用个人 QQ 登录。
2. 完成开发者实名认证（个人开发者即可免费申请）。

### 2. 创建机器人并获取凭据
1. 进入「应用管理」→「创建机器人」。
2. 填写机器人名称（如“JM助手”）、头像及简介。
3. 进入机器人详情页的「开发设置」，记录以下信息：
   - **机器人 AppID** (如 `102xxxxxx`)
   - **机器人 AppSecret** (点击重置/生成并复制保存)

### 3. 配置本地密钥

复制配置模板：
```bash
cp qq_official_bot/config.example.yaml qq_official_bot/config.yaml
```

编辑 `qq_official_bot/config.yaml`：
```yaml
appid: "你的AppID"
secret: "你的AppSecret"
sandbox: false       # 测试期可设为 true（仅限沙箱群/沙箱用户）

ai:
  enabled: true
  api_key: "你的DeepSeek或Anthropic_API_Key"
```
*注：亦可通过环境变量 `QQ_BOT_APP_ID`、`QQ_BOT_APP_SECRET` 进行配置。*

---

## 🚀 启动运行

### Windows
双击运行 `qq_official_bot/start.bat`，或在根目录下执行：
```bash
pip install -r qq_official_bot/requirements.txt
python -m qq_official_bot.main
```

### Linux / 服务器
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r qq_official_bot/requirements.txt
python3 -m qq_official_bot.main
```

---

## 💬 常用指令说明

在群聊中 **@机器人** 或在私聊中直接发送以下指令：

| 指令 | 示例 | 功能说明 |
| :--- | :--- | :--- |
| `/jm search <关键词>` | `@Bot /jm search 东方` | 检索相关漫画作品列表 |
| `/jm <ID>` | `@Bot /jm 1448061` | 查询指定作品详细信息（作者/章节/标签） |
| `/jm rank [日榜/周榜]` | `@Bot /jm rank 周榜` | 获取全站热门排行榜 TOP 5 |
| `/jm random` | `@Bot /jm random` | 随机发现并推荐一部作品 |
| `/jm ask <问题>` | `@Bot /jm ask 推荐一部纯爱漫画` | 召唤 AI 助手进行对话 |
| `/jm help` | `@Bot /jm help` | 获取完整指令帮助菜单 |

---

## ⚠️ 官方机器人注意事项与合规要求

1. **内容安全审查**：
   腾讯官方开放平台会对机器人发送的所有消息执行机器安全审核，若消息包含敏感词汇可能会被拦截。建议在 `config.yaml` 中保持 `neutral_mode: true`。
2. **被动消息时效**：
   官方机器人的群聊回复为被动回复模式，单次接收用户消息后需在规定时间内响应。
