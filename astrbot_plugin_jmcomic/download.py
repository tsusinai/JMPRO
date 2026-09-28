"""
JM 漫画异步下载引擎
基于 jmcomic，通过 asyncio.to_thread 在线程池中运行同步下载逻辑，
进度通过 queue.Queue（线程安全）桥接回异步事件循环。
"""
import os
import re
import io
import time
import queue
import asyncio
import logging
import threading
from contextlib import redirect_stderr

# SSL 证书修复
import certifi
ca_bundle = certifi.where()
os.environ["SSL_CERT_FILE"] = ca_bundle
os.environ["REQUESTS_CA_BUNDLE"] = ca_bundle

# 检测代理可用性（Windows SSH 反向隧道 → GoodbyeDPI）
_PROXY_HOST = os.environ.get("JM_PROXY_HOST", "127.0.0.1")
_PROXY_PORT = int(os.environ.get("JM_PROXY_PORT", "8888"))
_PROXY_URL = f"http://{_PROXY_HOST}:{_PROXY_PORT}"


def _check_proxy() -> bool:
    """检测代理是否可用（快速 TCP 连接测试）"""
    import socket
    try:
        s = socket.create_connection((_PROXY_HOST, _PROXY_PORT), timeout=2)
        s.close()
        return True
    except Exception:
        return False


if _check_proxy():
    os.environ["HTTP_PROXY"] = _PROXY_URL
    os.environ["HTTPS_PROXY"] = _PROXY_URL
    os.environ["NO_PROXY"] = "127.0.0.1,localhost,127.0.0.0/8"
    os.environ["no_proxy"] = "127.0.0.1,localhost,127.0.0.0/8"
    _PROXY_ENABLED = True
else:
    _PROXY_ENABLED = False

import jmcomic  # noqa: E402
from jmcomic import Feature  # noqa: E402

jmcomic.disable_jm_log()

# 禁止 jmcomic 内部 logger 传播到 AstrBot（避免 topic/keyword 字段冲突）
for _name in ("jmcomic", "commonx", "curl_cffi"):
    _l = logging.getLogger(_name)
    _l.handlers = []
    _l.propagate = False

logger = logging.getLogger("jmcomic")
logger.propagate = False
# 使用简单格式，避免 AstrBot 自定义字段冲突
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s [JM] %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.WARNING)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OPTION_FILE = os.path.join(SCRIPT_DIR, "option.yml")


# ═══════════════════════════════════════════
# 辅助函数 — 进度条 / ETA / 文件查找
# ═══════════════════════════════════════════

def _format_progress_bar(completed: int, total: int, width: int = 10) -> str:
    """格式化进度条 [████░░░░]"""
    if total <= 0:
        return "[" + "░" * width + "]"
    done = max(0, min(completed, total))
    pct = done / total
    filled = round(pct * width)
    filled = max(0, min(filled, width))
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def _format_eta(done: int, total: int, speed: float, bytes_downloaded: int = 0) -> str:
    """格式化预计剩余时间"""
    if speed <= 0 or total <= 0 or done >= total:
        return ""
    try:
        # 用平均图片大小估算剩余量
        remaining = total - done
        if done > 0 and bytes_downloaded > 0:
            avg_size = bytes_downloaded / done
            eta_seconds = int(avg_size * remaining / speed)
        else:
            return ""
        if eta_seconds <= 0:
            return ""
        if eta_seconds < 60:
            return f" | ⏱ 约 {eta_seconds}s"
        elif eta_seconds < 3600:
            return f" | ⏱ 约 {eta_seconds // 60}min"
        else:
            h = eta_seconds // 3600
            m = (eta_seconds % 3600) // 60
            return f" | ⏱ 约 {h}h{m}min"
    except Exception:
        return ""


def find_album_dir(base_dir: str, album_id: str) -> str:
    """在 base_dir 下查找 album_id 对应的下载目录"""
    if not os.path.isdir(base_dir):
        return base_dir
    pattern = re.compile(rf"(?<!\d){re.escape(album_id)}(?!\d)")
    for entry in os.listdir(base_dir):
        full = os.path.join(base_dir, entry)
        if not os.path.isdir(full):
            continue
        if entry == album_id or entry.startswith(f"[JM{album_id}]"):
            return full
    for entry in os.listdir(base_dir):
        full = os.path.join(base_dir, entry)
        if os.path.isdir(full) and pattern.search(entry):
            return full
    dirs = []
    for entry in os.listdir(base_dir):
        full = os.path.join(base_dir, entry)
        if os.path.isdir(full):
            dirs.append((os.path.getmtime(full), full))
    dirs.sort(reverse=True)
    if dirs:
        return dirs[0][1]
    return base_dir


