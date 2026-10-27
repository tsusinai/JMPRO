"""自然语言管线模块 (bot.handlers.nl)

本模块实现基于自然语言交互的执行管线，涵盖意图分类、思考、有界工具循环、澄清确认与回复生成。
整体设计采用全异步架构，同构于 cmd_ask 调度流程。

关键机制设计：
1. 待确认状态机口径：
   - 针对多本漫画批量下载 (len(ids) >= 2) 与全量/过期缓存清理 (cache_clean) 等高耗能或破坏性操作，
     系统不会立即执行，而是进入等待确认状态 (挂起在模块级 _pending 字典中，附带 TTL 过期时间)；
   - 仅当用户在超时窗口内输入合规的确认词时才触发真实动作，单本下载等安全只读/常规操作不入等待态；
   - 超时后自动过期清除，收到非确认消息时视为撤销并作为新一轮消息重新消费。
2. 工具循环上限来源：
   - 依赖 config.CONFIG["nl"]["tool_loop_max"]（默认 2 次），强制限制链式调用深度，
     确保即便模型多次生成数据追问意图，也会在触达硬上限后强制收束并调用 generate_reply 生成自然回复。
3. Shadow Log 只记不发：
   - shadow_log 纯粹作为离线评估与特征采样的旁路链路，受分类预算控制，
     仅将分类意图结构异步追加到 nl_shadow.log，绝对不产生任何出站消息。
4. 主动插话 10 级护栏清单（P0 新增 8-10，仍是单一决策闸，不另起主动插件）：
   - 1) 功能总开关 (enabled)
   - 2) 群每日插话上限 (daily_max_per_group)
   - 3) 群冷却时间窗 (group_cooldown_seconds)
   - 4) 随机采样概率过滤 (sample_probability，热场时按冷热权重放大、冷场时直接拦)
   - 5) 防封分类预算校验 (budget_check)
   - 6) LLM 话题相关性与保守决策评判 (join == True 且 conf >= judge_min_confidence)
   - 7) 生成回复非空兜底校验
   - 8) 夜间静默：23:00-08:00（config humanity 段可调）不主动插话
   - 9) 冷场降权：距上一条群消息 >600 秒时不硬凑（权重 0.25 直接拦）
   - 10) 连续主动熔断：连续主动插话 2 条且期间无人唤醒 → 拦住下一次主动，直到有人唤醒才清零
5. 「会话内主动 ≠ 定时推送」边界：
   - 会话内主动插话 (maybe_proactive) 是严格由用户消息驱动的「旁路事件判定」，依赖群内新消息触发，
     仅在检测到合适话题语境时顺势搭话；
   - 严禁将其与脱离群消息上下文、由系统时钟驱动的定时轮询任务或单向主动广播推送混淆。
"""

import asyncio
import json
import logging
import os
import random
import time
from typing import Any, Optional

logger = logging.getLogger("jm_bot.nl")

from .. import ai_chat, antiban, config, humanity, memory, tools
from ..faces import pick_sticker, strip_markers
from ..messages import M
from ..messaging import (
    send_group_msg,
    send_group_msg_rich,
    send_group_msg_segments,
    send_group_reply,
    send_group_reply_rich,
    send_group_voice,
)
from ..roles import ROLES, get_group_role
from ..runtime import async_api_run, io_call

# 模块级待确认状态机容器及并发锁
_pending: dict[str, dict[str, Any]] = {}
_pending_lock = asyncio.Lock()

# 主动插话状态记录：群每日调用计数 {session_id: (date_str, count)} 与冷却时间 {session_id: last_ts}
_proactive_daily: dict[int, tuple[str, int]] = {}
_proactive_last: dict[int, float] = {}

# P0 活人感状态机（humanity.py 的纯逻辑，NL 管线只做接线；参数来自 config humanity 段）
_hum_cfg: dict[str, Any] = config.CONFIG.get("humanity", {}) if isinstance(config.CONFIG.get("humanity", {}), dict) else {}
_followup = humanity.FollowupWindow()
_field = humanity.FieldTracker(
    quiet_seconds=float(_hum_cfg.get("field_quiet_seconds", 600)),
    hot_threshold=int(_hum_cfg.get("field_hot_threshold", 5)),
)
_streak = humanity.ProactiveStreak(fuse=int(_hum_cfg.get("proactive_fuse", 2)))
_duel = humanity.DuelTracker(cooldown_seconds=float(_hum_cfg.get("duel_cooldown_seconds", 30)))


