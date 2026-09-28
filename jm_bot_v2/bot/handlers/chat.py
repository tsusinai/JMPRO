"""AI 聊天域命令 — /jm ask、ask clear、role"""
import asyncio
import logging

from ..ai_chat import classify_intent, clear_history, generate_reply, group_chat, save_history
from ..messaging import send_group_msg, send_group_reply
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
    """清理当前群的 AI 聊天上下文"""
    count = clear_history(group_id)
    logger.info(f"清理聊天历史 (群 {group_id}): {count} 条")
    await io_call(send_group_msg, group_id, M("ask_clear", n=count))


async def cmd_ask(group_id: int, message: str, reply_msg_id: int):
    """AI 聊天：意图分类 → 执行动作 → 猫娘回复"""
    from ..handlers.browse import execute_action
    from ..handlers.download import cmd_download

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

    if act == "chat":
        # 纯聊天：直接用群聊模式
        result = await asyncio.get_running_loop().run_in_executor(
            api_executor, group_chat, group_id, message
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
            await io_call(send_group_voice, group_id, result, reply_msg_id, role_id)
            return

    elif act == "download":
        # 下载：回复确认后下发到 cmd_download 处理
        aid = action.get("id", "")
        if aid and aid.isdigit():
            task = asyncio.create_task(cmd_download(group_id, aid, reply_msg_id, skip_confirm=True))
            task.add_done_callback(
                lambda t: logger.error(f"cmd_ask 后台下载任务异常: {t.exception()}") if t.exception() else None
            )
            result = M("download_confirm", id=aid, warning="")
        else:
            result = "呜...主人要给一个数字 ID 才能下载啦~"

    else:
        # 工具类：执行动作 → 生成回复
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

    # 截断过长回复
    if len(result) > 800:
        result = result[:780] + "..."

    await io_call(send_group_reply, group_id, result, reply_msg_id)
