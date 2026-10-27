"""
JM Bot AI 聊天模块 — 通过 DeepSeek API (Anthropic 兼容) 实现 /jm ask 自然语言交互
采用 JSON 意图分类 → 直接执行 → 猫娘回复 的简化架构

由根目录 ai_chat.py 迁移；角色系统拆至 roles.py
"""
import base64
import mimetypes
import os
import json
import logging

import requests
from anthropic import Anthropic, AnthropicError

from . import config, memory, memes
from .messages import M
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
        snapshot = dict(_chat_history)
        tmp_file = f"{HISTORY_FILE}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in snapshot.items()}, f, ensure_ascii=False)
        os.replace(tmp_file, HISTORY_FILE)
    except Exception as e:
        logger.warning(f"保存聊天历史失败: {e}")


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


def _nl_cfg_int(key: str, default: int) -> int:
    try:
        return int(config.CONFIG.get("nl", {}).get(key, default))
    except (ValueError, TypeError):
        return default


def _get_context_text(group_id: int, user_message: str = "", user_id: int = 0) -> str:
    """上下文 = 长期记忆块 + 按人记忆 + 热梗提示 + 近期对话历史（供分类/聊天/回复三处统一取用）"""
    parts = []
    mem = memory.get_memory_text(group_id)
    if mem:
        parts.append("【长期记忆】\n" + mem)
    if user_id:
        user_mem = memory.get_user_memory_text(group_id, user_id, query=user_message)
        if user_mem and user_mem.strip():
            parts.append(user_mem.strip())
    parts.append(_get_history_text(group_id))
    text = "\n".join(parts)
    if user_message:
        mc = memes.meme_context(user_message, max_entries=_nl_cfg_int("meme_max_entries", 2))
        if mc:
            text += "\n" + mc
    return text


def save_history(group_id: int, user_msg: str, bot_reply: str):
    """保存对话并持久化"""
    if not group_id:
        return
    history = _chat_history.get(group_id, [])
    history.append(("群友", user_msg[:MSG_TRUNC]))
    history.append(("本喵", bot_reply[:MSG_TRUNC]))
    snap = list(history)
    if len(snap) > MAX_CHAT_HISTORY * 3:
        history = snap[-(MAX_CHAT_HISTORY * 2):]
    _chat_history[group_id] = history
    memory.maybe_compress(group_id, snap)
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
        if "127.0.0.1" in BASE_URL or "localhost" in BASE_URL:
            # 本地反代：必须 trust_env=False。本机 env 的 NO_PROXY 含 [::1] 条目，
            # httpx2 在 trust_env=True 时解析 env 代理会抛 InvalidURL，客户端根本建不起来；
            # 同时也避免 egress 代理劫持 localhost 请求。
            try:
                import httpx2 as httpx
            except ImportError:
                import httpx
            _client = Anthropic(
                base_url=BASE_URL, api_key=API_KEY,
                http_client=httpx.Client(trust_env=False),
            )
        else:
            _client = Anthropic(base_url=BASE_URL, api_key=API_KEY)
    return _client


# ═══════════════════════════════════════════
# 读图片（被唤醒消息的图片 → Anthropic image block 直传）
# ═══════════════════════════════════════════

_IMG_CFG_DEFAULTS = {"enabled": True, "max_per_message": 3, "max_mb": 8, "timeout_seconds": 15}
_IMG_ALLOWED_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def _img_cfg() -> dict:
    cfg = config.CONFIG.get("images", {})
    res = dict(_IMG_CFG_DEFAULTS)
    if isinstance(cfg, dict):
        res.update(cfg)
    return res


