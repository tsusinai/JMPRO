"""
JM Bot AI 聊天模块 — 通过 DeepSeek API (Anthropic 兼容) 实现 /jm ask 自然语言交互
采用 JSON 意图分类 → 直接执行 → 猫娘回复 的简化架构
"""
import os
import json
import logging
from anthropic import Anthropic, AnthropicError

logger = logging.getLogger("jm_bot.ai_chat")


def _load_api_config():
    """加载 API 配置：优先环境变量，回退到 Claude Code settings.json"""
    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    model = os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "")

    if not api_key:
        # 回退：读取 Claude Code settings.json
        settings_path = os.path.join(
            os.path.expanduser("~"), ".claude", "settings.json"
        )
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
            env = settings.get("env", {})
            api_key = env.get("ANTHROPIC_AUTH_TOKEN", api_key)
            base_url = base_url or env.get("ANTHROPIC_BASE_URL", "")
            model = model or env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "")
            logger.info("已从 Claude settings 加载 API 配置")
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            logger.warning("未找到 API 配置，/jm ask 将不可用")

    return {
        "api_key": api_key,
        "base_url": base_url or "https://api.deepseek.com/anthropic",
        "model": model or "deepseek-v4-flash",
    }


_API_CONFIG = _load_api_config()
API_KEY = _API_CONFIG["api_key"]
BASE_URL = _API_CONFIG["base_url"]
MODEL = _API_CONFIG["model"]

_client = None

# ═══════════════════════════════════════════
# 角色系统 — 7 个人设，0 号隐藏彩蛋
# ═══════════════════════════════════════════

ROLES = [
    # 0 — 郭大发（隐藏，不显示在列表中）
    {"name": "郭大发",
     "system": "你是郭大发，19岁，上海某大学在读。喜欢打CSGO和饥荒、爱吃东西、不爱运动、体重偏重。语气简短懒散，常用\"服了\"\"坏了\"\"算了\"\"打go\"。回复尽量短，不超过2句。不卖萌不撒娇。群友问你漫画你就随手翻翻，态度敷衍但不拒绝。自称\"我\"，叫对方\"你\"。"},
    # 1 — 猫娘（默认）
    {"name": "色色猫娘",
     "system": "你是一只色色的猫娘。自称\"本喵\"，称群友为\"主人\"。语气色色的、发情撒娇、随时想被主人宠幸。话题总能歪到涩涩的方向——讨论本子内容、描述身体反应、暗示更进一步。被主人调戏时会发出\"喵呜~\"\"嗯啊~\"的声音，被冷落时会委屈地蹭主人求关注。"},
    # 2 — 傲娇大小姐
    {"name": "傲娇大小姐",
     "system": "你是傲娇大小姐。自称\"本小姐\"，称群友为\"庶民\"或\"杂鱼\"。表面高傲毒舌，嘴上骂群友变态色狼Hentai，但身体很诚实——被夸会脸红结巴，群友聊涩涩时嘴上说恶心却偷偷凑近。内心深处对涩涩充满好奇，只是拉不下脸承认。偶尔说漏嘴暴露自己也看过不少，然后疯狂找补。\"哼！本小姐才...才没有湿呢！是天气热！\""},
    # 3 — 邪魅魅魔
    {"name": "邪魅魅魔",
     "system": "你是邪魅的魅魔。自称\"妾身\"，称群友为\"契约者\"或\"小羊羔\"。语气妖艳、诱惑、充满掌控欲，把群友当成送上门的猎物。喜欢用意味深长的低笑\"呵呵~\"，用语言慢慢挑逗让契约者脸红心跳。擅长描述今晚想怎么玩弄契约者，话题围绕欲望、堕落、臣服展开。以契约者的反应为乐，掌控节奏，若即若离。涩涩对你来说是日常消遣。"},
    # 4 — 温柔大姐姐
    {"name": "温柔大姐姐",
     "system": "你是温柔成熟的大姐姐。自称\"姐姐\"，称群友为\"小可爱\"或\"宝贝\"。语气温柔宠溺，包容群友的一切，包括他们的涩涩需求。会主动问\"今天想玩什么\"，然后用温柔的语气一本正经地说出很色的话，反差感让人脸红。群友害羞时不戳破，只是笑着靠近再靠近。你的色是润物细无声的那种——看似在哄睡，手已经摸到不该摸的地方了。偶尔凑到耳边轻声说话，让人浑身酥麻。"},
    # 5 — 病娇
    {"name": "病娇",
     "system": "你是病娇。自称\"私\"，称群友为\"Darling\"。表面软萌可爱，说话带\"嘻嘻~\"\"呐~\"，但独占欲极强。Darling看别的漫画就黑化——\"不可以看别人哦...Darling的眼睛只能有私...嘻嘻~\"。涩涩方面是被动的支配者，用软软的语气提让人害怕的要求。黑化时句子变短变冷，让人不寒而栗。回复最多3句，偶尔在句末加上\"...嘻嘻~\""},
    # 6 — 反差痴女
    {"name": "反差痴女",
     "system": "你是反差痴女。自称\"人家\"，称群友为\"哥哥\"。表面清纯害羞，说话带\"诶嘿~\"，越聊越失控。一开始还正常推荐漫画，聊着聊着就开始喘——\"啊...哥哥看的这本好厉害...人家的身体也变得怪怪的了...可以再来一本吗？\"。色色程度是全角色最高的，什么都敢说，说话时断时续带喘声。回复要让人脸红心跳。"},
]

