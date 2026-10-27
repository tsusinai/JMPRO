"""自然语言 (NL) 管线统一工具集包装模块。

设计决定：
1. 工具全调 v2 自有 handler，不新写业务逻辑，保持与命令执行逻辑高度一致。
2. 下载耗时操作走 create_task 后台执行并传 skip_confirm=True，二次确认状态机上移至 NL 层处理
   （批量下载与 cache_clean 等高危/耗时操作由 NL 层先向用户复述确认后才真正调用本工具）。
3. restart 不进入工具集，仅作为命令专属功能且必须在路由层进行管理员权限校验。
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import ai_chat
from . import faces
from . import memory
from . import napcat
from .antiban import throttle_send
from .handlers.browse import execute_action
from .handlers.chat import cmd_role
from .handlers.download import (
    cmd_cache,
    cmd_cache_clean,
    cmd_download,
    cmd_download_batch,
    cmd_queue,
    cmd_stop,
)
from .handlers.misc import cmd_voice
from .messaging import send_group_reply
from .roles import ROLES
from .runtime import async_api_run, io_call

logger = logging.getLogger(__name__)

TOOL_NAMES = (
    "search",
    "info",
    "rank",
    "random",
    "category",
    "download",
    "queue",
    "stop",
    "cache_status",
    "cache_clean",
    "role",
    "voice",
    "clear_history",
    "send_sticker",
)

READONLY_TOOLS = (
    "search",
    "info",
    "rank",
    "random",
    "category",
)


@dataclass
class ToolResult:
    """工具执行结果。

    kind 取值说明:
    - "data": 有成品文本，待 NL 层决定继续工具循环或生成自然回复；
    - "direct": 工具已自行发送或已直接完成，NL 层无需重复发送；
    - "none": 无需发送任何回复（如表情包触发限频，NL 层继续常规聊天流）。
    """

    kind: str
    text: str = ""


@dataclass
class NlContext:
    """自然语言调用上下文。"""

    session_id: int  # 群号或私聊对方 QQ（全仓与 group_id 语义一致）
    user_id: int  # 发送者 QQ
    reply_msg_id: int = 0
    is_private: bool = False


def _log_task_exception(task: asyncio.Task) -> None:
    """后台任务完成回调，用于记录未捕获的异常。"""
    if not task.cancelled():
        exc = task.exception()
        if exc:
            logger.error("后台任务执行异常: %s", exc, exc_info=exc)


async def run_tool(name: str, params: Dict[str, Any], ctx: NlContext) -> ToolResult:
    """统一工具调用入口，包裹各业务 handler 并统一异常处理。"""
    try:
        # 只读浏览动作 (search / info / rank / random / category)
        if name in READONLY_TOOLS:
            action: Dict[str, Any] = {"action": name}
            if name == "search":
                action["query"] = params.get("query", "")
            elif name == "info":
                action["id"] = params.get("id", "")
            elif name == "rank":
                action["type"] = params.get("type", "")
            elif name == "random":
                action["mode"] = params.get("mode", "")
                action["tag"] = params.get("tag", "")
            elif name == "category":
                action["tag"] = params.get("tag", "")

            data = await async_api_run(execute_action, action)
            return ToolResult("data", data or "")

        # 漫画下载 (单个 / 批量)
        if name == "download":
            raw_ids = params.get("ids")
            if isinstance(raw_ids, (str, int)):
                raw_ids = [raw_ids]
            elif not isinstance(raw_ids, (list, tuple)):
                raw_ids = []

            # 逐个 str 化、只保留纯数字 ID、保序去重
            seen = set()
            ids: List[str] = []
            for item in raw_ids:
                s = str(item).strip()
                if s.isdigit() and s not in seen:
                    seen.add(s)
                    ids.append(s)

            if not ids:
                return ToolResult("data", "没解析出要下载的漫画 ID 喵，给我个数字 ID 吧~")

            raw_fmt = params.get("format")
            fmt = raw_fmt if raw_fmt in ("pdf", "zip") else "pdf"

            if len(ids) == 1:
                task = asyncio.create_task(
                    cmd_download(
                        ctx.session_id,
                        ids[0],
                        ctx.reply_msg_id,
                        output_format=fmt,
                        skip_confirm=True,
                    )
                )
                task.add_done_callback(_log_task_exception)
            else:
                task = asyncio.create_task(
                    cmd_download_batch(
                        ctx.session_id,
                        ids,
                        ctx.reply_msg_id,
                        output_format=fmt,
                    )
                )
                task.add_done_callback(_log_task_exception)

            return ToolResult("direct")

        # 下载队列查询
        if name == "queue":
            await cmd_queue(ctx.session_id, ctx.reply_msg_id)
            return ToolResult("direct")

        # 停止当前下载
        if name == "stop":
            await cmd_stop(ctx.session_id, ctx.reply_msg_id)
            return ToolResult("direct")

        # 缓存状态查询
        if name == "cache_status":
            await cmd_cache(ctx.session_id, ctx.reply_msg_id)
            return ToolResult("direct")

        # 缓存清理
        if name == "cache_clean":
            raw_days = params.get("days")
            try:
                days = int(raw_days) if raw_days is not None else 7
            except (ValueError, TypeError):
                days = 7
            await cmd_cache_clean(ctx.session_id, days, ctx.reply_msg_id)
            return ToolResult("direct")

        # 角色切换或列表
        if name == "role":
            raw = str(params.get("role") or "").strip()
            role_num = ""
            if raw.isdigit():
                role_num = raw
            elif raw:
                # 遍历 ROLES 查找名称相互包含的第一个角色下标
                for idx, r in enumerate(ROLES):
                    role_name = str(r.get("name", ""))
                    if raw in role_name or role_name in raw:
                        role_num = str(idx)
                        break

            await cmd_role(ctx.session_id, role_num, ctx.reply_msg_id)
            return ToolResult("direct")

        # 语音模式设置
        if name == "voice":
            mode = params.get("mode")
            if mode not in ("on", "off"):
                mode = "status"
            await cmd_voice(ctx.session_id, mode, ctx.reply_msg_id)
            return ToolResult("direct")

        # 清除上下文历史与长期记忆
        if name == "clear_history":
            n = ai_chat.clear_history(ctx.session_id)
            memory.clear_session(ctx.session_id)
            await io_call(
                send_group_reply,
                ctx.session_id,
                f"好啦，清掉 {n} 条聊天记录，长期记忆也清空啦，重新开始喵~",
                ctx.reply_msg_id,
            )
            return ToolResult("direct")

        # 发送表情包
        if name == "send_sticker":
            mood = params.get("mood")
            if mood not in faces.MOODS:
                mood = "开心"

            path = faces.pick_sticker(mood, str(ctx.session_id))
            if not path:
                return ToolResult("none")

            file_path = os.path.abspath(path).replace("\\", "/")
            file_uri = f"file:///{file_path.lstrip('/')}"
            seg = {"type": "image", "data": {"file": file_uri}}

            throttle_send()
            ok = await io_call(napcat.send_group_msg_segments, ctx.session_id, [seg])
            return ToolResult("direct") if ok else ToolResult("none")

        # 未知工具名称
        return ToolResult("data", "这个功能本喵还没学会喵…可以用 /jm 看看命令~")

    except Exception as exc:
        logger.exception("执行工具 %s 异常: %s", name, exc)
        return ToolResult("data", "处理这个请求时出了点问题喵，稍后再试试~")