def _count_downloaded_files(album_id: str, base_dir: str, result: dict):
    """从已下载目录统计文件数和总大小"""
    try:
        album_dir = find_album_dir(base_dir, album_id)
        if os.path.isdir(album_dir):
            total_size = 0
            for root, dirs, files in os.walk(album_dir):
                result["photo_count"] += len(dirs)
                for f in files:
                    if not f.endswith(".yml"):
                        result["image_count"] += 1
                    fp = os.path.join(root, f)
                    if os.path.exists(fp):
                        total_size += os.path.getsize(fp)
            result["total_size"] = total_size
            result["total_size_str"] = _format_size_static(total_size)
    except Exception:
        pass


def _format_size_static(size_bytes: int) -> str:
    """人类可读文件大小（同步版，供线程内使用）"""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ═══════════════════════════════════════════
# 代理可达性检查
# ═══════════════════════════════════════════

def is_proxy_available() -> bool:
    """检查代理是否当前可用"""
    return _PROXY_ENABLED and _check_proxy()


def _raise_if_not_reachable():
    """如果 JMComic 不可达则抛出明确错误"""
    if not _PROXY_ENABLED:
        raise RuntimeError(
            "JMComic 网络不可达。需要 Windows 本机运行代理："
            "python jm_proxy.py，然后 ssh -R 8888:127.0.0.1:8888 jmbot"
        )
    if not _check_proxy():
        raise RuntimeError(
            "JMComic 代理已断开。请在 Windows 本机重新建立 SSH 隧道："
            "ssh -R 8888:127.0.0.1:8888 jmbot"
        )


# ═══════════════════════════════════════════
# 异步 API 调用 — 通过 asyncio.to_thread 桥接 jmcomic
# ═══════════════════════════════════════════

async def _build_option():
    """构建 jmcomic 配置（在 OS 线程中，因为涉及文件 I/O）"""
    def _inner():
        if os.path.exists(OPTION_FILE):
            return jmcomic.create_option_by_file(OPTION_FILE)
        return jmcomic.JmOption.default()
    return await asyncio.to_thread(_inner)


async def _build_client():
    """构建 jmcomic 客户端"""
    option = await _build_option()
    return await asyncio.to_thread(option.build_jm_client)


def _get(d, key, default=None):
    """安全取值：兼容 dict 和对象"""
    if isinstance(d, dict):
        return d.get(key, default)
    return getattr(d, key, default)


def _get_id(item):
    """安全取 id：兼容 dict、对象、tuple"""
    if isinstance(item, tuple):
        return str(item[0])
    if isinstance(item, dict):
        return str(item.get("aid", item.get("id", "")))
    return str(getattr(item, "aid", getattr(item, "id", "")))


def _get_name(item):
    if isinstance(item, tuple):
        return item[1] if len(item) > 1 else ""
    if isinstance(item, dict):
        return item.get("name", "")
    return getattr(item, "name", "")


def _get_author(item):
    if isinstance(item, tuple):
        return item[2] if len(item) > 2 else "未知"
    if isinstance(item, dict):
        return item.get("author", "未知")
    return getattr(item, "author", "未知")


