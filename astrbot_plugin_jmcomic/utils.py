"""
工具函数 — 从旧 napcat_utils.py 提取
"""
import os
import time
import shutil
import logging

logger = logging.getLogger("astrbot.jmcomic")


def format_size(size_bytes: int) -> str:
    """人类可读的文件大小"""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def get_dir_size(dir_path: str) -> int:
    """递归计算目录大小（字节）"""
    total = 0
    try:
        for dirpath, _, filenames in os.walk(dir_path):
            for f in filenames:
                try:
                    fp = os.path.join(dirpath, f)
                    if os.path.exists(fp):
                        total += os.path.getsize(fp)
                except OSError:
                    pass
    except (FileNotFoundError, PermissionError, OSError):
        pass
    return total


def get_free_space(path: str) -> int:
    """返回磁盘剩余空间（字节），失败返回 -1"""
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return -1


def get_dir_info(dir_path: str) -> tuple:
    """返回 (total_bytes, subdir_count, file_count)"""
    total = 0
    subdirs = 0
    files = 0
    if not os.path.isdir(dir_path):
        return 0, 0, 0
    for entry in os.listdir(dir_path):
        full = os.path.join(dir_path, entry)
        if os.path.isdir(full):
            subdirs += 1
            total += get_dir_size(full)
        elif os.path.isfile(full):
            files += 1
            try:
                total += os.path.getsize(full)
            except OSError:
                pass
    return total, subdirs, files


def clean_old_dirs(base_dir: str, max_age_days: int = 7) -> tuple:
    """删除超过 max_age_days 天未修改的子目录。返回 (removed, freed, errors)"""
    removed = 0
    freed = 0
    errors = []
    now = time.time()
    cutoff = now - max_age_days * 86400.0

    if not os.path.isdir(base_dir):
        return 0, 0, ["目录不存在"]

    for entry in sorted(os.listdir(base_dir)):
        full = os.path.join(base_dir, entry)
        if not os.path.isdir(full):
            continue
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                size = get_dir_size(full)
            except Exception:
                size = 0
            try:
                shutil.rmtree(full, ignore_errors=False)
                removed += 1
                freed += size
                logger.info(f"清理旧目录: {entry} ({format_size(size)})")
            except OSError as e:
                errors.append(f"{entry}: {e}")
                logger.warning(f"清理失败: {entry}: {e}")
    return removed, freed, errors


def find_pdf(album_id: str, pdf_dir: str) -> str | None:
    """查找生成的 PDF，返回路径或 None"""
    pdf_path = os.path.join(pdf_dir, f"{album_id}.pdf")
    if os.path.exists(pdf_path):
        return pdf_path
    return None
