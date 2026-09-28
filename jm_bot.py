"""
JM QQ Bot — 独立 OneBot 监听器
直连 NapCat WebSocket，匹配 /jm 命令。

命令列表：
  /jm download <ID>  下载漫画（/jm <ID> 向后兼容）
  /jm search <关键词>  搜索漫画
  /jm info <ID>      查看漫画详情
  /jm rank <day|week|month>  排行榜
  /jm help            显示帮助
"""
import asyncio
import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import jmcomic
import websockets

from napcat_utils import (
    clean_old_dirs,
    format_size,
    get_dir_info,
    get_free_space,
    load_json,
    rotate_log_if_needed,
    save_json,
    send_group_msg,
    send_group_reply,
    upload_group_file,
    upload_private_file,
)
from download import download_single

# === 日志 ===

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s.%(funcName)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(SCRIPT_DIR, "bot.log"), encoding="utf-8"
        ),
    ],
)
logger = logging.getLogger("jm_bot")

# 抑制第三方库 DEBUG 噪音
for lib in ["websockets", "urllib3", "asyncio", "requests"]:
    logging.getLogger(lib).setLevel(logging.WARNING)

jmcomic.disable_jm_log()

# === 扩展图片 CDN 域名列表（增加冗余防止单点故障） ===
# jmcomic 内置 DOMAIN_IMAGE_LIST 仅含 jmapiproxy + jmapinodeudzn，
# 后者全部被 RST，所以追加所有已知可用域名提高下载成功率
from jmcomic import JmModuleConfig  # noqa: E402
_extra_image_domains = [
    "cdn-msp.jmapiproxy1.cc",
    "cdn-msp.jmapiproxy2.cc",
    "cdn-msp2.jmapiproxy2.cc",
    "cdn-msp3.jmapiproxy2.cc",
    "cdn-msp.jmapinodeudzn.net",
    "cdn-msp3.jmapinodeudzn.net",
]
# 合并去重
JmModuleConfig.DOMAIN_IMAGE_LIST = list(dict.fromkeys(
    JmModuleConfig.DOMAIN_IMAGE_LIST + _extra_image_domains
))

# === 配置 ===

NAPCAT_TOKEN = "O~3GVdp9kwlCH.Zg"
WS_URL = f"ws://127.0.0.1:3001?access_token={NAPCAT_TOKEN}"

# === 常用提示文本（集中管理，方便修改风格）===

from messages import M, M_single  # noqa: E402
from ai_chat import classify_intent, generate_reply, group_chat, _save_history, apply_role, ROLES, get_group_role, set_group_role  # noqa: E402

# === 命令路由 ===

JM_RE = re.compile(r"^/jm\s+(\d{1,10})$")
JM_DOWNLOAD_RE = re.compile(r"^/jm\s+download\s+(\d{1,10}(?:\s+\d{1,10})*)\s*(?:\s+(pdf|zip))?\s*$")
JM_SEARCH_RE = re.compile(r"^/jm\s+search\s+(.+)$")
JM_INFO_RE = re.compile(r"^/jm\s+info\s+(\d{1,10})$")
JM_RANK_RE = re.compile(r"^/jm\s+rank\s*(day|week|month)?$")
JM_HELP_RE = re.compile(r"^/jm\s+help(?:\s+(\S+))?$")
JM_CACHE_RE = re.compile(r"^/jm\s+cache$")
JM_CACHE_CLEAN_RE = re.compile(r"^/jm\s+cache\s+clean(?:\s+(\d{1,3}))?$")
JM_RESTART_RE = re.compile(r"^/jm\s+restart$")
JM_STOP_RE = re.compile(r"^/jm\s+stop$")
JM_CATEGORY_RE = re.compile(r"^/jm\s+category\s+(.+)$")
JM_RANDOM_RE = re.compile(r"^/jm\s+random(\s+.*)?$")
JM_ASK_RE = re.compile(r"^/jm\s+ask\s+(.+)$", re.DOTALL)
JM_ASK_CLEAR_RE = re.compile(r"^/jm\s+ask\s+clear$")
JM_QUEUE_RE = re.compile(r"^/jm\s+queue$")
JM_ROLE_RE = re.compile(r"^/jm\s+role(?:\s+(\d))?$")

# === 角色口吻注入：覆写 napcat 发送函数 ===
# 所有 send_group_msg / send_group_reply 调用自动 apply_role，无需修改调用点

_send_group_msg_raw = send_group_msg
_send_group_reply_raw = send_group_reply


def send_group_msg(group_id: int, text: str):
    return _send_group_msg_raw(group_id, apply_role(text, group_id))


def send_group_reply(group_id: int, text: str, reply_msg_id: int):
    return _send_group_reply_raw(group_id, apply_role(text, group_id), reply_msg_id)


# === WebSocket 引用（用于重启）===

_current_ws = None

# === 下载去重 & 速率限制 ===

_downloading: set = set()
_download_progress: dict = {}  # album_id -> {completed, total, photo_name, image_completed, image_total, speed, bytes_downloaded}
_stop_requests: set = set()    # 用户请求取消的 album_id（还在下载中）
_private_chats: set = set()    # user_id 集合，标记哪些是私聊而非群聊
_stop_times: dict = {}        # album_id -> 停止时间戳，用于冷却期检查
STOP_COOLDOWN = 5              # 停止后 N 秒内不允许重新启动同一 ID
_last_request: dict = {}  # group_id -> timestamp
_last_download_global: float = 0  # 全局上次下载时间戳
RATE_LIMIT_SECONDS = 15           # 同群冷却
GLOBAL_COOLDOWN_SECONDS = 20      # 全局冷却（跨群），避免 CDN 封锁

# === 磁盘配额 ===
DISK_WARN_MB = 500          # 低于此值发出警告但仍允许下载
DISK_CRITICAL_MB = 100      # 低于此值拒绝下载
DISK_CRITICAL_BYTES = DISK_CRITICAL_MB * 1024 * 1024
DISK_WARN_BYTES = DISK_WARN_MB * 1024 * 1024
DOWNLOADS_DIR = os.path.join(SCRIPT_DIR, "downloads")
PDFS_DIR = os.path.join(SCRIPT_DIR, "pdfs")
ZIPS_DIR = os.path.join(SCRIPT_DIR, "zips")
ERROR_LOG_PATH = os.path.join(SCRIPT_DIR, "download_errors.log")

# === 线程池 ===
# executor: 3线程，下载+上传共享（实际并发由速率限制控制，避免CDN封禁）
# io_executor: 4线程，消息发送（轻量IO，不阻塞命令处理）
# api_executor: 6线程，搜索/信息/排行/随机/AI（不阻塞消息发送）
# WARNING: raising these may trigger CDN bans or OS handle exhaustion

executor = ThreadPoolExecutor(max_workers=3)       # 下载 + 上传
io_executor = ThreadPoolExecutor(max_workers=4)    # 消息发送
api_executor = ThreadPoolExecutor(max_workers=6)    # 搜索/信息/排行/随机/AI

# === API 超时保护 ===
import concurrent.futures

_API_TIMEOUT = 20  # 单次 API 调用最长等待秒数
UPLOAD_TIMEOUT_PDF_BASE = 600        # PDF 基础超时（秒）
UPLOAD_TIMEOUT_PDF_PER_MB = 5        # 每 MB 额外秒数
UPLOAD_TIMEOUT_PDF_MAX = 1800        # PDF 上限（秒）
UPLOAD_TIMEOUT_ZIP = 600             # ZIP 上传超时（秒），ZIP 通常更大
RANDOM_MAX_PAGES = 200  # /jm random 最多翻多少页中随机


