"""消息发送门面 — 所有对外群消息统一经过角色口吻注入（原 jm_bot.py 的覆写方案改为显式封装）

send_group_voice：语音模式下的发送路径（TTS → 缓存 → record 段 → 失败回退文本）
"""
import logging
import os

from . import napcat
from . import antiban
from . import faces
from .roles import apply_role
from . import tts as tts_mod

logger = logging.getLogger("jm_bot")


def send_group_msg(group_id: int, text: str) -> bool:
    antiban.throttle_send()
    return napcat.send_group_msg(group_id, apply_role(text, group_id))


def send_group_reply(group_id: int, text: str, reply_msg_id: int) -> bool:
    antiban.throttle_send()
    return napcat.send_group_reply(group_id, apply_role(text, group_id), reply_msg_id)


def send_group_msg_rich(group_id: int, text: str) -> bool:
    """不带引用的 AI 回复专用：与 send_group_reply_rich 同款表情装饰，用于分段后续段与主动插话。"""
    antiban.throttle_send()
    styled = apply_role(text, group_id)
    segments = faces.decorate(styled, str(group_id))
    if segments:
        return napcat.send_group_msg_segments(group_id, segments)
    return napcat.send_group_msg(group_id, styled)


def send_group_msg_segments(group_id: int, segments: list) -> bool:
    """不带引用的分段发送（斗图反甩用）：仅节流 + 直发，不做角色口吻注入。"""
    antiban.throttle_send()
    return napcat.send_group_msg_segments(group_id, segments)


def send_group_reply_rich(group_id: int, text: str, reply_msg_id: int) -> bool:
    """AI 回复专用：apply_role 后做表情装饰（[表情名]→Face 段、[[sticker:情绪]]→表情包图片段）；
    无装饰命中时与 send_group_reply 行为一致"""
    antiban.throttle_send()
    styled = apply_role(text, group_id)
    segments = faces.decorate(styled, str(group_id))
    if segments:
        return napcat.send_group_reply_segments(group_id, segments, reply_msg_id)
    return napcat.send_group_reply(group_id, styled, reply_msg_id)


def _voice_record_msg(file_path: str) -> list:
    """构造 OneBot record 段消息（NapCat 自动转 silk，依赖 ffmpeg）"""
    return [{"type": "record", "data": {"file": f"file:///{file_path}"}}]


def send_group_voice(group_id: int, text: str, reply_msg_id: int, role_id: int = 1) -> bool:
    """聊天回复转语音：TTS 合成（带缓存）→ record 段发送 → 任一步失败回退文本
    返回 True 表示语音已发送，False 表示已回退文本发送"""
    try:
        path = tts_mod.synthesize(text, role_id)
    except Exception as e:
        logger.error(f"TTS 合成异常，回退文本: {e}", exc_info=True)
        path = None
    if not path or not os.path.exists(path):
        return send_group_reply(group_id, text, reply_msg_id)
    antiban.throttle_send()
    ok = napcat.send_group_msg(group_id, _voice_record_msg(path))
    if not ok:
        logger.warning("语音发送失败，回退文本")
        return send_group_reply(group_id, text, reply_msg_id)
    return True
