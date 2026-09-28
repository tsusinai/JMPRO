"""WebSocket 主循环 — 连接 NapCat、过滤 /jm 消息、分发处理"""
import asyncio
import json
import logging
import os

import websockets

from . import config, state
from .fsutils import load_json, save_json, rotate_log_if_needed
from .router import safe_dispatch

logger = logging.getLogger("jm_bot")


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
                    if event.get("post_type") != "message":
                        continue
                    msg_type = event.get("message_type", "")
                    if msg_type not in ("group", "private"):
                        continue

                    raw_msg = event.get("raw_message", "")
                    if not raw_msg.strip().startswith("/jm"):
                        continue

                    group_id = event.get("group_id") or event.get("user_id")
                    is_private = msg_type == "private"
                    if not group_id:
                        continue
                    reply_msg_id = event.get("message_id", 0)

                    asyncio.create_task(
                        safe_dispatch(group_id, raw_msg, reply_msg_id, is_private=is_private)
                    )

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
