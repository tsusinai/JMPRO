"""QQ 空间决策层 — 后台 tick 周期性让模型自决发不发说说。

模式（config qzone.mode）：
- off：任务直接退出，不产出任何东西
- draft（出厂默认，风控底线）：决策照常跑，但只把说说/日记落本地草稿，绝不真发
- auto：真发；每日硬顶 max_per_day 条（默认 1），以 publish 返回 tid 为准计数

已知近似：ai_chat 的历史记录无时间戳，"最近 history_hours 小时"以每会话最后 20 条近似。
日记无论何种模式都只存草稿、永不直发。
"""

import asyncio
import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict

from . import config
from .ai_chat import MODEL, _chat_history, _get_client
from .fsutils import load_json, save_json
from .qzone import publish_post
from .runtime import api_executor

logger = logging.getLogger("jm_bot")

STATE_FILE = os.path.join(config.BASE_DIR, "qzone_state.json")
DRAFTS_DIR = os.path.join(config.BASE_DIR, "qzone_drafts")

DEFAULT_STATE: Dict[str, Any] = {
    "last_post_date": "",
    "post_count_today": 0,
    "last_diary_date": "",
    "last_say_draft_date": "",
}

_state_lock = threading.Lock()


def _get_state() -> Dict[str, Any]:
    with _state_lock:
        state = load_json(STATE_FILE, DEFAULT_STATE.copy())
        for k, v in DEFAULT_STATE.items():
            if k not in state:
                state[k] = v
        return state


def _update_state(**kwargs: Any) -> Dict[str, Any]:
    with _state_lock:
        state = load_json(STATE_FILE, DEFAULT_STATE.copy())
        for k, v in DEFAULT_STATE.items():
            if k not in state:
                state[k] = v
        state.update(kwargs)
        save_json(STATE_FILE, state)
        return state


def save_draft(kind: str, text: str) -> None:
    os.makedirs(DRAFTS_DIR, exist_ok=True)
    now = datetime.now()
    filename = f"{now.strftime('%Y%m%d-%H%M%S')}-{kind}.txt"
    file_path = os.path.join(DRAFTS_DIR, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)

    log_path = os.path.join(DRAFTS_DIR, "drafts.log")
    log_line = f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] [{kind}] {text[:40]}\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(log_line)

    logger.info(f"空间草稿已保存: {filename}")


def collect_recent_history() -> str:
    """收集白名单会话的近期聊天（每会话最后 20 条）拼成文本；无记录返回空串。

    历史条目为 (role, content) 元组（落盘恢复后为二元 list），无时间戳，
    故以条数近似"最近若干小时"。
    """
    wl = config.CONFIG.get("whitelist", {})
    allowed_keys = None
    if wl.get("enabled", False):
        allowed_keys = {str(x) for x in (wl.get("groups", []) + wl.get("private", []))}

    try:
        snapshot = list(_chat_history.items())
    except Exception:
        snapshot = []

    records = []
    for session_id, msgs in snapshot:
        if allowed_keys is not None and str(session_id) not in allowed_keys:
            continue
        for item in msgs[-20:]:
            try:
                role, content = item
            except (TypeError, ValueError):
                continue
            records.append(f"[{role}]: {content}")

    if not records:
        return ""

    merged = "\n".join(records)
    if len(merged) > 6000:
        merged = merged[-6000:]  # 保留最新部分
    return merged


def _extract_json(raw: str) -> str:
    s = raw.strip()
    if "```" in s:
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return s[start:end + 1]
    return s


def decide_post(history_text: str) -> Dict[str, Any]:
    """让模型自决是否发说说；任何异常都返回不发。"""
    system_prompt = (
        "你是一个社交媒体观察助手。请根据提供的群组近期聊天记录，判断其中是否有值得分享为QQ空间说说的有趣日常、梗或心得感悟。\n"
        "要求：\n"
        "1. 仅输出合法 JSON 格式：{\"publish\": true/false, \"text\": \"说说正文\"}，不要包含任何额外说明或代码块包裹。\n"
        "2. 如果有值得分享的内容，publish 为 true，text 为 20-60 字的说说正文，文风自然生活化，切勿生硬；"
        "如果没有值得分享的日常或趣事，publish 为 false，text 为空字符串。\n"
        "3. 说说必须以第一人称或客观事实陈述，禁止透露群友私人信息或密钥敏感词。"
    )
    try:
        client = _get_client()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=256,
            system=system_prompt,
            messages=[{"role": "user", "content": f"聊天记录如下：\n{history_text}"}],
        )
        content_text = ""
        for block in resp.content:
            if getattr(block, "text", None):
                content_text = block.text
                break

        if not content_text:
            return {"publish": False}

        data = json.loads(_extract_json(content_text))
        if isinstance(data, dict) and "publish" in data:
            return {
                "publish": bool(data.get("publish")),
                "text": str(data.get("text", "")).strip(),
            }
        return {"publish": False}
    except Exception as e:
        logger.warning(f"空间说说决策异常: {e}")
        return {"publish": False}


