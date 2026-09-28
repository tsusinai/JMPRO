"""共享运行状态 — 下载去重/进度/取消/冷却（模块级单例，原 jm_bot.py 全局变量收拢）"""
import time

# 下载状态
downloading: set = set()          # 正在下载的 album_id
download_progress: dict = {}      # album_id -> 进度 dict
stop_requests: set = set()        # 用户请求取消的 album_id（还在下载中）
private_chats: set = set()        # 私聊目标 user_id 集合（决定上传走私聊接口）
stop_times: dict = {}             # album_id -> 停止时间戳，用于冷却期检查

# 限流状态
last_request: dict = {}           # group_id -> timestamp（同群冷却）
last_download_global: float = 0   # 全局上次下载时间戳

# WebSocket 引用（用于 /jm restart 软重启）
current_ws = None


def record_download_done(group_id: int):
    """下载完成后记录冷却时间戳"""
    last_request[group_id] = time.time()
    global last_download_global
    last_download_global = time.time()