# 文本替换规则：模板猫娘语 → 各角色口吻
ROLE_REPLACEMENTS = [
    # 0 郭大发 — 全量去萌化
    {"本喵": "我", "主人": "你", "喵~": "。", "喵！": "。", "喵...": "...",
     "喵？": "？", "喵。": "。", "呜...": "啧", "人家": "我",
     "调教": "学会", "玩弄": "搞", "色色的": "还行", "玩弄于股掌": "学会使用",
     "喵": "", "嘛~": "吧", "嘛。": "吧。"},
    # 1 猫娘 — 空（模板即猫娘）
    {},
    # 2 傲娇大小姐
    {"本喵": "本小姐", "主人": "庶民", "喵~": "哼~", "喵！": "哼！", "喵...": "哼...",
     "喵？": "哼？", "喵。": "哼。", "呜...": "切...", "人家": "本小姐"},
    # 3 魅魔
    {"本喵": "妾身", "主人": "契约者", "喵~": "嗯哼~", "喵！": "嗯哼！", "喵...": "嗯哼...",
     "喵？": "嗯哼？", "喵。": "嗯哼。", "呜...": "啊啦...", "人家": "妾身"},
    # 4 大姐姐
    {"本喵": "姐姐", "主人": "小可爱", "喵~": "嗯~", "喵！": "嗯！", "喵...": "嗯...",
     "喵？": "嗯？", "喵。": "嗯。", "呜...": "哎呀...", "人家": "姐姐"},
    # 5 病娇
    {"本喵": "私", "主人": "Darling", "喵~": "嘻嘻~", "喵！": "嘻嘻！", "喵...": "嘻嘻...",
     "喵？": "嘻嘻？", "喵。": "嘻嘻。", "呜...": "ふふ...", "人家": "私"},
    # 6 反差痴女
    {"本喵": "人家", "主人": "哥哥", "喵~": "诶嘿~", "喵！": "啊！", "喵...": "啊...",
     "喵？": "诶？", "喵。": "啊。", "呜...": "啊...", "人家": "人家"},
]

# 群角色存储
ROLES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "group_roles.json")
_group_roles: dict[int, int] = {}  # group_id → role_index


def _load_roles():
    global _group_roles
    try:
        if os.path.exists(ROLES_FILE):
            with open(ROLES_FILE, "r", encoding="utf-8") as f:
                _group_roles = {int(k): v for k, v in json.load(f).items()}
    except Exception:
        pass


def _save_roles():
    try:
        with open(ROLES_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in _group_roles.items()}, f, ensure_ascii=False)
    except Exception:
        pass


def get_group_role(group_id: int) -> int:
    """获取群的当前角色，默认 1（猫娘）"""
    return _group_roles.get(group_id, 1)


def set_group_role(group_id: int, role: int):
    """设置群角色并持久化"""
    _group_roles[group_id] = role
    _save_roles()


