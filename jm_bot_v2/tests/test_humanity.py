#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
JM Bot v2 活人感 P0 单元测试（打字分段 / 追问窗口 / 冷热场 / 夜间 / 关系记忆 / 斗图冷却）。
独立运行：python tests/test_humanity.py ；全程离线（不调 NapCat、不调 LLM、不上线）。
"""
import asyncio
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)  # jm_bot_v2/
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

_pass = 0
_fail = 0
_failures = []


def ok(name):
    global _pass
    _pass += 1
    print(f"  [PASS] {name}")


def fail(name, msg):
    global _fail
    _fail += 1
    _failures.append((name, msg))
    print(f"  [FAIL] {name}: {msg}")


def eq(name, actual, expected):
    if actual == expected:
        ok(name)
    else:
        fail(name, f"expected {expected!r}, got {actual!r}")


def true(name, cond):
    if cond:
        ok(name)
    else:
        fail(name, f"expected truthy, got {cond!r}")


def section(title):
    print(f"\n--- {title} ---")


def test_split():
    section("humanity: 打字分段")
    from bot import humanity

    eq("空文本", humanity.split_reply(""), [])
    eq("单句不切", humanity.split_reply("你好呀。"), ["你好呀。"])
    code = "看这段：```python\nprint(1)\n```结束了。"
    eq("代码块整条不切", humanity.split_reply(code), [code])
    parts = humanity.split_reply("今天赢了它一回。到底是哪儿在捣乱？明天再战一次。")
    eq("三句切成两段", len(parts), 2)
    eq("分段拼接还原原文", "".join(parts), "今天赢了它一回。到底是哪儿在捣乱？明天再战一次。")


def test_followup_field_sleep():
    section("humanity: 追问窗口 / 冷热场 / 夜间")
    from bot import humanity

    w = humanity.FollowupWindow()
    w.open(1, 2, seconds=300, now=1000.0)
    true("窗口内有效", w.is_active(1, 2, now=1200.0))
    true("窗口过期失效", not w.is_active(1, 2, now=1400.0))

    f = humanity.FieldTracker(quiet_seconds=600, hot_threshold=5)
    eq("首条权重 1.0", f.record(10, now=1000.0), 1.0)
    eq("冷场后权重 0.25", f.record(10, now=2000.0), 0.25)
    f2 = humanity.FieldTracker(quiet_seconds=600, hot_threshold=5)
    for i in range(5):
        wgt = f2.record(11, now=1000.0 + i * 10)
    eq("热场权重 1.5", wgt, 1.5)

    true("23 点是夜间", humanity.is_sleep_time(23, 23, 8))
    true("3 点是夜间", humanity.is_sleep_time(3, 23, 8))
    true("8 点不是夜间", not humanity.is_sleep_time(8, 23, 8))
    true("12 点不是夜间", not humanity.is_sleep_time(12, 23, 8))


def test_streak_duel_mood():
    section("humanity: 主动熔断 / 斗图冷却 / 情绪推断")
    from bot import humanity

    s = humanity.ProactiveStreak(fuse=2)
    true("初始不熔断", not s.blocked(20))
    s.record_send(20)
    true("发 1 条不熔断", not s.blocked(20))
    s.record_send(20)
    true("连续发 2 条熔断", s.blocked(20))
    s.record_wake(20)
    true("有人唤醒清零", not s.blocked(20))

    d = humanity.DuelTracker(cooldown_seconds=30)
    true("斗图首次允许", d.allowed(21, now=1000.0))
    true("30 秒内拒绝", not d.allowed(21, now=1010.0))
    true("30 秒后允许", d.allowed(21, now=1040.0))

    eq("哈哈推断开心", humanity.infer_mood("哈哈太棒了"), "开心")
    eq("饿了推断饿", humanity.infer_mood("我饿了想吃饭"), "饿")
    eq("无关键词无情绪", humanity.infer_mood("今天天气不错"), None)


def test_memory_relation():
    section("memory: 关系记忆（画像+好感+待核实+召回）")
    from bot import memory

    sid, uid = 999001, 555001
    try:
        memory.clear_session(sid)
        eq("初始好感 0", memory.get_user_profile(sid, uid)["affection"], 0.0)
        prof = memory.adjust_affection(sid, uid, 30, impression="喜欢全彩，讨厌被叫全名")
        eq("好感 +30", prof["affection"], 30.0)
        prof = memory.adjust_affection(sid, uid, 200)
        eq("好感夹顶 100", prof["affection"], 100.0)
        prof = memory.adjust_affection(sid, uid, -250)
        eq("好感夹底 -100", prof["affection"], -100.0)
        eq("画像保留", memory.get_user_profile(sid, uid)["impression"], "喜欢全彩，讨厌被叫全名")

        memory.add_facts(sid, ["用户喜欢全彩漫画", "用户周末常熬夜打游戏"])
        top = memory.recall_facts(sid, "全彩漫画")
        true("召回首条命中全彩", top and "全彩" in top[0])

        pid = memory.add_pending_fact(sid, "用户可能养了一只猫")
        true("待核实有 id", pid is not None)
        true("待核实列表含该条", any(f == "用户可能养了一只猫" for _, f in memory.list_pending_facts(sid)))
        true("核实后转入事实", memory.confirm_pending_fact(sid, pid))
        true("核实后待核实清空", memory.list_pending_facts(sid) == [])
        true("核实后事实可查", "用户可能养了一只猫" in memory.get_facts(sid, limit=50))
        true("按人记忆文本含画像", "喜欢全彩" in memory.get_user_memory_text(sid, uid, query="全彩"))
    finally:
        memory.clear_session(sid)
        eq("清理后记忆为空", memory.get_memory_text(sid), "")


def test_runner_wiring():
    section("runner/nl 接线：戳一戳开窗口、群消息记冷热场")
    from bot.handlers import nl
    from bot import runner

    # 戳一戳事件：只开窗口，不发消息（离线可断言窗口状态）
    evt = {
        "post_type": "notice", "notice_type": "notify", "sub_type": "poke",
        "self_id": 123, "target_id": 123, "group_id": 999888, "user_id": 777,
    }
    asyncio.run(runner.handle_event(evt))
    true("戳一戳后追问窗口有效", nl.is_followup_active(999888, 777))
    nl._followup.close(999888, 777)

    wgt = nl.note_group_message(999889, now=time.time())
    true("群消息记冷热场返回权重", wgt in (0.25, 1.0, 1.5))

def test_round1_gaps():
    """第1轮缺口 A/B 回归（按本文件自有 runner 风格写，不用 pytest monkeypatch）。"""
    section("round1: 按人记忆上下文 + 代码块跳过贴图")
    from bot import ai_chat, memory
    from bot.handlers import nl

    # --- 缺口 A：_get_context_text ---
    orig_mem = memory.get_memory_text
    orig_user = memory.get_user_memory_text
    orig_hist = ai_chat._get_history_text
    orig_meme = ai_chat.memes.meme_context
    try:
        memory.get_memory_text = lambda gid: "群长期记忆条目"
        ai_chat._get_history_text = lambda gid: "近期对话历史"
        ai_chat.memes.meme_context = lambda text, max_entries=2: ""
        memory.get_user_memory_text = lambda gid, uid, query="": f"【用户画像】用户:{uid} 偏好:纯爱"
        ctx = ai_chat._get_context_text(group_id=12345, user_message="找本子", user_id=9999)
        true("按人记忆追加进上下文", "【用户画像】用户:9999 偏好:纯爱" in ctx)
        true("长期记忆仍在上下文", "【长期记忆】\n群长期记忆条目" in ctx)
        memory.get_user_memory_text = lambda gid, uid, query="": ""
        ctx_zero = ai_chat._get_context_text(group_id=12345, user_message="找本子", user_id=0)
        ctx_empty = ai_chat._get_context_text(group_id=12345, user_message="找本子", user_id=9999)
        eq("user_id=0 时格式不变", ctx_zero, "【长期记忆】\n群长期记忆条目\n近期对话历史")
        eq("按人记忆为空时格式不变", ctx_empty, "【长期记忆】\n群长期记忆条目\n近期对话历史")
        true("空记忆不留三连空行", "\n\n\n" not in ctx_empty)
    finally:
        memory.get_memory_text = orig_mem
        memory.get_user_memory_text = orig_user
        ai_chat._get_history_text = orig_hist
        ai_chat.memes.meme_context = orig_meme

    # --- 缺口 A：group_chat 透传 user_id ---
    captured = {}
    orig_ctx = ai_chat._get_context_text
    orig_client = ai_chat._get_client
    orig_save = ai_chat.save_history
    try:
        def mock_get_context(group_id, user_message="", user_id=0):
            captured["group_id"] = group_id
            captured["user_id"] = user_id
            return "mock_history"
        class MockResp:
            content = [type("Block", (), {"text": "回复内容"})()]
        class MockMessages:
            def create(self, **kwargs):
                return MockResp()
        class MockClient:
            messages = MockMessages()
        ai_chat._get_context_text = mock_get_context
        ai_chat._get_client = lambda: MockClient()
        ai_chat.save_history = lambda *a, **k: None
        reply = ai_chat.group_chat(group_id=777, user_message="你好", user_id=888)
        eq("group_chat 透传后返回", reply, "回复内容")
        eq("group_chat 透传 user_id", captured.get("user_id"), 888)
    finally:
        ai_chat._get_context_text = orig_ctx
        ai_chat._get_client = orig_client
        ai_chat.save_history = orig_save

    # --- 缺口 B：_send_persona ---
    orig_io = nl.io_call
    orig_cfg = nl._humanity_cfg
    try:
        sent = []
        async def mock_io_call(func, *args, **kwargs):
            sent.append(args[1] if len(args) > 1 else None)
            return True
        nl.io_call = mock_io_call
        nl._humanity_cfg = lambda key, default=None: False
        code_text = "哈哈给你看这段代码：\n```python\nprint('hello')\n```"
        sent.clear()
        asyncio.run(nl._send_persona(session_id=1001, text=code_text, reply_msg_id=0))
        true("代码块不自动补贴图", len(sent) == 1 and "[[sticker:" not in sent[0])
        sent.clear()
        asyncio.run(nl._send_persona(session_id=1001, text="哈哈太好笑了", reply_msg_id=0))
        true("普通情绪文本正常补贴图", len(sent) == 1 and "[[sticker:开心]]" in sent[0])
        sent.clear()
        asyncio.run(nl._send_persona(session_id=1001, text="哈哈 [[sticker:开心]]", reply_msg_id=0))
        true("已有贴图不重复追加", len(sent) == 1 and sent[0].count("[[sticker:") == 1)
    finally:
        nl.io_call = orig_io
        nl._humanity_cfg = orig_cfg


def test_round2_gaps():
    """第2轮缺口 A 剩余透传点回归（按本文件自有 runner 风格写）。"""
    section("round2: 分类/澄清/影子/主动插话透传 user_id")
    from bot import ai_chat, config, humanity
    from bot.handlers import nl

    class _Block:
        def __init__(self, text):
            self.text = text
    class _Msgs:
        def __init__(self, text):
            self._text = text
        def create(self, **kwargs):
            return type("Resp", (), {"content": [_Block(self._text)]})()
    class _Client:
        def __init__(self, text):
            self.messages = _Msgs(text)

    # --- classify_intent / generate_clarify 透传 ---
    orig_ctx = ai_chat._get_context_text
    orig_client = ai_chat._get_client
    captured = {}
    try:
        def mock_ctx(group_id, user_message="", user_id=0):
            captured["group_id"] = group_id
            captured["user_id"] = user_id
            return "mock_context"
        ai_chat._get_context_text = mock_ctx
        ai_chat._get_client = lambda: _Client('{"action": "chat", "confidence": 0.9}')
        ai_chat.classify_intent("测试消息", group_id=1001, user_id=2002)
        eq("classify 透传 user_id", captured.get("user_id"), 2002)
        eq("classify 透传 group_id", captured.get("group_id"), 1001)
        captured.clear()
        ai_chat._get_client = lambda: _Client("您是指哪一项？")
        ai_chat.generate_clarify(group_id=1001, user_message="我想查一下", candidates=["搜漫画"], user_id=2002)
        eq("clarify 透传 user_id", captured.get("user_id"), 2002)
    finally:
        ai_chat._get_context_text = orig_ctx
        ai_chat._get_client = orig_client

    # --- shadow_log 透传（只记不发） ---
    orig_classify = ai_chat.classify_intent
    orig_budget = nl.antiban.budget_check
    orig_io = nl.io_call
    shadow_calls = []
    try:
        def mock_classify(user_message, group_id=0, user_id=0):
            captured["shadow_user_id"] = user_id
            return {"action": "chat", "confidence": 0.9}
        ai_chat.classify_intent = mock_classify
        nl.antiban.budget_check = lambda *a, **k: True
        async def mock_io(fn, *args, **kwargs):
            shadow_calls.append(args)
            return True
        nl.io_call = mock_io
        asyncio.run(nl.shadow_log(session_id=3003, user_id=4004, text="采样消息"))
        eq("shadow 透传 user_id", captured.get("shadow_user_id"), 4004)
        true("shadow 只记不发（走 _append_shadow）", len(shadow_calls) == 1 and isinstance(shadow_calls[0][0], dict) and shadow_calls[0][0].get("user") == 4004)
    finally:
        ai_chat.classify_intent = orig_classify
        nl.antiban.budget_check = orig_budget
        nl.io_call = orig_io

    # --- maybe_proactive 透传 ---
    orig_sleep = humanity.is_sleep_time
    orig_weight = nl._field.weight
    orig_blocked = nl._streak.blocked
    orig_judge = nl._judge_relevant
    orig_think = ai_chat.think
    orig_group_chat = ai_chat.group_chat
    orig_send = nl._send_persona
    orig_pro_cfg = dict(config.CONFIG.get("proactive_reply", {}))
    try:
        humanity.is_sleep_time = lambda h, s=23, e=8: False
        nl._field.weight = lambda sid: 1.0
        nl._streak.blocked = lambda sid: False
        nl._judge_relevant = lambda sid, txt: (True, 0.9)
        ai_chat.think = lambda *a, **k: {"think": "主动接话思考"}
        def mock_group_chat(group_id, user_message, images=None, thought="", user_id=0):
            captured["pro_user_id"] = user_id
            captured["pro_group_id"] = group_id
            return "插话内容"
        ai_chat.group_chat = mock_group_chat
        async def mock_send(*a, **k):
            return None
        nl._send_persona = mock_send
        config.CONFIG["proactive_reply"] = {"enabled": True, "sample_probability": 1.0, "judge_min_confidence": 0.6, "daily_max_per_group": 10, "group_cooldown_seconds": 0}
        nl._proactive_last.pop(5005, None)
        nl._proactive_daily.pop(5005, None)
        handled = asyncio.run(nl.maybe_proactive(session_id=5005, user_id=6006, text="插话触发词"))
        true("maybe_proactive 命中后返回 True", handled is True)
        eq("maybe_proactive 透传 user_id", captured.get("pro_user_id"), 6006)
        eq("maybe_proactive 透传 session 作 group_id", captured.get("pro_group_id"), 5005)
        nl._proactive_last.pop(5005, None)
        nl._proactive_daily.pop(5005, None)
        nl._streak._counts.pop(5005, None) if hasattr(nl._streak, "_counts") else None
    finally:
        humanity.is_sleep_time = orig_sleep
        nl._field.weight = orig_weight
        nl._streak.blocked = orig_blocked
        nl._judge_relevant = orig_judge
        ai_chat.think = orig_think
        ai_chat.group_chat = orig_group_chat
        nl._send_persona = orig_send
        config.CONFIG["proactive_reply"] = orig_pro_cfg



def main():
    test_split()
    test_followup_field_sleep()
    test_streak_duel_mood()
    test_memory_relation()
    test_runner_wiring()
    test_round1_gaps()
    test_round2_gaps()
    print(f"\n{'=' * 40}\n通过 {_pass} / 失败 {_fail}")
    if _failures:
        for name, msg in _failures:
            print(f"  - {name}: {msg}")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
