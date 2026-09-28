"""配置加载 — 所有可调项集中在 config.json，敏感项（token/key）不再散落源码"""
import json
import os

# jm_bot_v2/ 根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# 深合并默认值与 config.json，config.json 缺项时回退默认
DEFAULTS = {
    "napcat": {
        "http_url": "http://127.0.0.1:3002",
        "ws_url": "ws://127.0.0.1:3001",
        "access_token": "",
    },
    "ai": {
        "api_key": "",
        "base_url": "https://api.deepseek.com/anthropic",
        "model": "deepseek-v4-flash",
    },
    "limits": {
        "rate_group_seconds": 15,
        "rate_global_seconds": 20,
        "stop_cooldown_seconds": 5,
        "api_timeout_seconds": 20,
        "random_max_pages": 200,
        "random_timeout_seconds": 30,
    },
    "disk": {"warn_mb": 500, "critical_mb": 100},
    "upload_timeout": {
        "pdf_base_seconds": 600,
        "pdf_per_mb_seconds": 5,
        "pdf_max_seconds": 1800,
        "zip_seconds": 600,
    },
    "threads": {"download": 3, "io": 4, "api": 6},
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    user = {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
            user = json.load(f)
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError) as e:
        import logging
        logging.getLogger("jm_bot").warning(f"config.json 读取失败，使用默认配置: {e}")
    return _merge(DEFAULTS, user)


CONFIG = load_config()

# === 路径常量（产物目录独立于旧版，在 jm_bot_v2/ 下） ===
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
PDFS_DIR = os.path.join(BASE_DIR, "pdfs")
ZIPS_DIR = os.path.join(BASE_DIR, "zips")
ERROR_LOG_PATH = os.path.join(BASE_DIR, "download_errors.log")
BOT_LOG_PATH = os.path.join(BASE_DIR, "bot.log")
RATE_LIMITS_FILE = os.path.join(BASE_DIR, "rate_limits.json")
OPTION_FILE = os.path.join(BASE_DIR, "option.yml")

# === NapCat ===
NAPCAT_HTTP = CONFIG["napcat"]["http_url"]
NAPCAT_TOKEN = CONFIG["napcat"]["access_token"]
WS_URL = f"{CONFIG['napcat']['ws_url']}?access_token={NAPCAT_TOKEN}"

# === 限流 / 冷却 ===
RATE_LIMIT_SECONDS = CONFIG["limits"]["rate_group_seconds"]
GLOBAL_COOLDOWN_SECONDS = CONFIG["limits"]["rate_global_seconds"]
STOP_COOLDOWN = CONFIG["limits"]["stop_cooldown_seconds"]
API_TIMEOUT = CONFIG["limits"]["api_timeout_seconds"]
RANDOM_MAX_PAGES = CONFIG["limits"]["random_max_pages"]
RANDOM_TIMEOUT = CONFIG["limits"]["random_timeout_seconds"]

# === 磁盘配额 ===
DISK_WARN_BYTES = CONFIG["disk"]["warn_mb"] * 1024 * 1024
DISK_CRITICAL_BYTES = CONFIG["disk"]["critical_mb"] * 1024 * 1024

# === 上传超时 ===
UPLOAD_TIMEOUT_PDF_BASE = CONFIG["upload_timeout"]["pdf_base_seconds"]
UPLOAD_TIMEOUT_PDF_PER_MB = CONFIG["upload_timeout"]["pdf_per_mb_seconds"]
UPLOAD_TIMEOUT_PDF_MAX = CONFIG["upload_timeout"]["pdf_max_seconds"]
UPLOAD_TIMEOUT_ZIP = CONFIG["upload_timeout"]["zip_seconds"]

# === 线程池 ===
THREAD_DOWNLOAD = CONFIG["threads"]["download"]
THREAD_IO = CONFIG["threads"]["io"]
THREAD_API = CONFIG["threads"]["api"]
