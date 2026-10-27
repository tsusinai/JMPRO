"""SQLite 轻量长期记忆模块。

提供会话级别的摘要与关键事实存储，支持后台异步压缩旧对话。
"""

import json
import logging
import os
import sqlite3
import threading
import time

from . import config, state

logger = logging.getLogger(__name__)

# 默认配置
DEFAULTS = {
    "enabled": True,
    "db_file": "memory.db",
    "compress_after_messages": 90,
    "compress_after_chars": 15000,
    "keep_recent": 60,
    "max_facts": 50,
    "inject_facts": 10,
    "compress_cooldown_seconds": 600,
}

# 数据库连接与锁
_db_conn: sqlite3.Connection | None = None
_db_lock = threading.RLock()

# 压缩状态维护
_compress_lock = threading.Lock()
_last_compress_time: dict[str, float] = {}
_compressing_sessions: set[str] = set()

# 压缩提示词模板
COMPRESS_PROMPT = """你是一个记忆整理助手。请把「已有摘要」与「一段对话记录」合并成新摘要并抽取关键事实。

要求：
1. 合并已有摘要与对话记录，写出新的摘要（不超过 200 字）。
2. 抽取关键事实列表（不超过 8 条，每条不超过 40 字，只记用户偏好、约定或重要事件，不记闲聊流水）。
3. 必须且只能输出严格合法的 JSON 对象，不要输出 markdown 标记（如 ```json）或任何多余文字。
JSON 结构如下：
{"summary": "...", "facts": ["...", "..."]}

【已有摘要】
{old_summary}

【对话记录】
{transcript}
"""


def _cfg(key: str):
    """读取配置项，合并默认值。"""
    mem_cfg = getattr(config, "CONFIG", {}).get("memory")
    if isinstance(mem_cfg, dict) and key in mem_cfg:
        return mem_cfg[key]
    return DEFAULTS[key]


def _ensure_init() -> sqlite3.Connection:
    """懒初始化 SQLite 连接并建表。"""
    global _db_conn
    with _db_lock:
        if _db_conn is not None:
            return _db_conn
        db_path = os.path.join(config.BASE_DIR, _cfg("db_file"))
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS summaries (
                    session_key TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    updated_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_key TEXT NOT NULL,
                    fact TEXT NOT NULL,
                    created_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_facts_session_key ON facts(session_key)
                """
            )
            # P0 关系记忆：按人画像 + 好感 + 待核实区（molly 式：没把握先进待核实，不直接进事实）
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    session_key TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    affection REAL NOT NULL DEFAULT 0,
                    impression TEXT NOT NULL DEFAULT '',
                    updated_at REAL,
                    PRIMARY KEY (session_key, user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_key TEXT NOT NULL,
                    fact TEXT NOT NULL,
                    created_at REAL
                )
                """
            )
        _db_conn = conn
        return _db_conn


def session_key(session_id: int) -> str:
    """计算会话隔离键。私聊前缀 p:，群聊前缀 g:。"""
    try:
        sid = int(session_id)
    except (ValueError, TypeError):
        sid = session_id
    if hasattr(state, "private_chats") and sid in state.private_chats:
        return f"p:{session_id}"
    return f"g:{session_id}"


def get_summary(session_id) -> str:
    """获取指定会话的长期摘要，无则返回空串。"""
    try:
        conn = _ensure_init()
        skey = session_key(session_id)
        with _db_lock:
            cursor = conn.execute(
                "SELECT summary FROM summaries WHERE session_key = ?",
                (skey,),
            )
            row = cursor.fetchone()
            return row[0] if row and row[0] else ""
    except Exception as e:
        logger.warning("get_summary failed for session %s: %s", session_id, e)
        return ""


