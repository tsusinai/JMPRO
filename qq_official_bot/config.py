"""QQ 官方机器人配置管理模块
支持优先读取 config.yaml，缺失时自动回退读取系统环境变量。
"""
import os
import yaml
import logging

logger = logging.getLogger("qq_bot.config")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.yaml")

class BotConfig:
    def __init__(self):
        self.appid: str = ""
        self.secret: str = ""
        self.sandbox: bool = False
        self.log_level: int = 20
        self.ai_enabled: bool = True
        self.ai_api_key: str = ""
        self.ai_base_url: str = "https://api.deepseek.com/anthropic"
        self.ai_model: str = "deepseek-v4-flash"
        self.neutral_mode: bool = True
        self.max_search_results: int = 5
        self.load()

    def load(self):
        data = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                logger.info("已加载本地 config.yaml 配置")
            except Exception as e:
                logger.warning(f"读取 config.yaml 异常: {e}，使用默认与环境变量配置")

        # 优先读取配置文件，兜底读取环境变量
        self.appid = str(data.get("appid") or os.getenv("QQ_BOT_APP_ID", "")).strip()
        self.secret = str(data.get("secret") or os.getenv("QQ_BOT_APP_SECRET", "")).strip()
        self.sandbox = bool(data.get("sandbox", os.getenv("QQ_BOT_SANDBOX", "false").lower() == "true"))
        self.log_level = int(data.get("log_level", 20))

        ai_cfg = data.get("ai", {})
        self.ai_enabled = bool(ai_cfg.get("enabled", True))
        self.ai_api_key = str(ai_cfg.get("api_key") or os.getenv("ANTHROPIC_AUTH_TOKEN", "")).strip()
        self.ai_base_url = str(ai_cfg.get("base_url") or os.getenv("AI_BASE_URL", "https://api.deepseek.com/anthropic")).strip()
        self.ai_model = str(ai_cfg.get("model") or os.getenv("AI_MODEL", "deepseek-v4-flash")).strip()

        safety_cfg = data.get("content_safety", {})
        self.neutral_mode = bool(safety_cfg.get("neutral_mode", True))
        self.max_search_results = int(safety_cfg.get("max_search_results", 5))

config = BotConfig()