def note_group_message(session_id: int, now: float | None = None) -> float:
    """记录一条群消息并返回当前冷热权重（runner 在白名单后、路由前调用）。"""
    return _field.record(session_id, now=now)


def is_followup_active(session_id: int, user_id: int) -> bool:
    """追问窗口是否仍有效（runner 用它判定未唤醒消息是否直达 NL）。"""
    return _followup.is_active(session_id, user_id)


def open_followup(session_id: int, user_id: int) -> None:
    """手动开追问窗口（runner 的戳一戳事件用：只开窗口，不自动回消息）。"""
    _followup.open(
        session_id, user_id,
        seconds=float(_humanity_cfg("followup_seconds", 300)),
    )


def _humanity_cfg(key: str, default: Any) -> Any:
    return config.CONFIG.get("humanity", {}).get(key, default)

# 确认词集合
CONFIRM_WORDS = {
    "是", "确认", "好", "好的", "嗯", "ok", "yes",
    "下", "下载", "继续", "是的", "对"
}

# 主动插话判定提示词模板
JUDGE_PROMPT = """你是一个群聊机器人，正在决定要不要主动接一句话。只输出 JSON：{"join": true/false, "confidence": 0~1, "reason": "一句话理由"}
判断标准（偏保守，拿不准就 false）：
- 话题与漫画、动漫、游戏、日常闲聊相关，或有人提问一直没人回答、气氛冷场 → 可 true
- 与你的人设和兴趣无关、纯通知、刷屏、别人正聊得热闹且已有回应、敏感话题 → false
## 你的人设
{role_identity}
## 最近的聊天记录
{history}
## 刚路过的一条消息
{text}
只输出 JSON："""


def has_pending(session_id: int, user_id: int) -> bool:
    """检查指定用户是否存在未过期的待确认状态（过期则顺手清理）。"""
    key = f"{session_id}:{user_id}"
    item = _pending.get(key)
    if not item:
        return False
    if time.time() > item.get("expires", 0.0):
        _pending.pop(key, None)
        return False
    return True


def _intent_desc(intent: dict[str, Any]) -> str:
    """生成意图的简要人类可读描述，用于注入思考上下文。"""
    action = intent.get("action", "")
    if action == "download":
        ids = [str(i) for i in intent.get("ids", [])]
        return f"想下载漫画 {', '.join(ids)}"
    if action == "search":
        return f"想搜「{intent.get('query', '')}」"
    if action == "info":
        return f"想看漫画 {intent.get('id', '')} 详情"
    if action == "send_sticker":
        return "想发表情包"
    if action == "chat":
        return "闲聊"
    return f"想执行 {action}"


def _followup_prompt(original: str, result_text: str) -> str:
    """生成多轮工具链的后续追问提示词。"""
    return (
        f"（系统内部消息，不要当作用户发言）用户原话：{original}。"
        f"刚执行的工具结果摘要：{result_text[:300]}。"
        f"如果还需要再查一个相关动作就给出该动作的 JSON；信息已足够、或该正常回复用户了就输出 chat。"
    )