def set_summary(session_id, text: str):
    """保存或更新指定会话的长期摘要。"""
    try:
        conn = _ensure_init()
        skey = session_key(session_id)
        now = time.time()
        with _db_lock:
            with conn:
                conn.execute(
                    """
                    INSERT INTO summaries (session_key, summary, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(session_key) DO UPDATE SET
                        summary = excluded.summary,
                        updated_at = excluded.updated_at
                    """,
                    (skey, text, now),
                )
    except Exception as e:
        logger.warning("set_summary failed for session %s: %s", session_id, e)


def add_facts(session_id, facts: list):
    """追加关键事实，自动去重并按 max_facts 裁剪最旧条目。"""
    if not facts:
        return
    try:
        conn = _ensure_init()
        skey = session_key(session_id)
        max_facts = int(_cfg("max_facts"))
        now = time.time()
        with _db_lock:
            cursor = conn.execute(
                "SELECT fact FROM facts WHERE session_key = ?",
                (skey,),
            )
            existing = {row[0] for row in cursor.fetchall()}
            to_insert = []
            for item in facts:
                if not isinstance(item, str):
                    continue
                cleaned = item.strip()
                if not cleaned or cleaned in existing:
                    continue
                to_insert.append((skey, cleaned, now))
                existing.add(cleaned)

            if to_insert:
                with conn:
                    conn.executemany(
                        "INSERT INTO facts (session_key, fact, created_at) VALUES (?, ?, ?)",
                        to_insert,
                    )
                    conn.execute(
                        """
                        DELETE FROM facts
                        WHERE session_key = ?
                          AND id NOT IN (
                            SELECT id FROM facts
                            WHERE session_key = ?
                            ORDER BY id DESC
                            LIMIT ?
                        )
                        """,
                        (skey, skey, max_facts),
                    )
    except Exception as e:
        logger.warning("add_facts failed for session %s: %s", session_id, e)


def get_facts(session_id, limit=None) -> list:
    """获取指定会话的最新事实列表，按时间正序排列。"""
    try:
        if limit is None:
            limit = int(_cfg("inject_facts"))
        conn = _ensure_init()
        skey = session_key(session_id)
        with _db_lock:
            cursor = conn.execute(
                """
                SELECT fact FROM (
                    SELECT id, fact FROM facts
                    WHERE session_key = ?
                    ORDER BY id DESC
                    LIMIT ?
                ) ORDER BY id ASC
                """,
                (skey, limit),
            )
            return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.warning("get_facts failed for session %s: %s", session_id, e)
        return []


def get_memory_text(session_id) -> str:
    """拼接会话记忆注入文本（不含标题行，标题由调用方按上下文添加），摘要/事实单独或组合输出。"""
    try:
        if not _cfg("enabled"):
            return ""
        summary = get_summary(session_id)
        facts = get_facts(session_id)
        if not summary and not facts:
            return ""
        parts = []
        if summary:
            parts.append(f"摘要：{summary}")
        if facts:
            fact_lines = "\n".join(f"- {f}" for f in facts)
            parts.append(f"近期事实：\n{fact_lines}")
        return "\n".join(parts)
    except Exception as e:
        logger.warning("get_memory_text failed for session %s: %s", session_id, e)
        return ""


def clear_session(session_id):
    """清除指定会话的长期记忆与事实记录（含按人画像与待核实区）。"""
    try:
        conn = _ensure_init()
        skey = session_key(session_id)
        with _db_lock:
            with conn:
                conn.execute("DELETE FROM summaries WHERE session_key = ?", (skey,))
                conn.execute("DELETE FROM facts WHERE session_key = ?", (skey,))
                conn.execute("DELETE FROM user_profiles WHERE session_key = ?", (skey,))
                conn.execute("DELETE FROM pending_facts WHERE session_key = ?", (skey,))
    except Exception as e:
        logger.warning("clear_session failed for session %s: %s", session_id, e)


# ---------------------------------------------------------------- P0 关系记忆


