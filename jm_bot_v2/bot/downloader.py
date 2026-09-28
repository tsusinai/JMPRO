"""JM 漫画下载核心 — 由根目录 download.py 迁移

职责：自定义下载器（进度回调/取消检查/卡死检测/CDN 域名切换）、
单本下载入口 download_single（含部分失败重试）、CLI 下载发送入口。
"""
import io
import logging
import os
import re
import sys
import threading
import time
from contextlib import redirect_stderr

from . import config
from .fsutils import find_pdf, format_size, rotate_log_if_needed
from .napcat import upload_group_file

logger = logging.getLogger("jm_bot")

# 修复 Windows SSL 证书问题
import certifi

ca_bundle = certifi.where()
os.environ["SSL_CERT_FILE"] = ca_bundle
os.environ["REQUESTS_CA_BUNDLE"] = ca_bundle
os.environ["CURL_CA_BUNDLE"] = ca_bundle
try:
    import certifi_win32  # noqa: F401
except ImportError:
    pass

# 确保 jmcomic CLI 路径在 PATH 中（pip 用户安装）
SCRIPTS_DIR = os.path.expandvars(r"%APPDATA%\Python\Python314\Scripts")
if SCRIPTS_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = SCRIPTS_DIR + os.pathsep + os.environ.get("PATH", "")

import jmcomic  # noqa: E402
from jmcomic import Feature  # noqa: E402

# 关掉 jmcomic 调试日志
jmcomic.disable_jm_log()

# 日志轮转阈值
LOG_MAX_MB = 10       # 超过此值触发轮转
LOG_KEEP_KB = 512     # 轮转时保留最后 N KB

# 轻量锁，仅保护日志文件写入（不再锁整个下载过程）
_log_lock = threading.Lock()


def _run_captured(func, *args, **kwargs):
    """在 per-call StringIO 中执行 func，捕获 stderr 返回 (result, stderr_text)"""
    buf = io.StringIO()
    with redirect_stderr(buf):
        result = func(*args, **kwargs)
    return result, buf.getvalue()


