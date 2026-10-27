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
    "tts": {
        "engine": "vocu",
        "api_key": "",
        "model": "FunAudioLLM/CosyVoice2-0.5B",
        "timeout_seconds": 30,
        "max_chars": 300,
        "async_timeout_seconds": 120,
        "async_poll_seconds": 4,
        "default_voice_id": "",
    },
    "antiban": {
        "min_send_interval_seconds": 1.2,
        "ai_cooldown_seconds": 8,
        "ai_max_per_minute": 10,
        # NL 混合入口的 AI 预算（按会话隔离、分类与生成分开计数）
        "ai_classify_per_minute": 20,
        "ai_generate_per_minute": 6
    },
    # 读图片：被唤醒消息中的图片直传多模态模型（单条上限/大小/超时）
    "images": {
        "enabled": True,
        "max_per_message": 3,
        "max_mb": 8,
        "timeout_seconds": 15,
    },
    # 出站表情装饰：AI 回复里的 [表情名] 转 Face 段、[[sticker:情绪]] 发表情包图片
    "faces": {
        "enabled": True,
        "max_per_message": 2,
        "cooldown_minutes": 10,
        "cooldown_max_uses": 2,
        "stickers_enabled": True,
    },
    # QQ 空间自动说说：mode=off 关闭 / draft 只落草稿（出厂默认，风控底线）/ auto 真发；
    # 每日硬顶 max_per_day 条；tick 每 tick_minutes 分钟决策一次；diary_hour 点生成日记草稿（只存草稿，永不直发）
    "qzone": {
        "mode": "draft",
        "tick_minutes": 90,
        "max_per_day": 1,
        "diary_hour": 20,
        "history_hours": 6,
        "model_timeout": 180,
    },
    # 白名单 fail-closed：enabled=true 且列表为空时拒绝一切会话；
    # groups 填群号、private 填 QQ 号，只有名单内会话的 /jm 消息会被处理
    "whitelist": {
        "enabled": True,
        "groups": [],
        "private": []
    },
    # 管理员 QQ 号列表（restart 等特权命令）；为空时回退口径：
    # 白名单私聊号、群主（sender.role == "owner"）视为管理员
    "admins": [],
    # NL 混合入口总开关：off 关闭 / shadow 只记录意图不执行 / hybrid 自然语言默认入口（/jm 保留直达）
    "nl_mode": "hybrid",
    "nl": {
        "confidence_threshold": 0.6,       # 分类置信度低于此值 → 反问澄清，不猜
        "confirm_timeout_seconds": 60,     # 重动作（批量下载/cache clean）待确认有效期
        "wake_names": ["大肥鱼", "肥鱼", "猫娘", "本喵"],  # 群聊呼名唤醒（另含 @Bot 与当前角色名）
        "busy_reply_cooldown_seconds": 60,  # "忙"提示同会话最短间隔（防刷屏）
    },
    # 活人感 P0（humanity.py）：分段 / 追问窗口 / 冷热场 / 夜间静默 / 斗图冷却 / 主动熔断
    # 注意：夜间静默只关主动插话，不拦被唤醒聊天与 /jm 工具；config.json 可覆盖本段
    "humanity": {
        "segment_enabled": True,
        "segment_pause_seconds": 0.8,
        "followup_seconds": 300,
        "field_quiet_seconds": 600,
        "field_hot_threshold": 5,
        "sleep_start_hour": 23,   # 主动插话夜间静默起点（与 lifefuck 23:00 休眠同口径，结束见下）
        "sleep_end_hour": 8,      # 主动插话夜间静默终点
        "duel_cooldown_seconds": 30,
        "proactive_fuse": 2,      # 连续主动插话 fuse 条且期间无人唤醒 → 拦住下一次主动
    },
    # SQLite 轻量记忆（livingmemory 的 v2 替代）：按 session 隔离的长期摘要 + 事实条目
    "memory": {
        "enabled": True,
        "db_file": "memory.db",
        "compress_after_messages": 90,     # history 条数超过此值触发压缩
        "compress_after_chars": 15000,     # 或 history 总字数超过此值触发
        "keep_recent": 60,                 # 压缩时保留的最近条数（更早的折进摘要）
        "max_facts": 50,                   # 每 session 最多保留的事实条目（滚动淘汰最旧）
        "inject_facts": 10,                # 注入上下文的最近事实条数
        "compress_cooldown_seconds": 600,  # 同 session 压缩最短间隔
    },
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

# === TTS ===
TTS_ENGINE = CONFIG["tts"]["engine"]
TTS_API_KEY = CONFIG["tts"]["api_key"]
TTS_MODEL = CONFIG["tts"]["model"]
TTS_TIMEOUT_SECONDS = CONFIG["tts"]["timeout_seconds"]
TTS_MAX_CHARS = CONFIG["tts"]["max_chars"]
TTS_ASYNC_TIMEOUT_SECONDS = CONFIG["tts"]["async_timeout_seconds"]
TTS_ASYNC_POLL_SECONDS = CONFIG["tts"]["async_poll_seconds"]
TTS_DEFAULT_VOICE_ID = CONFIG["tts"]["default_voice_id"]

# === 风控节流 ===
_AB = CONFIG["antiban"]
ANTIBAN_MIN_SEND_INTERVAL = _AB["min_send_interval_seconds"]
ANTIBAN_AI_COOLDOWN_SECONDS = _AB["ai_cooldown_seconds"]
ANTIBAN_AI_MAX_PER_MINUTE = _AB["ai_max_per_minute"]
ANTIBAN_AI_CLASSIFY_PER_MINUTE = _AB.get("ai_classify_per_minute", 20)
ANTIBAN_AI_GENERATE_PER_MINUTE = _AB.get("ai_generate_per_minute", 6)
