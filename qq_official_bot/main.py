"""QQ 官方机器人启动入口
读取配置、检查参数并启动 botpy 事件循环网关。
"""
import sys
import logging
import botpy

from qq_official_bot.config import config
from qq_official_bot.client import JMOfficialBotClient

logging.basicConfig(
    level=config.log_level,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger("qq_bot.main")


def main():
    print("=" * 55)
    print("   JM 漫画 QQ 官方机器人 (基于 qq-botpy SDK)")
    print("   项目主页: https://q.qq.com")
    print("=" * 55)

    if not config.appid or not config.secret or "YOUR_APP_ID" in config.appid:
        logger.error(
            "\n【错误】未检测到有效的 QQ 官方机器人凭据！\n"
            "请前往 QQ 开放平台 (https://q.qq.com/) 创建机器人，并在以下任意位置配置凭证：\n"
            "  1. 在 qq_official_bot/config.yaml 中填入 appid 与 secret\n"
            "  2. 或设置环境变量 QQ_BOT_APP_ID 与 QQ_BOT_APP_SECRET\n"
        )
        sys.exit(1)

    logger.info(f"正在以 AppID: {config.appid} 启动连接 (沙箱模式: {config.sandbox})...")

    # 配置网关监听意图 (启用公开消息与群聊被动事件)
    intents = botpy.Intents(public_messages=True)

    client = JMOfficialBotClient(intents=intents, is_sandbox=config.sandbox)
    client.run(appid=config.appid, secret=config.secret)


if __name__ == "__main__":
    main()
