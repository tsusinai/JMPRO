"""WebSocket 主循环 — 连接 NapCat、过滤消息、分发处理（/jm 命令 + NL 自然语言管线）"""
import asyncio
import html
import json
import logging
import os
import re

import websockets

from . import config, state
from .fsutils import load_json, save_json, rotate_log_if_needed
from .router import safe_dispatch
from .handlers import nl

logger = logging.getLogger("jm_bot")

_CQ_IMAGE_URL_RE = re.compile(r"\[CQ:image,[^\]]*?url=([^,\]]+)", re.IGNORECASE)
_CQ_AT_RE = re.compile(r"\[CQ:at,qq=\d+(?:,[^\]]*)?\]")
_CQ_IMAGE_RE = re.compile(r"\[CQ:image,[^\]]*\]")
_CQ_ANY_RE = re.compile(r"\[CQ:[^\]]*\]")
_WAKE_STRIP_CHARS = " ，,：:、~～！!？?。."


def extract_image_urls(event: dict) -> list:
    """从 OneBot 事件提取图片 URL：优先 message 段数组中 image 段的 data.url，
    无段数组时回退解析 raw_message 的 [CQ:image,...]（url 需 html.unescape）；最多 3 条，去重保序"""
    urls = []
    message = event.get("message")
    if isinstance(message, list):
        for seg in message:
            if isinstance(seg, dict) and seg.get("type") == "image":
                url = (seg.get("data") or {}).get("url")
                if isinstance(url, str):
                    url = url.strip()
                    if url.startswith(("http://", "https://")) and url not in urls:
                        urls.append(url)
    if not urls:
        raw_msg = event.get("raw_message", "")
        if isinstance(raw_msg, str):
            for m in _CQ_IMAGE_URL_RE.finditer(raw_msg):
                url = html.unescape(m.group(1)).strip()
                if url.startswith(("http://", "https://")) and url not in urls:
                    urls.append(url)
    return urls[:3]


def _whitelist_allowed(event: dict, is_private: bool) -> bool:
    """fail-closed 白名单：未启用时全放行；启用后仅名单内会话放行，空名单=全关"""
    wl = config.CONFIG.get("whitelist", {})
    if not wl.get("enabled", False):
        return True
    if is_private:
        return event.get("user_id") in wl.get("private", [])
    return event.get("group_id") in wl.get("groups", [])


def _plain_text(raw_msg: str) -> str:
    """把 raw_message 清成纯文本：图片 CQ 替成 [图片] 占位，其余 CQ 段删除"""
    t = _CQ_IMAGE_RE.sub("[图片]", raw_msg or "")
    t = _CQ_ANY_RE.sub("", t)
    return t.strip()


def _is_wake(event: dict, text: str, session_id: int) -> tuple:
    """群聊唤醒判定：@Bot 或文本以唤醒名/当前角色名开头。返回 (是否唤醒, 剥离前缀后的文本)"""
    self_id = str(event.get("self_id", "") or "")
    # @ 唤醒：message 段数组中的 at 段
    message = event.get("message")
    if isinstance(message, list) and self_id:
        for seg in message:
            if isinstance(seg, dict) and seg.get("type") == "at":
                if str((seg.get("data") or {}).get("qq", "")) == self_id:
                    return True, text
    raw_msg = event.get("raw_message", "") or ""
    if self_id and f"[CQ:at,qq={self_id}]" in raw_msg:
        return True, text
    # 呼名唤醒：config 唤醒名 + 当前会话角色名
    names = list(config.CONFIG.get("nl", {}).get("wake_names", []) or [])
    try:
        from .roles import ROLES, get_group_role
        names.append(ROLES[get_group_role(session_id)]["name"])
    except Exception:
        pass
    t = (text or "").strip()
    for name in names:
        if name and t.startswith(name):
            rest = t[len(name):].lstrip(_WAKE_STRIP_CHARS)
            return True, rest
    return False, text


async def _nl_handle(session_id, user_id, text, reply_msg_id, is_private, image_urls):
    try:
        await nl.handle_nl(session_id, user_id, text, reply_msg_id, is_private, image_urls)
    except Exception:
        logger.exception("NL 管线异常 (session=%s)", session_id)


async def _nl_shadow(session_id, user_id, text):
    try:
        await nl.shadow_log(session_id, user_id, text)
    except Exception:
        logger.exception("NL shadow 记录异常 (session=%s)", session_id)


async def _nl_proactive(session_id, user_id, text):
    try:
        await nl.maybe_proactive(session_id, user_id, text)
    except Exception:
        logger.exception("NL 主动插话异常 (session=%s)", session_id)