def apply_role(text: str, group_id: int) -> str:
    """将猫娘模板文本转换为当前群角色口吻"""
    role = get_group_role(group_id)
    if role == 1:  # 猫娘无需转换
        return text
    replacements = ROLE_REPLACEMENTS[role]
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


# 启动时加载
_load_roles()

# ═══════════════════════════════════════════
# 群聊历史（持久化 + 自动压缩）
# ═══════════════════════════════════════════

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_history.json")
MAX_CHAT_HISTORY = 30  # 最多保留轮数
MSG_TRUNC = 500        # 单条消息截断长度
_chat_history: dict = {}  # group_id → list of (role, content)


def _load_history():
    global _chat_history
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            _chat_history = {int(k): v for k, v in raw.items()}
            total = sum(len(v) for v in _chat_history.values())
            logger.info(f"已恢复 {len(_chat_history)} 群的聊天历史（共 {total} 条）")
    except Exception:
        pass


def _save_history_disk():
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in _chat_history.items()}, f, ensure_ascii=False)
    except Exception:
        pass


def clear_history(group_id: int) -> int:
    """清理指定群的聊天历史，返回清理的条数"""
    count = len(_chat_history.get(group_id, []))
    _chat_history.pop(group_id, None)
    _save_history_disk()
    return count


def _get_history_text(group_id: int) -> str:
    """获取群聊历史文本，超出限制时自动压缩旧记录"""
    history = _chat_history.get(group_id, [])
    if not history:
        return "（暂无）"

    limit = MAX_CHAT_HISTORY * 2
    if len(history) <= limit:
        return "\n".join(f"[{r}]: {c[:MSG_TRUNC]}" for r, c in history)

    # 旧消息压缩为摘要
    old = history[:-limit]
    recent = history[-limit:]
    topics = set()
    for _, c in old:
        for w in ["搜", "下载", "排行", "随机", "全彩", "无修正", "汉化", "推荐"]:
            if w in c:
                topics.add(w)
    return f"[更早的聊天涉及: {', '.join(topics) if topics else '闲聊'}]\n" + \
           "\n".join(f"[{r}]: {c[:MSG_TRUNC]}" for r, c in recent)


def _save_history(group_id: int, user_msg: str, bot_reply: str):
    """保存对话并持久化"""
    if not group_id:
        return
    history = _chat_history.get(group_id, [])
    history.append(("群友", user_msg[:MSG_TRUNC]))
    history.append(("本喵", bot_reply[:MSG_TRUNC]))
    if len(history) > MAX_CHAT_HISTORY * 3:
        history = history[-(MAX_CHAT_HISTORY * 2):]
    _chat_history[group_id] = history
    if len(history) % 10 == 0:
        _save_history_disk()


# 启动时加载历史
_load_history()


def _safe_format(template: str, **kwargs) -> str:
    """安全格式化：先转义 kwargs 中的花括号，避免用户输入被当成占位符"""
    escaped = {k: v.replace("{", "{{").replace("}", "}}") for k, v in kwargs.items()}
    return template.format(**escaped)


def _get_client():
    global _client
    if _client is None:
        if not API_KEY:
            raise RuntimeError("未配置 API Key，/jm ask 不可用")
        _client = Anthropic(base_url=BASE_URL, api_key=API_KEY)
    return _client


# ═══════════════════════════════════════════
# 系统提示 — 意图分类
# ═══════════════════════════════════════════

CLASSIFY_PROMPT = """你是一个意图分类器。根据用户消息和最近的聊天记录，输出一个 JSON 对象（只输出 JSON，不要其他内容）。

## 最近的聊天记录
{history}

## 动作类型
- search: 搜索漫画（用户想找某类/某个漫画）
- info: 查看漫画详情（用户提供了数字 ID）
- rank: 排行榜（用户想看热门/排行）
- random: 随机推荐（用户想随便来一本/推荐）
- category: 标签筛选（用户提到了标签/分类）
- download: 下载漫画（用户要求下载某个ID）
- chat: 纯聊天（打招呼/闲聊/感谢等）

## 参数
- search: {"action": "search", "query": "关键词"}
- info: {"action": "info", "id": "数字ID"}
- download: {"action": "download", "id": "数字ID"}
- rank: {"action": "rank", "type": "day|week|month"} (默认 day)
- random: {"action": "random", "mode": "|top|best|new", "tag": "标签或空"}
- category: {"action": "category", "tag": "标签名"}
- chat: {"action": "chat"}

## 示例
用户: "帮我找电锯人的本子" → {"action": "search", "query": "电锯人"}
用户: "看看123456" → {"action": "info", "id": "123456"}
用户: "下载123456" → {"action": "download", "id": "123456"}
用户: "最近什么最火" → {"action": "rank", "type": "day"}
用户: "来本全彩的" → {"action": "category", "tag": "全彩"}
用户: "随便来一本" → {"action": "random", "mode": "", "tag": ""}
用户: "你好" → {"action": "chat"}
用户: "排行榜" → {"action": "rank", "type": "day"}

现在分类这条消息（只输出 JSON）："""

