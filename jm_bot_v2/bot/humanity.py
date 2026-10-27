"""活人感纯逻辑模块（P0 五件套）。

只含可离线单测的纯函数与状态机，不调 NapCat、不调 LLM、不读磁盘：
借鉴口径（只借机制，不搬整仓）：
- lifefuck/qq-deepseek-realistic-bot：打字分段、5 分钟追问窗口、冷热场权重、23:00 休眠、情绪表情包、斗图反甩
- molly-qq-whale：长期记忆去重、待核实区、好感画像
- nanbengxian-cyber/dafeiyu-qq-bot：主动行为必须收进单一决策闸（它复盘过 11 个状态存储、33 个插件各说各话的教训）

注意边界（写进代码，防以后误读）：
- 夜间休眠只关主动插话，不拦被唤醒的聊天与 /jm 工具（半夜找漫画是正事）。
- 连续主动熔断的口径是“连续主动插话 2 次期间无人唤醒”，不是精确的“引用回复检测”：
  现有发送层只回 bool、不回 message_id，做不了引用级判定，精确版需改 NapCat 返回值，留作后续。
"""

import math
import re
import time

# ---------------------------------------------------------------- 打字分段

_SENTENCE_RE = re.compile(r"[^。！？；\n]+[。！？；\n]?")
_CODE_FENCE = "```"


def split_reply(text: str, max_parts: int = 2) -> list:
    """把长回复切成最多 max_parts 段（默认 2 段），模拟真人分段打字。

    - 含代码块整条不切（lifefuck 同款口径：代码块整条发）。
    - 单句不切；多句按句子数对半切，拼接后与原文一致（除首尾空白）。
    - 空文本返回 []。
    """
    if not text or not text.strip():
        return []
    if _CODE_FENCE in text:
        return [text]
    sentences = [s for s in _SENTENCE_RE.findall(text) if s]
    if len(sentences) <= 1:
        return [text]
    if max_parts <= 1:
        return [text]
    # 对半切：前半句数 = ceil(n/2)，保证两段都不空
    mid = (len(sentences) + 1) // 2
    first = "".join(sentences[:mid]).strip()
    second = "".join(sentences[mid:]).strip()
    parts = [p for p in (first, second) if p]
    return parts if parts else [text]


# ---------------------------------------------------------------- 追问窗口


class FollowupWindow:
    """@ / 戳一戳后开启的追问窗口：窗口内不用反复 @ 也能直达 NL 管线。"""

    def __init__(self):
        self._expiry: dict[tuple, float] = {}

    def open(self, session_id: int, user_id: int, seconds: float = 300, now: float | None = None) -> None:
        self._expiry[(session_id, user_id)] = (now if now is not None else time.time()) + seconds

    def is_active(self, session_id: int, user_id: int, now: float | None = None) -> bool:
        exp = self._expiry.get((session_id, user_id))
        if exp is None:
            return False
        t = now if now is not None else time.time()
        if t > exp:
            self._expiry.pop((session_id, user_id), None)
            return False
        return True

    def close(self, session_id: int, user_id: int) -> None:
        self._expiry.pop((session_id, user_id), None)


# ---------------------------------------------------------------- 冷热场


class FieldTracker:
    """群冷热场：记录每群消息时间戳，算权重。

    - 距上一条 > quiet_seconds（默认 600 秒）→ 0.25，不硬凑。
    - 10 分钟内消息 >= hot_threshold（默认 5 条）→ 1.5，跟着接梗。
    - 其余 → 1.0。
    """

    def __init__(self, quiet_seconds: float = 600, hot_threshold: int = 5):
        self.quiet_seconds = quiet_seconds
        self.hot_threshold = hot_threshold
        self._last: dict[int, float] = {}
        self._times: dict[int, list] = {}

    def record(self, session_id: int, now: float | None = None) -> float:
        t = now if now is not None else time.time()
        last = self._last.get(session_id)
        self._last[session_id] = t
        times = [x for x in self._times.get(session_id, []) if t - x < self.quiet_seconds]
        times.append(t)
        self._times[session_id] = times
        if last is not None and t - last > self.quiet_seconds:
            return 0.25
        if len(times) >= self.hot_threshold:
            return 1.5
        return 1.0

    def weight(self, session_id: int, now: float | None = None) -> float:
        t = now if now is not None else time.time()
        last = self._last.get(session_id)
        if last is not None and t - last > self.quiet_seconds:
            return 0.25
        times = [x for x in self._times.get(session_id, []) if t - x < self.quiet_seconds]
        if len(times) >= self.hot_threshold:
            return 1.5
        return 1.0