async def _album_info(album_id: str) -> dict | None:
    """获取漫画详情（异步包装）"""
    _raise_if_not_reachable()
    def _inner():
        client = jmcomic.JmOption.default().build_jm_client()
        detail = client.get_album_detail(album_id)
        # jmcomic 2.7.1: JmAlbumDetail 对象
        # photo_count = len(episode_list) 即章节数
        photo_count = 0
        try:
            photo_count = len(detail.episode_list) if hasattr(detail, 'episode_list') and detail.episode_list else len(detail)
        except:
            pass
        return {
            "id": str(album_id),
            "name": getattr(detail, "name", "") or getattr(detail, "title", "") or "",
            "author": getattr(detail, "author", "") or "未知",
            "authors": ", ".join(getattr(detail, "authors", []) or []) or getattr(detail, "author", "") or "未知",
            "tags": list(getattr(detail, "tags", []) or []),
            "pages": getattr(detail, "page_count", 0) or 0,
            "photo_count": photo_count,
            "likes": getattr(detail, "likes", 0) or 0,
            "views": getattr(detail, "views", 0) or 0,
            "related_list": [
                {"id": _get_id(r), "name": _get_name(r), "author": _get_author(r)}
                for r in (getattr(detail, "related_list", []) or [])[:5]
            ],
        }
    try:
        return await asyncio.to_thread(_inner)
    except Exception as e:
        logger.warning(f"_album_info({album_id}) 失败: {e}")
        return None


async def _search_site(query: str, page: int = 1) -> list[dict]:
    """搜索漫画（异步包装）"""
    _raise_if_not_reachable()
    def _inner():
        client = jmcomic.JmOption.default().build_jm_client()
        search_page = list(client.search_site(query, page=page))
        results = []
        for item in search_page[:5]:
            results.append({
                "id": _get_id(item),
                "name": _get_name(item) or "",
                "author": _get_author(item),
            })
        return results
    try:
        return await asyncio.to_thread(_inner)
    except Exception as e:
        logger.warning(f"_search_site({query}) 失败: {e}")
        return []


async def _rank_site(period: str = "day") -> list[dict]:
    """获取排行榜（异步包装）"""
    _raise_if_not_reachable()
    def _inner():
        client = jmcomic.JmOption.default().build_jm_client()
        rank_methods = {"day": client.day_ranking, "week": client.week_ranking, "month": client.month_ranking}
        rank_fn = rank_methods.get(period, client.day_ranking)
        data = rank_fn(page=1)
        results = []
        for item in list(data)[:10]:
            results.append({
                "id": _get_id(item),
                "name": _get_name(item) or "",
                "author": _get_author(item),
            })
        return results
    try:
        return await asyncio.to_thread(_inner)
    except Exception as e:
        logger.warning(f"_rank_site({period}) 失败: {e}")
        return []


async def _random_manga(mode: str = "", tag: str = "") -> list[dict]:
    """随机推荐（异步包装）"""
    _raise_if_not_reachable()
    def _inner():
        client = jmcomic.JmOption.default().build_jm_client()
        results = []
        import random
        if tag:
            search_page = client.search_site(f"+{tag}", page=1)
            candidates = list(search_page)[:20]
            if len(candidates) > 3:
                candidates = random.sample(candidates, min(3, len(candidates)))
            for item in candidates[:3]:
                results.append({
                    "id": _get_id(item),
                    "name": _get_name(item) or "",
                    "author": _get_author(item),
                    "tags": (lambda x: list(x) if isinstance(x, (list, tuple)) else [str(x)])(_get(item, "tags", [])) if not isinstance(item, tuple) else [],
                    "pages": _get(item, "page_count", 0) if not isinstance(item, tuple) else 0,
                    "photo_count": _get(item, "photo_count", 0) if not isinstance(item, tuple) else 0,
                })
        else:
            period = {"top": "day", "best": "day", "new": "day"}.get(mode, random.choice(["day", "week", "month"]))
            page = random.randint(1, 5)
            rank_methods = {"day": client.day_ranking, "week": client.week_ranking, "month": client.month_ranking}
            rank_fn = rank_methods.get(period, client.day_ranking)
            data = rank_fn(page=page)
            candidates = list(data)
            if len(candidates) > 3:
                candidates = random.sample(candidates, min(3, len(candidates)))
            for item in candidates[:3]:
                results.append({
                    "id": _get_id(item),
                    "name": _get_name(item) or "",
                    "author": _get_author(item),
                    "tags": (lambda x: list(x) if isinstance(x, (list, tuple)) else [str(x)])(_get(item, "tags", [])) if not isinstance(item, tuple) else [],
                    "pages": _get(item, "page_count", 0) if not isinstance(item, tuple) else 0,
                    "photo_count": _get(item, "photo_count", 0) if not isinstance(item, tuple) else 0,
                })
        return results
    try:
        return await asyncio.to_thread(_inner)
    except Exception as e:
        logger.warning(f"_random_manga 失败: {e}")
        return []