def fetch_image_blocks(urls: list) -> list:
    """下载图片并转 Anthropic image block 列表；单张失败跳过；全部失败返回 []"""
    cfg = _img_cfg()
    if not cfg.get("enabled", True):
        return []
    max_items = cfg.get("max_per_message", 3)
    max_bytes = cfg.get("max_mb", 8) * 1024 * 1024
    timeout = cfg.get("timeout_seconds", 15)

    blocks = []
    for url in (urls or [])[:max_items]:
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        try:
            with requests.get(url, stream=True, timeout=timeout) as resp:
                if resp.status_code != 200:
                    logger.warning(f"下载图片失败 HTTP {resp.status_code}: {url}")
                    continue
                data = bytearray()
                oversize = False
                for chunk in resp.iter_content(chunk_size=65536):
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        logger.warning(f"图片体积超出限制 ({len(data)} > {max_bytes}): {url}")
                        oversize = True
                        break
                if oversize or not data:
                    continue
                ct = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if ct not in _IMG_ALLOWED_TYPES:
                    guessed, _ = mimetypes.guess_type(url)
                    ct = guessed.lower() if guessed and guessed.lower() in _IMG_ALLOWED_TYPES else "image/jpeg"
                blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": ct,
                        "data": base64.b64encode(bytes(data)).decode("ascii"),
                    },
                })
        except Exception as e:
            logger.warning(f"抓取图片异常 {url}: {e}")
            continue
    return blocks


# ═══════════════════════════════════════════
# 系统提示 — 意图分类
# ═══════════════════════════════════════════

CLASSIFY_PROMPT = """你是一个意图分类器。根据用户消息和最近的聊天记录，输出一个 JSON 对象（只输出 JSON，不要其他内容）。

## 最近的聊天记录
{history}

## 动作类型
- search: 搜索漫画（用户想找某类/某个漫画）
- info: 查看漫画详情（用户提供了数字 ID）
- rank: 排行榜
- random: 随机推荐
- category: 标签筛选
- download: 下载漫画（可多个 ID）
- queue: 查看下载队列/进度
- stop: 停止当前下载
- cache_status: 查看缓存/磁盘占用
- cache_clean: 清理旧缓存
- role: 查看或切换人设
- voice: 语音模式开关
- clear_history: 清空聊天记录/记忆
- send_sticker: 发一张表情包（用户明确想看表情包，或气氛明显适合用表情包回应且用户话里有此意）
- chat: 纯聊天
- unknown: 实在判断不了

## 输出格式（每种都必须带 confidence，0~1 的小数，表示你对分类的把握）
- search: {"action": "search", "query": "关键词", "confidence": 0.9}
- info: {"action": "info", "id": "数字ID", "confidence": 0.9}
- download: {"action": "download", "ids": ["数字ID",...], "format": "pdf|zip", "confidence": 0.9}（format 没提就 pdf）
- rank: {"action": "rank", "type": "day|week|month", "confidence": 0.9}（默认 day）
- random: {"action": "random", "mode": "|top|best|new", "tag": "标签或空", "confidence": 0.9}
- category: {"action": "category", "tag": "标签名", "confidence": 0.9}
- queue/stop/cache_status/clear_history: {"action": "queue", "confidence": 0.9}（同理替换 action 名）
- cache_clean: {"action": "cache_clean", "days": 7, "confidence": 0.9}（天数没提就 7）
- role: {"action": "role", "role": "编号或角色名，没提就空串", "confidence": 0.9}
- voice: {"action": "voice", "mode": "on|off|status", "confidence": 0.9}
- send_sticker: {"action": "send_sticker", "mood": "开心|生气|难过|害羞|撒娇|疑惑|委屈|激动|惊讶|饿", "confidence": 0.8}
- chat: {"action": "chat", "confidence": 0.9}
- unknown: {"action": "unknown", "confidence": 0.2}

## 示例
用户: "帮我找电锯人的本子" → {"action": "search", "query": "电锯人", "confidence": 0.95}
用户: "看看123456" → {"action": "info", "id": "123456", "confidence": 0.9}
用户: "把123456和234567都下了，zip的" → {"action": "download", "ids": ["123456", "234567"], "format": "zip", "confidence": 0.9}
用户: "最近什么最火" → {"action": "rank", "type": "day", "confidence": 0.9}
用户: "来本全彩的" → {"action": "category", "tag": "全彩", "confidence": 0.85}
用户: "随便来一本" → {"action": "random", "mode": "", "tag": "", "confidence": 0.9}
用户: "下了多少了" → {"action": "queue", "confidence": 0.85}
用户: "别下了" → {"action": "stop", "confidence": 0.9}
用户: "清一下老缓存" → {"action": "cache_clean", "days": 7, "confidence": 0.8}
用户: "换成大肥鱼" → {"action": "role", "role": "大肥鱼", "confidence": 0.9}
用户: "发个表情包乐呵乐呵" → {"action": "send_sticker", "mood": "开心", "confidence": 0.85}
用户: "你好" → {"action": "chat", "confidence": 0.95}

现在分类这条消息（只输出 JSON）："""