# ---------------------------------------------------------------- 夜间


def is_sleep_time(hour: int, start: int = 23, end: int = 8) -> bool:
    """夜间时段判定（跨午夜区间）：start=23, end=8 时，23:00-08:00 为 True。"""
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


# ---------------------------------------------------------------- 主动熔断 / 斗图冷却


class ProactiveStreak:
    """连续主动熔断：主动发了 fuse 条且期间无人唤醒 → 下一次主动直接拦住，直到有人唤醒才清零。"""

    def __init__(self, fuse: int = 2):
        self.fuse = fuse
        self._streak: dict[int, int] = {}

    def record_send(self, session_id: int) -> None:
        self._streak[session_id] = self._streak.get(session_id, 0) + 1

    def record_wake(self, session_id: int) -> None:
        self._streak[session_id] = 0

    def blocked(self, session_id: int) -> bool:
        return self._streak.get(session_id, 0) >= self.fuse


class DuelTracker:
    """斗图反甩冷却：同群 cooldown 秒内只反甩一次。"""

    def __init__(self, cooldown_seconds: float = 30):
        self.cooldown_seconds = cooldown_seconds
        self._last: dict[int, float] = {}

    def allowed(self, session_id: int, now: float | None = None) -> bool:
        t = now if now is not None else time.time()
        last = self._last.get(session_id, 0.0)
        if t - last < self.cooldown_seconds:
            return False
        self._last[session_id] = t
        return True


# ---------------------------------------------------------------- 情绪推断（表情包选图用）


_MOOD_KEYWORDS: list[tuple] = [
    # 强情绪先判，避免“哈哈饿了”这类混合句被弱关键词抢走
    ("饿", ("饿", "吃饭", "干饭", "白饭", "想吃")),
    ("生气", ("气死", "可恶", "怒", "气人")),
    ("难过", ("难过", "想哭", "哭了", "伤心")),
    ("害羞", ("害羞", "脸红", "不好意思")),
    ("委屈", ("委屈", "明明", "哼")),
    ("惊讶", ("居然", "竟然", "天啊", "不会吧")),
    ("开心", ("哈哈", "笑死", "开心", "厉害", "棒", "太棒", "太好了")),
    ("激动", ("哇塞", "激动")),
    ("撒娇", ("求求", "嘛", "好不好")),
    ("疑惑", ("为什么", "啥", "什么意思", "? ", "？")),
]


def infer_mood(text: str) -> str | None:
    """从文本关键词推断情绪（只用于补一个 [[sticker:情绪]]，已有标记时调用方不补）。"""
    if not text:
        return None
    for mood, keywords in _MOOD_KEYWORDS:
        for kw in keywords:
            if kw in text:
                return mood
    return None


# ---------------------------------------------------------------- 事实召回打分（BM25 式简化版）


def _query_tokens(query: str) -> list:
    """中文按单字 + 二字组、英文按词切分，去重保序。"""
    if not query:
        return []
    tokens: list[str] = []
    seen: set[str] = set()
    # 英文/数字词
    for w in re.findall(r"[A-Za-z0-9]+", query):
        lw = w.lower()
        if lw not in seen:
            seen.add(lw)
            tokens.append(lw)
    # 中文单字与二字组
    chars = re.findall(r"[\u4e00-\u9fff]", query)
    for ch in chars:
        if ch not in seen:
            seen.add(ch)
            tokens.append(ch)
    for i in range(len(chars) - 1):
        bg = chars[i] + chars[i + 1]
        if bg not in seen:
            seen.add(bg)
            tokens.append(bg)
    return tokens


def score_facts(facts_with_time: list, query: str, now: float | None = None) -> list:
    """给事实打分：命中 token 数为主，时间衰减为辅（30 天半衰-ish 的指数衰减）。

    输入：[(fact, created_at), ...]；返回按分数降序的 fact 列表（零分事实排最后但仍保留，
    调用方按需截断）。
    """
    t = now if now is not None else time.time()
    tokens = _query_tokens(query)
    scored = []
    for fact, created_at in facts_with_time:
        if not tokens:
            score = 0.0
        else:
            hits = sum(1 for tok in tokens if tok in fact)
            age_days = max(0.0, (t - (created_at or t)) / 86400.0)
            decay = math.exp(-age_days / 30.0)
            score = hits * (0.5 + 0.5 * decay)
        scored.append((score, created_at or 0.0, fact))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [fact for _, _, fact in scored]