async def handle_event(event: dict):
    """单条 OneBot 事件的路由（主循环与离线验收共用此入口）。

    顺序：白名单 fail-closed 先行（所有消息）→ /jm 前缀走命令分发（确定性直达）→
    其余按 config nl_mode 进 NL 管线：私聊全进；群聊需 @/呼名唤醒或有待确认状态；
    shadow 模式只记录唤醒消息的意图不执行；hybrid 下群聊未唤醒消息走主动插话评判。
    P0 补充：戳一戳事件只开追问窗口不自动回消息；群消息先记冷热场；追问窗口内消息直达 NL。
    """
    if event.get("post_type") == "notice":
        # 戳一戳：目标是 Bot 本人时只开追问窗口，窗口内不用反复 @；不自动回消息
        if event.get("notice_type") == "notify" and event.get("sub_type") == "poke":
            self_id = str(event.get("self_id", "") or "")
            if self_id and str(event.get("target_id", "")) == self_id:
                gid = event.get("group_id") or event.get("user_id")
                uid = event.get("user_id", 0)
                if gid and uid:
                    nl.open_followup(int(gid), int(uid))
        return
    if event.get("post_type") != "message":
        return
    msg_type = event.get("message_type", "")
    if msg_type not in ("group", "private"):
        return

    raw_msg = event.get("raw_message", "") or ""
    group_id = event.get("group_id") or event.get("user_id")
    is_private = msg_type == "private"
    if not group_id:
        return
    if not _whitelist_allowed(event, is_private):
        if raw_msg.strip().startswith("/jm"):
            logger.info(
                f"白名单拦截: {'私聊' if is_private else '群'} {group_id} 的 /jm 消息已丢弃"
            )
        return

    if is_private:
        state.private_chats.add(int(group_id))

    reply_msg_id = event.get("message_id", 0)
    user_id = event.get("user_id", 0)
    image_urls = extract_image_urls(event)

    # P0 冷热场：群消息先记一笔（/jm 命令也算群活跃），供主动插话加权用
    if msg_type == "group":
        try:
            nl.note_group_message(int(group_id))
        except Exception:
            pass

    # /jm 命令：绕过 LLM 的确定性直达通道
    if raw_msg.strip().startswith("/jm"):
        sender = event.get("sender") or {}
        asyncio.create_task(
            safe_dispatch(
                group_id, raw_msg, reply_msg_id,
                is_private=is_private, image_urls=image_urls,
                sender_id=user_id, sender_role=sender.get("role", ""),
            )
        )
        return

    # NL 自然语言管线
    mode = config.CONFIG.get("nl_mode", "hybrid")
    if mode == "off":
        return

    text = _plain_text(raw_msg)
    if is_private:
        wake, nl_text = True, text
    else:
        wake, nl_text = _is_wake(event, text, group_id)
        if not wake and user_id and nl.has_pending(group_id, user_id):
            # 有待确认状态时，后续消息（多半是确认词）直达 NL 管线消费
            wake, nl_text = True, text
        if not wake and user_id and nl.is_followup_active(group_id, user_id):
            # P0 追问窗口内：不用反复 @，直达 NL 管线
            wake, nl_text = True, text

    if mode == "shadow":
        if wake and nl_text:
            asyncio.create_task(_nl_shadow(group_id, user_id, nl_text))
        return

    # hybrid
    if wake:
        if not nl_text and not image_urls:
            return
        asyncio.create_task(
            _nl_handle(group_id, user_id, nl_text or "[图片]", reply_msg_id, is_private, image_urls)
        )
    elif not is_private:
        if text:
            asyncio.create_task(_nl_proactive(group_id, user_id, text))


async def persist_limits():
    """定期保存限流状态"""
    rate_file = config.RATE_LIMITS_FILE
    while True:
        await asyncio.sleep(300)  # 每 5 分钟
        try:
            save_json(rate_file, {str(k): v for k, v in state.last_request.items()})
        except Exception:
            pass


async def run():
    os.chdir(config.BASE_DIR)
    logger.info("JM Bot 启动中...")

    # 恢复限流状态（防止重启后刷屏）
    saved = load_json(config.RATE_LIMITS_FILE, {})
    for gid, ts in saved.items():
        try:
            state.last_request[int(gid)] = float(ts)
        except (ValueError, TypeError):
            pass
    if state.last_request:
        logger.info(f"已恢复 {len(state.last_request)} 条限流记录")

    # 轮转日志
    rotate_log_if_needed(config.BOT_LOG_PATH, max_mb=20, keep_kb=1024)

    asyncio.create_task(persist_limits())

    # 空间决策后台任务（mode=off 时任务自身立即退出；启动失败不影响主循环）
    try:
        from .qzone_task import qzone_loop
        asyncio.create_task(qzone_loop())
    except Exception as e:
        logger.warning(f"空间决策任务启动失败: {e}")

    while True:
        try:
            async with websockets.connect(config.WS_URL) as ws:
                state.current_ws = ws
                logger.info("已连接 NapCat WebSocket")
                async for raw in ws:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if not isinstance(event, dict):
                        continue
                    await handle_event(event)

        except websockets.ConnectionClosed:
            state.current_ws = None
            logger.warning("连接断开，5 秒后重连...")
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            state.current_ws = None
            break
        except Exception as e:
            state.current_ws = None
            logger.error(f"异常: {e}")
            await asyncio.sleep(5)