def write_diary(history_text: str) -> str:
    """据今日聊天生成 150-300 字日记正文；异常返回空串。"""
    system_prompt = (
        "你是一个日记撰写助手。请阅读今日的聊天记录，以第一人称口吻写一篇总结性的简短日记。\n"
        "要求：\n"
        "1. 正文字数控制在 150-300 字之间。\n"
        "2. 文风真诚自然，记录今日讨论的亮点、日常趣事或个人情绪感悟。\n"
        "3. 直接输出纯文本日记正文，不要输出任何多余的标题、标记或解释。"
    )
    try:
        client = _get_client()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=system_prompt,
            messages=[{"role": "user", "content": f"今日聊天记录如下：\n{history_text}"}],
        )
        for block in resp.content:
            if getattr(block, "text", None):
                return block.text.strip()
        return ""
    except Exception as e:
        logger.warning(f"空间日记生成异常: {e}")
        return ""


async def qzone_loop() -> None:
    cfg = config.CONFIG.get("qzone", {})
    if cfg.get("mode", "draft") == "off":
        logger.info("QQ空间功能模式为 off，退出后台任务。")
        return

    logger.info(f"QQ空间决策循环已启动 (mode={cfg.get('mode', 'draft')})")
    last_tick_time = 0.0

    while True:
        try:
            await asyncio.sleep(60)

            cfg = config.CONFIG.get("qzone", {})
            mode = cfg.get("mode", "draft")
            if mode == "off":
                logger.info("QQ空间功能模式已变更为 off，退出后台任务。")
                return

            tick_minutes = cfg.get("tick_minutes", 90)
            daily_limit = cfg.get("max_per_day", 1)
            diary_hour = cfg.get("diary_hour", 20)

            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            state = _get_state()
            if state.get("last_post_date") != today_str:
                state = _update_state(last_post_date=today_str, post_count_today=0)

            loop = asyncio.get_running_loop()

            # (a) 定时自决说说
            now_mono = time.monotonic()
            if now_mono - last_tick_time >= tick_minutes * 60:
                last_tick_time = now_mono
                history = collect_recent_history()
                if history:
                    decide_res = await loop.run_in_executor(api_executor, decide_post, history)
                    if decide_res.get("publish") and decide_res.get("text"):
                        post_text = decide_res["text"].strip()
                        if len(post_text) > 60:
                            post_text = post_text[:60]
                        if len(post_text) >= 20:
                            if mode == "draft":
                                if state.get("last_say_draft_date") == today_str:
                                    logger.info("今日已保存过说说草稿，跳过保存。")
                                else:
                                    save_draft("say", post_text)
                                    _update_state(last_say_draft_date=today_str)
                                    logger.info("说说草稿保存完成。")
                            elif mode == "auto":
                                state = _get_state()
                                if state.get("post_count_today", 0) >= daily_limit:
                                    logger.info(f"今日空间发表已达上限 ({daily_limit})，跳过发表。")
                                else:
                                    pub_res = await loop.run_in_executor(api_executor, publish_post, post_text)
                                    if pub_res.get("ok") and pub_res.get("tid"):
                                        cnt = state.get("post_count_today", 0) + 1
                                        _update_state(post_count_today=cnt, last_post_date=today_str)
                                        logger.info(f"QQ空间说说发表成功! tid={pub_res.get('tid')}, 今日累计={cnt}")
                                    else:
                                        logger.warning(
                                            f"QQ空间说说发表未确认: {pub_res.get('message')} (code={pub_res.get('code')})，不重试"
                                        )

            # (b) 晚间日记草稿（任何模式都只存草稿）
            state = _get_state()
            if now.hour >= diary_hour and state.get("last_diary_date") != today_str:
                history = collect_recent_history()
                if history:
                    diary_content = await loop.run_in_executor(api_executor, write_diary, history)
                    if diary_content:
                        save_draft("diary", diary_content)
                        _update_state(last_diary_date=today_str)
                        logger.info("晚间空间日记草稿已保存。")

        except Exception:
            logger.exception("QQ空间决策循环执行异常，任务保持运行:")
