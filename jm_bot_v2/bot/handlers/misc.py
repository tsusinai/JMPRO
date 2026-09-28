"""辅助域命令 — /jm help、restart、voice（群级语音模式开关）"""
import logging

from .. import config, state
from ..messaging import send_group_msg, send_group_reply
from ..messages import M
from ..runtime import io_call
from ..fsutils import load_json, save_json

logger = logging.getLogger("jm_bot")

HELP_MAIN = M("help_main")
HELP_ASK = M("help_ask")
HELP_DOWNLOAD = M("help_download")
HELP_DISCOVER = M("help_discover")
HELP_MANAGE = M("help_manage")
HELP_MAP = {"0": HELP_ASK, "1": HELP_DOWNLOAD, "2": HELP_DISCOVER, "3": HELP_MANAGE}

VOICE_MODES_FILE = config.RATE_LIMITS_FILE.replace("rate_limits.json", "voice_modes.json")
_voice_modes: dict = {}


def _load_voice_modes():
    global _voice_modes
    _voice_modes = {int(k): bool(v) for k, v in load_json(VOICE_MODES_FILE, {}).items()}


def voice_mode_enabled(group_id: int) -> bool:
    """群级语音模式开关（默认关，持久化）"""
    return _voice_modes.get(group_id, False)


def set_voice_mode(group_id: int, enabled: bool):
    _voice_modes[group_id] = enabled
    save_json(VOICE_MODES_FILE, {str(k): v for k, v in _voice_modes.items()})


_load_voice_modes()


async def cmd_voice(group_id: int, action: str, reply_msg_id: int):
    """群级语音模式开关：/jm voice on|off|status"""
    if action == "on":
        set_voice_mode(group_id, True)
        text = "🎙️ 本群语音模式已开启喵~ 聊天回复会变成语音，数据类回复还是文字哦"
    elif action == "off":
        set_voice_mode(group_id, False)
        text = "💤 本群语音模式已关闭，恢复纯文字回复~"
    else:
        cur = "开启" if voice_mode_enabled(group_id) else "关闭"
        text = f"🎙️ 本群语音模式当前：{cur}\n（/jm voice on 开启 | /jm voice off 关闭）"
    logger.info(f"语音模式 (群 {group_id}): {action or 'status'}")
    await io_call(send_group_reply, group_id, text, reply_msg_id)


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
