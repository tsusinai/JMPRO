"""AI 聊天域命令 — /jm ask、ask clear、role"""
import asyncio
import logging
import re

from ..ai_chat import classify_intent, clear_history, fetch_image_blocks, generate_reply, group_chat, save_history
from ..faces import strip_markers
from ..messaging import send_group_msg, send_group_reply, send_group_reply_rich
from ..messages import M
from ..roles import ROLES, get_group_role, set_group_role
from ..runtime import api_executor, io_call

logger = logging.getLogger("jm_bot")


async def cmd_role(group_id: int, role_num: str, reply_msg_id: int):
    """查看/切换 Bot 角色"""
    if not role_num:
        # 列出可用角色（0 号隐藏）
        lines = []
        for i in range(1, len(ROLES)):
            current = " ← 当前" if get_group_role(group_id) == i else ""
            lines.append(f"  {i}: {ROLES[i]['name']}{current}")
        text = "🎭 可用人设：\n" + "\n".join(lines) + "\n回复 /jm role <数字> 切换"
    else:
        r = int(role_num)
        if 0 <= r < len(ROLES):
            set_group_role(group_id, r)
            if r == 0:
                text = f"🎭 已切换为隐藏人设 —— {ROLES[r]['name']}"
            else:
                text = f"🎭 已切换为：{r} - {ROLES[r]['name']}"
        else:
            text = f"没有这个人设啦~ 范围是 0-{len(ROLES)-1} 喵~"
    logger.info(f"角色切换 (群 {group_id}): {role_num or '查询'}")
    await io_call(send_group_reply, group_id, text, reply_msg_id)


async def cmd_ask_clear(group_id: int, reply_msg_id: int):
    """清理当前群的 AI 聊天上下文（短期历史 + SQLite 长期记忆，与 NL clear_history 口径一致）"""
    count = clear_history(group_id)
    from .. import memory
    memory.clear_session(group_id)
    logger.info(f"清理聊天历史 (群 {group_id}): {count} 条")
    await io_call(send_group_msg, group_id, M("ask_clear", n=count))


async def cmd_ask(group_id: int, message: str, reply_msg_id: int, image_urls: list | None = None):
    """AI 聊天：意图分类 → 执行动作 → 猫娘回复（image_urls 非空时 chat 分支走多模态读图）"""
    from ..handlers.browse import execute_action
    from ..handlers.download import cmd_download

    # 清洗 CQ 码：图片段替成 "[图片]" 占位（本体走 image_urls 直传），其余 CQ 段删除
    message = re.sub(r"\[CQ:image,[^\]]*\]", "[图片]", message)
    message = re.sub(r"\[CQ:[^\]]*\]", "", message).strip()
    if not message and image_urls:
        message = "[图片]"

    # 风控节流：同群冷却 + 全局每分钟上限（超限时静默跳过，不回复）
    from ..antiban import check_ai_allowed
    if not check_ai_allowed(group_id):
        logger.info(f"AI 回复限频跳过 (群 {group_id})")
        return

    logger.info(f"AI 聊天 (群 {group_id}): {message[:50]}...")

    try:
        # Step 1: 意图分类（API 调用，放 api_executor）
        action = await asyncio.get_running_loop().run_in_executor(
            api_executor, classify_intent, message, group_id
        )
        logger.info(f"意图: {action}")
    except Exception as e:
        logger.error(f"意图分类失败: {e}")
        await io_call(send_group_reply, group_id, M("ask_error"), reply_msg_id)
        return

    # Step 2: 根据意图执行
    act = action.get("action", "chat")

    if act == "error":
        # 分类失败：明确提示，不再静默回退成闲聊
        await io_call(send_group_reply, group_id, M("ask_error"), reply_msg_id)
        return

    if act == "unknown":
        await io_call(send_group_reply, group_id, M("nl_unclear"), reply_msg_id)
        return

    if act == "chat":
        # 纯聊天：直接用群聊模式；带图片时先抓取编码再多模态直传（抓不到则降级纯文本，图以 "[图片]" 占位留在文本里）
        blocks = None
        if image_urls:
            fetched = await asyncio.get_running_loop().run_in_executor(
                api_executor, fetch_image_blocks, image_urls
            )
            blocks = fetched or None
        result = await asyncio.get_running_loop().run_in_executor(
            api_executor, group_chat, group_id, message, blocks
        )
        if not result:
            await io_call(send_group_reply, group_id, M("ask_error"), reply_msg_id)
            return
        # 语音模式：聊天回复转语音（数据类回复不受影响）；失败在 send_group_voice 内部回退文本
        from ..handlers.misc import voice_mode_enabled
        from ..messaging import send_group_voice
        from ..roles import get_group_role as _ggr
        if voice_mode_enabled(group_id):
            role_id = _ggr(group_id)
            result = strip_markers(result)
            await io_call(send_group_voice, group_id, result, reply_msg_id, role_id)
            return

    elif act == "download" and len(action.get("ids") or []) >= 2:
        # 批量下载：走 NL 统一工具层（create_task 后台批量下发）
        from .. import tools
        ctx = tools.NlContext(session_id=group_id, user_id=0, reply_msg_id=reply_msg_id, is_private=False)
        await tools.run_tool("download", action, ctx)
        return

    elif act == "download":
        # 下载：回复确认后下发到 cmd_download 处理
        aid = str(action.get("id", "") or "")
        if aid and aid.isdigit():
            task = asyncio.create_task(cmd_download(group_id, aid, reply_msg_id, skip_confirm=True))
            task.add_done_callback(
                lambda t: logger.error(f"cmd_ask 后台下载任务异常: {t.exception()}") if t.exception() else None
            )
            result = M("download_confirm", id=aid, warning="")
        else:
            result = "呜...主人要给一个数字 ID 才能下载啦~"

    elif act in ("search", "info", "rank", "random", "category"):
        # 只读工具类：执行动作 → 生成回复
        try:
            data = await asyncio.get_running_loop().run_in_executor(
                api_executor, execute_action, action
            )
        except Exception as e:
            logger.error(f"执行动作失败: {e}")
            await io_call(send_group_reply, group_id, M("ask_error"), reply_msg_id)
            return

        try:
            result = await asyncio.get_running_loop().run_in_executor(
                api_executor, generate_reply, data, group_id
            )
        except Exception as e:
            logger.error(f"生成回复失败: {e}")
            result = data  # 回退到原始数据

        # 保存到群聊历史
        save_history(group_id, message, result)

    else:
        # 其余新动作（批量下载/队列/停止/缓存/角色/语音/清记忆/表情包）：走 NL 统一工具层
        # 口径：/jm ask 是显式命令通道（前缀即确认），不走 NL 的复述确认状态机
        from .. import tools
        ctx = tools.NlContext(session_id=group_id, user_id=0, reply_msg_id=reply_msg_id, is_private=False)
        res = await tools.run_tool(act, action, ctx)
        if res.kind == "data" and res.text:
            result = res.text
        else:
            return

    # 截断过长回复
    if len(result) > 800:
        result = result[:780] + "..."

    await io_call(send_group_reply_rich, group_id, result, reply_msg_id)
