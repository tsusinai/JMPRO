"""QQ 官方机器人网关客户端 (基于 qq-botpy SDK)
监听群聊 @消息 (GROUP_AT_MESSAGE_CREATE)、私聊消息 (C2C_MESSAGE_CREATE) 与频道消息。
"""
import logging
import botpy
from botpy.message import GroupMessage, C2CMessage, Message

from .router import CommandRouter

logger = logging.getLogger("qq_bot.client")

class JMOfficialBotClient(botpy.Client):
    """JM 漫画 QQ 官方机器人客户端"""

    async def on_ready(self):
        logger.info(f"「{self.robot.name}」已成功登录 QQ 开放平台网关！")

    async def on_group_at_message_create(self, message: GroupMessage):
        """处理 QQ 群内 @机器人 消息事件"""
        logger.info(f"[群聊@{message.group_openid}] 用户 {message.author.member_openid}: {message.content}")
        try:
            reply_text = await CommandRouter.dispatch(
                raw_content=message.content,
                user_id=message.author.member_openid,
                is_group=True,
            )
            # 被动回复群消息
            await message.reply(content=reply_text)
        except Exception as e:
            logger.error(f"处理群消息异常: {e}", exc_info=True)
            await message.reply(content="⚠️ 机器人处理指令遇到异常，请稍后重试。")

    async def on_c2c_message_create(self, message: C2CMessage):
        """处理 QQ 单聊 (C2C) 私信消息事件"""
        logger.info(f"[私聊 {message.author.user_openid}]: {message.content}")
        try:
            reply_text = await CommandRouter.dispatch(
                raw_content=message.content,
                user_id=message.author.user_openid,
                is_group=False,
            )
            # 被动回复私聊消息
            await message.reply(content=reply_text)
        except Exception as e:
            logger.error(f"处理私聊消息异常: {e}", exc_info=True)
            await message.reply(content="⚠️ 机器人处理指令遇到异常，请稍后重试。")

    async def on_at_message_create(self, message: Message):
        """处理频道内 @机器人 消息事件 (兼容频道场景)"""
        logger.info(f"[频道 {message.channel_id}] 用户 {message.author.id}: {message.content}")
        try:
            reply_text = await CommandRouter.dispatch(
                raw_content=message.content,
                user_id=message.author.id,
                is_group=True,
            )
            await message.reply(content=reply_text)
        except Exception as e:
            logger.error(f"处理频道消息异常: {e}", exc_info=True)
            await message.reply(content="⚠️ 机器人处理指令遇到异常，请稍后重试。")
