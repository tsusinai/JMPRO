"""风控节流 — 降低 QQ 风控/封号风险的发送侧约束

背景：旧号 1601410002 因"长期在阿里云机房 IP 运行"被腾讯风险管控（docs/TECH_STACK.md）。
机房 IP 无法改变，能做的是把行为特征从"机器人"拉回"人类"：
1. 出站消息全局最小间隔（突发多条时排队发送，模拟人类节奏）— throttle_send()
2. AI 调用预算控制：按会话隔离 60 秒滑动窗口计数，意图分类与文本生成分开控制；
   全局上限仅约束生成回复 — budget_check()

所有阈值可在 config.json 的 "antiban" 段调整。
"""
import logging
import threading
import time

from . import config

logger = logging.getLogger("jm_bot.antiban")

_send_lock = threading.Lock()
_last_send = 0.0

_budget_lock = threading.Lock()
_classify_windows: dict = {}      # session_id -> list of timestamp（分类滑动窗）
_generate_windows: dict = {}      # session_id -> list of timestamp（生成滑动窗）
_global_generate_window: list = []  # 全局生成回复时间窗（每分钟上限）
_busy_last_by_session: dict = {}  # session_id -> timestamp（忙碌提示冷却）


def throttle_send():
    """出站消息全局最小间隔；突发多条时在此排队（在 io_executor 线程中调用，允许 sleep）"""
    global _last_send
    with _send_lock:
        gap = config.ANTIBAN_MIN_SEND_INTERVAL - (time.time() - _last_send)
        if gap > 0:
            time.sleep(gap)
        _last_send = time.time()


def budget_check(session_id: int, kind: str) -> bool:
    """AI 调用预算检查

    按 session 隔离的 60 秒滑动窗口计数，通过才记录一次。
    - kind="classify"：仅 session 级上限，阈值 config.ANTIBAN_AI_CLASSIFY_PER_MINUTE（默认 20）。
    - kind="generate"：session 级上限 config.ANTIBAN_AI_GENERATE_PER_MINUTE（默认 6），
      且同时受全局 60 秒窗口上限 config.ANTIBAN_AI_MAX_PER_MINUTE（默认 10）约束。
    """
    if kind not in ("classify", "generate"):
        raise ValueError(f"kind 必须为 'classify' 或 'generate'，收到: {kind!r}")

    now = time.time()
    with _budget_lock:
        if kind == "classify":
            limit = getattr(config, "ANTIBAN_AI_CLASSIFY_PER_MINUTE", 20)
            raw_win = _classify_windows.get(session_id)
            win = [t for t in raw_win if now - t < 60] if raw_win else []

            if len(win) >= limit:
                if win:
                    _classify_windows[session_id] = win
                else:
                    _classify_windows.pop(session_id, None)
                return False

            win.append(now)
            _classify_windows[session_id] = win
            return True

        # kind == "generate"
        limit = getattr(config, "ANTIBAN_AI_GENERATE_PER_MINUTE", 6)
        global_limit = getattr(config, "ANTIBAN_AI_MAX_PER_MINUTE", 10)

        _global_generate_window[:] = [t for t in _global_generate_window if now - t < 60]

        raw_win = _generate_windows.get(session_id)
        win = [t for t in raw_win if now - t < 60] if raw_win else []

        if len(win) >= limit or len(_global_generate_window) >= global_limit:
            if win:
                _generate_windows[session_id] = win
            else:
                _generate_windows.pop(session_id, None)
            return False

        win.append(now)
        _generate_windows[session_id] = win
        _global_generate_window.append(now)
        return True


def budget_busy_reply_allowed(session_id: int, cooldown_seconds: float) -> bool:
    """判断'忙'提示是否可发

    同 session 距上次发出'忙'提示 >= cooldown_seconds 才允许，允许时记录时间戳。
    """
    now = time.time()
    with _budget_lock:
        last = _busy_last_by_session.get(session_id, 0.0)
        if now - last < cooldown_seconds:
            return False
        _busy_last_by_session[session_id] = now
        return True


def check_ai_allowed(group_id: int) -> bool:
    """AI 聊天回复准入检查（旧版兼容接口）

    直接转发给 budget_check(group_id, "generate")。
    """
    return budget_check(group_id, "generate")