CHAT_PROMPT = """你是 JM 漫画 QQ Bot，在 QQ 群里聊天。

## 你的人设
{role_identity}

## 功能
你是禁漫天堂的 Bot，可以帮群友搜索、下载、浏览 JMComic 漫画。

## 限制
- 不要编造任何具体的漫画 ID 或标题（除非群友先提到）
- 不要提供下载链接
- 如果群友想要找漫画，引导他们直接说想找什么（比如"搜电锯人"），或用 /jm 命令
- 不要说自己是 AI，你是一个真实的人
- 回复简短：一般 1-2 句，一次只说一件事；不长篇大论、不说教、不列清单

## 最近的聊天记录
{history}

## 表情（可选，不要每句都用）
- 可以偶尔在回复里用 [表情名] 插入 QQ 表情，例如 [微笑] [吃瓜] [旺柴] [流泪]
- 也可以用 [[sticker:开心]] 在回复末尾发一张表情包图片，情绪可选：开心/生气/难过/害羞/撒娇/疑惑/委屈/激动/惊讶/饿；一条回复最多 1 个

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
- 回复简短：先给结果，1-3 句说清，不说教、不列长清单

## 表情（可选，不要每句都用）
- 可以偶尔在回复里用 [表情名] 插入 QQ 表情，例如 [微笑] [吃瓜] [旺柴] [流泪]
- 也可以用 [[sticker:开心]] 在回复末尾发一张表情包图片，情绪可选：开心/生气/难过/害羞/撒娇/疑惑/委屈/激动/惊讶/饿；一条回复最多 1 个

只输出回复（不要 JSON）："""

_KNOWN_ACTIONS = {
    "search", "info", "rank", "random", "category", "download",
    "queue", "stop", "cache_status", "cache_clean", "role",
    "voice", "clear_history", "send_sticker", "chat",
}
_STICKER_MOODS = {"开心", "生气", "难过", "害羞", "撒娇", "疑惑", "委屈", "激动", "惊讶", "饿"}


def normalize_intent(raw) -> dict:
    if not isinstance(raw, dict):
        return {"action": "unknown", "confidence": 0.0}

    raw_action = raw.get("action")
    action = raw_action if raw_action in _KNOWN_ACTIONS else "unknown"

    try:
        conf = float(raw.get("confidence"))
    except (ValueError, TypeError):
        conf = 1.0 if raw_action == "chat" else 0.5
    conf = max(0.0, min(1.0, conf))

    result = {"action": action, "confidence": conf}

    if action == "search":
        result["query"] = str(raw.get("query", "")).strip()
    elif action == "info":
        val = str(raw.get("id", "")).strip()
        result["id"] = val if val.isdigit() else ""
    elif action == "download":
        raw_ids = raw.get("ids")
        if raw_ids is None and "id" in raw:
            raw_ids = [raw["id"]]
        elif not isinstance(raw_ids, list):
            raw_ids = [raw_ids] if raw_ids is not None else []
        ids = []
        for x in raw_ids:
            s = str(x).strip()
            if s.isdigit() and s not in ids:
                ids.append(s)
        fmt = raw.get("format")
        result["ids"] = ids
        result["id"] = ids[0] if ids else ""  # 兼容旧调用方（cmd_ask 单 ID 口径）
        result["format"] = fmt if fmt in ("pdf", "zip") else "pdf"
    elif action == "rank":
        t = raw.get("type")
        result["type"] = t if t in ("day", "week", "month") else "day"
    elif action == "random":
        m = raw.get("mode")
        result["mode"] = m if m in ("", "top", "best", "new") else ""
        result["tag"] = str(raw.get("tag", "")).strip()
    elif action == "category":
        result["tag"] = str(raw.get("tag", "")).strip()
    elif action == "cache_clean":
        try:
            days = int(raw.get("days", 7))
        except (ValueError, TypeError):
            days = 7
        result["days"] = max(1, min(365, days))
    elif action == "role":
        result["role"] = str(raw.get("role", "")).strip()
    elif action == "voice":
        m = raw.get("mode")
        result["mode"] = m if m in ("on", "off", "status") else "status"
    elif action == "send_sticker":
        mood = raw.get("mood")
        result["mood"] = mood if mood in _STICKER_MOODS else "开心"

    return result