def get_user_profile(session_id, user_id: int) -> dict:
    """取按人画像：affection 夹在 -100..100，impression 为一句话画像，无则默认值。"""
    try:
        conn = _ensure_init()
        skey = session_key(session_id)
        with _db_lock:
            row = conn.execute(
                "SELECT affection, impression FROM user_profiles WHERE session_key = ? AND user_id = ?",
                (skey, int(user_id)),
            ).fetchone()
        if not row:
            return {"affection": 0.0, "impression": ""}
        return {"affection": float(row[0]), "impression": row[1] or ""}
    except Exception as e:
        logger.warning("get_user_profile failed: %s", e)
        return {"affection": 0.0, "impression": ""}


def adjust_affection(session_id, user_id: int, delta: float, impression: str | None = None) -> dict:
    """调好感：delta 可正可负，结果夹在 -100..100；impression 非空时覆盖画像。返回新画像。"""
    try:
        conn = _ensure_init()
        skey = session_key(session_id)
        cur = get_user_profile(session_id, user_id)
        new_aff = max(-100.0, min(100.0, cur["affection"] + float(delta)))
        new_imp = impression if impression else cur["impression"]
        with _db_lock:
            with conn:
                conn.execute(
                    """
                    INSERT INTO user_profiles (session_key, user_id, affection, impression, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(session_key, user_id) DO UPDATE SET
                        affection = excluded.affection,
                        impression = excluded.impression,
                        updated_at = excluded.updated_at
                    """,
                    (skey, int(user_id), new_aff, new_imp, time.time()),
                )
        return {"affection": new_aff, "impression": new_imp}
    except Exception as e:
        logger.warning("adjust_affection failed: %s", e)
        return {"affection": 0.0, "impression": ""}


def add_pending_fact(session_id, fact: str) -> int | None:
    """没把握的事实先进待核实区，不直接进 facts；返回 pending id。"""
    if not fact or not str(fact).strip():
        return None
    try:
        conn = _ensure_init()
        skey = session_key(session_id)
        with _db_lock:
            with conn:
                cur = conn.execute(
                    "INSERT INTO pending_facts (session_key, fact, created_at) VALUES (?, ?, ?)",
                    (skey, str(fact).strip(), time.time()),
                )
                return int(cur.lastrowid)
    except Exception as e:
        logger.warning("add_pending_fact failed: %s", e)
        return None


def list_pending_facts(session_id) -> list:
    """列出本会话待核实事实 [(id, fact), ...]，按时间正序。"""
    try:
        conn = _ensure_init()
        skey = session_key(session_id)
        with _db_lock:
            rows = conn.execute(
                "SELECT id, fact FROM pending_facts WHERE session_key = ? ORDER BY id ASC",
                (skey,),
            ).fetchall()
        return [(int(r[0]), r[1]) for r in rows]
    except Exception as e:
        logger.warning("list_pending_facts failed: %s", e)
        return []


def confirm_pending_fact(session_id, pending_id: int) -> bool:
    """核实通过：pending 事实转入 facts 并删除 pending 行；不存在返回 False。"""
    try:
        conn = _ensure_init()
        skey = session_key(session_id)
        with _db_lock:
            row = conn.execute(
                "SELECT fact FROM pending_facts WHERE session_key = ? AND id = ?",
                (skey, int(pending_id)),
            ).fetchone()
            if not row:
                return False
            with conn:
                conn.execute(
                    "DELETE FROM pending_facts WHERE session_key = ? AND id = ?",
                    (skey, int(pending_id)),
                )
        add_facts(session_id, [row[0]])
        return True
    except Exception as e:
        logger.warning("confirm_pending_fact failed: %s", e)
        return False


def _facts_with_time(session_id, limit: int = 50) -> list:
    """内部：取事实 + 创建时间，供召回打分用。"""
    try:
        conn = _ensure_init()
        skey = session_key(session_id)
        with _db_lock:
            rows = conn.execute(
                "SELECT fact, created_at FROM facts WHERE session_key = ? ORDER BY id DESC LIMIT ?",
                (skey, int(limit)),
            ).fetchall()
        return [(r[0], r[1] or 0.0) for r in rows]
    except Exception:
        return []