def _append_shadow(record: dict[str, Any]) -> None:
    """将 shadow log 记录追加写入磁盘文件。"""
    log_path = os.path.join(config.BASE_DIR, "nl_shadow.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _judge_relevant(session_id: int, text: str) -> tuple[bool, float]:
    """同步调用大模型评判是否应当主动接话，返回 (join, confidence)。"""
    try:
        role_idx = get_group_role(session_id)
        role_identity = ROLES[role_idx]["system"]
        history = ai_chat._get_history_text(session_id)

        prompt = (
            JUDGE_PROMPT.replace("{role_identity}", str(role_identity))
            .replace("{history}", str(history))
            .replace("{text}", str(text))
        )

        client = ai_chat._get_client()
        resp = client.messages.create(
            model=ai_chat.MODEL,
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = ""
        for block in resp.content:
            if hasattr(block, "text") and block.text.strip():
                raw = block.text.strip()
                break
        s = raw.find("{")
        e = raw.rfind("}")
        if s != -1 and e != -1 and e > s:
            data = json.loads(raw[s : e + 1])
            return bool(data.get("join", False)), float(data.get("confidence", 0.0))
        return False, 0.0
    except Exception:
        return False, 0.0


async def _send_persona(
    session_id: int,
    text: str,
    reply_msg_id: int = 0,
    quote: bool = True,
) -> None:
    """统一的人设文本发送出口，对齐 cmd_ask 口径。"""
    target_reply_id = reply_msg_id if (quote and reply_msg_id != 0) else 0

    if not text:
        err_msg = M("ask_error")
        if target_reply_id != 0:
            await io_call(send_group_reply, session_id, err_msg, target_reply_id)
        else:
            await io_call(send_group_msg, session_id, err_msg)
        return

    from .misc import voice_mode_enabled  # 函数内懒导入，仿 cmd_ask

    if voice_mode_enabled(session_id):
        clean_text = strip_markers(text)
        await io_call(
            send_group_voice,
            session_id,
            clean_text,
            target_reply_id,
            get_group_role(session_id),
        )
        return

    send_text = text
    if len(send_text) > 800:
        send_text = send_text[:780] + "..."

    # P0 情绪表情：无模型标记时，按关键词补一个 [[sticker:情绪]]（已有标记不补；
    # decorate() 每条最多 1 张图，语音路径在前面已 return，不受影响）
    if "[[sticker:" not in send_text and "```" not in send_text:
        mood = humanity.infer_mood(send_text)
        if mood:
            send_text = send_text + f" [[sticker:{mood}]]"

    # P0 打字分段：多句长回复切成两段发，中间微停顿；单句 / 代码块不切
    if _humanity_cfg("segment_enabled", True):
        parts = humanity.split_reply(send_text)
    else:
        parts = [send_text]
    if len(parts) <= 1:
        if target_reply_id != 0:
            await io_call(send_group_reply_rich, session_id, send_text, target_reply_id)
        else:
            await io_call(send_group_msg_rich, session_id, send_text)
        return

    first, rest = parts[0], parts[1:]
    if target_reply_id != 0:
        await io_call(send_group_reply_rich, session_id, first, target_reply_id)
    else:
        await io_call(send_group_msg_rich, session_id, first)
    pause = float(_humanity_cfg("segment_pause_seconds", 0.8))
    for part in rest:
        if pause > 0:
            await asyncio.sleep(pause)
        await io_call(send_group_msg_rich, session_id, part)


async def handle_nl(
    session_id: int,
    user_id: int,
    text: str,
    reply_msg_id: int = 0,
    is_private: bool = False,
    image_urls: Optional[list[str]] = None,
) -> None:
    """自然语言管线主入口：确认消费、意图分析、思考和有界工具循环。"""
    try:
        # P0：被唤醒即清零主动熔断 streak，并开追问窗口（默认 300 秒，窗口内不用反复 @）
        _streak.record_wake(session_id)
        _followup.open(
            session_id, user_id,
            seconds=float(_humanity_cfg("followup_seconds", 300)),
        )
        nl_cfg = config.CONFIG.get("nl", {})
        conf_threshold = float(nl_cfg.get("confidence_threshold", 0.6))
        confirm_timeout = float(nl_cfg.get("confirm_timeout_seconds", 60))
        busy_cooldown = float(nl_cfg.get("busy_reply_cooldown_seconds", 60))
        tool_loop_max = int(nl_cfg.get("tool_loop_max", 2))

        key = f"{session_id}:{user_id}"

        # 1. 待确认状态机检查与消费
        async with _pending_lock:
            pending_item = _pending.get(key)
            if pending_item:
                if time.time() > pending_item.get("expires", 0.0):
                    _pending.pop(key, None)
                else:
                    norm_word = text.strip().lower()
                    if norm_word in CONFIRM_WORDS:
                        _pending.pop(key, None)
                        ctx = tools.NlContext(session_id, user_id, reply_msg_id, is_private)
                        kind = pending_item["kind"]
                        params = pending_item.get("params", {})
                        res = await tools.run_tool(kind, params, ctx)
                        if res.kind == "data":
                            await _send_persona(session_id, res.text, reply_msg_id)
                        return
                    else:
                        # 收到非确认词，取消挂起的确认，继续作为新消息向下流动
                        _pending.pop(key, None)

        # 2. 分类预算检查
        if not antiban.budget_check(session_id, "classify"):
            if antiban.budget_busy_reply_allowed(session_id, busy_cooldown):
                await io_call(send_group_reply, session_id, M("nl_busy"), reply_msg_id)
            return

        # 3. 意图分类与特化分支拦截
        intent = await async_api_run(ai_chat.classify_intent, text, session_id, user_id=user_id)
        if not isinstance(intent, dict):
            intent = {"action": "error"}

        action = intent.get("action", "")
        confidence = float(intent.get("confidence", 0.0))

        if action == "error":
            await io_call(send_group_reply, session_id, M("ask_error"), reply_msg_id)
            return

        if action == "unknown" or confidence < conf_threshold:
            clarify_text = await async_api_run(
                ai_chat.generate_clarify,
                session_id,
                text,
                ["搜漫画", "看详情", "下载漫画", "闲聊"],
                user_id=user_id,
            )
            await _send_persona(session_id, clarify_text, reply_msg_id)
            ai_chat.save_history(session_id, text, clarify_text)
            return

        if action == "download":
            raw_ids = intent.get("ids", [])
            ids = [str(x) for x in raw_ids]
            if len(ids) >= 2:
                fmt = intent.get("format", "pdf")
                async with _pending_lock:
                    _pending[key] = {
                        "kind": "download",
                        "params": {"ids": ids, "format": fmt},
                        "expires": time.time() + confirm_timeout,
                    }
                await io_call(
                    send_group_reply,
                    session_id,
                    M(
                        "nl_confirm_download",
                        ids=", ".join(ids),
                        fmt=fmt,
                        seconds=int(confirm_timeout),
                    ),
                    reply_msg_id,
                )
                return

        if action == "cache_clean":
            days = intent.get("days", 7)
            async with _pending_lock:
                _pending[key] = {
                    "kind": "cache_clean",
                    "params": {"days": days},
                    "expires": time.time() + confirm_timeout,
                }
            await io_call(
                send_group_reply,
                session_id,
                M("nl_confirm_cache_clean", days=days, seconds=int(confirm_timeout)),
                reply_msg_id,
            )
            return

        # 4. 思考阶段
        th = await async_api_run(ai_chat.think, session_id, text, _intent_desc(intent))
        thought = th.get("think", "") if isinstance(th, dict) else ""

        # 5. 执行循环
        ctx = tools.NlContext(session_id, user_id, reply_msg_id, is_private)
        executed = 0
        current = intent
        tool_texts: list[str] = []

        async def _maybe_duel(user_text: str) -> None:
            """P0 斗图反甩：被唤醒消息带图时，同群 30 秒内只反甩一张，按用户情绪选图。"""
            try:
                if not image_urls or not _duel.allowed(session_id):
                    return
                mood = humanity.infer_mood(user_text) or "开心"
                path = pick_sticker(mood, str(session_id))
                if not path:
                    return
                uri = "file:///" + os.path.abspath(path).replace("\\", "/").lstrip("/")
                await io_call(
                    send_group_msg_segments, session_id,
                    [{"type": "image", "data": {"file": uri}}],
                )
            except Exception:
                return

        async def _chat_branch(msg: str) -> None:
            blocks = None
            if image_urls and executed == 0:
                blocks = await async_api_run(ai_chat.fetch_image_blocks, image_urls)
                if not blocks:
                    blocks = None
            result = await async_api_run(ai_chat.group_chat, session_id, msg, blocks, thought, user_id)
            if not result:
                await io_call(send_group_reply, session_id, M("ask_error"), reply_msg_id)
            else:
                await _send_persona(session_id, result, reply_msg_id)
                await _maybe_duel(msg)

        async def _finish(texts: list[str]) -> None:
            data_text = "\n".join(texts)
            reply_text = await async_api_run(
                ai_chat.generate_reply,
                data_text,
                session_id,
                text,
                thought,
                user_id,
            )
            ai_chat.save_history(session_id, text, reply_text)
            await _send_persona(session_id, reply_text, reply_msg_id)

        while True:
            act = current.get("action", "")

            if act == "chat":
                await _chat_branch(text)
                return

            if act == "send_sticker":
                res = await tools.run_tool("send_sticker", current, ctx)
                if res.kind == "direct":
                    await _chat_branch(text)
                    return
                elif res.kind == "none":
                    await _chat_branch(text)
                    return
                return

            # 其余功能性动作：检查生成预算
            if not antiban.budget_check(session_id, "generate"):
                if tool_texts:
                    await _finish(tool_texts)
                else:
                    if antiban.budget_busy_reply_allowed(session_id, busy_cooldown):
                        await io_call(send_group_reply, session_id, M("nl_busy"), reply_msg_id)
                return

            res = await tools.run_tool(act, current, ctx)
            executed += 1

            if res.kind == "direct":
                return
            elif res.kind == "none":
                await _chat_branch(text)
                return
            elif res.kind == "data":
                tool_texts.append(res.text)
                if executed >= tool_loop_max:
                    await _finish(tool_texts)
                    return

                follow = await async_api_run(
                    ai_chat.classify_intent,
                    _followup_prompt(text, res.text),
                    session_id,
                    user_id=user_id,
                )
                follow_act = follow.get("action", "") if isinstance(follow, dict) else "error"
                if follow_act in ("chat", "unknown", "error") or follow_act == act:
                    await _finish(tool_texts)
                    return
                if follow_act in ("download", "cache_clean"):
                    await _finish(tool_texts)
                    return

                current = follow

    except Exception:
        logger.exception("handle_nl 处理异常 (session=%s)", session_id)
        return


async def shadow_log(session_id: int, user_id: int, text: str) -> None:
    """静默影子日志采样：仅识别意图并落盘，用于离线效果评估，全程吞异常。"""
    try:
        if not antiban.budget_check(session_id, "classify"):
            return
        intent = await async_api_run(ai_chat.classify_intent, text, session_id, user_id=user_id)
        record = {
            "ts": time.time(),
            "session": session_id,
            "user": user_id,
            "text": text[:200],
            "intent": intent,
        }
        await io_call(_append_shadow, record)
    except Exception:
        return


async def maybe_proactive(session_id: int, user_id: int, text: str) -> bool:
    """主动插话判断与执行：严格遵循 7 级安全护栏，全程异常兜底返回 False。"""
    try:
        cfg = config.CONFIG.get("proactive_reply", {})

        # 护栏 1：功能总开关
        if not cfg.get("enabled", False):
            return False

        # 护栏 8：夜间静默（只关主动插话，不拦被唤醒聊天与 /jm 工具）
        _hour = time.localtime().tm_hour
        if humanity.is_sleep_time(
            _hour,
            int(_humanity_cfg("sleep_start_hour", 23)),
            int(_humanity_cfg("sleep_end_hour", 8)),
        ):
            return False

        # 护栏 10：连续主动熔断（连续主动 fuse 条且期间无人唤醒 → 拦住，直到唤醒清零）
        if _streak.blocked(session_id):
            return False

        # 护栏 2：群每日调用上限
        today_str = time.strftime("%Y-%m-%d")
        daily_max = int(cfg.get("daily_max_per_group", 10))
        last_date, count = _proactive_daily.get(session_id, ("", 0))
        if last_date != today_str:
            count = 0
        if count >= daily_max:
            return False

        # 护栏 3：群冷却时间
        cooldown = float(cfg.get("group_cooldown_seconds", 300))
        now = time.time()
        if now - _proactive_last.get(session_id, 0.0) < cooldown:
            return False

        # 护栏 4：概率抽样（冷热场加权：冷场权重 0.25 直接拦，热场 1.5 放大采样）
        _weight = _field.weight(session_id)
        if _weight <= 0.25:
            return False
        sample_prob = float(cfg.get("sample_probability", 0.0))
        if _weight > 1.0:
            sample_prob = min(1.0, sample_prob * _weight)
        if random.random() >= sample_prob:
            return False

        # 护栏 5：流控预算
        if not antiban.budget_check(session_id, "classify"):
            return False

        # 护栏 6：大模型动机与置信度评判
        judge_min_confidence = float(cfg.get("judge_min_confidence", 0.6))
        join, conf = await async_api_run(_judge_relevant, session_id, text)
        if not join or conf < judge_min_confidence:
            return False

        # 护栏 7：思考并生成插话内容
        th = await async_api_run(ai_chat.think, session_id, text, "主动接话")
        thought = th.get("think", "") if isinstance(th, dict) else ""
        result = await async_api_run(ai_chat.group_chat, session_id, text, None, thought, user_id=user_id)
        if not result:
            return False

        # 发送插话（主动插话不带引用，reply_msg_id 为 0，quote=False）
        await _send_persona(session_id, result, 0, quote=False)

        # 状态更新（含主动 streak：下一次主动前若无人唤醒，满 fuse 条即熔断）
        _proactive_last[session_id] = now
        _proactive_daily[session_id] = (today_str, count + 1)
        _streak.record_send(session_id)
        return True

    except Exception:
        return False