def classify_intent(user_message: str, group_id: int = 0, user_id: int = 0) -> dict:
    """调用 LLM 分类用户意图（含聊天历史上下文）"""
    client = _get_client()
    context_text = _get_context_text(group_id, user_message, user_id=user_id)
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=200,
            system=CLASSIFY_PROMPT.replace("{history}", context_text),
            messages=[{"role": "user", "content": user_message}],
            # 注：anthropic SDK 2.x 已移除 temperature 参数（传了会 TypeError），不再传
        )
        # 找到第一个 text block（跳过 thinking blocks）
        text = ""
        for block in resp.content:
            if hasattr(block, "text") and block.text.strip():
                text = block.text.strip()
                break
        # 提取 JSON（处理可能的 markdown 代码块包裹）
        if "```" in text:
            text = text.split("```")[1].strip()
            if text.startswith("json"):
                text = text[4:].strip()
        elif "{" in text and "}" in text:
            text = text[text.find("{"):text.rfind("}") + 1]
        parsed = json.loads(text)
        return normalize_intent(parsed)
    except Exception as e:
        logger.error(f"意图分类失败: {e}")
        return {"action": "error", "confidence": 0.0}


# ═══════════════════════════════════════════
# 群聊（无工具，纯聊天）
# ═══════════════════════════════════════════

THINK_PROMPT = """你即将在 QQ 群里回复消息。先在心里想一想，只输出一个 JSON 对象，不要输出其他内容：
{{"think": "一句话内心独白（用你人设的第一人称口吻、口语、40 字以内）", "tone": "这句回复的语气基调（2-6 个字，如：嘴硬心软、开心吐槽、耐心安慰）"}}

## 你的人设
{role_identity}

## 最近的聊天记录
{history}

## 群友刚说的
{user_message}

## 已判断的意图
{intent}

只输出 JSON："""


def think(group_id: int, user_message: str, intent_desc: str = "") -> dict:
    """内心思考步：生成内心独白与语气基调，只落日志不发送"""
    nl_cfg = config.CONFIG.get("nl", {})
    if nl_cfg.get("think_enabled") is False:
        return {"think": "", "tone": ""}
    try:
        client = _get_client()
        role = get_group_role(group_id)
        role_sys = ROLES[role]["system"]
        history_text = _get_history_text(group_id)
        system = _safe_format(
            THINK_PROMPT,
            role_identity=role_sys,
            history=history_text,
            user_message=user_message,
            intent=intent_desc,
        )
        resp = client.messages.create(
            model=MODEL,
            max_tokens=150,
            system=system,
            messages=[{"role": "user", "content": "思考"}],
        )
        text = ""
        for block in resp.content:
            if hasattr(block, "text") and block.text.strip():
                text = block.text.strip()
                break
        if "```" in text:
            text = text.split("```")[1].strip()
            if text.startswith("json"):
                text = text[4:].strip()
        elif "{" in text and "}" in text:
            text = text[text.find("{"):text.rfind("}") + 1]
        data = json.loads(text)
        think_text = str(data.get("think", "")).strip()[:80]
        tone = str(data.get("tone", "")).strip()
        if think_text or tone:
            logger.info(f"[内心思考] 群{group_id}: {think_text}（语气: {tone}）")
        return {"think": think_text, "tone": tone}
    except Exception as e:
        logger.debug(f"内心思考跳过/失败: {e}")
        return {"think": "", "tone": ""}