def recall_facts(session_id, query: str, limit: int = 5) -> list:
    """按查询召回事实：BM25 式简化打分（命中 token + 30 天衰减），返回最多 limit 条。"""
    try:
        from .humanity import score_facts

        return score_facts(_facts_with_time(session_id), query)[: int(limit)]
    except Exception as e:
        logger.warning("recall_facts failed: %s", e)
        return []


def get_user_memory_text(session_id, user_id: int, query: str = "") -> str:
    """拼按人记忆注入文本：画像 + 好感 +（有查询时召回事实，否则最近事实）。"""
    try:
        prof = get_user_profile(session_id, user_id)
        parts = []
        if prof["impression"]:
            parts.append(f"对这位群友的印象：{prof['impression']}（好感 {prof['affection']:.0f}）")
        elif prof["affection"] != 0:
            parts.append(f"对这位群友的好感：{prof['affection']:.0f}")
        facts = recall_facts(session_id, query) if query else get_facts(session_id, limit=5)
        if facts:
            parts.append("相关事实：\n" + "\n".join(f"- {f}" for f in facts))
        return "\n".join(parts)
    except Exception as e:
        logger.warning("get_user_memory_text failed: %s", e)
        return ""


def _call_llm(prompt: str) -> str:
    """调用大模型生成文本（独立函数，便于测试打桩）。"""
    from . import ai_chat

    client = ai_chat._get_client()
    resp = client.messages.create(
        model=ai_chat.MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    for block in resp.content:
        if getattr(block, "text", None):
            return block.text
        if isinstance(block, dict) and block.get("text"):
            return block["text"]
    return ""


def compress_now(session_id, history: list) -> bool:
    """将旧对话历史压缩为新摘要并抽取关键事实。"""
    try:
        keep = _cfg("keep_recent")
        if len(history) <= keep:
            return False
        old = history[:-keep]
        transcript = "\n".join(f"[{r}]: {str(c)[:200]}" for r, c in old)
        old_summary = get_summary(session_id) or "（暂无）"
        prompt = COMPRESS_PROMPT.replace("{old_summary}", old_summary).replace("{transcript}", transcript)

        raw_text = _call_llm(prompt)
        if not raw_text:
            return False

        # 提取 JSON 对象
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start == -1 or end == -1 or end < start:
            return False

        json_str = raw_text[start : end + 1]
        data = json.loads(json_str)
        if not isinstance(data, dict):
            return False

        summary = data.get("summary")
        facts = data.get("facts")
        if not isinstance(summary, str) or not isinstance(facts, list):
            return False

        set_summary(session_id, summary)
        add_facts(session_id, facts)
        logger.info("Session %s memory compressed successfully", session_id)
        return True
    except Exception as e:
        logger.warning("compress_now failed for session %s: %s", session_id, e)
        return False


def maybe_compress(session_id, history: list) -> bool:
    """满足条件时异步触发记忆压缩任务。"""
    try:
        if not _cfg("enabled"):
            return False

        msg_count = len(history)
        char_count = sum(len(c) for _, c in history if isinstance(c, str))
        if msg_count < _cfg("compress_after_messages") and char_count < _cfg("compress_after_chars"):
            return False

        skey = session_key(session_id)
        now = time.time()
        cooldown = _cfg("compress_cooldown_seconds")

        with _compress_lock:
            if skey in _compressing_sessions:
                return False
            last_time = _last_compress_time.get(skey, 0.0)
            if now - last_time < cooldown:
                return False
            _compressing_sessions.add(skey)
            _last_compress_time[skey] = now

        history_copy = list(history)

        def _worker():
            try:
                compress_now(session_id, history_copy)
            except Exception as ex:
                logger.warning("Background compress failed for session %s: %s", session_id, ex)
            finally:
                with _compress_lock:
                    _compressing_sessions.discard(skey)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        return True
    except Exception as e:
        logger.warning("maybe_compress failed for session %s: %s", session_id, e)
        return False
