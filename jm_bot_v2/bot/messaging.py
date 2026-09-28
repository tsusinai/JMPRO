"""消息发送门面 — 所有对外群消息统一经过角色口吻注入（原 jm_bot.py 的覆写方案改为显式封装）"""
from . import napcat
from .roles import apply_role


def send_group_msg(group_id: int, text: str) -> bool:
    return napcat.send_group_msg(group_id, apply_role(text, group_id))


def send_group_reply(group_id: int, text: str, reply_msg_id: int) -> bool:
    return napcat.send_group_reply(group_id, apply_role(text, group_id), reply_msg_id)