def api_run(func, *args, timeout=_API_TIMEOUT):
    """在 api_executor 线程池执行阻塞函数，带超时防护，不阻塞消息发送
    返回: 成功返回数据，失败返回 "[TIMEOUT]" 或 "[API_ERR]..." 前缀的字符串
    """
    fut = api_executor.submit(func, *args)
    try:
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return M("api_timeout")
    except Exception as e:
        return M("api_fail", what=str(e))


def is_api_error(result) -> bool:
    """检查 api_run / async_api_run 返回是否为错误"""
    return isinstance(result, str) and result.startswith("[")


def api_error_msg(result) -> str:
    """从 api_run 错误字符串中提取友好消息（去掉前缀标签）"""
    if isinstance(result, str) and result.startswith("[API_ERR] "):
        return result[10:]  # strip [API_ERR] prefix
    if isinstance(result, str) and result.startswith("[TIMEOUT] "):
        return result[10:]  # strip [TIMEOUT] prefix
    return str(result) if isinstance(result, str) else ""


def run_with_timeout(timeout, func, *args):
    """定制超时版本的 api_run"""
    return api_run(func, *args, timeout=timeout)


async def async_api_run(func, *args, timeout=_API_TIMEOUT, **kwargs):
    """协程版：在 api_executor 中运行阻塞函数，不占用 io_executor"""
    import asyncio as _asyncio
    if kwargs:
        from functools import partial
        func = partial(func, **kwargs)
    try:
        return await _asyncio.wait_for(
            _asyncio.get_running_loop().run_in_executor(api_executor, func, *args),
            timeout=timeout,
        )
    except _asyncio.TimeoutError:
        return M("api_timeout")
    except Exception as e:
        return M("api_fail", what=str(e))


