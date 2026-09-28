# JM Bot TTS 语音方案（设计稿 · 云端 API 版）

> 状态：**已定稿，待 jm_bot_v2 重构完成后实施**（2026-09-28 决策）
> 决策：音色走二次元克隆 → **云端 API（硅基流动，CosyVoice2/fish-speech 克隆音色）**，不用本机 GPU；触发用群级语音模式开关；先覆盖本机 v2，本机开发与服务器部署共用同一套 API，零迁移成本。

## 一、为什么选云端 API（决策记录）

- 最终部署在阿里云服务器，TTS 引擎必须是"两边跑都一样"的东西——云端 API 天然满足：本机 v2 开发期和服务器运行期用同一个 key，无迁移步骤
- 二次元克隆音色：上传参考音频到云端提取音色，不需要本机 GPU / 整合包 / 常驻推理服务（RTX 5060 方案已否决）
- 备选引擎：**阿里云百炼 CosyVoice 声音复刻**（服务器同厂商、账号现成）。`tts.py` 做成引擎可配置，两者都只是 HTTP 客户端，切换只改配置
- 已评估并否决 **Gemini TTS**（2026-09-28）：音质和自然语言风格控制第一梯队、支持中文，但 (1) 只有 ~30 个预置音色，**不支持音色克隆**，与"二次元克隆音色"决策冲突；(2) `generativelanguage.googleapis.com` 大陆被墙，阿里云服务器直连不通，加代理违背"国内直连、零故障点"的部署约束；(3) 需国际支付绑卡。仅可留作 `tts.py` 可选引擎（本机翻墙调试用），生产不依赖

### 音色克隆选型对比（2026-09-28 调研，价格为调研时口径，以各家定价页为准）

| 服务 | 克隆方式 | 克隆费用 | 合成费用（~300 字/条约） | 国内直连 | 接入难度 | 二次元/口碑备注 |
|---|---|---|---|---|---|---|
| **硅基流动**（现主力） | 上传参考音频即时克隆（`/v1/uploads/audio/voice`），账号需实名 | 免费 | ~¥0.09（约 ¥105/百万 UTF-8 字节） | ✅ | **最低**（OpenAI 兼容，克隆+合成各一个 POST） | CosyVoice2 依赖参考音频质量；fish-speech-1.5 戏感更好 |
| **Reecho 睿声 / vocu.ai** | 5 秒瞬时克隆 + 声音市场（现成二次元音色） | 注册送积分 + 每日额度 | 积分制，注册后在控制台确认 | ✅ | 低（REST API） | **ACG 配音社区口碑最好**，二次元升级首选 |
| **MiniMax** Speech 2.x | 快速复刻（无需长录音）；voice_id 7 天内合成一次才永久保留 | 首次用该音色合成时收，约 50 元/音色（7 角色 ≈ 350 元一次性） | ~¥0.03（约 0.9-2 元/万字符） | ✅ | 中（上传→克隆→激活多两步） | 中文自然度天花板级，社区评测优于 ElevenLabs |
| **火山豆包** 声音复刻 2.0 | 5 秒样本复刻，官方称相似度 97.5% | 未查到公开免费额度，资源包制 | 资源包，控制台为准 | ✅ | 高（火山应用/控制台体系） | 大厂稳定，接入企业味重 |
| **阿里百炼** CosyVoice 复刻 | 参考音频提交审核制 | 复刻免费 | ~¥2/万字符量级 | ✅ | 中 | 与部署环境同厂商，账号现成 |

**选型结论**：主力维持硅基流动（唯一"克隆免费 + 接入最简 + 直连"三占的），实施清单第 1 步改为**试音对比**：同一段参考音频在 CosyVoice2 和 fish-speech 各生成 2-3 条样品，同时验证色色文案的内容审核通过率。若音色不满意，按需求方向升级：**要二次元味 → Reecho；要自然度 → MiniMax**（两者都只是 `tts.py` 里换引擎）。

## 二、目标与边界

