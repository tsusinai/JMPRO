"""文件系统 / 磁盘 / JSON 持久化工具"""
import json
import logging
import os
import shutil
import time
from typing import Optional

logger = logging.getLogger("jm_bot")


def format_size(size_bytes: int) -> str:
    """人类可读的文件大小"""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def get_dir_size(dir_path: str) -> int:
    """递归计算目录大小（字节），权限错误等返回 0"""
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
    """返回 path 所在磁盘的剩余空间（字节），失败返回 -1"""
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return -1


def get_dir_info(dir_path: str) -> tuple:
    """返回目录统计信息: (total_bytes, subdir_count, file_count)"""
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


def rotate_log_if_needed(log_path: str, max_mb: int = 10, keep_kb: int = 512) -> bool:
    """日志超过 max_mb MB 时截断，保留最后 keep_kb KB。返回是否执行了截断"""
    try:
        if not os.path.exists(log_path):
            return False
        size = os.path.getsize(log_path)
        max_bytes = max_mb * 1024 * 1024
        if size <= max_bytes:
            return False
        keep_bytes = keep_kb * 1024
        with open(log_path, "rb") as f:
            if size > keep_bytes:
                f.seek(size - keep_bytes)
            # 跳过可能不完整的首行
            f.readline()
            data = f.read()
        with open(log_path, "wb") as f:
            f.write(data)
        logger.info(
            f"日志轮转: {os.path.basename(log_path)} "
            f"({format_size(size)} -> {format_size(len(data))})"
        )
        return True
    except OSError as e:
        logger.warning(f"日志轮转失败: {e}")
        return False


def clean_old_dirs(base_dir: str, max_age_days: int = 7) -> tuple:
    """删除 base_dir 下超过 max_age_days 天未修改的子目录。
    返回 (removed_count, freed_bytes, errors_list)"""
    removed = 0
    freed = 0
    errors = []
    cutoff = time.time() - max_age_days * 86400.0

    if not os.path.isdir(base_dir):
        return 0, 0, ["下载目录不存在"]

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


def find_pdf(pdfs_dir: str, album_id: str) -> Optional[str]:
    """查找生成的 PDF，返回路径或 None"""
    pdf_path = os.path.join(pdfs_dir, f"{album_id}.pdf")
    if os.path.exists(pdf_path):
        return pdf_path
    return None


def load_json(path: str, default=None):
    """从 JSON 文件加载数据，文件不存在或损坏时返回 default"""
    if default is None:
        default = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def save_json(path: str, data):
    """原子写入 JSON 文件（先写临时文件再替换）"""
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        logger.warning(f"保存 JSON 失败: {path}: {e}")
