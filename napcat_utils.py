"""
NapCat 共享工具模块
- NapCat HTTP 通信
- PDF 查找 / 文件上传
- 通用格式化工具
- 缓存管理 / 磁盘工具
"""
import json
import os
import logging
import shutil
import time
from typing import Optional, Tuple

import requests

logger = logging.getLogger("jm_bot")

# === NapCat 配置 ===
NAPCAT_HTTP = os.getenv("NAPCAT_HTTP_URL", "http://127.0.0.1:3002")
NAPCAT_TOKEN = os.getenv("NAPCAT_ACCESS_TOKEN", "")
HEADERS = {
    "Authorization": f"Bearer {NAPCAT_TOKEN}" if NAPCAT_TOKEN else "",
    "Content-Type": "application/json",
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(SCRIPT_DIR, "pdfs")

# 避免 Windows 系统代理劫持 localhost 请求
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

def napcat_post(endpoint: str, payload: dict) -> dict:
    """调用 NapCat HTTP API，确保中文不被转义"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        resp = requests.post(
            f"{NAPCAT_HTTP}/{endpoint}",
            headers=HEADERS,
            data=body,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.JSONDecodeError:
        logger.warning(f"NapCat POST {endpoint} 返回非 JSON: {resp.text[:200]}")
        return {"retcode": -1, "message": "非 JSON 响应"}
    except Exception as e:
        logger.warning(f"NapCat POST {endpoint} 失败: {e}")
        return {"retcode": -1, "message": str(e)}


def find_pdf(album_id: str) -> Optional[str]:
    """查找生成的 PDF，返回路径或 None"""
    pdf_path = os.path.join(PDF_DIR, f"{album_id}.pdf")
    if os.path.exists(pdf_path):
        return pdf_path
    return None


def send_group_msg(group_id: int, text: str) -> bool:
    """发送文本消息到群"""
    data = napcat_post("send_group_msg", {"group_id": group_id, "message": text})
    ok = data.get("retcode") == 0 or data.get("status") == "ok"
    if not ok:
        logger.warning(f"send_group_msg 失败: {text[:50]}... -> {data}")
    return ok


def send_group_reply(group_id: int, text: str, reply_msg_id: int) -> bool:
    """发送引用回复到群"""
    msg = [
        {"type": "reply", "data": {"id": str(reply_msg_id)}},
        {"type": "text", "data": {"text": text}},
    ]
    data = napcat_post("send_group_msg", {"group_id": group_id, "message": msg})
    ok = data.get("retcode") == 0 or data.get("status") == "ok"
    if not ok:
        logger.warning(f"send_group_reply 失败: {text[:50]}... -> {data}")
    return ok


def upload_group_file(group_id: int, file_path: str, file_name: str) -> Tuple[bool, str]:
    """上传文件到 QQ 群，返回 (ok, detail)，带重试"""
    last_error = ""
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{NAPCAT_HTTP}/upload_group_file",
                headers=HEADERS,
                json={"group_id": group_id, "file": file_path, "name": file_name},
                timeout=1800,
            )
            resp.raise_for_status()
            try:
                data = resp.json()
            except requests.exceptions.JSONDecodeError:
                logger.warning(f"NapCat upload 返回非 JSON: {resp.text[:200]}")
                last_error = f"NapCat 异常响应 (HTTP {resp.status_code})"
                continue
            ok = data.get("retcode") == 0 or data.get("status") == "ok"
            detail = "ok" if ok else (data.get("message") or data.get("wording") or str(data))
            if not ok:
                logger.warning(
                    f"上传失败: group={group_id} file={file_name} "
                    f"retcode={data.get('retcode')} msg={data.get('message')} "
                    f"wording={data.get('wording')} raw={json.dumps(data, ensure_ascii=False)[:300]}"
                )
            else:
                logger.info(f"上传成功: group={group_id} file={file_name}")
            return ok, detail
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            logger.warning(f"上传请求异常 (attempt {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    return False, last_error


def upload_private_file(user_id: int, file_path: str, file_name: str) -> Tuple[bool, str]:
    """上传文件到 QQ 私聊，返回 (ok, detail)，带重试"""
    last_error = ""
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{NAPCAT_HTTP}/upload_private_file",
                headers=HEADERS,
                json={"user_id": user_id, "file": file_path, "name": file_name},
                timeout=1800,
            )
            resp.raise_for_status()
            try:
                data = resp.json()
            except requests.exceptions.JSONDecodeError:
                logger.warning(f"NapCat private upload 返回非 JSON: {resp.text[:200]}")
                last_error = f"NapCat 异常响应 (HTTP {resp.status_code})"
                continue
            ok = data.get("retcode") == 0 or data.get("status") == "ok"
            detail = "ok" if ok else (data.get("message") or data.get("wording") or str(data))
            return ok, detail
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    return False, last_error


# === 通用工具 ===

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


# === 缓存管理 / 磁盘工具 ===


def get_free_space(path: str) -> int:
    """返回 path 所在磁盘的剩余空间（字节），失败返回 -1"""
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return -1


def get_dir_info(dir_path: str) -> tuple:
    """
    返回目录统计信息: (total_bytes, subdir_count, file_count)
    目录不存在时返回 (0, 0, 0)
    """
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
    """
    如果日志文件超过 max_mb MB，截断保留最后 keep_kb KB。
    返回 True 表示执行了截断。
    """
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
    """
    删除 base_dir 下超过 max_age_days 天未修改的子目录。
    返回 (removed_count, freed_bytes, errors_list)
    """
    removed = 0
    freed = 0
    errors = []
    now = time.time()
    cutoff = now - max_age_days * 86400.0

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
    import tempfile
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        logger.warning(f"保存 JSON 失败: {path}: {e}")