- 群主可用 `/jm voice on|off` 开关本群语音模式（持久化，默认关）
- 语音模式开启后，**AI 聊天/闲聊回复**转为语音发送；**数据类回复保持文字**
- 语音合成失败时自动回退发文本，永远不吞回复

### 哪些消息走语音（显式优于隐式）

| 走语音 | 保持文字 |
|---|---|
| `group_chat` 纯聊天回复（@本喵 闲聊、/jm ask 的 chat 分支） | 搜索结果、info、rank、random（ID/标题列表需要复制） |
| | 下载全链路状态、错误提示、help |

实现方式：聊天路径显式改调 `messaging.send_group_voice()`，数据路径一行不动。

## 三、架构

```
本机（开发期）                        阿里云服务器（部署后）
├─ NapCat 3001/3002                  ├─ NapCat 3001/3002
├─ jm_bot_v2 ──┐                     ├─ AstrBot + JM 插件 ──┐
└──────────────┼── HTTPS ──> 硅基流动 https://api.siliconflow.cn/v1/audio/speech
               │    （国内直连，无需代理/翻墙）
```

### 云端 API 要点（硅基流动）

- **合成**：`POST https://api.siliconflow.cn/v1/audio/speech`
  - 请求体：`{"model": "FunAudioLLM/CosyVoice2-0.5B", "input": "<文本>", "voice": "<克隆音色ID>", "speed": 1.0, "response_format": "mp3"}`，Bearer 鉴权，响应为音频二进制
  - 备选模型 `fishaudio/fish-speech-1.5`（动漫语气通常更好，实施时两个都试）
- **音色克隆（一次性准备）**：`POST /v1/uploads/audio/voice` 上传参考音频 → 返回自定义音色 ID（形如 `speech:xxx:yyy`）；`GET /v1/audio/voice/list` 可查已建音色
  - 注意：音色 ID 与账号的 API key 绑定，账号需实名认证
- **成本量级**：按官方定价约 ¥100/百万 UTF-8 字节（以定价页为准），一条 ~300 字回复约 1 毛钱，群聊日常用量每月几块~几十块；新用户有免费额度可直接开发调试

### 新增/改动组件（jm_bot_v2）

1. **`bot/tts.py`（新增）** — TTS 引擎抽象 + 硅基流动实现
   - 接口：`synthesize(text: str, role_id: int) -> Optional[str]`，返回音频文件路径，失败返回 None
   - 引擎由 `config.json` 配置：
     ```json
     "tts": {
       "engine": "siliconflow",
       "api_key": "",
       "model": "FunAudioLLM/CosyVoice2-0.5B",
       "timeout_seconds": 30,
       "max_chars": 300
     }
     ```
   - 文本预处理 `preprocess(text)`：过滤 emoji/`[]`表情/Markdown 符号（正则），截断至 **300 字符**（约 40-50 秒语音，低于 QQ 群语音 60 秒上限）
   - 请求用 `requests` 直连（走系统 `NO_PROXY` 约定，仅放行 localhost；对 api.siliconflow.cn 不设代理）

2. **`tts_voices.json`（新增，音色映射表）**
   - `role_id → {"voice_id": "speech:xxx:yyy", "ref_audio": "tts_voices/<role>/ref.wav"}`（ref_audio 留作重建音色/换引擎时用）
   - 7 个角色各配一条（猫娘/傲娇/魅魔/大姐姐/病娇/痴女/郭大发）= 7 个克隆音色；没配的角色回退默认音色
   - 素材自备：每角色一段 5-10 秒干净人声即可（云端克隆，无需微调训练）

3. **`bot/messaging.py`（改动）** — 新增 `send_group_voice(group_id, text, reply_msg_id)`
   - 查缓存 `tts_cache/<md5(text+role)>.mp3`，命中直接发（省钱省延迟）
   - 未命中 → `tts.synthesize()` → 发送 → 落缓存（复用 `clean_old_dirs` 定期清理 tts_cache）
   - 发送：NapCat `send_group_msg`，消息段 `{"type": "record", "data": {"file": "file:///<abs path>"}}`；NapCat 自动转 silk（**依赖 ffmpeg，NapCat Shell 首次会自下载**）
   - 任何一步失败 → 回退 `send_group_reply()` 原文本

