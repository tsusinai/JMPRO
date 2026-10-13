"""
NapCat 正向 WS 桥接 — 连接 NapCat WS Server (3001) 并提交消息到 AstrBot
用法: python napcat_ws_bridge.py
"""
import asyncio
import json
import logging
import sys
import os
import hashlib
import time
import re

import websockets
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [Bridge] %(message)s")
logger = logging.getLogger("napcat_bridge")

# NapCat WS
NAPCAT_TOKEN = os.getenv("NAPCAT_ACCESS_TOKEN", "")
WS_URL = os.getenv("NAPCAT_WS_URL", f"ws://127.0.0.1:3001?access_token={NAPCAT_TOKEN}")
# AstrBot API
ASTRBOT_API = os.getenv("ASTRBOT_API_URL", "http://127.0.0.1:6185")
ASTRBOT_USER = os.getenv("ASTRBOT_USERNAME", "astrbot")
ASTRBOT_PASS = os.getenv("ASTRBOT_PASSWORD", "")

_token = None
_token_expire = 0


def _get_token() -> str:
    global _token, _token_expire
    if _token and time.time() < _token_expire:
        return _token
    try:
        pwd = hashlib.md5(ASTRBOT_PASS.encode()).hexdigest()
        resp = requests.post(
            f"{ASTRBOT_API}/api/auth/login",
            json={"username": ASTRBOT_USER, "password": ASTRBOT_PASS},
            timeout=10,
        )
        data = resp.json()
        _token = data.get("data", {}).get("access_token", "")
        _token_expire = time.time() + 3600
        logger.info("AstrBot login OK")
        return _token
    except Exception as e:
        logger.error(f"Login failed: {e}")
        return ""


