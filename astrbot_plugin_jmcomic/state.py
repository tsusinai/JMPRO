"""
JM Bot 状态管理 — 下载队列 / 进度 / 限流 / 持久化
"""
import os
import time
import asyncio
import logging

logger = logging.getLogger("jmcomic")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(SCRIPT_DIR, "downloads")
PDF_DIR = os.path.join(SCRIPT_DIR, "pdfs")
ZIP_DIR = os.path.join(SCRIPT_DIR, "zips")


class JMBotState:
    """单例状态管理，替代旧 jm_bot.py 中的全局变量"""

    def __init__(self):
        # 下载去重
        self._downloading: set[str] = set()

        # 进度追踪 {album_id: {completed, total, image_completed, image_total,
        #   speed, bytes_downloaded, domain_switches, start_time}}
        self._download_progress: dict = {}

        # 下载队列 [(album_id, fmt, group_id, reply_msg_id), ...]
        self._download_queue: list = []

        # 停止请求标记
        self._stop_requests: set[str] = set()

        # 速率限制
        self._last_group_time: dict[int, float] = {}  # group_id → timestamp
        self._last_global_time: float = 0.0
        self.GROUP_COOLDOWN = 15  # 同群冷却秒数
        self.GLOBAL_COOLDOWN = 20  # 全局冷却秒数

        # 锁
        self._queue_lock = asyncio.Lock()
        self._progress_lock = asyncio.Lock()

    # ── 速率限制 ──

    def check_rate_limit(self, group_id: int) -> tuple[float, bool]:
        """返回 (剩余冷却秒数, 是否被限制)"""
        now = time.time()
        group_remaining = self._last_group_time.get(group_id, 0) + self.GROUP_COOLDOWN - now
        global_remaining = self._last_global_time + self.GLOBAL_COOLDOWN - now
        remaining = max(group_remaining, global_remaining, 0)
        return remaining, remaining > 0

    def mark_rate_limit(self, group_id: int):
        """记录一次请求，更新冷却计时"""
        now = time.time()
        self._last_group_time[group_id] = now
        self._last_global_time = now

    def reset_global_cooldown(self):
        """重置全局冷却（/jm stop 时调用）"""
        self._last_global_time = 0.0

    # ── 下载去重 ──

    def is_downloading(self, album_id: str) -> bool:
        return album_id in self._downloading

    def mark_download_start(self, album_id: str):
        self._downloading.add(album_id)

    def mark_download_done(self, album_id: str):
        self._downloading.discard(album_id)
        self._download_progress.pop(album_id, None)

    # ── 进度追踪 ──

    async def update_progress(self, album_id: str, **kwargs):
        async with self._progress_lock:
            if album_id not in self._download_progress:
                self._download_progress[album_id] = {
                    "completed": 0,
                    "total": 0,
                    "image_completed": 0,
                    "image_total": 0,
                    "speed": 0.0,
                    "bytes_downloaded": 0,
                    "domain_switches": 0,
                    "start_time": time.time(),
                }
            self._download_progress[album_id].update(kwargs)

    async def get_progress(self, album_id: str) -> dict | None:
        async with self._progress_lock:
            return self._download_progress.get(album_id)

    def get_all_progress(self) -> dict:
        return dict(self._download_progress)

    # ── 队列管理 ──

    async def enqueue(self, album_id: str, fmt: str, group_id: int, reply_msg_id: int):
        async with self._queue_lock:
            self._download_queue.append((album_id, fmt, group_id, reply_msg_id))

    async def dequeue(self) -> tuple | None:
        async with self._queue_lock:
            if self._download_queue:
                return self._download_queue.pop(0)
            return None

    def queue_size(self) -> int:
        return len(self._download_queue)

    async def clear_queue(self):
        async with self._queue_lock:
            self._download_queue.clear()

    # ── 停止请求 ──

    def request_stop(self, album_id: str = "*"):
        """标记停止，* 表示停止所有"""
        self._stop_requests.add(album_id)

    def is_stop_requested(self, album_id: str) -> bool:
        return "*" in self._stop_requests or album_id in self._stop_requests

    def clear_stop_requests(self):
        self._stop_requests.clear()

    # ── 持久化 ──

    async def restore_from_kv(self, plugin):
        """从 AstrBot KV 存储恢复限流状态"""
        try:
            data = await plugin.get_kv("rate_limits")
            if data:
                self._last_group_time = data.get("groups", {})
                self._last_global_time = data.get("global", 0.0)
                logger.info("已恢复限流状态")
        except Exception:
            pass

    async def persist_to_kv(self, plugin):
        """持久化限流状态到 AstrBot KV 存储"""
        try:
            await plugin.put_kv(
                "rate_limits",
                {"groups": self._last_group_time, "global": self._last_global_time},
            )
        except Exception as e:
            logger.warning(f"持久化限流状态失败: {e}")

    async def shutdown(self):
        """插件关闭时的清理"""
        self._stop_requests.add("*")
        await self.clear_queue()
