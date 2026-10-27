"""QQ 空间发表层 — 移植自 Zhalslar/astrbot_plugin_qzone 的 Cookie 方案。

经 NapCat OneBot HTTP get_cookies 现取 user.qzone.qq.com 域 Cookie（TTL 600s 缓存），
算 g_tk 后调网页 CGI emotion_cgi_publish_v6 发纯文本说说。
发表纪律：单次请求、绝不重试；以响应 tid 为准，无 tid 视为未确认（可能已发、状态未知）。
注意：Cookie 是敏感凭证，只在内存中短暂持有，严禁落盘/打日志。
"""

import http.cookies
import json
import logging
import re
import threading
import time
from typing import Any, Dict, Optional

import requests

from . import config
from .napcat import napcat_post

logger = logging.getLogger("jm_bot")

EMOTION_URL = "https://user.qzone.qq.com/proxy/domain/taotao.qzone.qq.com/cgi-bin/emotion_cgi_publish_v6"


def g_tk(p_skey: str) -> str:
    """计算 QQ 空间 g_tk：hash=5381 起迭代 h += (h<<5) + ord(c)，结果 & 0x7FFFFFFF"""
    hash_val = 5381
    for ch in p_skey:
        hash_val += (hash_val << 5) + ord(ch)
    return str(hash_val & 0x7FFFFFFF)


def _parse_cookie_string(raw: str) -> Dict[str, str]:
    """解析 Cookie 字符串：先试 SimpleCookie，关键字段缺失时回退手工 split 解析"""
    result: Dict[str, str] = {}
    try:
        parser = http.cookies.SimpleCookie()
        parser.load(raw)
        for key, morsel in parser.items():
            result[key] = morsel.value
    except Exception:
        result = {}
    if "uin" not in result:
        for part in raw.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                result[k.strip()] = v.strip()
    return result


class QzoneContext:
    def __init__(self, uin: int, skey: str, p_skey: str):
        self.uin = uin
        self.skey = skey
        self.p_skey = p_skey

    @property
    def gtk2(self) -> str:
        return g_tk(self.p_skey)

    def cookies(self) -> Dict[str, str]:
        return {
            "uin": f"o{self.uin}",
            "skey": self.skey,
            "p_skey": self.p_skey,
        }

    def headers(self) -> Dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://user.qzone.qq.com/{self.uin}",
            "Origin": "https://user.qzone.qq.com",
            "Host": "user.qzone.qq.com",
            "Connection": "keep-alive",
        }


class QzoneSession:
    DOMAIN = "user.qzone.qq.com"

    def __init__(self, cookie_ttl: int = 600):
        self.cookie_ttl = cookie_ttl
        self._ctx: Optional[QzoneContext] = None
        self._last_fetch: float = 0.0
        self._lock = threading.Lock()

    def get_ctx(self) -> QzoneContext:
        with self._lock:
            now = time.monotonic()
            if self._ctx is not None and (now - self._last_fetch < self.cookie_ttl):
                return self._ctx

            resp = napcat_post("get_cookies", {"domain": self.DOMAIN})
            data = resp.get("data") if isinstance(resp, dict) else None
            raw_cookies = data.get("cookies", "") if isinstance(data, dict) else ""
            if not raw_cookies:
                raise RuntimeError("get_cookies 未返回可用 Cookie")

            fields = _parse_cookie_string(raw_cookies)
            uin_raw = str(fields.get("uin", "")).lstrip("o")
            if not uin_raw.isdigit() or int(uin_raw) == 0:
                raise RuntimeError("Cookie 中缺少合法 uin 字段")
            uin = int(uin_raw)

            skey = fields.get("skey", "")
            p_skey = fields.get("p_skey", "") or skey  # p_skey 缺失回退 skey（Zhalslar 同口径）
            if not p_skey:
                raise RuntimeError("Cookie 中缺少 p_skey/skey，无法计算 g_tk")

            self._ctx = QzoneContext(uin=uin, skey=skey, p_skey=p_skey)
            self._last_fetch = time.monotonic()
            return self._ctx

    def invalidate(self) -> None:
        with self._lock:
            self._ctx = None
            self._last_fetch = 0.0


class QzoneAPI:
    def __init__(self, session: QzoneSession):
        self.session = session

    def publish(self, text: str) -> Dict[str, Any]:
        """发表纯文本说说。只发单次请求，任何情况不重试；无 tid 视为未确认。"""
        try:
            ctx = self.session.get_ctx()
        except Exception as e:
            logger.error(f"获取空间上下文失败: {e}")
            return {"ok": False, "code": -1, "message": f"Cookie 获取失败: {e}", "tid": None}

        data = {
            "syn_tweet_verson": "1",
            "paramstr": "1",
            "who": "1",
            "con": text,
            "feedversion": "1",
            "ver": "1",
            "ugc_right": "1",
            "to_sign": "0",
            "hostuin": str(ctx.uin),
            "code_version": "1",
            "format": "json",
            "qzreferrer": f"https://user.qzone.qq.com/{ctx.uin}",
        }

        try:
            resp = requests.post(
                EMOTION_URL,
                params={"g_tk": ctx.gtk2, "uin": str(ctx.uin)},
                data=data,
                headers=ctx.headers(),
                cookies=ctx.cookies(),
                timeout=30,
            )
        except requests.RequestException as e:
            logger.error(f"发表空间说说网络请求异常: {e}")
            return {"ok": False, "code": -1, "message": str(e), "tid": None}

        raw_text = resp.text.strip()
        jsonp_match = re.search(r"^\s*[_a-zA-Z0-9]+\s*\((.*)\)\s*;?\s*$", raw_text, re.DOTALL)
        if jsonp_match:
            raw_text = jsonp_match.group(1).strip()

        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError:
            logger.error(f"空间说说响应解析失败: {resp.text[:200]}")
            return {"ok": False, "code": -1, "message": "响应解析失败", "tid": None}

        code = raw.get("code")
        tid = raw.get("tid")
        data_field = raw.get("data")
        if not tid and isinstance(data_field, dict):
            tid = data_field.get("tid")

        message = raw.get("message") or raw.get("msg") or ""
        ok = (code == 0) and bool(tid)

        return {
            "ok": ok,
            "tid": tid if ok else None,
            "code": code,
            "message": message,
        }


_session: Optional[QzoneSession] = None
_api: Optional[QzoneAPI] = None
_singleton_lock = threading.Lock()


def get_api() -> QzoneAPI:
    global _session, _api
    with _singleton_lock:
        if _api is None:
            _session = QzoneSession(cookie_ttl=600)
            _api = QzoneAPI(_session)
        return _api


def publish_post(text: str) -> Dict[str, Any]:
    return get_api().publish(text)