async def handle_message(msg: dict):
    """将 OneBot 消息转发到 AstrBot 内置 conversation API"""
    post_type = msg.get("post_type", "")
    if post_type != "message":
        return

    message_type = msg.get("message_type", "")
    if message_type not in ("group", "private"):
        return

    message_array = msg.get("message", [])
    if not message_array and isinstance(msg.get("raw_message"), list):
        message_array = msg.get("raw_message", [])

    # 组装可读摘要用于日志
    raw_parts = []
    if isinstance(message_array, list):
        for d in message_array:
            t = d.get("type", "")
            if t == "text":
                raw_parts.append(d.get("data", {}).get("text", ""))
            elif t == "image":
                raw_parts.append("[图片]")
            elif t == "at":
                raw_parts.append(f"@{d.get('data', {}).get('qq', '')}")
            elif t == "json":
                try:
                    jdata = d.get("data", {}).get("data", "")
                    if isinstance(jdata, str):
                        import json as _json
                        jdata = _json.loads(jdata)
                    if isinstance(jdata, dict):
                        meta = jdata.get("meta", {})
                        detail = meta.get("detail_1", {}) if isinstance(meta, dict) else {}
                        desc = jdata.get("desc", "")
                        title = detail.get("title", "") if isinstance(detail, dict) else ""
                        qqdocurl = detail.get("qqdocurl", "") if isinstance(detail, dict) else ""
                        if title and title != "哔哩哔哩":
                            raw_parts.append(f"[分享]{title}")
                        if desc:
                            raw_parts.append(f" {desc}")
                        if qqdocurl:
                            raw_parts.append(f" {qqdocurl}")
                        else:
                            raw_parts.append("[小程序卡片]")
                    else:
                        raw_parts.append("[小程序卡片]")
                except Exception:
                    raw_parts.append("[小程序卡片]")
            else:
                raw_parts.append(f"[{t}]")
    raw = "".join(raw_parts) if raw_parts else str(message_array)

    # 过滤空消息（输入状态通知等无内容事件）
    if not isinstance(message_array, list) or len(message_array) == 0:
        return
    has_content = any(
        d.get("type") in ("text", "image", "at", "reply", "file", "json")
        for d in message_array
    )
    if not has_content:
        return

    user_id = msg.get("sender", {}).get("user_id", msg.get("user_id", ""))
    group_id = msg.get("group_id", "")
    message_id = msg.get("message_id", 0)
    self_id = msg.get("self_id", "")

    # 给 raw 追加图片 recall 缓存路径提示（帮助 Agent 定位图片文件）
    # 群聊图片 AI 识图：调用 MiMo 生成描述，替换 [图片] 占位符
    image_hints = []
    if isinstance(message_array, list):
        for d in message_array:
            if d.get("type") == "image":
                image_hints.append(d)
    if image_hints:
        import base64 as _b64
        napcat_token = os.getenv("NAPCAT_ACCESS_TOKEN", "")
        for i, img in enumerate(image_hints):
            img_data = img.get("data", {})
            img_url = img_data.get("url", "")
            img_file = img_data.get("file", "")
            try:
                # 先从 NapCat 下载图片
                img_bytes = None
                if img_url and img_url.startswith("http"):
                    r = requests.get(img_url, timeout=10)
                    if r.status_code == 200:
                        img_bytes = r.content
                if not img_bytes and img_file:
                    # 尝试 NapCat get_image API
                    r = requests.post(
                        "http://127.0.0.1:3002/get_image",
                        headers={"Authorization": f"Bearer {napcat_token}"},
                        json={"file": img_file},
                        timeout=10,
                    )
                    if r.status_code == 200:
                        data = r.json()
                        img_path = data.get("data", {}).get("file", "")
                        if img_path:
                            img_bytes = open(img_path, "rb").read()

                if img_bytes:
                    img_b64 = _b64.b64encode(img_bytes).decode()
                    resp = requests.post(
                        "https://api.xiaomimimo.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {os.getenv('XIAOMI_MIMO_API_KEY', '')}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "mimo-v2.5",
                            "messages": [{"role": "user", "content": [
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                                {"type": "text", "text": "用一句话描述这张图（30字以内，格式：风格/类型+主体+关键内容）"}
                            ]}],
                            "max_tokens": 600,
                        },
                        timeout=25,
                    )
                    caption_data = resp.json()
                    choices = caption_data.get("choices", [])
                    first = choices[0] if choices else {}
                    msg = first.get("message", {}) if isinstance(first, dict) else {}
                    caption = msg.get("content", "") if isinstance(msg, dict) else ""
                    if caption:
                        raw = raw.replace("[图片]", f"[图片：{caption.strip()}]", 1)
                        message_array = list(message_array) + [{"type": "text", "data": {"text": f"[图片描述：{caption.strip()}]"}}]
                        # 直接通过 AstrBot platform API 注入 caption 文本到会话
                        try:
                            token = _get_token()
                            if token:
                                requests.post(
                                    f"{ASTRBOT_API}/api/platform/message",
                                    json={
                                        "platform": "onebot", "platform_id": "onebot",
                                        "message": {
                                            "type": "GroupMessage" if group_id else "FriendMessage",
                                            "self_id": str(self_id),
                                            "session_id": str(group_id) if group_id else str(user_id),
                                            "message_id": f"{message_id}_caption",
                                            "group_id": str(group_id) if group_id else "",
                                            "sender": {"user_id": str(user_id), "nickname": str(msg.get("sender", {}).get("nickname", ""))},
                                            "message_str": f"[图片描述] {caption.strip()}",
                                            "message": [{"type": "text", "data": {"text": f"[图片描述] {caption.strip()}"}}],
                                        },
                                    },
                                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                                    timeout=10,
                                )
                        except Exception:
                            pass
                        logger.info(f"[Bridge] 图片识图: {caption[:60]}")
                else:
                    logger.info(f"[Bridge] 图片无URL且本地获取失败: url={bool(img_url)} file={bool(img_file)}")
            except Exception as e:
                logger.info(f"[Bridge] 图片识图异常: {e!r:.80}")
    if image_hints and group_id:
        recall_root = r"C:\Users\a'su's\.astrbot\data\plugin_data\astrbot_plugin_private_companion\recall_message_images"
        recall_dir = f"{recall_root}\\group_{group_id}"
        hint = f"\n[系统提示：本条消息包含{len(image_hints)}张图片，已缓存在 {recall_dir} 目录，可按时间戳排序用 astrbot_file_read_tool 读取最新的 jpg 文件]"
        raw = raw + hint

    # 桥接只做识图+卡片，消息转发由 NapCat→AstrBot WS 直连处理
    logger.info(f"[{message_type}] g={group_id} u={user_id}: {str(raw)[:80]}")
    return

    # 检测 Bilibili 小程序卡片，直接通过 AstrBot 对话 API 注入文本
    json_texts = []
    if isinstance(message_array, list):
        for d in message_array:
            if d.get("type") == "json":
                try:
                    import json as _json
                    jdata = d.get("data", {}).get("data", "")
                    if isinstance(jdata, str):
                        jdata = _json.loads(jdata)
                    if isinstance(jdata, dict):
                        meta = jdata.get("meta", {}) or {}
                        detail = meta.get("detail_1", {}) or {}
                        title = detail.get("title", "")
                        desc = detail.get("desc", "") or jdata.get("desc", "")
                        qqdocurl = detail.get("qqdocurl", "") or jdata.get("qqdocurl", "")
                        text_parts = []
                        if title:
                            text_parts.append(f"[B站分享]{title}")
                        if desc:
                            text_parts.append(f" - {desc}")
                        if qqdocurl:
                            text_parts.append(f"\n链接: {qqdocurl}")
                        if text_parts:
                            json_texts.append("".join(text_parts))
                except Exception:
                    pass

    # 小程序卡片：提取文本后走平台消息 API（正常消息通道，会触发回复）
    if json_texts:
        token = _get_token()
        session_id = str(group_id) if group_id else str(user_id)
        for t in json_texts:
            try:
                raw_msg_copy = msg.copy()
                raw_msg_copy["message"] = [{"type": "text", "data": {"text": t}}]
                payload = {
                    "platform": "onebot",
                    "platform_id": "onebot",
                    "message": {
                        "type": "GroupMessage" if group_id else "FriendMessage",
                        "self_id": str(self_id),
                        "session_id": session_id,
                        "message_id": str(message_id),
                        "group_id": str(group_id) if group_id else "",
                        "sender": {
                            "user_id": str(user_id),
                            "nickname": str(msg.get("sender", {}).get("nickname", "")),
                        },
                        "raw_message": raw_msg_copy,
                        "message_str": t,
                        "message": [{"type": "text", "data": {"text": t}}],
                    },
                }
                resp = requests.post(
                    f"{ASTRBOT_API}/api/platform/message",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    timeout=10,
                )
                logger.info(f"[Bridge] 小程序卡片→文本消息已发送: status={resp.status_code} text={t[:80]}")
            except Exception as e:
                logger.error(f"[Bridge] 小程序卡片发送失败: {e}")
        return

    # 非 JSON 消息或没有提取到内容，正常转发
    enriched_array = list(message_array) if isinstance(message_array, list) else [{"type": "text", "data": {"text": str(raw)}}]
    raw_msg_copy = msg

    logger.info(f"[{message_type}] g={group_id} u={user_id}: {str(raw)[:80]}")

    # 通过 AstrBot HTTP API 提交消息
    token = _get_token()
    if not token:
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # 构造 AstrBot 格式的消息
    payload = {
        "platform": "onebot",
        "platform_id": "onebot",
        "message": {
            "type": "GroupMessage" if group_id else "FriendMessage",
            "self_id": str(self_id),
            "session_id": str(group_id) if group_id else str(user_id),
            "message_id": str(message_id),
            "group_id": str(group_id) if group_id else "",
            "sender": {
                "user_id": str(user_id),
                "nickname": str(msg.get("sender", {}).get("nickname", "")),
            },
            "raw_message": raw_msg_copy,
            "message_str": str(raw),
            "message": enriched_array if enriched_array
                       else [{"type": "text", "data": {"text": str(raw)}}],
        },
    }

    try:
        resp = requests.post(
            f"{ASTRBOT_API}/api/platform/message",
            json=payload,
            headers=headers,
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(f"Send failed: {resp.status_code} {resp.text[:100]}")
    except Exception as e:
        logger.error(f"Send error: {e}")


async def main():
    while True:
        try:
            async with websockets.connect(WS_URL, max_size=2**26) as ws:
                logger.info(f"Connected to NapCat WS")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        asyncio.create_task(handle_message(msg))
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            logger.error(f"WS disconnected: {e}, retry in 5s...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
