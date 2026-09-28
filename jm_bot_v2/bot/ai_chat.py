"""
JM Bot AI 聊天模块 — 通过 DeepSeek API (Anthropic 兼容) 实现 /jm ask 自然语言交互
采用 JSON 意图分类 → 直接执行 → 猫娘回复 的简化架构

由根目录 ai_chat.py 迁移；角色系统拆至 roles.py
"""
import os
import json
import logging
from anthropic import Anthropic, AnthropicError

from . import config
from .roles import ROLES, get_group_role

logger = logging.getLogger("jm_bot.ai_chat")


def _load_api_config():
    """加载 API 配置：优先环境变量，缺失项回退 config.json 的 ai 段"""
    cfg = config.CONFIG.get("ai", {})
    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN", "") or cfg.get("api_key", "")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "") or cfg.get("base_url", "")
    model = os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "") or cfg.get("model", "")

    if not api_key:
        logger.warning("未配置 API Key，/jm ask 将不可用")

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
# 群聊历史（持久化 + 自动压缩）
# ═══════════════════════════════════════════

HISTORY_FILE = os.path.join(config.BASE_DIR, "chat_history.json")
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


def save_history(group_id: int, user_msg: str, bot_reply: str):
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
                save_history(group_id, user_message, reply)
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