def _format_progress_bar(done: int, total: int, width: int = 10) -> tuple:
    """返回 (bar_str, pct) 如 ('[█████░░░░░]', 50)"""
    if total <= 0:
        return "[?]", 0
    pct = min(done * 100 // total, 100)
    filled = pct * width // 100
    bar = "[" + "█" * filled + "░" * (width - filled) + "]"
    return bar, pct


def _format_eta(image_done: int, image_total: int, speed: float, bytes_downloaded: int = 0) -> str:
    """返回 ETA 字符串，如 '约 2 分钟'，信息不足时返回 ''
    基于已下载字节数估算平均图片大小，而非直接用图片张数除以速度"""
    if speed <= 0 or image_total <= 0 or image_done <= 0:
        return ""
    remaining_images = image_total - image_done
    if remaining_images <= 0:
        return ""
    # 尚无字节数据则不估算，避免硬编码回退值误导
    if bytes_downloaded <= 0:
        return ""
    avg_bytes = bytes_downloaded / image_done
    remaining_bytes = remaining_images * avg_bytes
    eta_sec = int(remaining_bytes / speed)
    if eta_sec < 60:
        return f"约 {eta_sec}s"
    elif eta_sec < 3600:
        return f"约 {eta_sec // 60}min"
    else:
        return f"约 {eta_sec // 3600}h{(eta_sec % 3600) // 60}m"


# === jmcomic 客户端（懒加载）===


def get_jm_client():
    global _jm_client
    if _jm_client is None:
        with _jm_client_lock:
            if _jm_client is None:
                option_file = os.path.join(SCRIPT_DIR, "option.yml")
                if os.path.exists(option_file):
                    option = jmcomic.create_option_by_file(option_file)
                else:
                    option = jmcomic.JmOption.default()
                _jm_client = option.build_jm_client()
    return _jm_client


_jm_client = None
_jm_client_lock = threading.Lock()


# === 命令处理 ===


async def _ack(group_id, reply_msg_id):
    """立即确认收到命令，防止用户误以为 Bot 未启动"""
    await asyncio.get_running_loop().run_in_executor(
        io_executor, send_group_reply, group_id, M("ack"), reply_msg_id
    )


async def cmd_download(group_id: int, album_id: str, reply_msg_id: int, output_format: str = "pdf",
                     batch_prefix: str = "", skip_rate_checks: bool = False,
                     skip_confirm: bool = False):
    """处理下载命令"""
    global _last_download_global

    # 停止冷却检查（同 ID 停止后 5s 内不允许重新启动）
    stop_ts = _stop_times.get(album_id, 0)
    if stop_ts and time.time() - stop_ts < STOP_COOLDOWN:
        remaining = int(STOP_COOLDOWN - (time.time() - stop_ts))
        await asyncio.get_running_loop().run_in_executor(
            io_executor, send_group_reply, group_id,
            f"🛑 [{album_id}] 刚停下来呢...再等 {remaining}s 才能重新启动喵~",
            reply_msg_id,
        )
        return

    # 去重检查
    if album_id in _downloading:
        if album_id in _stop_requests:
            msg = f"🛑 [{album_id}] 正在停下中，请等人家拔出来再试喵~"
        else:
            prog = _download_progress.get(album_id)
            if prog and (prog.get("image_total", 0) > 0 or prog.get("total", 0) > 0):
                img_total = prog.get("image_total", 0)
                img_done = prog.get("image_completed", 0)
                pct = 0
                if img_total > 0:
                    bar, pct = _format_progress_bar(img_done, img_total)
                    img_part = bar
                else:
                    img_part = f"图片: {img_done}/?"
                    pct = "?"
                ch_total = prog.get("total", 0)
                ch_part = ""
                if ch_total > 0:
                    ch_part = f" | {prog['completed']}/{ch_total} 章节"
                speed_part = ""
                speed = prog.get("speed", 0)
                if speed > 0:
                    speed_part = f" | {format_size(int(speed))}/s"
                eta_part = ""
                if img_total > 0 and speed > 0:
                    eta_str = _format_eta(img_done, img_total, speed,
                                          prog.get("bytes_downloaded", 0))
                    if eta_str:
                        eta_part = f" | ⏱ {eta_str}"
                switch_warn = ""
                if prog.get("domain_switches", 0) > 0:
                    switch_warn = "\n" + M("download_progress_stall", n=prog['domain_switches'])
                msg = M("download_duplicate", id=album_id, bar=img_part, pct=pct, done=img_done,
                        total=img_total, speed=speed_part, eta=eta_part, switch=switch_warn)
            else:
                msg = M("download_queued", id=album_id)

        # 附上完整队列
        queue_lines = []
        for aid in _downloading:
            if aid == album_id:
                continue
            prog = _download_progress.get(aid, {})
            d = prog.get("image_completed", 0)
            t = prog.get("image_total", 0)
            if t > 0:
                bar, p = _format_progress_bar(d, t)
                queue_lines.append(f"  [{aid}] {bar} {p}%")
            else:
                queue_lines.append(f"  [{aid}] 排队中...")
        if queue_lines:
            msg += "\n\n📋 队列：\n" + "\n".join(queue_lines)

        await asyncio.get_running_loop().run_in_executor(
            io_executor,
            send_group_reply,
            group_id,
            msg,
            reply_msg_id,
        )
        return

    # 速率限制（批次内跳过）
    if not skip_rate_checks:
        now = time.time()
        for gid in list(_last_request):
            if now - _last_request[gid] > 3600:
                del _last_request[gid]
        last = _last_request.get(group_id, 0)
        if now - last < RATE_LIMIT_SECONDS:
            remaining = int(RATE_LIMIT_SECONDS - (now - last))
            await asyncio.get_running_loop().run_in_executor(
                io_executor,
                send_group_reply,
                group_id,
                M("rate_group", s=remaining),
                reply_msg_id,
            )
            return

        # 全局冷却（跨群），降低 CDN 封锁概率
        global_now = time.time()
        since_last_global = global_now - _last_download_global
        if since_last_global < GLOBAL_COOLDOWN_SECONDS:
            remaining = int(GLOBAL_COOLDOWN_SECONDS - since_last_global)
            await asyncio.get_running_loop().run_in_executor(
                io_executor,
                send_group_reply,
                group_id,
                M("rate_global", s=remaining, g=GLOBAL_COOLDOWN_SECONDS),
                reply_msg_id,
            )
            return

        # 磁盘配额检查
        free_bytes = get_free_space(SCRIPT_DIR)
        if free_bytes >= 0 and free_bytes < DISK_CRITICAL_BYTES:
            await asyncio.get_running_loop().run_in_executor(
                io_executor,
                send_group_reply,
                group_id,
                M("disk_critical", free=format_size(free_bytes)),
                reply_msg_id,
            )
            return

    disk_warning = ""
    if not skip_rate_checks:
        free_bytes = get_free_space(SCRIPT_DIR)
        if free_bytes >= 0 and free_bytes < DISK_WARN_BYTES:
            disk_warning = M("disk_warn", free=format_size(free_bytes))

    _downloading.add(album_id)
    timeout_task = None
    _album_info = None  # 缓存 API 结果，供后续推荐复用
    logger.info(f"开始下载 {album_id} (群 {group_id}){f' {batch_prefix}' if batch_prefix else ''}")

    try:
        # 立即发送确认（不等待 API），秒回防止用户误以为未启动
        if not skip_confirm:
            confirm_msg = M("download_confirm", id=album_id, warning=disk_warning)

            # 如果已有排队中的下载，附上队列摘要
            other_downloads = [aid for aid in _downloading if aid != album_id]
            if other_downloads:
                queue_lines = []
                for aid in other_downloads:
                    prog = _download_progress.get(aid, {})
                    img_done = prog.get("image_completed", 0)
                    img_total = prog.get("image_total", 0)
                    if img_total > 0:
                        bar, pct = _format_progress_bar(img_done, img_total)
                        queue_lines.append(f"  [{aid}] {bar} {pct}%")
                    else:
                        queue_lines.append(f"  [{aid}] 排队中...")
                if queue_lines:
                    confirm_msg += "\n\n📋 当前队列：\n" + "\n".join(queue_lines)

            await asyncio.get_running_loop().run_in_executor(
                io_executor,
                send_group_reply,
                group_id,
                confirm_msg,
                reply_msg_id,
            )
        # 后台获取 info 用于相关推荐（失败不影响下载主流程）
        try:
            info = await asyncio.get_running_loop().run_in_executor(api_executor, _do_info, album_id)
            if info == "NOT_FOUND":
                _album_info = None
            elif not isinstance(info, str) and info is not None:
                _album_info = info
        except Exception:
            _album_info = None

        # 超时提醒：短间隔检查，有进度变化时通知
        async def timeout_notifier():
            last_reported = (-1, -1, -1)  # (img_done, img_total, switches)，-1 确保首轮一定发送
            stale_ticks = 0           # 连续无变化计数，≥2 时发停滞提醒
            try:
                # 每 70s 检查一次进度（减少刷屏）
                intervals = [70] * 8  # 最多 560s ≈ 9min
                for interval in intervals:
                    await asyncio.sleep(interval)
                    if album_id not in _downloading:
                        logger.info(f"进度通知退出: {album_id} 不在下载队列")
                        return
                    prog = _download_progress.get(album_id)
                    if not prog:
                        # 尚无进度数据，首轮发送"准备中"消息
                        if last_reported == (-1, -1):
                            msg = M("download_progress_first")
                            await asyncio.get_running_loop().run_in_executor(
                                io_executor, send_group_msg, group_id, msg
                            )
                            last_reported = (0, 0, 0)
                        else:
                            logger.info(f"进度通知跳过: {album_id} 尚无进度数据")
                        continue
                    img_done = prog.get("image_completed", 0)
                    img_total = prog.get("image_total", 0)
                    switches = prog.get("domain_switches", 0)
                    # 图片总数尚未确定（API 不返回 page_count，需等 before_photo 累加）
                    if img_total == 0 and img_done == 0:
                        if last_reported == (-1, -1):
                            msg = M("download_progress_first")
                            await asyncio.get_running_loop().run_in_executor(
                                io_executor, send_group_msg, group_id, msg
                            )
                            last_reported = (0, 0, 0)
                        continue
                    if (img_done, img_total, switches) == last_reported:
                        stale_ticks += 1
                        if stale_ticks >= 2:
                            msg = M("download_progress_stuck", done=img_done, total=img_total)
                            await asyncio.get_running_loop().run_in_executor(
                                io_executor, send_group_msg, group_id, msg
                            )
                            stale_ticks = 0  # 重置避免刷屏
                        continue
                    stale_ticks = 0
                    last_reported = (img_done, img_total, switches)
                    if img_total > 0 or prog.get("total", 0) > 0:
                        img_total = prog.get("image_total", 0)
                        if img_total > 0:
                            bar, pct = _format_progress_bar(img_done, img_total)
                            img_part = bar
                        else:
                            img_part = f"图片: {img_done}/?"
                            pct = "?"
                        ch_total = prog.get("total", 0)
                        ch_part = f"\n章节: {prog['completed']}/{ch_total}" if ch_total > 0 else ""
                        speed = prog.get("speed", 0)
                        speed_part = f" | {format_size(int(speed))}/s" if speed > 0 else ""
                        eta_part = ""
                        if img_total > 0 and speed > 0:
                            eta_str = _format_eta(img_done, img_total, speed,
                                                  prog.get("bytes_downloaded", 0))
                            if eta_str:
                                eta_part = f" | ⏱ {eta_str}"
                        switch_warn = ""
                        if switches > 0:
                            switch_warn = "\n" + M("download_progress_stall", n=switches)
                        msg = M("download_progress", bar=img_part, pct=pct if img_total > 0 else "?",
                                done=img_done, total=img_total, speed=speed_part, eta=eta_part,
                                ch=ch_part, switch=switch_warn)
                    else:
                        msg = M("download_progress_nochap")
                    ok = await asyncio.get_running_loop().run_in_executor(
                        io_executor, send_group_msg, group_id, msg
                    )
                    if ok:
                        logger.info(f"进度通知已发送: {album_id} ({img_done}/{img_total})")
                    else:
                        logger.warning(f"进度通知发送失败 (群{group_id})")
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        timeout_task = asyncio.create_task(timeout_notifier())

        def on_progress(completed: int, total: int, photo_name: str,
                        image_completed: int, image_total: int,
                        speed: float = 0.0, bytes_downloaded: int = 0,
                        domain_switches: int = 0):
            _download_progress[album_id] = {
                "completed": completed,
                "total": total,
                "photo_name": photo_name,
                "image_completed": image_completed,
                "image_total": image_total,
                "speed": speed,
                "bytes_downloaded": bytes_downloaded,
                "domain_switches": domain_switches,
            }

        def check_cancelled():
            return album_id in _stop_requests

        result = await asyncio.get_running_loop().run_in_executor(
            executor, download_single, album_id, on_progress, check_cancelled, output_format
        )

        upload_info = ""
        output_path = result.get("output_path") or result.get("pdf_path")
        if output_path:
            ext = "zip" if output_format == "zip" else "pdf"
            fname = f"{album_id}.{ext}"
            label = "ZIP" if output_format == "zip" else "PDF"
            try:
                fsize = os.path.getsize(output_path)
                fsize_str = format_size(fsize)
                logger.info(f"准备上传: {output_path} ({fsize_str})")
            except OSError:
                fsize = 0
                fsize_str = "?"
            # ZIP 超过 100MB 警告，QQ 群文件通常有大小限制
            if output_format == "zip" and fsize > 100 * 1024 * 1024:
                upload_info = M("upload_too_big", fmt=label, size=fsize_str, id=album_id)
            else:
                try:
                    if output_format == "zip":
                        upload_timeout = UPLOAD_TIMEOUT_ZIP
                    else:
                        # PDF 超时按文件大小动态计算：基础 300s + 每 MB 2s，上限 900s
                        size_mb = fsize / (1024 * 1024) if fsize > 0 else 0
                        upload_timeout = min(
                            UPLOAD_TIMEOUT_PDF_BASE + int(size_mb * UPLOAD_TIMEOUT_PDF_PER_MB),
                            UPLOAD_TIMEOUT_PDF_MAX,
                        )
                    upload_func = upload_private_file if int(group_id) in _private_chats else upload_group_file
                    ok, detail = await asyncio.wait_for(
                        asyncio.get_running_loop().run_in_executor(
                            executor, upload_func, group_id, output_path, fname,
                        ),
                        timeout=upload_timeout,
                    )
                except asyncio.TimeoutError:
                    ok, detail = False, f"上传超时（{fsize_str}），文件过大或网络不佳"
                if ok:
                    upload_info = M("upload_ok", fmt=label, size=fsize_str)
                else:
                    if output_format == "zip":
                        detail += M_single("hint_zip_too_big", id=album_id)
                    upload_info = M("upload_fail", fmt=label, detail=detail)
        else:
            label = "ZIP" if output_format == "zip" else "PDF"
            upload_info = M("upload_no_output", fmt=label)

        retries = result.get("retry_count", 0)
        if result["status"] == "cancelled":
            summary = M("download_cancelled")
        elif result["status"] == "ok":
            if retries > 0:
                summary = M("download_ok_retry", n=retries, count=result.get("image_count", 0))
            else:
                summary = M("download_ok")
        elif result["status"] == "partial":
            lost = result.get("failed_images", result.get("image_count", 0))
            et = result.get("error_type", "")
            hint = M_single("hint_cdn_partial") if et == "cdn_partial" else ""
            summary = M("download_partial", n=lost, r=retries, got=result.get("image_count", 0), hint=hint)
        else:
            et = result.get("error_type", "")
            if et == "not_found":
                hint = M_single("hint_not_found")
            elif et == "cdn_down":
                hint = M_single("hint_cdn_down")
            elif et == "unknown":
                hint = M_single("hint_unknown", error=result.get("error", "未知"))
            else:
                hint = ""
            summary = M("download_fail", error=result.get("error", "未知错误"), hint=hint)

        fmt_label = "ZIP" if output_format == "zip" else "PDF"
        upload_display = upload_info
        if not upload_info.startswith("📦"):
            upload_display = "😿 " + upload_info
        text = M("download_report", prefix=batch_prefix,
                 title=result.get("title", ""),
                 author=result.get("author", "未知"),
                 photo_count=result.get("photo_count", 0),
                 image_count=result.get("image_count", 0),
                 total_size_str=result.get("total_size_str", ""),
                 fmt=fmt_label, upload=upload_display) + "\n\n" + summary
        await asyncio.get_running_loop().run_in_executor(
            io_executor, send_group_reply, group_id, text, reply_msg_id
        )

        # 相关推荐：复用初次 API 调用获取的 related_list，附加到报告末尾
        if result["status"] == "ok" and _album_info is not None:
            try:
                related = getattr(_album_info, "related_list", None)
                if related and len(related) >= 1:
                    import random as _rnd
                    picks = _rnd.sample(related, min(3, len(related)))
                    items = []
                    for r in picks:
                        rid = r.get("id", "?")
                        rname = r.get("name", "未知")[:35]
                        rauthor = r.get("author", "")
                        items.append(M_single("download_related_item", id=rid, title=rname, author=rauthor))
                    text += "\n\n" + M("download_related", items="\n".join(items))
            except Exception:
                pass

        _last_request[group_id] = time.time()
        _last_download_global = time.time()
        logger.info(f"下载完成 {album_id} (群 {group_id})")
        return result

    except Exception as e:
        logger.error(f"下载异常 {album_id}: {e}", exc_info=True)
        await asyncio.get_running_loop().run_in_executor(
            io_executor,
            send_group_reply,
            group_id,
            M("download_crash"),
            reply_msg_id,
        )
        return None
    finally:
        if timeout_task:
            timeout_task.cancel()
        _downloading.discard(album_id)
        _download_progress.pop(album_id, None)
        _stop_requests.discard(album_id)
        # 冷却时间戳保留在 _stop_times 中让 STOP_COOLDOWN 检查生效


async def cmd_download_batch(group_id: int, ids: list, reply_msg_id: int, output_format: str = "pdf"):
    """批量下载：顺序调用 cmd_download，共享冷却窗口"""
    # 去重
    ids = [aid for aid in ids if aid not in _downloading]
    if not ids:
        await asyncio.get_running_loop().run_in_executor(
            io_executor, send_group_reply, group_id,
            M("all_queued"),
            reply_msg_id,
        )
        return

    total = len(ids)
    success_count = 0
    failed_ids = []

    await asyncio.get_running_loop().run_in_executor(
        io_executor, send_group_reply, group_id,
        M("batch_start", n=total),
        reply_msg_id,
    )

    for idx, album_id in enumerate(ids, 1):
        batch_prefix = f"[{idx}/{total}] "
        result = await cmd_download(
            group_id, album_id, reply_msg_id, output_format=output_format,
            batch_prefix=batch_prefix, skip_rate_checks=True,
        )
        if result and result.get("status") == "ok":
            success_count += 1
        elif result and result.get("status") != "cancelled":
            failed_ids.append(album_id)
        if result and result.get("status") == "cancelled":
            break

    # 失败项重试一次
    if failed_ids:
        logger.info(f"批量重试 {len(failed_ids)} 个失败项: {failed_ids}")
        for aid in failed_ids:
            retry_prefix = f"[🔄] "
            result = await cmd_download(
                group_id, aid, reply_msg_id, output_format=output_format,
                batch_prefix=retry_prefix, skip_rate_checks=True,
            )
            if result and result.get("status") == "ok":
                success_count += 1

    # 批次完成后设置全局冷却
    global _last_download_global
    _last_download_global = time.time()

    if total > 1:
        summary = M("batch_done", ok=success_count, total=total)
        if success_count < total:
            summary += f"\n有 {total - success_count} 个失败了，查看上面报告了解详情~"
        await asyncio.get_running_loop().run_in_executor(
            io_executor, send_group_msg, group_id, summary
        )


async def cmd_search(group_id: int, query: str, reply_msg_id: int):
    """处理搜索命令"""
    query = query.strip()
    if len(query) < 1:
        await asyncio.get_running_loop().run_in_executor(
            io_executor,
            send_group_reply,
            group_id,
            M("search_empty_query"),
            reply_msg_id,
        )
        return

    logger.info(f"搜索: {query} (群 {group_id})")

    await _ack(group_id, reply_msg_id)
    result = await async_api_run(get_jm_client().search_site, query, page=1)

    if isinstance(result, str):
        logger.error(f"搜索异常: {result}")
        text = M("search_error")
    else:
        total = getattr(result, "total", 0) if hasattr(result, "total") else (len(list(result)) if hasattr(result, '__iter__') else 0)
        items = list(result)[:5]
        if not items:
            text = M("search_none", query=query)
        else:
            item_lines = []
            for i, item in enumerate(items, 1):
                if isinstance(item, tuple):
                    aid, title = item[0], item[1][:40]
                    author = ""
                else:
                    aid = getattr(item, "id", "?")
                    title = getattr(item, "name", "未知")[:40]
                    author = getattr(item, "author", "未知")
                item_lines.append(M_single("search_item", i=i, id=aid, title=title, author=author))
            text = M("search_result", total=total, query=query, items="\n".join(item_lines))

    await asyncio.get_running_loop().run_in_executor(
        io_executor, send_group_msg, group_id, text
    )


async def cmd_info(group_id: int, album_id: str, reply_msg_id: int):
    """处理详情命令"""
    logger.info(f"查询详情: {album_id} (群 {group_id})")

    await _ack(group_id, reply_msg_id)
    result = await async_api_run(_do_info, album_id)

    if result == "NOT_FOUND":
        text = M("not_found", id=album_id)
    elif isinstance(result, str):
        logger.error(f"查询异常: {result}")
        text = M("info_error")
    else:
        tags = ", ".join(result.tags) if result.tags else "无"
        authors = ", ".join(result.authors) if result.authors else "未知"
        likes = getattr(result, "likes", 0) or 0
        views = getattr(result, "views", 0) or 0
        page_count = getattr(result, "page_count", 0) or 0
        try:
            chapter_count = len(result)
        except Exception:
            chapter_count = 0

        # page_count 可能为 0（JM API 不保证返回），尝试从章节累加
        if page_count == 0 and chapter_count > 0:
            try:
                total_pages = 0
                for photo in result:
                    try:
                        total_pages += len(photo)
                    except Exception:
                        pass
                if total_pages > 0:
                    page_count = total_pages
            except Exception:
                pass

        pages_str = f"{page_count}页" if page_count > 0 else "未知"
        chapters_str = f"{chapter_count}章" if chapter_count > 0 else ""

        text = M("info_display", id=result.id, name=result.name,
                authors=authors, tags=tags, pages=pages_str,
                chapters=chapters_str, likes=likes, views=views)

    await asyncio.get_running_loop().run_in_executor(
        io_executor, send_group_msg, group_id, text
    )


def _do_info(album_id):
    client = get_jm_client()
    try:
        album = client.get_album_detail(album_id)
    except Exception as e:
        # 本子不存在时 jmcomic 抛异常，返回特殊标记便于上层识别
        if "not found" in str(e).lower() or "不存在" in str(e) or "下架" in str(e):
            return "NOT_FOUND"
        raise
    # page_count 可能为 0（JM API 不保证返回），
    # 此时对每个章节调 check_photo 获取真实图片数
    if getattr(album, 'page_count', 0) == 0:
        total = 0
        for photo in album:
            try:
                client.check_photo(photo)
                total += len(photo)
            except Exception:
                pass
        if total > 0:
            album.page_count = total
    return album


async def cmd_rank(group_id: int, rank_type: str, reply_msg_id: int):
    """处理排行榜命令"""
    rank_type = rank_type or "day"
    label = {"day": "日榜", "week": "周榜", "month": "月榜"}.get(rank_type, "")

    logger.info(f"排行榜: {rank_type} (群 {group_id})")

    await _ack(group_id, reply_msg_id)
    result = await async_api_run(_do_rank, rank_type)

    if isinstance(result, str):
        logger.error(f"排行榜异常: {result}")
        text = M("rank_error")
    else:
        items = list(result)[:10]
        if not items:
            text = M("rank_empty", label=label)
        else:
            item_lines = []
            for i, item in enumerate(items, 1):
                if isinstance(item, tuple):
                    aid, title = item[0], item[1][:40]
                    author = ""
                else:
                    aid = getattr(item, "id", "?")
                    title = getattr(item, "name", "未知")[:40]
                    author = getattr(item, "author", "未知")
                item_lines.append(M_single("rank_item", i=i, id=aid, title=title, author=author))
            text = M("rank_display", label=label, items="\n".join(item_lines))

    await asyncio.get_running_loop().run_in_executor(
        io_executor, send_group_msg, group_id, text
    )


def _do_rank(rank_type):
    client = get_jm_client()
    if rank_type == "week":
        return client.week_ranking(page=1)
    elif rank_type == "month":
        return client.month_ranking(page=1)
    else:
        return client.day_ranking(page=1)


async def cmd_cache(group_id: int, reply_msg_id: int):
    """显示磁盘使用情况概览"""
    logger.info(f"缓存查询 (群 {group_id})")

    def do_cache_query():
        dl_size, dl_dirs, _ = get_dir_info(DOWNLOADS_DIR)
        pdf_size, _, pdf_files = get_dir_info(PDFS_DIR)
        zip_size, _, zip_files = get_dir_info(ZIPS_DIR)
        log_size = (
            os.path.getsize(ERROR_LOG_PATH)
            if os.path.exists(ERROR_LOG_PATH) else 0
        )
        total_size = dl_size + pdf_size + zip_size + log_size
        try:
            free = get_free_space(SCRIPT_DIR)
            free_str = format_size(free) if free >= 0 else "无法获取"
        except Exception:
            free_str = "无法获取"

        return M("cache_status",
                dl_size=format_size(dl_size), dl_dirs=dl_dirs,
                pdf_size=format_size(pdf_size), pdf_files=pdf_files,
                zip_size=format_size(zip_size), zip_files=zip_files, free=free_str)

    text = await asyncio.get_running_loop().run_in_executor(io_executor, do_cache_query)
    await asyncio.get_running_loop().run_in_executor(
        io_executor, send_group_reply, group_id, text, reply_msg_id
    )


async def cmd_cache_clean(group_id: int, days: int, reply_msg_id: int):
    """清理超过 N 天的下载目录，保留 PDF"""
    logger.info(f"缓存清理: {days} 天 (群 {group_id})")

    def do_clean():
        removed, freed, errors = clean_old_dirs(DOWNLOADS_DIR, max_age_days=days)
        text = M("cache_clean", days=days, removed=removed, freed=format_size(freed))
        if errors:
            text += f"\n😿 有 {len(errors)} 团排不出来..."
        return text

    text = await asyncio.get_running_loop().run_in_executor(io_executor, do_clean)
    await asyncio.get_running_loop().run_in_executor(
        io_executor, send_group_reply, group_id, text, reply_msg_id
    )


async def cmd_restart(group_id: int, reply_msg_id: int):
    """软重启：断开 WebSocket 让主循环自动重连"""
    logger.info(f"重启请求 (群 {group_id})")
    await asyncio.get_running_loop().run_in_executor(
        io_executor,
        send_group_reply,
        group_id,
        M("restart_ok"),
        reply_msg_id,
    )
    if _current_ws is not None:
        await _current_ws.close()


async def cmd_stop(group_id: int, reply_msg_id: int):
    """停止当前正在下载的任务"""
    logger.info(f"停止下载请求 (群 {group_id})")
    active = [aid for aid in _downloading if aid not in _stop_requests]
    if not active:
        await asyncio.get_running_loop().run_in_executor(
            io_executor,
            send_group_reply,
            group_id,
            M("stop_none"),
            reply_msg_id,
        )
        return
    # 标记所有进行中的下载为取消（不清除 _downloading 防止竞态，由 finally 清理）
    now = time.time()
    count = len(active)
    for aid in active:
        _stop_requests.add(aid)
        _stop_times[aid] = now
    # 重置冷却限制，停止后可以立即重新下载（不同 ID）
    _last_request.pop(group_id, None)
    _last_download_global = 0
    await asyncio.get_running_loop().run_in_executor(
        io_executor,
        send_group_reply,
        group_id,
        M("stop_ok", n=count),
        reply_msg_id,
    )


async def cmd_category(group_id: int, query: str, reply_msg_id: int):
    """按标签筛选漫画"""
    query = query.strip()
    if len(query) < 1:
        await asyncio.get_running_loop().run_in_executor(
            io_executor, send_group_reply, group_id,
            M("category_empty_query"),
            reply_msg_id,
        )
        return

    logger.info(f"标签筛选: {query} (群 {group_id})")

    await _ack(group_id, reply_msg_id)
    result = await async_api_run(get_jm_client().search_tag, query, page=1)

    if isinstance(result, str):
        logger.error(f"标签筛选异常: {result}")
        text = M("category_error")
    else:
        total = getattr(result, "total", 0) if hasattr(result, "total") else (len(list(result)) if hasattr(result, '__iter__') else 0)
        items = list(result)[:5]
        if not items:
            text = M("category_none", query=query)
        else:
            item_lines = []
            for i, item in enumerate(items, 1):
                if isinstance(item, tuple):
                    aid, title = item[0], item[1][:40]
                    author = ""
                else:
                    aid = getattr(item, "id", "?")
                    title = getattr(item, "name", "未知")[:40]
                    author = getattr(item, "author", "未知")
                item_lines.append(M_single("search_item", i=i, id=aid, title=title, author=author))
            text = M("category_result", total=total, query=query, items="\n".join(item_lines))

    await asyncio.get_running_loop().run_in_executor(
        io_executor, send_group_msg, group_id, text
    )


async def cmd_random(group_id: int, reply_msg_id: int, mode: str = "", tag: str = ""):
    """随机推荐一本漫画，支持 --top/--best/--new 模式和 --tag 筛选"""
    labels = {"top": "人气", "best": "好评", "new": "最新"}
    extra = f" {labels.get(mode, '')}" if mode else ""
    extra += f" #{tag}" if tag else ""
    logger.info(f"随机推荐 (群 {group_id}){extra}")
    import random as _random

    await _ack(group_id, reply_msg_id)
    raw = await async_api_run(_do_random, _random, mode, tag, timeout=30)
    # api_call 超时返回字符串，正常返回 (albums_list, error) 元组
    if isinstance(raw, str):
        logger.error(f"随机推荐异常: {raw}")
        text = M("random_error")
    else:
        albums, error = raw
        if error:
            logger.error(f"随机推荐异常: {error}")
            text = error if albums is None else M("random_error") + f" {error}"
        else:
            item_lines = []
            for album in albums:
                tags = ", ".join(album.tags[:5]) if album.tags else "无"
                authors = ", ".join(album.authors) if album.authors else "未知"
                page_count = getattr(album, "page_count", 0) or 0
                try:
                    chapter_count = len(album)
                except Exception:
                    chapter_count = 0
                item_lines.append(M("random_result_item", id=album.id, name=album.name,
                    authors=authors, tags=tags, pages=page_count, chapters=chapter_count))
            text = M("random_result", items="\n".join(item_lines))

    await asyncio.get_running_loop().run_in_executor(
        io_executor, send_group_msg, group_id, text
    )


def _do_random(_random, mode: str = "", tag: str = ""):
    client = get_jm_client()
    # 确定排序方式
    order_map = {
        "top": jmcomic.JmMagicConstants.ORDER_BY_VIEW,
        "best": jmcomic.JmMagicConstants.ORDER_BY_SCORE,
        "new": jmcomic.JmMagicConstants.ORDER_BY_LATEST,
    }
    order_by = order_map.get(mode, jmcomic.JmMagicConstants.ORDER_BY_LATEST)

    # 第一步：获取第一页确定总数
    # 使用 +tag 语法精确匹配标签（search_tag 可能模糊匹配标题）
    if tag:
        first_page = client.search_site(f"+{tag}", page=1, order_by=order_by)
    else:
        first_page = client.search_site('', page=1, order_by=order_by)
    total = getattr(first_page, "total", 0)
    if total == 0:
        error_msg = "找不到匹配的漫画呢...换个标签试试？(◞‸◟)" if tag else "什么都没找到...服务器可能在摸鱼 (´•ω•`)"
        return None, error_msg
    page_count = max(1, (total + 79) // 80)  # ceil(total/80)
    max_page = min(page_count, RANDOM_MAX_PAGES) if page_count > 0 else 1
    # 每本从不同随机页各取 1 条，纯随机
    num_picks = min(3, total)
    pages_to_fetch = _random.sample(range(1, max_page + 1), min(num_picks, max_page))
    picks = []
    for page in pages_to_fetch:
        if page == 1:
            items = list(first_page)
        else:
            if tag:
                items = list(client.search_site(f"+{tag}", page=page, order_by=order_by))
            else:
                items = list(client.search_site('', page=page, order_by=order_by))
        if items:
            picks.append(_random.choice(items))
    if not picks:
        return None, "这页是空的喵...再试一次？(◞‸◟)"
    # 并行获取详情（最多 3 个同步调用）
    ids_to_fetch = []
    for item in picks:
        aid = item[0] if isinstance(item, tuple) else item.id
        if aid not in ids_to_fetch:
            ids_to_fetch.append(aid)
    albums = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(client.get_album_detail, aid): aid for aid in ids_to_fetch}
        for future in concurrent.futures.as_completed(futures, timeout=30):
            aid = futures[future]
            try:
                albums.append(future.result())
            except Exception as e:
                logger.warning(f"随机推荐获取详情失败 {aid}: {e}")
    if not albums:
        return None, "获取详情失败喵...再试一次？(◞‸◟)"
    return albums, None


async def cmd_queue(group_id: int, reply_msg_id: int):
    """查看下载队列"""
    logger.info(f"队列查询 (群 {group_id})")
    # 过滤掉已标记取消的
    active = [aid for aid in _downloading if aid not in _stop_requests]
    stopping = [aid for aid in _downloading if aid in _stop_requests]
    if not active and not stopping:
        text = M("queue_empty")
    else:
        item_lines = []
        for aid in active:
            prog = _download_progress.get(aid, {})
            img_done = prog.get("image_completed", 0)
            img_total = prog.get("image_total", 0)
            speed = prog.get("speed", 0)
            eta_str = ""
            bar = ""
            pct = ""
            if img_total > 0:
                bar, pct = _format_progress_bar(img_done, img_total)
                pct_str = bar
                speed_str = f" | {format_size(int(speed))}/s" if speed > 0 else ""
                if speed > 0:
                    eta_str = _format_eta(img_done, img_total, speed,
                                          prog.get("bytes_downloaded", 0))
                    eta_str = f" | ⏱ {eta_str}" if eta_str else ""
                if img_done > 0:
                    item_lines.append(M_single("queue_item_active", id=aid, bar=pct_str,
                        pct=pct, done=img_done, total=img_total, speed=speed_str, eta=eta_str))
                else:
                    item_lines.append(M_single("queue_item_waiting", id=aid))
            else:
                item_lines.append(M_single("queue_item_waiting", id=aid))
        if stopping:
            for aid in stopping:
                item_lines.append(f"  🛑 [{aid}] 正在停下...")
        text = M("queue_display", items="\n".join(item_lines))

    await asyncio.get_running_loop().run_in_executor(
        io_executor, send_group_reply, group_id, text, reply_msg_id
    )


def _execute_action(action: dict) -> str:
    """执行意图分类后的动作，返回格式化数据文本"""
    import random as _random
    client = get_jm_client()
    act = action.get("action", "chat")

    def _format_items(items, max_n=5):
        """格式化漫画列表为文本"""
        item_list = list(items)[:max_n]
        if not item_list:
            return None
        lines = []
        for i, item in enumerate(item_list, 1):
            if isinstance(item, tuple):
                aid, title = item[0], str(item[1])[:50]
                author = ""
            else:
                aid = getattr(item, "id", "?")
                title = str(getattr(item, "name", "未知"))[:50]
                author = str(getattr(item, "author", ""))
            lines.append(f"  {i}. [{aid}] {title}" + (f" ({author})" if author else ""))
        return "\n".join(lines)

    if act == "search":
        query = action.get("query", "")
        result = client.search_site(query, page=1)
        items_text = _format_items(result)
        if not items_text:
            return f"搜索 \"{query}\" 未找到任何漫画"
        total = getattr(result, "total", 0)
        return f"搜索 \"{query}\" 共 {total} 条，前 5 条：\n{items_text}"

    elif act == "info":
        aid = action.get("id", "")
        info = _do_info(aid)
        if info == "NOT_FOUND":
            return f"漫画 [{aid}] 不存在或已下架"
        if isinstance(info, str):
            return f"获取详情失败: {info}"
        tags = ", ".join(info.tags[:5]) if info.tags else "无"
        authors = ", ".join(info.authors) if info.authors else "未知"
        likes = getattr(info, "likes", 0) or 0
        views = getattr(info, "views", 0) or 0
        page_count = getattr(info, "page_count", 0) or 0
        try:
            chapter_count = len(info)
        except Exception:
            chapter_count = 0
        return (
            f"漫画 [{info.id}] {info.name}\n"
            f"作者: {authors}\n标签: {tags}\n"
            f"页数: {page_count}, 章节: {chapter_count}\n"
            f"点赞: {likes}, 浏览: {views}"
        )

    elif act == "rank":
        rank_type = action.get("type", "day")
        result = _do_rank(rank_type)
        if isinstance(result, str):
            return f"获取排行榜失败: {result}"
        items_text = _format_items(result, 10)
        if not items_text:
            return "暂无排行数据"
        label = {"day": "日榜", "week": "周榜", "month": "月榜"}.get(rank_type, "")
        return f"JM {label}TOP10：\n{items_text}"

    elif act == "random":
        mode = action.get("mode", "")
        tag = action.get("tag", "")
        raw = _do_random(_random, mode, tag)
        if isinstance(raw, str):
            return f"随机推荐失败: {raw}"
        albums, error = raw
        if error:
            return f"随机推荐失败: {error}"
        if not albums:
            return "未找到符合条件的漫画"
        lines = [f"随机推荐 {len(albums)} 本："]
        for album in albums:
            tags_str = ", ".join(album.tags[:3]) if album.tags else "无"
            a = ", ".join(album.authors) if album.authors else "未知"
            pc = getattr(album, "page_count", 0) or 0
            try:
                cc = len(album)
            except Exception:
                cc = 0
            lines.append(f"  [{album.id}] {album.name} ({a}) | {pc}页 {cc}章 | {tags_str}")
        return "\n".join(lines)

    elif act == "category":
        tag = action.get("tag", "")
        result = client.search_tag(tag, page=1)
        items_text = _format_items(result)
        if not items_text:
            return f"标签 \"{tag}\" 未找到漫画"
        total = getattr(result, "total", 0)
        return f"标签 \"{tag}\" 共 {total} 条，前 5 条：\n{items_text}"

    else:
        return ""  # chat


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
    await asyncio.get_running_loop().run_in_executor(
        io_executor, send_group_reply, group_id, text, reply_msg_id,
    )


async def cmd_ask_clear(group_id: int, reply_msg_id: int):
    """清理当前群的 AI 聊天上下文"""
    from ai_chat import clear_history
    count = clear_history(group_id)
    logger.info(f"清理聊天历史 (群 {group_id}): {count} 条")
    await asyncio.get_running_loop().run_in_executor(
        io_executor, send_group_msg, group_id, M("ask_clear", n=count),
    )


async def cmd_ask(group_id: int, message: str, reply_msg_id: int):
    """AI 聊天：意图分类 → 执行动作 → 猫娘回复"""
    logger.info(f"AI 聊天 (群 {group_id}): {message[:50]}...")

    try:
        # Step 1: 意图分类（API 调用，放 api_executor）
        action = await asyncio.get_running_loop().run_in_executor(
            api_executor, classify_intent, message, group_id
        )
        logger.info(f"意图: {action}")
    except Exception as e:
        logger.error(f"意图分类失败: {e}")
        await asyncio.get_running_loop().run_in_executor(
            io_executor, send_group_reply, group_id, M("ask_error"), reply_msg_id
        )
        return

    # Step 2: 根据意图执行
    act = action.get("action", "chat")

    if act == "chat":
        # 纯聊天：直接用群聊模式
        result = await asyncio.get_running_loop().run_in_executor(
            api_executor, group_chat, group_id, message
        )

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
                api_executor, _execute_action, action
            )
        except Exception as e:
            logger.error(f"执行动作失败: {e}")
            await asyncio.get_running_loop().run_in_executor(
                io_executor, send_group_reply, group_id, M("ask_error"), reply_msg_id
            )
            return

        try:
            result = await asyncio.get_running_loop().run_in_executor(
                api_executor, generate_reply, data, group_id
            )
        except Exception as e:
            logger.error(f"生成回复失败: {e}")
            result = data  # 回退到原始数据

        # 保存到群聊历史
        _save_history(group_id, message, result)

    # 截断过长回复
    if len(result) > 800:
        result = result[:780] + "..."

    await asyncio.get_running_loop().run_in_executor(
        io_executor, send_group_reply, group_id, result, reply_msg_id
    )