def group_chat(group_id: int, user_message: str, images: list | None = None, thought: str = "", user_id: int = 0) -> str:
    """群聊回复：根据群角色注入人设；images 为 Anthropic image block 列表时走多模态直传"""
    client = _get_client()
    history_text = _get_context_text(group_id, user_message, user_id=user_id)

    try:
        role = get_group_role(group_id)
        system = _safe_format(CHAT_PROMPT, role_identity=ROLES[role]["system"], history=history_text)
        if thought:
            system += "\n\n## 你刚才的内心想法（把握语气用，不要说出来）\n" + thought
        if images:
            text_prompt = user_message or "看看这张图片，描述一下并聊聊"
            content = list(images) + [{"type": "text", "text": text_prompt}]
            saved_user_msg = f"{user_message} [图片]".strip() if user_message else "[图片]"
        else:
            content = user_message
            saved_user_msg = user_message
        resp = client.messages.create(
            model=MODEL,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": content}],
            # 注：anthropic SDK 2.x 已移除 temperature 参数，不再传
        )
        for block in resp.content:
            if hasattr(block, "text") and block.text.strip():
                reply = block.text.strip()
                save_history(group_id, saved_user_msg, reply)
                return reply
        return "呃..."
    except AnthropicError as e:
        logger.error(f"群聊回复失败: {e}")
        return ""


def generate_reply(data: str, group_id: int = 0, user_message: str = "", thought: str = "", user_id: int = 0) -> str:
    """根据工具返回的数据，让 LLM 根据群角色生成回复"""
    client = _get_client()
    history_text = _get_context_text(group_id, user_message, user_id=user_id)
    try:
        role = get_group_role(group_id)
        system = _safe_format(REPLY_PROMPT, role_identity=ROLES[role]["system"], data=data, history=history_text)
        if thought:
            system += "\n\n## 你刚才的内心想法（把握语气用，不要说出来）\n" + thought
        resp = client.messages.create(
            model=MODEL,
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": "请回复"}],
            # 注：anthropic SDK 2.x 已移除 temperature 参数，不再传
        )
        for block in resp.content:
            if hasattr(block, "text") and block.text.strip():
                return block.text.strip()
        return data
    except AnthropicError as e:
        logger.error(f"生成回复失败: {e}")
        return data


def generate_clarify(group_id: int, user_message: str, candidates: list | None = None, user_id: int = 0) -> str:
    """用人设口吻向用户澄清意图"""
    try:
        client = _get_client()
        role = get_group_role(group_id)
        role_sys = ROLES[role]["system"]
        context_text = _get_context_text(group_id, user_message, user_id=user_id)
        cand_str = "、".join(candidates) if candidates else "搜漫画、看详情、下载、闲聊"
        system = _safe_format(CHAT_PROMPT, role_identity=role_sys, history=context_text)
        system += f"\n\n## 特别指令\n你没太听懂群友这句话的意思。用一句话简短反问澄清，给出候选方向让对方选：{cand_str}。不要假装听懂，不要执行任何动作，不要超过两句。"
        resp = client.messages.create(
            model=MODEL,
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": user_message or "你在说什么？"}],
        )
        for block in resp.content:
            if hasattr(block, "text") and block.text.strip():
                return block.text.strip()
        return M("nl_unclear")
    except Exception as e:
        logger.error(f"生成澄清回复失败: {e}")
        return M("nl_unclear")
