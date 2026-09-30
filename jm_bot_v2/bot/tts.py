"""TTS 模块 — 引擎抽象 + Vocu 实现（主）+ 硅基流动实现（备选）

设计稿：docs/TTS_DESIGN.md
- synthesize(text, role_id) -> 音频文件路径（失败返回 None，上层回退发文本）
- Vocu 引擎：同步 .mp3 直出（需付费计划）→ 403 TTS_PAID_ONLY 自动降级异步任务轮询（免费计划可用）
- 硅基流动引擎：POST /v1/audio/speech，OpenAI 兼容
- 文本预处理：过滤 emoji/[]表情/Markdown 符号，截断 max_chars
"""
import hashlib
import json
import logging
import os
import re
import time

import requests

from . import config

logger = logging.getLogger("jm_bot.tts")

TTS_CACHE_DIR = os.path.join(config.BASE_DIR, "tts_cache")
TTS_VOICES_FILE = os.path.join(config.BASE_DIR, "tts_voices.json")

VOCU_BASE = "https://v1.vocu.ai"
SILICONFLOW_BASE = "https://api.siliconflow.cn/v1"

# emoji / 符号预处理：QQ [xx] 表情、emoji、Markdown 强调符、@结构
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F000-\U0001F02F"
    "\U00002600-\U000026FF\U0001F900-\U0001F9FF\U00002B00-\U00002BFF"
    "\U0001FA70-\U0001FAFF\U0000FE0F\U000020E3]"
)
_BRACKET_TAG_RE = re.compile(r"\[[^\[\]]{1,12}\]")
_MD_MARK_RE = re.compile(r"[*_`~>#|]+'?")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def preprocess(text: str) -> str:
    """清洗文本用于合成：去 QQ [表情]/emoji/Markdown 符号，压空行，截断 max_chars"""
    text = _BRACKET_TAG_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)
    text = _MD_MARK_RE.sub("", text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    text = text.strip()
    max_chars = config.TTS_MAX_CHARS
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def load_voices() -> dict:
    """读取 tts_voices.json → {int role_id: voice_id}；文件缺失/损坏返回 {}"""
    try:
        with open(TTS_VOICES_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        voices = {}
        for k, v in (data.get("voices") or {}).items():
            vid = (v or {}).get("voice_id") if isinstance(v, dict) else v
            if vid:
                voices[int(k)] = vid
        return voices
    except (FileNotFoundError, json.JSONDecodeError, ValueError, AttributeError):
        return {}


def resolve_voice(role_id: int) -> str:
    """role_id → 音色 ID；未配置的角色回退 default_voice_id，再兜底 config.tts.default_voice_id"""
    voices = load_voices()
    if role_id in voices:
        return voices[role_id]
    try:
        with open(TTS_VOICES_FILE, "r", encoding="utf-8-sig") as f:
            default = json.load(f).get("default_voice_id")
        if default:
            return default
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return config.TTS_DEFAULT_VOICE_ID


def _cache_path(text: str, voice_id: str) -> str:
    key = hashlib.md5(f"{voice_id}|{text}".encode("utf-8")).hexdigest()[:20]
    return os.path.join(TTS_CACHE_DIR, f"{key}.mp3")


def cache_lookup(text: str, voice_id: str):
    """缓存命中返回路径，未命中返回 None"""
    p = _cache_path(text, voice_id)
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return p
    return None


def cache_store(text: str, voice_id: str, audio: bytes) -> str:
    os.makedirs(TTS_CACHE_DIR, exist_ok=True)
    p = _cache_path(text, voice_id)
    tmp = p + ".tmp"
    with open(tmp, "wb") as f:
        f.write(audio)
    os.replace(tmp, p)
    return p


def _post_binary(url, payload, headers, timeout):
    """POST 返回 (ok, bytes_or_err, retryable, status)"""
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as e:
        logger.warning(f"TTS 请求异常: {e}")
        return False, str(e), True, 0
    if resp.status_code == 200:
        return True, resp.content, False, 200
    # 429 限流 / 402 余额类：不重试直接回退；5xx / 网络异常：可重试一次
    retryable = resp.status_code >= 500
    if resp.status_code in (429, 402):
        logger.error(f"TTS 限流/余额不足 HTTP {resp.status_code}: {resp.text[:200]}")
    else:
        logger.warning(f"TTS HTTP {resp.status_code}: {resp.text[:200]}")
    return False, resp.text[:200], retryable, resp.status_code


def _download(url, timeout):
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def _synth_vocu_sync(text: str, voice_id: str):
    """Vocu 同步直出：POST /api/tts/simple-generate（JSON 请求，返回音频字节）
    付费计划专用；403 TTS_PAID_ONLY 时返回 paid_only 信号"""
    headers = {
        "Authorization": f"Bearer {config.TTS_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"voiceId": voice_id, "text": text}
    try:
        resp = requests.post(f"{VOCU_BASE}/api/tts/simple-generate",
                             json=payload, headers=headers, timeout=config.TTS_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as e:
        return None, str(e), True
    if resp.status_code == 200:
        return resp.content, None, False
    if resp.status_code == 403 and "PAID_ONLY" in resp.text:
        return None, "paid_only", False
    if resp.status_code in (429, 402):
        logger.error(f"TTS(Vocu) 限流/余额不足 HTTP {resp.status_code}: {resp.text[:200]}")
        return None, resp.text[:200], False
    logger.warning(f"TTS(Vocu sync) HTTP {resp.status_code}: {resp.text[:200]}")
    return None, resp.text[:200], resp.status_code >= 500


def _synth_vocu_async(text: str, voice_id: str):
    """Vocu 异步任务（免费计划可用）：POST /api/tts/generate → 轮询 → 下载
    返回 (audio_bytes, err, retryable)"""
    headers = {
        "Authorization": f"Bearer {config.TTS_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"contents": [{"type": "text", "voiceId": voice_id, "text": text}]}
    try:
        resp = requests.post(f"{VOCU_BASE}/api/tts/generate",
                             json=payload, headers=headers, timeout=config.TTS_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as e:
        return None, str(e), True
    if resp.status_code != 200:
        logger.warning(f"TTS(Vocu async create) HTTP {resp.status_code}: {resp.text[:200]}")
        return None, resp.text[:200], resp.status_code >= 500
    job = resp.json().get("data") or {}
    job_id = job.get("id") or job.get("taskId") or job.get("jobId")
    if not job_id:
        return None, f"no job id in response: {json.dumps(job)[:200]}", False

    deadline = time.time() + config.TTS_ASYNC_TIMEOUT_SECONDS
    while time.time() < deadline:
        time.sleep(config.TTS_ASYNC_POLL_SECONDS)
        try:
            detail = requests.get(f"{VOCU_BASE}/api/tts/generate/{job_id}",
                                  headers=headers, timeout=config.TTS_TIMEOUT_SECONDS)
        except requests.exceptions.RequestException as e:
            logger.warning(f"TTS(Vocu async poll) 异常: {e}")
            continue
        if detail.status_code != 200:
            logger.warning(f"TTS(Vocu async poll) HTTP {detail.status_code}")
            continue
        info = detail.json().get("data") or {}
        status = info.get("status")
        if status == "generated":
            # 实测 v1.vocu.ai：音频 URL 在 data.metadata.audio（contents[i].audio 同值）
            audio_url = (
                (info.get("metadata") or {}).get("audio")
                or info.get("audio")
                or info.get("audioUrl")
                or info.get("streamUrl")
            )
            if not audio_url:
                return None, f"generated but no audio url: {json.dumps(info)[:200]}", False
            try:
                return _download(audio_url, config.TTS_TIMEOUT_SECONDS), None, False
            except requests.exceptions.RequestException as e:
                return None, f"download failed: {e}", True
        if status == "failed":
            return None, f"job failed: {json.dumps(info)[:200]}", False
    return None, "async timeout", True


def _synth_vocu(text: str, voice_id: str):
    """Vocu：先同步直出，付费计划限制时降级异步轮询；网络/5xx 重试 1 次"""
    for attempt in (1, 2):
        audio, err, retryable = _synth_vocu_sync(text, voice_id)
        if audio:
            return audio, None
        if err == "paid_only":
            logger.info("TTS(Vocu) 免费计划，降级异步任务路径")
            audio, err, retryable = _synth_vocu_async(text, voice_id)
            if audio:
                return audio, None
            if not retryable or attempt == 2:
                return None, err
            continue
        if not retryable or attempt == 2:
            return None, err
        time.sleep(1)
    return None, "unreachable"


def _synth_siliconflow(text: str, voice_id: str):
    """硅基流动：POST /v1/audio/speech，响应为音频二进制；重试 1 次"""
    headers = {
        "Authorization": f"Bearer {config.TTS_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.TTS_MODEL,
        "input": text,
        "voice": voice_id,
        "response_format": "mp3",
    }
    for attempt in (1, 2):
        ok, data, retryable, status = _post_binary(
            f"{SILICONFLOW_BASE}/audio/speech", payload, headers, config.TTS_TIMEOUT_SECONDS)
        if ok:
            return data, None
        if not retryable or attempt == 2:
            return None, str(data)
        time.sleep(1)
    return None, "unreachable"


_ENGINES = {
    "vocu": _synth_vocu,
    "siliconflow": _synth_siliconflow,
}


def synthesize(text: str, role_id: int = 1):
    """合成入口：返回 mp3 文件路径；任何失败返回 None（上层回退发文本）"""
    text = preprocess(text)
    if not text:
        return None
    voice_id = resolve_voice(role_id)
    if not voice_id:
        logger.warning("TTS 未配置音色（tts_voices.json / config.tts.default_voice_id）")
        return None

    cached = cache_lookup(text, voice_id)
    if cached:
        return cached

    engine = _ENGINES.get(config.TTS_ENGINE)
    if engine is None:
        logger.error(f"TTS 未知引擎: {config.TTS_ENGINE}")
        return None
    if not config.TTS_API_KEY:
        logger.warning("TTS 未配置 API Key，跳过合成")
        return None

    audio, err = engine(text, voice_id)
    if not audio:
        logger.warning(f"TTS 合成失败 ({config.TTS_ENGINE}): {err}")
        return None
    return cache_store(text, voice_id, audio)


def check_ffmpeg() -> bool:
    """NapCat 转 silk 依赖 ffmpeg；缺失时启动日志要显眼提示"""
    import shutil
    return shutil.which("ffmpeg") is not None