HELP_MAIN = M("help_main")
HELP_ASK = M("help_ask")
HELP_DOWNLOAD = M("help_download")
HELP_DISCOVER = M("help_discover")
HELP_MANAGE = M("help_manage")
HELP_MAP = {"0": HELP_ASK, "1": HELP_DOWNLOAD, "2": HELP_DISCOVER, "3": HELP_MANAGE}


async def cmd_help(group_id: int, reply_msg_id: int, sub: str = ""):
    """发送帮助消息，支持多级菜单"""
    logger.info(f"帮助请求 (群 {group_id}){f' sub={sub}' if sub else ''}")
    text = HELP_MAP.get(sub, HELP_MAIN)
    await asyncio.get_running_loop().run_in_executor(
        io_executor, send_group_msg, group_id, text
    )


# === 事件分发 ===


async def safe_dispatch(group_id: int, raw_msg: str, reply_msg_id: int, is_private: bool = False):
    """包装 dispatch，捕获异常防止静默失败"""
    try:
        if is_private:
            _private_chats.add(int(group_id))
        await dispatch(group_id, raw_msg, reply_msg_id)
    except Exception as e:
        logger.error(
            f"命令处理异常 (chat={group_id}, msg={raw_msg[:50]}): {e}",
            exc_info=True,
        )


