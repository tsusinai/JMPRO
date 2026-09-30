"""命令路由 — 正则表按序匹配分发（顺序敏感：ask clear 先于 ask、/jm <ID> 兜底最后）"""
import asyncio
import logging

from . import state
from .messaging import send_group_reply
from .messages import M
from .runtime import io_call
from .handlers import browse, chat, misc
from .handlers.download import (
    cmd_cache,
    cmd_cache_clean,
    cmd_download,
    cmd_download_batch,
    cmd_queue,
    cmd_stop,
)

logger = logging.getLogger("jm_bot")

# 注意顺序：RESTART/STOP 等具体词在前，/jm <ID> 纯数字兜底在后
import re

JM_RE = re.compile(r"^/jm\s+(\d{1,10})$")
JM_DOWNLOAD_RE = re.compile(r"^/jm\s+download\s+(\d{1,10}(?:\s+\d{1,10})*)\s*(?:\s+(pdf|zip))?\s*$")
JM_SEARCH_RE = re.compile(r"^/jm\s+search\s+(.+)$")
JM_INFO_RE = re.compile(r"^/jm\s+info\s+(\d{1,10})$")
JM_RANK_RE = re.compile(r"^/jm\s+rank\s*(day|week|month)?$")
JM_HELP_RE = re.compile(r"^/jm\s+help(?:\s+(\S+))?$")
JM_CACHE_RE = re.compile(r"^/jm\s+cache$")
JM_CACHE_CLEAN_RE = re.compile(r"^/jm\s+cache\s+clean(?:\s+(\d{1,3}))?$")
JM_RESTART_RE = re.compile(r"^/jm\s+restart$")
JM_STOP_RE = re.compile(r"^/jm\s+stop$")
JM_CATEGORY_RE = re.compile(r"^/jm\s+category\s+(.+)$")
JM_RANDOM_RE = re.compile(r"^/jm\s+random(\s+.*)?$")
JM_ASK_RE = re.compile(r"^/jm\s+ask\s+(.+)$", re.DOTALL)
JM_ASK_CLEAR_RE = re.compile(r"^/jm\s+ask\s+clear$")
JM_QUEUE_RE = re.compile(r"^/jm\s+queue$")
JM_ROLE_RE = re.compile(r"^/jm\s+role(?:\s+(\d))?$")
JM_VOICE_RE = re.compile(r"^/jm\s+voice(?:\s+(on|off|status))?\s*$")


async def safe_dispatch(group_id: int, raw_msg: str, reply_msg_id: int, is_private: bool = False):
    """包装 dispatch，捕获异常防止静默失败"""
    try:
        if is_private:
            state.private_chats.add(int(group_id))
        await dispatch(group_id, raw_msg, reply_msg_id)
    except Exception as e:
        logger.error(
            f"命令处理异常 (chat={group_id}, msg={raw_msg[:50]}): {e}",
            exc_info=True,
        )


async def dispatch(group_id: int, raw_msg: str, reply_msg_id: int):
    """根据消息内容分发到对应命令处理函数"""
    raw_msg = raw_msg.strip()

    m = JM_CACHE_CLEAN_RE.match(raw_msg)
    if m:
        days = int(m.group(1)) if m.group(1) else 7
        await cmd_cache_clean(group_id, days, reply_msg_id)
        return

    m = JM_CACHE_RE.match(raw_msg)
    if m:
        await cmd_cache(group_id, reply_msg_id)
        return

    if JM_RESTART_RE.match(raw_msg):
        await misc.cmd_restart(group_id, reply_msg_id)
        return

    if JM_STOP_RE.match(raw_msg):
        await cmd_stop(group_id, reply_msg_id)
        return

    m = JM_CATEGORY_RE.match(raw_msg)
    if m:
        await browse.cmd_category(group_id, m.group(1), reply_msg_id)
        return

    m = JM_RANDOM_RE.match(raw_msg)
    if m:
        mode, tag, unknown = browse.parse_random_flags((m.group(1) or "").strip())
        if unknown and not mode and not tag:
            await io_call(
                send_group_reply, group_id,
                M("random_bad_flags", flags=' '.join(unknown)),
                reply_msg_id,
            )
            return
        await browse.cmd_random(group_id, reply_msg_id, mode=mode, tag=tag)
        return

    if JM_QUEUE_RE.match(raw_msg):
        await cmd_queue(group_id, reply_msg_id)
        return

    m = JM_HELP_RE.match(raw_msg)
    if m:
        await misc.cmd_help(group_id, reply_msg_id, sub=m.group(1) or "")
        return

    # /jm role — 需要在 /jm ask 之前（避免角色名触发误判）
    m = JM_ROLE_RE.match(raw_msg)
    if m:
        await chat.cmd_role(group_id, m.group(1), reply_msg_id)
        return

    m = JM_VOICE_RE.match(raw_msg)
    if m:
        await misc.cmd_voice(group_id, m.group(1) or "status", reply_msg_id)
        return

    if JM_ASK_CLEAR_RE.match(raw_msg):
        await chat.cmd_ask_clear(group_id, reply_msg_id)
        return

    m = JM_ASK_RE.match(raw_msg)
    if m:
        await chat.cmd_ask(group_id, m.group(1).strip(), reply_msg_id)
        return

    m = JM_DOWNLOAD_RE.match(raw_msg)
    if m:
        fmt = m.group(2) or "pdf"
        ids_raw = m.group(1).split()
        # 去重保留顺序 + 验证纯数字
        ids = []
        seen = set()
        for aid in ids_raw:
            if aid.isdigit() and aid not in seen:
                ids.append(aid)
                seen.add(aid)
        if not ids:
            await io_call(
                send_group_reply, group_id,
                M("invalid_id"),
                reply_msg_id,
            )
            return
        if len(ids) == 1:
            await cmd_download(group_id, ids[0], reply_msg_id, output_format=fmt)
        else:
            await cmd_download_batch(group_id, ids, reply_msg_id, output_format=fmt)
        return

    m = JM_SEARCH_RE.match(raw_msg)
    if m:
        await browse.cmd_search(group_id, m.group(1), reply_msg_id)
        return

    m = JM_INFO_RE.match(raw_msg)
    if m:
        await browse.cmd_info(group_id, m.group(1), reply_msg_id)
        return

    m = JM_RANK_RE.match(raw_msg)
    if m:
        await browse.cmd_rank(group_id, m.group(1) or "day", reply_msg_id)
        return

    # /jm <ID> (向后兼容)
    m = JM_RE.match(raw_msg)
    if m:
        await cmd_download(group_id, m.group(1), reply_msg_id)
        return

    # 无匹配 → 未知命令
    await io_call(
        send_group_reply, group_id,
        M("unknown_command"),
        reply_msg_id,
    )