class ProgressDownloader(jmcomic.JmDownloader):
    """自定义下载器：每完成一个章节后调用 progress_callback，每次请求前添加延迟"""

    REQUEST_DELAY = 0.1  # 非缓存图片的请求间隔（秒）

    # 卡死检测
    STALL_SECONDS = 20         # 20 秒无新图片完成 → 判定卡死
    MAX_STALL_TIME = 180       # 累计卡死 3 分钟 → 报错放弃
    MAX_DOMAIN_SWITCHES = 3    # 最多切换 3 次 CDN 服务器
    FIRST_IMAGE_TIMEOUT = 300  # 5 分钟无首图 → 判定下载失败

    def __init__(self, option, progress_callback=None, cancel_check=None):
        super().__init__(option)
        self._progress_callback = progress_callback
        self._cancel_check = cancel_check
        self._cancelled = False
        self._completed = 0
        self._total = 0
        self._image_completed = 0
        self._image_total = 0
        self._thread_local = threading.local()  # 每线程独立请求计时
        self._counter_lock = threading.Lock()    # 保护 after_image 计数器
        self._start_time = 0.0
        self._bytes_downloaded = 0
        self._speed = 0.0
        self._current_photo_name = ""
        # 卡死检测状态
        self._last_image_time = 0.0
        self._stall_start = 0.0
        self._domain_switches = 0
        self._switched_domains = set()

    def before_album(self, album):
        self._total = len(album)
        # page_count 可能为 0（JM API 不保证返回），
        # photo.page_arr 此时为 None，不能在 before_album 中遍历 album
        self._image_total = album.page_count or 0
        self._has_api_image_count = self._image_total > 0
        self._start_time = time.time()
        self._bytes_downloaded = 0
        self._last_image_time = time.time()
        self._stall_start = 0.0
        self._domain_switches = 0
        self._switched_domains.clear()
        logger.info(f"开始下载: 共 {self._total} 个章节, {self._image_total} 张图片")
        if self._progress_callback:
            self._progress_callback(0, self._total, "准备中", 0, self._image_total, 0.0, 0, 0)
        super().before_album(album)

    def before_photo(self, photo):
        # 如果 API 未提供 page_count，从已加载的 photo 累加图片数
        # （此时 check_photo 已调用，len(photo) 准确）
        if not self._has_api_image_count:
            try:
                self._image_total += len(photo)
            except Exception:
                pass
        self._current_photo_name = photo.name or ""
        super().before_photo(photo)

    def before_image(self, image, img_save_path):
        # 用户取消检查：标记跳过，不抛异常，让下载器正常结束
        if self._cancel_check and self._cancel_check():
            self._cancelled = True
            image.skip = True
            return
        # 仅对需要实际下载的图片加延迟，缓存命中直接跳过
        # 每线程独立计时，4 线程可真正并发（vs 旧版共享锁串行化）
        if not (image.cache and image.exists):
            now = time.time()
            last = getattr(self._thread_local, 'last_request_time', 0.0)
            gap = self.REQUEST_DELAY - (now - last)
            if gap > 0:
                time.sleep(gap)
            self._thread_local.last_request_time = time.time()

        # 卡死检测：超过 STALL_SECONDS 无新图片完成
        now = time.time()
        gap = now - self._last_image_time
        # 首图超时：5 分钟无任何图片下载 → 直接判定失败
        if self._image_completed == 0 and gap > self.FIRST_IMAGE_TIMEOUT:
            raise RuntimeError(
                f"5 分钟未下载到任何图片，CDN 可能不可达，请稍后重试"
            )
        if gap > self.STALL_SECONDS:
            if self._stall_start == 0:
                self._stall_start = now
            total_stall = now - self._stall_start
            # 尝试切换 CDN 域名
            if self._domain_switches < self.MAX_DOMAIN_SWITCHES and total_stall <= self.MAX_STALL_TIME:
                self._switch_domain(image)
                self._domain_switches += 1
                self._last_image_time = now  # 给新域名一个机会
                logger.warning(
                    f"下载卡死检测: {gap:.0f}s 无进度，切换 CDN "
                    f"(第{self._domain_switches}次，累计卡死{total_stall:.0f}s)"
                )
            # 累计超时则报错
            if total_stall > self.MAX_STALL_TIME:
                raise RuntimeError(
                    f"下载长时间无响应（>3分钟），已切换{self._domain_switches}次服务器均失败，"
                    f"请稍后重试"
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
            self._stall_start = 0.0  # 有进度了，复位卡死计时
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
        logger.info(
            f"进度: {self._completed}/{self._total} 章节, "
            f"{self._image_completed}/{self._image_total} 图片, "
            f"{format_size(int(self._speed))}/s - {photo.name}"
        )
        super().after_photo(photo)

    def _switch_domain(self, image):
        """替换 image.img_url 中的 CDN 域名，换到未尝试过的服务器"""
        from jmcomic import JmModuleConfig
        current_url = image.img_url
        all_domains = list(JmModuleConfig.DOMAIN_IMAGE_LIST)
        # 选一个未尝试过的域名
        candidates = [d for d in all_domains if d not in self._switched_domains]
        if not candidates:
            # 回退：排除最近 2 个失败域名
            recent = list(self._switched_domains)[-2:]
            candidates = [d for d in all_domains if d not in recent]
        if not candidates:
            return
        new_domain = candidates[0]
        new_url = re.sub(r'https?://[^/]+/', f'https://{new_domain}/', current_url)
        image.img_url = new_url
        self._switched_domains.add(new_domain)


def find_album_dir(base_dir: str, album_id: str) -> str:
    """在 base_dir 下查找 album_id 对应的下载目录，使用数字边界匹配避免子串误匹配"""
    if not os.path.isdir(base_dir):
        return base_dir
    # 数字边界匹配：album_id 前后不能是数字，避免 "123" 匹配到 "1234"
    pattern = re.compile(rf"(?<!\d){re.escape(album_id)}(?!\d)")
    # 优先精确匹配（目录名以 [JM{album_id}] 开头或完全等于 album_id）
    for entry in os.listdir(base_dir):
        full = os.path.join(base_dir, entry)
        if not os.path.isdir(full):
            continue
        if entry == album_id or entry.startswith(f"[JM{album_id}]"):
            return full
    # 次选：数字边界匹配
    for entry in os.listdir(base_dir):
        full = os.path.join(base_dir, entry)
        if os.path.isdir(full) and pattern.search(entry):
            return full
    # 回退：返回最近修改的目录（仅在无匹配时）
    dirs = []
    for entry in os.listdir(base_dir):
        full = os.path.join(base_dir, entry)
        if os.path.isdir(full):
            dirs.append((os.path.getmtime(full), full))
    dirs.sort(reverse=True)
    if dirs:
        return dirs[0][1]
    return base_dir


def get_group_id() -> str:
    """获取目标群号：优先 JM_GROUP_ID，其次 CC_SESSION_KEY"""
    gid = os.environ.get("JM_GROUP_ID", "")
    if gid and gid.isdigit():
        return gid
    key = os.environ.get("CC_SESSION_KEY", "")
    if key.startswith("qq:") and key.count(":") == 2:
        return key[3:].split(":")[0]
    return ""


def _count_downloaded_files(album_id, base_dir, result):
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
            result["total_size_str"] = format_size(total_size)
    except Exception:
        pass


def download_single(album_id: str, progress_callback=None, cancel_check=None, output_format: str = "pdf") -> dict:
    """
    下载单个漫画，返回结构化结果 dict:
    {
        "status": "ok" | "partial" | "fail" | "cancelled",
        "album_id": str, "title": str, "author": str,
        "photo_count": int, "image_count": int,
        "total_size": int, "total_size_str": str,
        "pdf_path": str or None, "output_path": str or None,
        "error": str or None,
        "retry_count": int, "failed_images": int, "error_type": str,
    }
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

    _downloader = None
    try:
        os.chdir(config.BASE_DIR)

        if cancel_check and cancel_check():
            result["status"] = "cancelled"
            result["error"] = "用户取消了下载"
            return result

        # 加载配置
        if os.path.exists(config.OPTION_FILE):
            option = jmcomic.create_option_by_file(config.OPTION_FILE)
        else:
            option = jmcomic.JmOption.default()

        # 使用 Feature 系统选择输出格式（替代手动插件操作）
        if output_format == "zip":
            extra = Feature.export_zip(
                zip_dir=config.ZIPS_DIR,
                filename_rule="Aid",
            )
        else:
            extra = Feature.export_pdf(
                pdf_dir=config.PDFS_DIR,
                filename_rule="Aid",
            )

        # 预取元数据（异常时也能提供标题/作者）
        if cancel_check and cancel_check():
            result["status"] = "cancelled"
            result["error"] = "用户取消了下载"
            return result
        try:
            detail = option.build_jm_client().get_album_detail(album_id)
            result["title"] = detail.name or ""
            result["author"] = getattr(detail, "author", "") or "未知"
            result["_expected_total"] = getattr(detail, "page_count", 0) or 0
        except Exception:
            pass

        # 自定义下载器（进度回调 + 取消 + 卡死检测）
        if progress_callback:
            downloader_cls = lambda opt: ProgressDownloader(opt, progress_callback=progress_callback, cancel_check=cancel_check)
        else:
            downloader_cls = None

        if cancel_check and cancel_check():
            result["status"] = "cancelled"
            result["error"] = "用户取消了下载"
            return result

        # 下载（per-call stderr 捕获，无全局锁，支持真并发）
        err_log_path = config.ERROR_LOG_PATH
        (album, _downloader), stderr_text = _run_captured(
            jmcomic.download_album, album_id, option,
            downloader=downloader_cls, extra=extra,
        )
        with _log_lock:
            rotate_log_if_needed(err_log_path, max_mb=LOG_MAX_MB, keep_kb=LOG_KEEP_KB)
            if stderr_text:
                with open(err_log_path, "a", encoding="utf-8") as err_log:
                    err_log.write(stderr_text)

        # 检查取消
        if getattr(_downloader, '_cancelled', False):
            result["status"] = "cancelled"
            result["error"] = "用户取消了下载"
            return result

        # 填充结果
        result["title"] = getattr(album, "title", None) or ""
        result["author"] = getattr(album, "author", None) or "未知"
        try:
            result["photo_count"] = len(album)
        except Exception:
            result["photo_count"] = 0

        base_dir = option.dir_rule.decide_album_root_dir(album)
        _count_downloaded_files(album_id, base_dir, result)

        # 定位输出文件
        if output_format == "zip":
            zip_path = os.path.join(config.ZIPS_DIR, f"{album_id}.zip")
            if os.path.exists(zip_path):
                result["output_path"] = zip_path
            else:
                logger.warning(f"ZIP 未生成: {album_id}，ZipPlugin 可能失败")
        else:
            result["pdf_path"] = find_pdf(config.PDFS_DIR, album_id)
            if not result["pdf_path"]:
                logger.warning(f"PDF 未生成: {album_id}，img2pdf 插件可能失败")

        result["status"] = "ok"

    except jmcomic.MissingAlbumPhotoException:
        result["error_type"] = "not_found"
        result["error"] = f"漫画 {album_id} 不存在或已下架"
    except jmcomic.PartialDownloadFailedException:
        if getattr(_downloader, '_cancelled', False):
            result["status"] = "cancelled"
            result["error"] = "用户取消了下载"
            return result

        # 单次重试（AdvancedRetryPlugin + 内置 request_with_retry 已处理请求级重试，
        #   这里仅处理跨下载会话的残留失败，利用缓存跳过已成功图片）
        first_image_total = result.get("_expected_total", 0)
        if first_image_total == 0 and _downloader is not None:
            first_image_total = getattr(_downloader, "_image_total", 0) or 0
        downloader_cls_retry = (
            lambda opt: ProgressDownloader(opt, progress_callback=progress_callback, cancel_check=cancel_check)
        ) if progress_callback else None

        if cancel_check and cancel_check():
            result["status"] = "cancelled"
            result["error"] = "用户取消了下载"
            return result

        result["retry_count"] = 1
        logger.info(f"重试下载 {album_id} (第 1 次)...")
        time.sleep(3)
        try:
            (album, _downloader), stderr_text = _run_captured(
                jmcomic.download_album, album_id, option,
                downloader=downloader_cls_retry, extra=extra,
            )
            with _log_lock:
                rotate_log_if_needed(err_log_path, max_mb=LOG_MAX_MB, keep_kb=LOG_KEEP_KB)
                if stderr_text:
                    with open(err_log_path, "a", encoding="utf-8") as err_log:
                        err_log.write(stderr_text)
            if getattr(_downloader, '_cancelled', False):
                result["status"] = "cancelled"
                result["error"] = "用户取消了下载"
                return result

            result["title"] = getattr(album, "title", None) or ""
            result["author"] = getattr(album, "author", None) or "未知"
            try:
                result["photo_count"] = len(album)
            except Exception:
                result["photo_count"] = 0
            base_dir = option.dir_rule.decide_album_root_dir(album)
            prev_count = result.get("image_count", 0)
            _count_downloaded_files(album_id, base_dir, result)
            recovered = result["image_count"] - prev_count
            result["status"] = "ok"
            result["failed_images"] = max(0, first_image_total - result["image_count"]) if first_image_total > 0 else 0
            if output_format == "zip":
                zip_path = os.path.join(config.ZIPS_DIR, f"{album_id}.zip")
                if os.path.exists(zip_path):
                    result["output_path"] = zip_path
            else:
                result["pdf_path"] = find_pdf(config.PDFS_DIR, album_id)
            logger.info(f"重试成功 {album_id} (补回 {recovered} 张)")
        except jmcomic.PartialDownloadFailedException:
            if getattr(_downloader, '_cancelled', False):
                result["status"] = "cancelled"
                result["error"] = "用户取消了下载"
                return result

            # 重试也失败 → partial
            result["status"] = "partial"
            result["error_type"] = "cdn_partial"
            result["error"] = "CDN 服务器不稳定，部分图片下载失败"
            if not result["title"]:
                try:
                    client = jmcomic.JmOption.default().build_jm_client()
                    detail = client.get_album_detail(album_id)
                    result["title"] = detail.name or ""
                    result["author"] = getattr(detail, "author", "") or "未知"
                except Exception:
                    pass
            partial_base = option.dir_rule.base_dir
            if not os.path.isabs(partial_base):
                partial_base = os.path.join(config.BASE_DIR, partial_base.lstrip("./\\"))
            prev_count = result.get("image_count", 0)
            _count_downloaded_files(album_id, partial_base, result)
            result["failed_images"] = max(0, first_image_total - result["image_count"]) if first_image_total > 0 else 0
            if output_format == "zip":
                zip_path = os.path.join(config.ZIPS_DIR, f"{album_id}.zip")
                if os.path.exists(zip_path):
                    result["output_path"] = zip_path
            else:
                result["pdf_path"] = find_pdf(config.PDFS_DIR, album_id)
            if result["image_count"] == 0:
                result["status"] = "fail"
                result["error_type"] = "cdn_down"
                result["error"] = "CDN 服务器完全不可用，所有图片下载失败，请稍后重试"
    except Exception as e:
        result["error_type"] = "unknown"
        result["error"] = f"下载过程遇到意外 ({type(e).__name__})，请稍后重试喵~"
        logger.error(f"下载异常 {album_id}: {e}", exc_info=True)

    return result


def download_and_send(album_id: str, group_id: str = "") -> dict:
    """下载漫画并通过 NapCat 发送 PDF/ZIP 到群（CLI / subprocess 使用）"""
    result = download_single(album_id)

    upload_path = result.get("output_path") or result.get("pdf_path")
    if upload_path:
        gid = group_id or get_group_id()
        if gid:
            fname = os.path.basename(upload_path)
            ok, detail = upload_group_file(int(gid), upload_path, fname)
            if ok:
                result["upload_ok"] = True
                result["upload_group"] = gid
            else:
                result["upload_ok"] = False
                result["upload_error"] = detail
        else:
            result["upload_ok"] = False
            result["upload_error"] = "无法获取群号"
    return result


def format_result(result: dict) -> str:
    """将结果 dict 格式化为可读文本"""
    lines = [
        f"=== 下载完成 ===",
        f"ID: {result['album_id']}",
        f"标题: {result['title']}",
        f"作者: {result['author']}",
        f"章节数: {result['photo_count']}",
        f"图片数: {result['image_count']}",
        f"大小: {result['total_size_str']}",
    ]

    if result.get("pdf_path"):
        lines.append(f"PDF: {result['pdf_path']}")
        if result.get("upload_ok"):
            lines.append(f"PDF: 已发送至群 {result['upload_group']}")
        elif result.get("upload_error"):
            lines.append(f"发送失败: {result['upload_error']}")
    elif result.get("output_path"):
        lines.append(f"ZIP: {result['output_path']}")
        if result.get("upload_ok"):
            lines.append(f"ZIP: 已发送至群 {result['upload_group']}")
        elif result.get("upload_error"):
            lines.append(f"发送失败: {result['upload_error']}")
    elif result.get("error"):
        lines.append(f"错误: {result['error']}")

    return "\n".join(lines)


def main():
    os.chdir(config.BASE_DIR)

    if len(sys.argv) < 2:
        print("用法: python -m bot.downloader <漫画ID> [漫画ID ...] [--group <群号>]")
        print("示例: python -m bot.downloader 422866 --group 761064152")
        sys.exit(1)

    # 解析 --group 参数
    group_id = ""
    args = sys.argv[1:]
    if "--group" in args:
        idx = args.index("--group")
        if idx + 1 < len(args):
            group_id = args[idx + 1]
            args = args[:idx] + args[idx + 2:]
    os.environ["JM_GROUP_ID"] = group_id

    album_ids = args

    for aid in album_ids:
        aid = aid.strip()
        if not aid.isdigit():
            print(f"[跳过] '{aid}' 不是有效的漫画ID")
            continue

        result = download_and_send(aid, group_id)
        print(format_result(result))

        if result["status"] == "fail":
            print(f"[失败] {result['error']}")
        elif result["status"] == "partial":
            print(f"[部分成功] {result['error']}")

    if len(album_ids) > 1:
        print("---")
        print(f"全部完成，共处理 {len(album_ids)} 个漫画")


if __name__ == "__main__":
    main()