async def dispatch(group_id: int, raw_msg: str, reply_msg_id: int):
    """根据消息内容分发到对应命令处理函数"""
    raw_msg = raw_msg.strip()

    m = JM_CACHE_CLEAN_RE.match(raw_msg)
    if m:
        days = int(m.group(1)) if m.group(1) else 7
        await cmd_cache_clean(group_id, days, reply_msg_id)
        return

    m = JM_CACHE_RE.match(raw_msg)
    if m:
        await cmd_cache(group_id, reply_msg_id)
        return

    m = JM_RESTART_RE.match(raw_msg)
    if m:
        await cmd_restart(group_id, reply_msg_id)
        return

    if JM_STOP_RE.match(raw_msg):
        await cmd_stop(group_id, reply_msg_id)
        return

    m = JM_CATEGORY_RE.match(raw_msg)
    if m:
        await cmd_category(group_id, m.group(1), reply_msg_id)
        return

    m = JM_RANDOM_RE.match(raw_msg)
    if m:
        # 手动解析 --top/--best/--new 和 --tag X，支持任意顺序
        rest = (m.group(1) or "").strip()
        mode = ""
        tag = ""
        parts = rest.split()
        unknown = []
        i = 0
        while i < len(parts):
            if parts[i] in ("--top", "--best", "--new"):
                mode = parts[i][2:]  # strip --
            elif parts[i] == "--tag" and i + 1 < len(parts):
                tag = parts[i + 1]
                i += 1  # skip tag value
            elif parts[i].startswith("tag:") or parts[i].startswith("tag："):
                # 支持 tag:xxx 或 tag：xxx 简写
                tag = parts[i].split(":", 1)[-1].split("：", 1)[-1]
            else:
                unknown.append(parts[i])
            i += 1
        if unknown and not mode and not tag:
            await asyncio.get_running_loop().run_in_executor(
                io_executor, send_group_reply, group_id,
                M("random_bad_flags", flags=' '.join(unknown)),
                reply_msg_id,
            )
            return
        await cmd_random(group_id, reply_msg_id, mode=mode, tag=tag)
        return

    if JM_QUEUE_RE.match(raw_msg):
        await cmd_queue(group_id, reply_msg_id)
        return

    m = JM_HELP_RE.match(raw_msg)
    if m:
        await cmd_help(group_id, reply_msg_id, sub=m.group(1) or "")
        return

    # /jm role — 需要在 /jm ask 之前（避免角色名触发误判）
    m = JM_ROLE_RE.match(raw_msg)
    if m:
        await cmd_role(group_id, m.group(1), reply_msg_id)
        return

    if JM_ASK_CLEAR_RE.match(raw_msg):
        await cmd_ask_clear(group_id, reply_msg_id)
        return

    m = JM_ASK_RE.match(raw_msg)
    if m:
        await cmd_ask(group_id, m.group(1).strip(), reply_msg_id)
        return

    m = JM_DOWNLOAD_RE.match(raw_msg)
    if m:
        fmt = m.group(2) or "pdf"
        ids_raw = m.group(1).split()
        # 去重保留顺序 + 验证纯数字
        ids = []
        seen = set()
        for aid in ids_raw:
            if aid.isdigit() and aid not in seen:
                ids.append(aid)
                seen.add(aid)
        if not ids:
            await asyncio.get_running_loop().run_in_executor(
                io_executor, send_group_reply, group_id,
                M("invalid_id"),
                reply_msg_id,
            )
            return
        if len(ids) == 1:
            await cmd_download(group_id, ids[0], reply_msg_id, output_format=fmt)
        else:
            await cmd_download_batch(group_id, ids, reply_msg_id, output_format=fmt)
        return

    m = JM_SEARCH_RE.match(raw_msg)
    if m:
        await cmd_search(group_id, m.group(1), reply_msg_id)
        return

    m = JM_INFO_RE.match(raw_msg)
    if m:
        await cmd_info(group_id, m.group(1), reply_msg_id)
        return

    m = JM_RANK_RE.match(raw_msg)
    if m:
        await cmd_rank(group_id, m.group(1) or "day", reply_msg_id)
        return

    # /jm <ID> (向后兼容)
    m = JM_RE.match(raw_msg)
    if m:
        await cmd_download(group_id, m.group(1), reply_msg_id)
        return

    # 无匹配 → 未知命令
    await asyncio.get_running_loop().run_in_executor(
        io_executor, send_group_reply, group_id,
        M("unknown_command"),
        reply_msg_id,
    )