# ═══════════════════════════════════════════
# ProgressDownloader — 在线程中运行的同步下载器
# ═══════════════════════════════════════════

class ProgressDownloader(jmcomic.JmDownloader):
    """自定义下载器：进度回调 + 卡死检测 + CDN切换 + 取消检查"""

    REQUEST_DELAY = 0.1
    STALL_SECONDS = 20
    MAX_STALL_TIME = 180
    MAX_DOMAIN_SWITCHES = 3
    FIRST_IMAGE_TIMEOUT = 300

    def __init__(self, option, progress_callback=None, cancel_check=None):
        super().__init__(option)
        self._progress_callback = progress_callback
        self._cancel_check = cancel_check
        self._cancelled = False
        self._completed = 0
        self._total = 0
        self._image_completed = 0
        self._image_total = 0
        self._has_api_image_count = False
        self._thread_local = threading.local()
        self._counter_lock = threading.Lock()
        self._start_time = 0.0
        self._bytes_downloaded = 0
        self._speed = 0.0
        self._current_photo_name = ""
        self._last_image_time = 0.0
        self._stall_start = 0.0
        self._domain_switches = 0
        self._switched_domains = set()

    def before_album(self, album):
        self._total = len(album)
        self._image_total = album.page_count or 0
        self._has_api_image_count = self._image_total > 0
        self._start_time = time.time()
        self._bytes_downloaded = 0
        self._last_image_time = time.time()
        self._stall_start = 0.0
        self._domain_switches = 0
        self._switched_domains.clear()
        logger.info(f"开始下载: 共 {self._total} 章, {self._image_total} 张图片")
        if self._progress_callback:
            self._progress_callback(0, self._total, "准备中", 0, self._image_total, 0.0, 0, 0)
        super().before_album(album)

    def before_photo(self, photo):
        if not self._has_api_image_count:
            try:
                self._image_total += len(photo)
            except Exception:
                pass
        self._current_photo_name = photo.name or ""
        super().before_photo(photo)

    def before_image(self, image, img_save_path):
        if self._cancel_check and self._cancel_check():
            self._cancelled = True
            image.skip = True
            return

        if not (image.cache and image.exists):
            now = time.time()
            last = getattr(self._thread_local, "last_request_time", 0.0)
            gap = self.REQUEST_DELAY - (now - last)
            if gap > 0:
                time.sleep(gap)
            self._thread_local.last_request_time = time.time()

        now = time.time()
        gap = now - self._last_image_time
        if self._image_completed == 0 and gap > self.FIRST_IMAGE_TIMEOUT:
            raise RuntimeError("5 分钟未下载到任何图片，CDN 可能不可达，请稍后重试")
        if gap > self.STALL_SECONDS:
            if self._stall_start == 0:
                self._stall_start = now
            total_stall = now - self._stall_start
            if self._domain_switches < self.MAX_DOMAIN_SWITCHES and total_stall <= self.MAX_STALL_TIME:
                self._switch_domain(image)
                self._domain_switches += 1
                self._last_image_time = now
                logger.warning(
                    f"下载卡死: {gap:.0f}s 无进度，切换 CDN (第{self._domain_switches}次)"
                )
            if total_stall > self.MAX_STALL_TIME:
                raise RuntimeError(
                    f"下载长时间无响应（>3分钟），已切换{self._domain_switches}次服务器均失败"
                )

        super().before_image(image, img_save_path)

    def after_image(self, image, img_save_path):
        with self._counter_lock:
            self._image_completed += 1
            try:
                if os.path.exists(img_save_path):
                    self._bytes_downloaded += os.path.getsize(img_save_path)
            except OSError:
                pass
            elapsed = time.time() - self._start_time
            self._speed = self._bytes_downloaded / elapsed if elapsed > 0 else 0.0
            self._last_image_time = time.time()
            self._stall_start = 0.0
        if self._progress_callback:
            self._progress_callback(
                self._completed, self._total, self._current_photo_name,
                self._image_completed, self._image_total,
                self._speed, self._bytes_downloaded, self._domain_switches,
            )
        super().after_image(image, img_save_path)

    def after_photo(self, photo):
        self._completed += 1
        if self._progress_callback:
            self._progress_callback(
                self._completed, self._total, photo.name,
                self._image_completed, self._image_total,
                self._speed, self._bytes_downloaded, self._domain_switches,
            )
        super().after_photo(photo)

    def _switch_domain(self, image):
        from jmcomic import JmModuleConfig
        current_url = image.img_url
        all_domains = list(JmModuleConfig.DOMAIN_IMAGE_LIST)
        candidates = [d for d in all_domains if d not in self._switched_domains]
        if not candidates:
            recent = list(self._switched_domains)[-2:]
            candidates = [d for d in all_domains if d not in recent]
        if not candidates:
            return
        new_domain = candidates[0]
        new_url = re.sub(r"https?://[^/]+/", f"https://{new_domain}/", current_url)
        image.img_url = new_url
        self._switched_domains.add(new_domain)


