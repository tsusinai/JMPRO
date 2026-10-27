"""出站表情装饰模块 — 解析 AI 回复中的 QQ 表情标记 [表情名] 与表情包标记 [[sticker:情绪]]

语义移植自 dafeiyu 的 astrbot_plugin_face_convert（出站关口转换）：
- [表情名] 在 face_map 中才转成 OneBot Face 段；单条上限、会话级同脸冷却，超限连标记一并丢弃
- 字典不认的 [短词] 原样保留
- [[sticker:情绪]] 从 stickers/<情绪>/ 选图（避开本会话上一张），以图片段追加在末尾，整条最多 1 个
decorate() 无任何转换时返回 None，调用方回退到原纯文本发送路径。
"""
import json
import logging
import os
import random
import re
import threading
import time

from . import config

logger = logging.getLogger("jm_bot")

MOODS = ["开心", "生气", "难过", "害羞", "撒娇", "疑惑", "委屈", "激动", "惊讶", "饿"]
VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif"}

FACE_MAP: dict[str, int] = {}
_map_path = os.path.join(os.path.dirname(__file__), "data", "face_map.json")
try:
    if os.path.exists(_map_path):
        with open(_map_path, "r", encoding="utf-8") as f:
            FACE_MAP = json.load(f)
    else:
        logger.warning("表情映射文件不存在: %s", _map_path)
except Exception as e:
    logger.warning("加载表情映射文件失败: %s", e)
    FACE_MAP = {}

_lock = threading.Lock()
_face_history: dict[str, list[tuple[int, float]]] = {}
_last_stickers: dict[str, str] = {}


def pick_sticker(mood: str, session_key: str) -> str | None:
    """从指定情绪目录下挑选一张表情包图片，同一会话目录>=2张时避开上一次选图"""
    if mood not in MOODS:
        return None
    mood_dir = os.path.join(config.BASE_DIR, "stickers", mood)
    if not os.path.isdir(mood_dir):
        return None
    try:
        files = [
            f for f in os.listdir(mood_dir)
            if os.path.splitext(f)[1].lower() in VALID_EXTENSIONS
            and os.path.isfile(os.path.join(mood_dir, f))
        ]
    except OSError:
        return None

    if not files:
        return None

    with _lock:
        last = _last_stickers.get(session_key)
        candidates = files
        if len(files) >= 2 and last:
            candidates = [
                f for f in files
                if os.path.abspath(os.path.join(mood_dir, f)) != last
            ]
            if not candidates:
                candidates = files
        chosen = random.choice(candidates)
        full_path = os.path.abspath(os.path.join(mood_dir, chosen))
        _last_stickers[session_key] = full_path
        return full_path


def decorate(text: str, session_key: str) -> list | None:
    """将文本中的表情与表情包标记转换为 OneBot 消息段列表；无转换发生时返回 None"""
    if not text:
        return None

    faces_cfg = config.CONFIG.get("faces", {})
    if not faces_cfg.get("enabled", True):
        return None

    stickers_enabled = faces_cfg.get("stickers_enabled", True)
    max_per_message = faces_cfg.get("max_per_message", 2)
    cooldown_minutes = faces_cfg.get("cooldown_minutes", 10)
    cooldown_max_uses = faces_cfg.get("cooldown_max_uses", 2)

    sticker_pattern = re.compile(r"\[\[sticker:([^\]]{1,6})\]\]")
    face_pattern = re.compile(r"\[([^\[\]\s]{1,12})\]")

    chosen_sticker_path = None
    has_sticker_tag = False

    def _replace_sticker(match):
        nonlocal chosen_sticker_path, has_sticker_tag
        has_sticker_tag = True
        mood = match.group(1)
        if stickers_enabled and chosen_sticker_path is None and mood in MOODS:
            sp = pick_sticker(mood, session_key)
            if sp:
                chosen_sticker_path = sp
        return ""

    text_after_sticker = sticker_pattern.sub(_replace_sticker, text)

    converted = has_sticker_tag
    segments = []
    last_idx = 0
    success_count = 0

    for m in face_pattern.finditer(text_after_sticker):
        start, end = m.span()
        if start > last_idx:
            segments.append({"type": "text", "data": {"text": text_after_sticker[last_idx:start]}})
        last_idx = end

        face_name = m.group(1)
        if face_name not in FACE_MAP:
            segments.append({"type": "text", "data": {"text": m.group(0)}})
            continue

        converted = True
        fid = FACE_MAP[face_name]

        with _lock:
            now = time.time()
            history = _face_history.get(session_key, [])
            cutoff = now - cooldown_minutes * 60
            history = [item for item in history if item[1] >= cutoff]

            recent = history[-cooldown_max_uses:] if cooldown_max_uses > 0 else []
            in_cooldown = any(h_fid == fid for h_fid, _ in recent)

            if in_cooldown or success_count >= max_per_message:
                _face_history[session_key] = history
                continue

            history.append((fid, now))
            _face_history[session_key] = history[-8:]
            success_count += 1
            segments.append({"type": "face", "data": {"id": str(fid)}})

    if last_idx < len(text_after_sticker):
        segments.append({"type": "text", "data": {"text": text_after_sticker[last_idx:]}})

    if not converted:
        return None

    merged_segments = []
    for seg in segments:
        if seg["type"] == "text":
            txt = seg["data"]["text"]
            if not txt:
                continue
            if merged_segments and merged_segments[-1]["type"] == "text":
                merged_segments[-1]["data"]["text"] += txt
            else:
                merged_segments.append(seg)
        else:
            merged_segments.append(seg)

    if chosen_sticker_path:
        file_path = os.path.abspath(chosen_sticker_path).replace("\\", "/")
        file_uri = f"file:///{file_path.lstrip('/')}"
        merged_segments.append({"type": "image", "data": {"file": file_uri}})

    if not merged_segments:
        return None
    return merged_segments


def strip_markers(text: str) -> str:
    """给 TTS 语音路径用：摘除全部 [[sticker:...]] 标记；[表情名] 若在 face_map 中替换为表情名本身（去括号），不在则原样保留"""
    if not text:
        return ""
    text = re.sub(r"\[\[sticker:[^\]]{1,6}\]\]", "", text)

    def _replace_face(m):
        name = m.group(1)
        if name in FACE_MAP:
            return name
        return m.group(0)

    return re.sub(r"\[([^\[\]\s]{1,12})\]", _replace_face, text)