# === WebSocket 主循环 ===


async def main():
    global _current_ws
    os.chdir(SCRIPT_DIR)
    logger.info("JM Bot 启动中...")

    # 恢复限流状态（防止重启后刷屏）
    rate_file = os.path.join(SCRIPT_DIR, "rate_limits.json")
    saved = load_json(rate_file, {})
    for gid, ts in saved.items():
        try:
            _last_request[int(gid)] = float(ts)
        except (ValueError, TypeError):
            pass
    if _last_request:
        logger.info(f"已恢复 {len(_last_request)} 条限流记录")

    # 轮转日志
    bot_log = os.path.join(SCRIPT_DIR, "bot.log")
    rotate_log_if_needed(bot_log, max_mb=20, keep_kb=1024)

    async def persist_limits():
        """定期保存限流状态"""
        while True:
            await asyncio.sleep(300)  # 每 5 分钟
            try:
                save_json(rate_file, {str(k): v for k, v in _last_request.items()})
            except Exception:
                pass

    asyncio.create_task(persist_limits())

    while True:
        try:
            async with websockets.connect(WS_URL) as ws:
                _current_ws = ws
                logger.info("已连接 NapCat WebSocket")
                async for raw in ws:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if not isinstance(event, dict):
                        continue
                    if event.get("post_type") != "message":
                        continue
                    msg_type = event.get("message_type", "")
                    if msg_type not in ("group", "private"):
                        continue

                    raw_msg = event.get("raw_message", "")
                    if not raw_msg.strip().startswith("/jm"):
                        continue

                    group_id = event.get("group_id") or event.get("user_id")
                    is_private = msg_type == "private"
                    if not group_id:
                        continue
                    reply_msg_id = event.get("message_id", 0)

                    asyncio.create_task(safe_dispatch(group_id, raw_msg, reply_msg_id, is_private=is_private))

        except websockets.ConnectionClosed:
            _current_ws = None
            logger.warning("连接断开，5 秒后重连...")
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            _current_ws = None
            break
        except Exception as e:
            _current_ws = None
            logger.error(f"异常: {e}")
            await asyncio.sleep(5)


# === 优雅退出 ===
# 不使用 Python signal handler（Win/Linux 行为不一致且有死锁风险），
# 直接依赖 asyncio.run() 的 KeyboardInterrupt 处理 + finally 清理

if __name__ == "__main__":
    # Windows 控制台 UTF-8
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("正在关闭线程池...")
        executor.shutdown(wait=True)
        io_executor.shutdown(wait=True)
        api_executor.shutdown(wait=True)
        logger.info("JM Bot 已退出")