4. **`bot/runtime.py` / 命令路由（改动）** — `/jm voice on|off|status` 子命令，开关状态存入 v2 的 state（沿用 group_roles.json 同款持久化方式）

### 服务器二期（AstrBot 插件）

- 不需要 SSH 隧道回本机（已无本机推理服务），插件直接用同一个硅基流动 key
- 两条接入路径，实施时择一：
  - a) 插件内自建 voice 发送（复用 v2 的 tts.py 思路，注意插件目录的 download.py/messages.py 是独立副本，勿混改）
  - b) AstrBot WebUI 配 TTS provider（openai_compatible 类型指向硅基流动端点，或先用 edge-tts 过渡），群里 `/tts` 开关即用
- 插件侧群级开关（AstrBot 自带的是会话级）二期再评估是否需要插件化

## 四、数据流

```
群友 @本喵 说话
  → group_chat() 生成回复文本（现有链路不动）
  → 群 voice 模式开？
      ├─ 否 → send_group_reply 文本（现状）
      └─ 是 → tts.preprocess() → tts_cache 命中？
                  ├─ 命中 → record 段发送
                  └─ 未命中 → POST 硅基流动 → mp3 → 落缓存 → record 段发送
                                └─ 任一步失败 → 回退文本
```

## 五、错误处理

| 故障 | 处理 |
|---|---|
| 网络超时 / API 5xx（timeout 30s） | 重试 1 次 → 仍失败回退文本，log warning |
| 429 限流 / 余额不足 | 不重试直接回退文本，log error（余额类错误要显眼，避免长期静默降级） |
| **内容审核拒绝**（本项目特有风险：色色猫娘文案送云端合成可能被拒） | 回退文本；若某角色音色+文案组合频繁被拒，考虑该角色换模型（fish-speech）或降敏文本预处理 |
| 文本超长 | 预处理截断 300 字 |
| ffmpeg 缺失（NapCat 转 silk 失败） | bot 启动时 `ffmpeg -version` 自检，缺了在启动日志显眼提示 |
| 合成请求过频 | 复用群 15s 限速；同一群已有语音在发则排队 |
| 中文路径（用户名含单引号） | 音频落在脚本目录下的 tts_cache，record 段用绝对路径双引号包裹（沿用现有坑位约定） |

## 六、验证

- `test_all.py`（纯脚本风格）新增 tts 用例：preprocess 过滤、tts_voices.json 读取、mock HTTP 的 synthesize 调用与回退逻辑（不真实调 API）
- 手测清单：`/jm voice on` → @本喵 聊天收语音 → 搜索结果仍是文字 → `voice off` 恢复 → 断网/错 key 验证文本回退 → 重复同句验证缓存

## 七、实施清单（v2 重构完成后照此执行）

1. 硅基流动注册 + 实名 + 建 key；**试音对比**（同一段参考音频 × CosyVoice2 / fish-speech 各出几条样品，含色色文案审核验证），不满意则按上表换 Reecho/MiniMax；确定引擎后上传 7 角色参考音频建克隆音色，把音色 ID 填进 `tts_voices.json`
2. 写 `bot/tts.py`（引擎抽象 + siliconflow 实现 + preprocess + 预处理单测）
3. `messaging.send_group_voice()` + 缓存；聊天路径切换调用
4. `/jm voice` 子命令 + 持久化
5. ffmpeg 自检 + 手测清单过一遍
6. 二期：服务器插件接入（同 key）

## 八、工作量估算

| 项 | 估时 |
|---|---|
| 云端账号/克隆音色准备 | 0.5 天 |
| tts.py + messaging/路由改动 + 配置 | 1-1.5 天 |
| 服务器二期（插件接入） | 0.5-1 天 |
