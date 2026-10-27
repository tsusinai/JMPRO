#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
JM Bot v2 第三期单元测试（NL 工具层 / 记忆 / 热梗 / 限流预算 / 意图归一 / 唤醒与待确认）。
独立运行：python tests/test_phase3.py ；全程离线（网络与发送均打桩）。
"""
import asyncio
import json
import os
import sys
import tempfile
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


# ============================================================
def test_antiban_budget():
    section("antiban: AI 预算（分类/生成分开、按群隔离、忙提示节流）")
    from bot import antiban, config

    orig_c = config.ANTIBAN_AI_CLASSIFY_PER_MINUTE
    orig_g = config.ANTIBAN_AI_GENERATE_PER_MINUTE
    orig_glob = config.ANTIBAN_AI_MAX_PER_MINUTE
    try:
        config.ANTIBAN_AI_CLASSIFY_PER_MINUTE = 3
        config.ANTIBAN_AI_GENERATE_PER_MINUTE = 2
        config.ANTIBAN_AI_MAX_PER_MINUTE = 100
        s1, s2 = 88110001, 88110002
        true("classify 1/3 通过", antiban.budget_check(s1, "classify"))
        true("classify 2/3 通过", antiban.budget_check(s1, "classify"))
        true("classify 3/3 通过", antiban.budget_check(s1, "classify"))
        true("classify 第 4 次超限", not antiban.budget_check(s1, "classify"))
        true("classify 按 session 隔离", antiban.budget_check(s2, "classify"))
        true("generate 与 classify 分开计数", antiban.budget_check(s1, "generate"))
        true("generate 2/2 通过", antiban.budget_check(s1, "generate"))
        true("generate 第 3 次超限", not antiban.budget_check(s1, "generate"))
        true("忙提示首次允许", antiban.budget_busy_reply_allowed(s1, 60))
        true("忙提示冷却内拒绝", not antiban.budget_busy_reply_allowed(s1, 60))
        true("忙提示 cooldown=0 立即允许", antiban.budget_busy_reply_allowed(s1, 0))
        try:
            antiban.budget_check(s1, "bogus")
            fail("budget_check 非法 kind 抛错", "no exception")
        except ValueError:
            ok("budget_check 非法 kind 抛错")
        true("check_ai_allowed 兼容封装可用", isinstance(antiban.check_ai_allowed(88110009), bool))
    finally:
        config.ANTIBAN_AI_CLASSIFY_PER_MINUTE = orig_c
        config.ANTIBAN_AI_GENERATE_PER_MINUTE = orig_g
        config.ANTIBAN_AI_MAX_PER_MINUTE = orig_glob


# ============================================================
def test_normalize():
    section("ai_chat.normalize_intent 意图归一")
    from bot.ai_chat import normalize_intent

    r = normalize_intent({"action": "download", "ids": [123, "456", "456", "abc"], "format": "zip", "confidence": 0.9})
    eq("批量 ids 去重过滤", r["ids"], ["123", "456"])
    eq("format 保留 zip", r["format"], "zip")
    eq("download 兼容 id=首个", r["id"], "123")
    r = normalize_intent({"action": "download", "id": "777", "confidence": 5})
    eq("单 id 旧格式归一", r["ids"], ["777"])
    eq("confidence 上限 clamp", r["confidence"], 1.0)
    r = normalize_intent({"action": "fly", "confidence": 0.9})
    eq("未知动作归 unknown", r["action"], "unknown")
    r = normalize_intent("not a dict")
    eq("非 dict 归 unknown/0", (r["action"], r["confidence"]), ("unknown", 0.0))
    r = normalize_intent({"action": "cache_clean", "days": 9999})
    eq("cache_clean days clamp 到 365", r["days"], 365)
    r = normalize_intent({"action": "voice"})
    eq("voice 缺省 status", r["mode"], "status")
    r = normalize_intent({"action": "send_sticker", "mood": "愤怒"})
    eq("sticker 非法 mood 归 开心", r["mood"], "开心")
    r = normalize_intent({"action": "info", "id": "abc"})
    eq("info 非数字 id 置空", r["id"], "")
    r = normalize_intent({"action": "chat"})
    eq("chat 缺省 confidence=1", r["confidence"], 1.0)


# ============================================================
def test_memory():
    section("memory: SQLite 长期记忆 CRUD / 压缩 / 清空")
    from bot import config, memory

    tmp = tempfile.mkdtemp(prefix="jmbot_mem_")
    db_path = os.path.join(tmp, "mem.db")
    orig_cfg = dict(config.CONFIG.get("memory", {}))
    config.CONFIG["memory"] = {**orig_cfg, "db_file": db_path, "enabled": True,
                               "keep_recent": 3, "max_facts": 5, "inject_facts": 2}
    if memory._db_conn is not None:
        memory._db_conn.close()
        memory._db_conn = None
    try:
        sid = 88220001
        memory.clear_session(sid)
        eq("初始记忆为空", memory.get_memory_text(sid), "")
        memory.set_summary(sid, "用户喜欢全彩漫画")
        memory.add_facts(sid, ["偏好 pdf", "偏好 pdf", "周五在线", "讨厌黑白"])
        eq("facts 去重", memory.get_facts(sid, limit=10), ["偏好 pdf", "周五在线", "讨厌黑白"])
        eq("inject_facts 限量取最近", memory.get_facts(sid), ["周五在线", "讨厌黑白"])
        true("memory_text 含摘要", "用户喜欢全彩漫画" in memory.get_memory_text(sid))
        true("memory_text 含事实", "讨厌黑白" in memory.get_memory_text(sid))
        eq("session_key 群聊", memory.session_key(sid), f"g:{sid}")

        # 压缩：keep_recent=3，5 条历史 → 旧 2 条折成摘要+事实
        memory._call_llm_orig = memory._call_llm
        memory._call_llm = lambda prompt: json.dumps(
            {"summary": "压缩后的摘要", "facts": ["新事实甲"]}, ensure_ascii=False)
        hist = [("群友", f"消息{i}") for i in range(5)]
        true("compress_now 条数达标时执行", memory.compress_now(88220002, hist))
        eq("压缩后摘要落盘", memory.get_summary(88220002), "压缩后的摘要")
        true("压缩后事实落盘", "新事实甲" in memory.get_facts(88220002, limit=10))
        true("compress_now 条数不足跳过", not memory.compress_now(88220002, hist[:3]))
        true("maybe_compress 小历史不调度", not memory.maybe_compress(sid, hist[:3]))
        memory._call_llm = memory._call_llm_orig

        memory.clear_session(sid)
        eq("clear_session 清空", memory.get_memory_text(sid), "")
    finally:
        config.CONFIG["memory"] = orig_cfg
        if memory._db_conn is not None:
            memory._db_conn.close()
            memory._db_conn = None


# ============================================================
def test_memes():
    section("memes: 热梗词典检索注入")
    from bot import memes

    true("词典已加载（>=10 条）", len(memes.ENTRIES) >= 10)
    hits = memes.find_memes("kskbl，康神要开播了")
    eq("kskbl 命中 1 条", len(hits), 1)
    true("命中含接法 zdjd", bool(hits) and "zdjd" in hits[0])
    true("哈基米命中", len(memes.find_memes("这只猫也太哈基米了")) >= 1)
    eq("无关文本不命中", memes.find_memes("今天天气不错适合出门"), [])
    ctx = memes.meme_context("kskbl zdjd")
    true("context 带热梗提示头", ctx.startswith("【热梗提示"))
    true("max_entries 生效", len(memes.find_memes("kskbl 哈基米 情绪价值", max_entries=2)) <= 2)


# ============================================================
def test_tools():
    section("tools: NL 统一工具层路由")
    from bot import tools
    from bot.roles import ROLES

    calls = {}

    async def fake_download(gid, aid, mid, output_format="pdf", skip_confirm=False):
        calls["download"] = (gid, aid, mid, output_format, skip_confirm)

    async def fake_batch(gid, ids, mid, output_format="pdf"):
        calls["batch"] = (gid, ids, mid, output_format)

    async def fake_role(gid, role_num, mid):
        calls["role"] = (gid, role_num, mid)

    orig = (tools.execute_action, tools.cmd_download, tools.cmd_download_batch, tools.cmd_role)
    tools.execute_action = lambda action: f"DATA:{action.get('action')}:{action.get('query', '')}"
    tools.cmd_download = fake_download
    tools.cmd_download_batch = fake_batch
    tools.cmd_role = fake_role
    try:
        ctx = tools.NlContext(session_id=88330001, user_id=111, reply_msg_id=5)
        r = asyncio.run(tools.run_tool("search", {"query": "电锯人"}, ctx))
        eq("search 返回 data", (r.kind, r.text), ("data", "DATA:search:电锯人"))
        r = asyncio.run(tools.run_tool("download", {"ids": ["123"], "format": "zip"}, ctx))
        eq("单 ID download direct", r.kind, "direct")
        time.sleep(0.2)
        eq("单 ID 走 cmd_download 且 skip_confirm", calls.get("download"),
           (88330001, "123", 5, "zip", True))
        r = asyncio.run(tools.run_tool("download", {"ids": ["1", "2"]}, ctx))
        eq("批量 download direct", r.kind, "direct")
        time.sleep(0.2)
        eq("批量走 cmd_download_batch", calls.get("batch"), (88330001, ["1", "2"], 5, "pdf"))
        r = asyncio.run(tools.run_tool("download", {"ids": []}, ctx))
        eq("无 ID 返回 data 提示", r.kind, "data")
        idx = next(i for i, x in enumerate(ROLES) if x["name"] == "大肥鱼")
        r = asyncio.run(tools.run_tool("role", {"role": "大肥鱼"}, ctx))
        eq("role 按名映射下标", calls.get("role"), (88330001, str(idx), 5))
        r = asyncio.run(tools.run_tool("send_sticker", {"mood": "开心"}, ctx))
        true("send_sticker 返回 direct/none", r.kind in ("direct", "none"))
        r = asyncio.run(tools.run_tool("nope", {}, ctx))
        eq("未知工具返回 data", r.kind, "data")
    finally:
        (tools.execute_action, tools.cmd_download, tools.cmd_download_batch, tools.cmd_role) = orig


# ============================================================
def test_nl_pending_and_runner():
    section("nl 待确认状态机 / runner 唤醒判定")
    from bot import config, runner
    from bot.handlers import nl

    sid, uid = 88440001, 222
    nl._pending[f"{sid}:{uid}"] = {"kind": "download", "params": {"ids": ["1", "2"]},
                                   "expires": time.time() + 60}
    true("has_pending 未过期为真", nl.has_pending(sid, uid))
    nl._pending[f"{sid}:{uid}"]["expires"] = time.time() - 1
    true("has_pending 过期自动清", not nl.has_pending(sid, uid))

    eq("plain_text 清 CQ", runner._plain_text("[CQ:at,qq=999] 大肥鱼 搜电锯人"), "大肥鱼 搜电锯人")
    eq("plain_text 图片占位", runner._plain_text("[CQ:image,file=x]看看"), "[图片]看看")
    ev = {"self_id": 999, "group_id": sid,
          "message": [{"type": "at", "data": {"qq": "999"}}, {"type": "text", "data": {"text": " 在吗"}}],
          "raw_message": "[CQ:at,qq=999] 在吗"}
    wake, _ = runner._is_wake(ev, "在吗", sid)
    true("@Bot 唤醒", wake)
    wake, rest = runner._is_wake({"self_id": 999, "group_id": sid, "raw_message": "大肥鱼，搜电锯人"},
                                 "大肥鱼，搜电锯人", sid)
    true("呼名唤醒并剥前缀", wake and rest == "搜电锯人")
    wake, _ = runner._is_wake({"self_id": 999, "group_id": sid, "raw_message": "今天天气不错"},
                              "今天天气不错", sid)
    true("普通群消息不唤醒", not wake)

    orig_wl = config.CONFIG.get("whitelist")
    try:
        config.CONFIG["whitelist"] = {"enabled": True, "groups": [111], "private": [222]}
        true("白名单群放行", runner._whitelist_allowed({"group_id": 111}, False))
        true("白名单外群拦截", not runner._whitelist_allowed({"group_id": 333}, False))
        true("白名单私聊放行", runner._whitelist_allowed({"user_id": 222}, True))
        true("白名单外私聊拦截", not runner._whitelist_allowed({"user_id": 444}, True))
    finally:
        config.CONFIG["whitelist"] = orig_wl


def main():
    print("=" * 60)
    print("  JM Bot v2 Phase-3 Unit Tests")
    print("=" * 60)
    test_antiban_budget()
    test_normalize()
    test_memory()
    test_memes()
    test_tools()
    test_nl_pending_and_runner()
    total = _pass + _fail
    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {_pass} PASS, {_fail} FAIL, {total} TOTAL")
    print(f"{'=' * 60}")
    if _failures:
        print("\n  FAILURES:")
        for name, msg in _failures:
            print(f"    - {name}: {msg}")
    return _fail == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