# ═══════════════════════════════════════════
# 异步下载主函数
# ═══════════════════════════════════════════

async def download_single(
    album_id: str,
    fmt: str = "pdf",
    state=None,
) -> dict:
    """
    异步下载单个漫画。
    核心下载通过 asyncio.to_thread 在线程池中运行 jmcomic，
    进度通过 queue.Queue（线程安全）桥接回异步事件循环。

    返回: {status, title, author, photo_count, image_count,
           total_size, total_size_str, pdf_path, output_path,
           error, retry_count, failed_images, error_type}
    """
    result = {
        "status": "fail",
        "album_id": album_id,
        "title": "",
        "author": "",
        "photo_count": 0,
        "image_count": 0,
        "total_size": 0,
        "total_size_str": "",
        "pdf_path": None,
        "output_path": None,
        "error": None,
        "retry_count": 0,
        "failed_images": 0,
        "_expected_total": 0,
        "error_type": "",
    }

    # 线程安全队列：同步线程 → 异步事件循环
    _progress_queue: queue.Queue = queue.Queue()

    def _progress_callback(completed, total, photo_name, image_completed, image_total, speed, bytes_downloaded, domain_switches):
        """在下载线程中调用，放入线程安全队列"""
        _progress_queue.put({
            "completed": completed, "total": total,
            "photo_name": photo_name,
            "image_completed": image_completed,
            "image_total": image_total,
            "speed": speed / 1024 if speed > 0 else 0.0,  # B/s → KB/s
            "bytes_downloaded": bytes_downloaded,
            "domain_switches": domain_switches,
        })

    def _cancel_check():
        """检查是否被用户取消"""
        if state and state.is_stop_requested(album_id):
            return True
        return False

    # 后台异步任务：消费线程安全队列 → 更新 state
    async def _sync_progress():
        while True:
            try:
                p = await asyncio.to_thread(_progress_queue.get, timeout=1.0)
                if p is None:
                    break
                if state:
                    await state.update_progress(album_id, **p)
            except queue.Empty:
                continue
            except Exception:
                break

    progress_task = asyncio.create_task(_sync_progress())

    # 核心下载逻辑（在线程池中运行）
    def _run():
        nonlocal result

        _raise_if_not_reachable()

        if _cancel_check():
            result["status"] = "cancelled"
            result["error"] = "用户取消了下载"
            return

        if os.path.exists(OPTION_FILE):
            option = jmcomic.create_option_by_file(OPTION_FILE)
        else:
            option = jmcomic.JmOption.default()

        # PDF/ZIP 由 option.yml 的 plugins 配置驱动，不再用 Feature 系统
        extra = None

        # 预取元数据
        if _cancel_check():
            result["status"] = "cancelled"
            result["error"] = "用户取消了下载"
            return

        try:
            detail = option.build_jm_client().get_album_detail(album_id)
            result["title"] = detail.name or ""
            result["author"] = getattr(detail, "author", "") or "未知"
            result["_expected_total"] = getattr(detail, "page_count", 0) or 0
        except Exception:
            pass

        if _cancel_check():
            result["status"] = "cancelled"
            result["error"] = "用户取消了下载"
            return

        # 构建带有进度/取消回调的下载器
        downloader_cls = lambda opt: ProgressDownloader(
            opt,
            progress_callback=_progress_callback,
            cancel_check=_cancel_check,
        )

        downloader = None
        _retry_count = 0

        for attempt in range(2):  # 最多 1 次重试
            if _cancel_check():
                result["status"] = "cancelled"
                result["error"] = "用户取消了下载"
                return

            try:
                album, downloader = jmcomic.download_album(
                    album_id, option,
                    downloader=downloader_cls,
                    extra=extra,
                )
            except jmcomic.MissingAlbumPhotoException:
                result["error_type"] = "not_found"
                result["error"] = f"漫画 {album_id} 不存在或已下架"
                return
            except jmcomic.PartialDownloadFailedException:
                _retry_count += 1
                if attempt == 0:
                    result["retry_count"] = _retry_count
                    logger.info(f"重试下载 {album_id} (第 {_retry_count} 次)...")
                    time.sleep(3)
                    continue
                else:
                    result["status"] = "partial"
                    result["error_type"] = "cdn_partial"
                    result["error"] = "CDN 服务器不稳定，部分图片下载失败"
            except RuntimeError as e:
                result["error_type"] = "cdn_down"
                result["error"] = str(e)
                return
            except Exception as e:
                if attempt == 0:
                    _retry_count += 1
                    result["retry_count"] = _retry_count
                    logger.warning(f"下载异常，重试 {album_id}: {e}")
                    time.sleep(3)
                    continue
                result["error_type"] = "unknown"
                result["error"] = str(e)
                return
            else:
                break  # 成功

        if getattr(downloader, "_cancelled", False):
            result["status"] = "cancelled"
            result["error"] = "用户取消了下载"
            return

        if result["status"] == "partial":
            pass  # 已在 retry 耗尽分支设置
        elif result["status"] != "cancelled":
            result["status"] = "ok"

        # 填充结果
        result["title"] = getattr(album, "title", None) or result["title"]
        result["author"] = getattr(album, "author", None) or result["author"] or "未知"
        try:
            result["photo_count"] = len(album)
        except Exception:
            result["photo_count"] = 0

        base_dir = option.dir_rule.decide_album_root_dir(album)
        _count_downloaded_files(album_id, base_dir, result)

        if downloader and result["status"] == "ok":
            result["failed_images"] = max(0, result["_expected_total"] - result["image_count"]) if result["_expected_total"] > 0 else 0

        # 定位/生成输出文件
        if fmt == "zip":
            zip_path = os.path.join(SCRIPT_DIR, "zips", f"{album_id}.zip")
            if os.path.exists(zip_path):
                result["output_path"] = zip_path
        else:
            pdf_path = os.path.join(SCRIPT_DIR, "pdfs", f"{album_id}.pdf")
            if os.path.exists(pdf_path):
                result["pdf_path"] = pdf_path
                result["output_path"] = pdf_path
            else:
                # Feature.export_pdf 可能未生效，手动用 img2pdf 生成
                try:
                    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
                    images = sorted(
                        [os.path.join(root, f) for root, _, files in os.walk(base_dir)
                         for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))],
                        key=lambda x: (os.path.basename(os.path.dirname(x)), os.path.basename(x)),
                    )
                    if images:
                        import img2pdf
                        with open(pdf_path, "wb") as pf:
                            pf.write(img2pdf.convert(images))
                        result["pdf_path"] = pdf_path
                        result["output_path"] = pdf_path
                        result["total_size"] = os.path.getsize(pdf_path)
                        size_bytes = result["total_size"]
                        if size_bytes >= 1 << 30:
                            result["total_size_str"] = f"{size_bytes / (1 << 30):.1f} GB"
                        elif size_bytes >= 1 << 20:
                            result["total_size_str"] = f"{size_bytes / (1 << 20):.1f} MB"
                        elif size_bytes >= 1 << 10:
                            result["total_size_str"] = f"{size_bytes / (1 << 10):.1f} KB"
                        else:
                            result["total_size_str"] = f"{size_bytes} B"
                        logger.info(f"手动 img2pdf 生成: {pdf_path} ({len(images)} 张, {result['total_size_str']})")
                except Exception as e:
                    logger.warning(f"手动 img2pdf 失败: {e}")

    try:
        await asyncio.to_thread(_run)
    except Exception as e:
        result["status"] = "fail"
        result["error_type"] = "unknown"
        result["error"] = str(e)

    # 信号：停止进度同步
    _progress_queue.put(None)
    progress_task.cancel()
    try:
        await progress_task
    except asyncio.CancelledError:
        pass

    return result
