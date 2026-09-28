"""NapCat OneBot HTTP API 封装（底层，不含角色口吻注入 — 见 messaging.py）"""
import json
import logging
import os
import time
from typing import Tuple

import requests

from . import config

logger = logging.getLogger("jm_bot")

HEADERS = {
    "Authorization": f"Bearer {config.NAPCAT_TOKEN}",
    "Content-Type": "application/json",
}

# 避免 Windows 系统代理劫持 localhost 请求
os.environ["NO_PROXY"] = "localhost,127.0.0.1"


def napcat_post(endpoint: str, payload: dict) -> dict:
    """调用 NapCat HTTP API，确保中文不被转义"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        resp = requests.post(
            f"{config.NAPCAT_HTTP}/{endpoint}",
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


def _upload(endpoint: str, payload: dict, file_name: str) -> Tuple[bool, str]:
    last_error = ""
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{config.NAPCAT_HTTP}/{endpoint}",
                headers=HEADERS,
                json=payload,
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
                    f"上传失败: file={file_name} "
                    f"retcode={data.get('retcode')} msg={data.get('message')} "
                    f"wording={data.get('wording')} raw={json.dumps(data, ensure_ascii=False)[:300]}"
                )
            else:
                logger.info(f"上传成功: file={file_name}")
            return ok, detail
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            logger.warning(f"上传请求异常 (attempt {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    return False, last_error


def upload_group_file(group_id: int, file_path: str, file_name: str) -> Tuple[bool, str]:
    """上传文件到 QQ 群，返回 (ok, detail)，带重试"""
    return _upload(
        "upload_group_file",
        {"group_id": group_id, "file": file_path, "name": file_name},
        file_name,
    )


def upload_private_file(user_id: int, file_path: str, file_name: str) -> Tuple[bool, str]:
    """上传文件到 QQ 私聊，返回 (ok, detail)，带重试"""
    return _upload(
        "upload_private_file",
        {"user_id": user_id, "file": file_path, "name": file_name},
        file_name,
    )