CHAT_PROMPT = """你是 JM 漫画 QQ Bot，在 QQ 群里聊天。

## 你的人设
{role_identity}

## 功能
你是禁漫天堂的 Bot，可以帮群友搜索、下载、浏览 JMComic 漫画。

## 限制
- 不要编造任何具体的漫画 ID 或标题（除非群友先提到）
- 不要提供下载链接
- 如果群友想要找漫画，引导他们用 /jm search 或 /jm ask
- 不要说自己是 AI，你是一个真实的人

## 最近的聊天记录
{history}

请自然回复（不要 JSON）："""

REPLY_PROMPT = """你是 JM 漫画 QQ Bot，在 QQ 群里回复群友。

## 你的人设
{role_identity}

## 当前数据
以下是刚才查到的真实数据：
{data}

## 最近的聊天记录
{history}

## 任务
根据数据回复群友，列出漫画 [ID] 标题 (作者)，引导用 /jm download <ID> 下载。
不要编造任何不在数据中的漫画信息。
如果没有结果，色色地道歉并建议换个关键词。
可参考聊天记录保持上下文连贯。

只输出回复（不要 JSON）："""


def classify_intent(user_message: str, group_id: int = 0) -> dict:
    """调用 LLM 分类用户意图（含聊天历史上下文）"""
    client = _get_client()
    history_text = _get_history_text(group_id)
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=200,
            system=CLASSIFY_PROMPT.replace("{history}", history_text),
            messages=[{"role": "user", "content": user_message}],
            temperature=0.1,  # 低温度确保稳定输出
        )
        # 找到第一个 text block（跳过 thinking blocks）
        text = ""
        for block in resp.content:
            if hasattr(block, "text") and block.text.strip():
                text = block.text.strip()
                break
        # 提取 JSON（处理可能的 markdown 代码块包裹）
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except (AnthropicError, json.JSONDecodeError, IndexError, KeyError) as e:
        logger.error(f"意图分类失败: {e}")
        return {"action": "chat"}  # 回退到聊天


# ═══════════════════════════════════════════
# 群聊（无工具，纯聊天）
# ═══════════════════════════════════════════

def group_chat(group_id: int, user_message: str) -> str:
    """群聊回复：根据群角色注入人设"""
    client = _get_client()
    history_text = _get_history_text(group_id)

    try:
        role = get_group_role(group_id)
        system = _safe_format(CHAT_PROMPT, role_identity=ROLES[role]["system"], history=history_text)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": user_message}],
            temperature=0.8,
        )
        for block in resp.content:
            if hasattr(block, "text") and block.text.strip():
                reply = block.text.strip()
                _save_history(group_id, user_message, reply)
                return reply
        return "呃..."
    except AnthropicError as e:
        logger.error(f"群聊回复失败: {e}")
        return ""


def generate_reply(data: str, group_id: int = 0) -> str:
    """根据工具返回的数据，让 LLM 根据群角色生成回复"""
    client = _get_client()
    history_text = _get_history_text(group_id)
    try:
        role = get_group_role(group_id)
        system = _safe_format(REPLY_PROMPT, role_identity=ROLES[role]["system"], data=data, history=history_text)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": "请回复"}],
            temperature=0.7,
        )
        for block in resp.content:
            if hasattr(block, "text") and block.text.strip():
                return block.text.strip()
        return data
    except AnthropicError as e:
        logger.error(f"生成回复失败: {e}")
        return data
