"""风控节流 — 降低 QQ 风控/封号风险的发送侧约束

背景：旧号 1601410002 因"长期在阿里云机房 IP 运行"被腾讯风险管控（docs/TECH_STACK.md）。
机房 IP 无法改变，能做的是把行为特征从"机器人"拉回"人类"：
1. 出站消息全局最小间隔（突发多条时排队发送，模拟人类节奏）— throttle_send()
2. AI 聊天回复限频：同群冷却 + 全局每分钟上限 — check_ai_allowed()

所有阈值可在 config.json 的 "antiban" 段调整。
"""
import logging
import threading
import time

from . import config

logger = logging.getLogger("jm_bot.antiban")

_send_lock = threading.Lock()
_last_send = 0.0

_ai_lock = threading.Lock()
_ai_last_by_group: dict = {}     # group_id -> timestamp（同群 AI 回复冷却）
_ai_minute_window: list = []     # 全局 AI 回复时间窗（每分钟上限）


def throttle_send():
    """出站消息全局最小间隔；突发多条时在此排队（在 io_executor 线程中调用，允许 sleep）"""
    global _last_send
    with _send_lock:
        gap = config.ANTIBAN_MIN_SEND_INTERVAL - (time.time() - _last_send)
        if gap > 0:
            time.sleep(gap)
        _last_send = time.time()


def check_ai_allowed(group_id: int) -> bool:
    """AI 聊天回复准入检查（在发起 LLM 调用之前，省 API 也省消息）
    通过后记录时间戳；同群冷却与全局每分钟上限均由 config.antiban 控制"""
    now = time.time()
    with _ai_lock:
        last = _ai_last_by_group.get(group_id, 0)
        if now - last < config.ANTIBAN_AI_COOLDOWN_SECONDS:
            return False
        # 全局每分钟窗口
        _ai_minute_window[:] = [t for t in _ai_minute_window if now - t < 60]
        if len(_ai_minute_window) >= config.ANTIBAN_AI_MAX_PER_MINUTE:
            return False
        # 通过：记录
        _ai_last_by_group[group_id] = now
        _ai_minute_window.append(now)
    return True
