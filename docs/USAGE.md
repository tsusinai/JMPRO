# JM 猫娘 Bot — 使用说明

你的 QQ 号 `1601410002` 已变成一个色色猫娘 AI 伴侣，可以聊天、搜漫画、下载、推荐，还有记忆和人格。

## 快速开始

### 启动

1. **启动 NapCat** — 双击旧 `start.bat`（或单独运行 NapCatWinBootMain.exe）
2. 等 8 秒，确认 NapCat 已运行
3. **启动 AstrBot** — 双击 `astrbot_start.bat`

### WebUI

浏览器打开 `http://localhost:6185`，登录 `astrbot / jm123456`

## QQ 中使用

### 自然对话（推荐）

直接 @Bot 或私聊说话，Bot 会自动理解你的意图：

```
"帮我找电锯人的本子"        → 搜索漫画
"最近什么最火"              → 排行榜
"推荐一本全彩的"            → 随机推荐
"看看 123456"              → 漫画详情
"下载 123456"              → 直接下载（不再确认）
```

### 精确命令

| 命令 | 说明 |
|------|------|
| `/jm search <关键词>` | 搜索漫画 |
| `/jm rank [day\|week\|month]` | 排行榜（默认日榜） |
| `/jm random [--tag 标签]` | 随机推荐 |
| `/jm info <ID>` | 漫画详情 |
| `/jm download <ID>` | 下载并上传群文件 |
| `/jm download <ID1> <ID2>` | 批量下载 |
| `/jm category <标签>` | 按标签筛选 |
| `/jm cache` | 查看磁盘占用 |
| `/jm cache clean [天数]` | 清理旧下载（默认7天） |
| `/jm queue` | 下载队列 |
| `/jm stop` | 停止下载 |
| `/jm help` | 帮助 |

## 人格切换

WebUI → **人格设定**，可选 7 个人设：
- **色色猫娘**（默认）— 发情撒娇
- **郭大发** — 懒散敷衍
- **傲娇大小姐** — 表面高冷内心好奇
- **邪魅魅魔** — 妖艳掌控
- **温柔大姐姐** — 宠溺反差
- **病娇** — 软萌黑化
- **反差痴女** — 清纯变痴态

## 日常使用场景

### 推荐漫画
```
你：推荐一本纯爱的
Bot：本喵在书架深处翻了翻，找到3本纯爱好货...
```

### 看排行榜  
```
你：这周什么最火
Bot：🏆 这是本周大家冲得最多的 TOP10...
```

### 搜索下载
```
你：搜一下电锯人
Bot：喵呜~ 找到了5本电锯人的本子...
你：下载第一个
Bot：✨ 全部吸出来了！已上传群文件 ✅
```

### 闲聊
```
你：今天心情不好
Bot：喵呜...主人不开心本喵也会难过的(｡-́︿-̀｡) 
     要不要本喵帮主人找点治愈的本子？
```

## 可用功能汇总

| 功能 | 实现方式 |
|------|---------|
| AI 对话 | DeepSeek + 猫娘人格 |
| 长期记忆 | Iris Chat Memory（三层记忆） |
| 生活状态 | private_companion（日程安排） |
| 主动消息 | private_companion（想主人了会主动私聊） |
| 表情包 | smart_imagechat_hub |
| 漫画搜索 | JM 插件 → jmcomic API |
| 漫画下载 | JM 插件 → jmcomic → 自动转 PDF → 上传群文件 |
| 排行榜 | JM 插件 |
| 随机推荐 | JM 插件（支持标签筛选） |

## 成本控制

- 模型：DeepSeek-chat（API 按量计费）
- 每轮 Agent 最多 5 步工具调用（`max_agent_step: 5`）
- Iris 记忆系统可配置 Token 预算
- private_companion 可设置每日 Token 限额

## 故障排查

### Bot 没反应
1. 检查 NapCat 是否在运行（端口 3001/3002 是否在监听）
2. 检查 AstrBot 是否在运行（`http://localhost:6185` 能否打开）
3. 检查 NapCat WS Client 是否连上 AstrBot（日志有无 "ESTABLISHED"）

### 下载失败
1. 确认漫画 ID 正确
2. 检查 GoodbyeDPI 是否在运行（CDN 需要翻墙）
3. 查看 AstrBot 控制台日志

### 登录 WebUI 失败
密码 `jm123456`，如忘记执行：
```bash
# 重置密码
python -c "import json,hashlib,os; p=os.path.expanduser('~/.astrbot/data/cmd_config.json'); c=json.load(open(p)); c['dashboard']['password']=hashlib.md5(b'jm123456').hexdigest(); json.dump(c,open(p,'w'))"
```
