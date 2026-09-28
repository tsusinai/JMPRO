"""辅助域命令 — /jm help、restart"""
import logging

from .. import state
from ..messaging import send_group_msg, send_group_reply
from ..messages import M
from ..runtime import io_call

logger = logging.getLogger("jm_bot")

HELP_MAIN = M("help_main")
HELP_ASK = M("help_ask")
HELP_DOWNLOAD = M("help_download")
HELP_DISCOVER = M("help_discover")
HELP_MANAGE = M("help_manage")
HELP_MAP = {"0": HELP_ASK, "1": HELP_DOWNLOAD, "2": HELP_DISCOVER, "3": HELP_MANAGE}


async def cmd_help(group_id: int, reply_msg_id: int, sub: str = ""):
    """发送帮助消息，支持多级菜单"""
    logger.info(f"帮助请求 (群 {group_id}){f' sub={sub}' if sub else ''}")
    text = HELP_MAP.get(sub, HELP_MAIN)
    await io_call(send_group_msg, group_id, text)


async def cmd_restart(group_id: int, reply_msg_id: int):
    """软重启：断开 WebSocket 让主循环自动重连"""
    logger.info(f"重启请求 (群 {group_id})")
    await io_call(
        send_group_reply, group_id,
        M("restart_ok"),
        reply_msg_id,
    )
    if state.current_ws is not None:
        await state.current_ws.close()
