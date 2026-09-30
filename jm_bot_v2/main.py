"""JM Bot v2 入口 — python main.py

日志与第三方库噪音抑制集中在此，业务逻辑见 bot/ 包。
"""
import asyncio
import logging
import sys

from bot import config
from bot.runtime import shutdown
from bot.runner import run

# === 日志 ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s.%(funcName)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.BOT_LOG_PATH, encoding="utf-8"),
    ],
)
# 抑制第三方库 DEBUG 噪音
for lib in ["websockets", "urllib3", "asyncio", "requests"]:
    logging.getLogger(lib).setLevel(logging.WARNING)


def ffmpeg_selfcheck():
    """NapCat 把 mp3 转 silk 依赖 ffmpeg，缺失时语音功能不可用 — 启动时显眼提示"""
    from bot.tts import check_ffmpeg
    if not check_ffmpeg():
        logging.getLogger("jm_bot").warning(
            "⚠️ 未检测到 ffmpeg：NapCat 无法把语音转 silk，语音模式发送会失败"
            "（本机安装后重启 Bot；NapCat 侧也需可用）"
        )


def main():
    # Windows 控制台 UTF-8
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ffmpeg_selfcheck()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    finally:
        # 不使用 Python signal handler（Win/Linux 行为不一致且有死锁风险），
        # 直接依赖 asyncio.run() 的 KeyboardInterrupt 处理 + finally 清理
        shutdown()
        logging.getLogger("jm_bot").info("JM Bot 已退出")


if __name__ == "__main__":
    main()
