#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
JM Bot v2 第三期离线验收（对应用户 2026-10-24 验收标准五条）。

方式：mock OneBot 事件 → runner.handle_event 真实代码路径 → 断言出站行为。
打桩点：LLM 用脚本化 FakeClient（按提示词特征分发）、JM 网络用 tools.execute_action、
NapCat 发送用记录器、下载 handler 用记录器。全程离线，不连 QQ、不调真模型。
运行：python tests/test_acceptance.py
"""
import asyncio
import http.server
import json
import logging
import os
import sys
import threading
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)  # jm_bot_v2/
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

_pass = 0
_fail = 0
_failures = []


def ok(name, evidence=""):
    global _pass
    _pass += 1
    print(f"  [PASS] {name}")
    if evidence:
        print(f"         证据: {evidence}")


def fail(name, msg):
    global _fail
    _fail += 1
    _failures.append((name, msg))
    print(f"  [FAIL] {name}: {msg}")


def check(name, cond, evidence=""):
    if cond:
        ok(name, evidence)
    else:
        fail(name, f"条件不成立；证据: {evidence}")


# ============================================================
# 环境与打桩
# ============================================================
from bot import ai_chat, config, runner, state, tools  # noqa: E402
from bot.messages import _M as MESSAGES  # noqa: E402
import bot.napcat as napcat  # noqa: E402

BOT_QQ = 3346134945
GROUP_A, GROUP_B = 777001, 777002
ADMIN_QQ = 3263123370

config.CONFIG["whitelist"] = {"enabled": True, "groups": [GROUP_A, GROUP_B], "private": [ADMIN_QQ]}
config.CONFIG["nl_mode"] = "hybrid"
config.CONFIG["admins"] = [ADMIN_QQ]
config.CONFIG["proactive_reply"] = {
    "enabled": True, "sample_probability": 1.0, "group_cooldown_seconds": 420,
    "daily_max_per_group": 6, "judge_min_confidence": 0.7,
}
config.ANTIBAN_MIN_SEND_INTERVAL = 0  # 验收环境关掉发送间隔，避免节流干扰断言

# 记忆 DB 指到临时文件，避免污染生产 memory.db
_MEM_DB = "/tmp/jmbot_accept_memory.db"
if os.path.exists(_MEM_DB):
    os.remove(_MEM_DB)
config.CONFIG["memory"] = {**config.CONFIG.get("memory", {}), "db_file": _MEM_DB}

# ---- NapCat 发送记录器 ----
SENT = []  # (kind, group_id, payload)


def _rec(kind):
    def f(*args):
        SENT.append((kind,) + tuple(args))
        return True
    return f


napcat.send_group_msg = _rec("msg")
napcat.send_group_reply = _rec("reply")
napcat.send_group_msg_segments = _rec("segments")
napcat.send_group_reply_segments = _rec("reply_segments")

# ---- JM 网络与下载记录器 ----
EXEC_CALLS = []
DOWNLOADS = []


def _fake_execute_action(action):
    EXEC_CALLS.append(dict(action))
    return f"【工具结果】{action.get('action')} 共 3 条： [111] 示例漫画 (作者甲)"


async def _fake_download(gid, aid, mid, output_format="pdf", skip_confirm=False):
    DOWNLOADS.append(("single", gid, aid, output_format, skip_confirm))


async def _fake_batch(gid, ids, mid, output_format="pdf"):
    DOWNLOADS.append(("batch", gid, list(ids), output_format))


tools.execute_action = _fake_execute_action
tools.cmd_download = _fake_download
tools.cmd_download_batch = _fake_batch


# ---- 脚本化 Fake LLM ----
class _Block:
    def __init__(self, text):
        self.text = text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]


class _Messages:
    def __init__(self, client):
        self._c = client

    def create(self, model=None, max_tokens=None, system=None, messages=None):
        return self._c.route(system, messages)


class FakeClient:
    def __init__(self):
        self.messages = _Messages(self)
        self.calls = []            # (kind, system, messages)
        self.classify_script = []  # 队列：dict 或 "RAISE"
        self.judge_result = {"join": True, "confidence": 0.9, "reason": "话题对口"}
        self.think_result = {"think": "这话题我熟，接一句准没错", "tone": "开心吐槽"}
        self.chat_reply = "好呀好呀，就这么定了喵~"

    def route(self, system, messages):
        s = system or ""
        user = messages[0]["content"] if messages else ""
        u = user if isinstance(user, str) else json.dumps(user, ensure_ascii=False)
        if "意图分类器" in s:
            self.calls.append(("classify", s, messages))
            nxt = self.classify_script.pop(0) if self.classify_script else {"action": "chat", "confidence": 0.95}
            if nxt == "RAISE":
                raise RuntimeError("fake classify boom")
            return _Resp(json.dumps(nxt, ensure_ascii=False))
        if "先在心里想一想" in s or "内心独白" in s:
            self.calls.append(("think", s, messages))
            return _Resp(json.dumps(self.think_result, ensure_ascii=False))
        if "要不要主动接一句话" in u:
            self.calls.append(("judge", s, messages))
            return _Resp(json.dumps(self.judge_result, ensure_ascii=False))
        if "没太听懂" in s:
            self.calls.append(("clarify", s, messages))
            return _Resp("唔…你说的是想搜漫画、看详情，还是先闲聊两句呀？")
        if "当前数据" in s:
            self.calls.append(("reply", s, messages))
            return _Resp("给你找到了，就是这些喵~ 需要哪本直接报 ID 我帮你下")
        self.calls.append(("chat", s, messages))
        return _Resp(self.chat_reply)

    def kinds(self):
        return [c[0] for c in self.calls]

    def reset(self):
        self.calls.clear()
        self.classify_script = []


FAKE = FakeClient()
ai_chat._client = FAKE

# ---- think 日志捕获 ----
THINK_LOGS = []


class _ThinkLogHandler(logging.Handler):
    def emit(self, record):
        try:
            THINK_LOGS.append(record.getMessage())
        except Exception:
            pass


_ai_logger = logging.getLogger("jm_bot.ai_chat")
_ai_logger.addHandler(_ThinkLogHandler())
_ai_logger.setLevel(logging.INFO)


# ============================================================
# 事件构造与驱动
# ============================================================
def group_event(text, user=ADMIN_QQ, group=GROUP_A, mid=100, segments=None, role="member"):
    ev = {"post_type": "message", "message_type": "group", "group_id": group,
          "user_id": user, "message_id": mid, "raw_message": text,
          "self_id": BOT_QQ, "sender": {"role": role}}
    if segments is not None:
        ev["message"] = segments
    return ev


def private_event(text, user=ADMIN_QQ, mid=100, segments=None):
    ev = {"post_type": "message", "message_type": "private", "user_id": user,
          "message_id": mid, "raw_message": text, "self_id": BOT_QQ, "sender": {}}
    if segments is not None:
        ev["message"] = segments
    return ev


async def drive(ev, wait=0.9):
    await runner.handle_event(ev)
    await asyncio.sleep(wait)


def sent_texts():
    out = []
    for item in SENT:
        for a in item[2:]:
            if isinstance(a, str):
                out.append(a)
    return out


# ============================================================
# 验收用例
# ============================================================
async def case1_proactive():
    print("\n=== 验收1：主动回消息（群聊会话内插话 + 护栏）===")
    # 测试侧时段保护：P0 夜间静默 23:00–08:00 是生产设计行为，用例内临时置为 0,0（永不触发），用例末恢复，不改生产默认值
    _hum_cfg = config.CONFIG.setdefault("humanity", {})
    _orig_sleep = (_hum_cfg.get("sleep_start_hour", 23), _hum_cfg.get("sleep_end_hour", 8))
    _hum_cfg["sleep_start_hour"] = 0
    _hum_cfg["sleep_end_hour"] = 0
    SENT.clear(); FAKE.reset()
    FAKE.judge_result = {"join": True, "confidence": 0.92, "reason": "在聊直播，话题对口"}
    FAKE.chat_reply = "康神今晚真开播的话我必看，zdjd？"
    await drive(group_event("今晚有人一起看康神直播吗，群里好冷清"))
    texts = sent_texts()
    check("未唤醒群消息经评判后主动接话", any("康神今晚真开播" in t for t in texts),
          f"出站={texts}")
    check("评判调用真实发生（judge）", "judge" in FAKE.kinds(), f"调用链={FAKE.kinds()}")

    # 负例：评判拒绝 → 不发（换一个群避开冷却）
    SENT.clear(); FAKE.reset()
    FAKE.judge_result = {"join": False, "confidence": 0.9, "reason": "与我无关"}
    await drive(group_event("物业通知：明天停水", group=GROUP_B))
    check("评判拒绝时不插话", sent_texts() == [], f"出站={sent_texts()}")

    # 护栏：proactive 关闭 → 未唤醒消息零出站（唤醒门）
    SENT.clear(); FAKE.reset()
    config.CONFIG["proactive_reply"]["enabled"] = False
    await drive(group_event("今天天气不错", group=GROUP_B))
    config.CONFIG["proactive_reply"]["enabled"] = True
    check("proactive 关闭时群聊未唤醒零出站", sent_texts() == [], f"出站={sent_texts()}")
    _hum_cfg["sleep_start_hour"], _hum_cfg["sleep_end_hour"] = _orig_sleep


async def case2_meme():
    print("\n=== 验收2：简短接梗（热梗词典注入上下文）===")
    SENT.clear(); FAKE.reset()
    FAKE.classify_script = [{"action": "chat", "confidence": 0.95}]
    FAKE.chat_reply = "wkzkbl！真的假的，康神开播我必到场"
    await drive(private_event("kskbl，康神要开播了"))
    chat_calls = [c for c in FAKE.calls if c[0] == "chat"]
    system = chat_calls[0][1] if chat_calls else ""
    check("梗条目接法（zdjd）注入了聊天系统提示", "zdjd" in system,
          f"系统提示节选: …{system[system.find('热梗'):system.find('热梗') + 80] if '热梗' in system else '未找到热梗段'}…")
    texts = sent_texts()
    check("回复接住了梗（wkzkbl 对暗号）", any("wkzkbl" in t for t in texts), f"出站={texts}")


async def case3_tools_media():
    print("\n=== 验收3：发图 / 读图 / 主动搜索（有界工具循环）===")
    # 3a 发图：send_sticker 工具自主触发
    SENT.clear(); FAKE.reset()
    FAKE.classify_script = [{"action": "send_sticker", "mood": "开心", "confidence": 0.9}]
    FAKE.chat_reply = "图来了，乐呵乐呵就好喵~"
    await drive(private_event("发个表情包乐呵乐呵"))
    seg_sends = [it for it in SENT if it[0] in ("segments", "reply_segments")]
    has_image = any(
        isinstance(a, list) and any(isinstance(sg, dict) and sg.get("type") == "image" for sg in a)
        for it in seg_sends for a in it[2:]
    )
    check("模型自主触发发表情包（image 段出站）", has_image, f"段出站={seg_sends}")
    check("发图后还有一句人设接话", any("乐呵" in t for t in sent_texts()), f"出站文本={sent_texts()}")

    # 3b 读图：被唤醒消息带图 → image block 进模型
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080600000"
        "01f15c4890000000a49444154789c6360000000020001e221bc330000"
        "000049454e44ae426082")
    handler = type("H", (http.server.BaseHTTPRequestHandler,), {
        "do_GET": lambda self: (self.send_response(200),
                                self.send_header("Content-Type", "image/png"),
                                self.end_headers(), self.wfile.write(png)),
        "log_message": lambda *a: None,
    })
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/x.png"
    SENT.clear(); FAKE.reset()
    FAKE.classify_script = [{"action": "chat", "confidence": 0.95}]
    FAKE.chat_reply = "图里是个小色块，收到啦"
    ev = private_event(f"[CQ:image,url={url}] 看看这张图",
                       segments=[{"type": "image", "data": {"url": url}},
                                 {"type": "text", "data": {"text": "看看这张图"}}])
    await drive(ev, wait=1.2)
    srv.shutdown()
    img_in_model = False
    for kind, s, msgs in FAKE.calls:
        if kind == "chat":
            content = msgs[0]["content"]
            if isinstance(content, list) and any(
                    isinstance(b, dict) and b.get("type") == "image" for b in content):
                img_in_model = True
    check("图片以 image block 直传进模型", img_in_model,
          f"chat 调用数={len([c for c in FAKE.calls if c[0] == 'chat'])}")

    # 3c 主动搜索：有界工具循环（search → 续判 rank → 收束回复，工具恰 2 次）
    SENT.clear(); FAKE.reset(); EXEC_CALLS.clear()
    FAKE.classify_script = [
        {"action": "search", "query": "电锯人", "confidence": 0.95},
        {"action": "rank", "type": "day", "confidence": 0.9},
    ]
    await drive(private_event("帮我找电锯人的本子，再看看今天的排行榜"))
    check("工具被模型自调用 2 次（未超上限）", len(EXEC_CALLS) == 2,
          f"EXEC_CALLS={[c.get('action') for c in EXEC_CALLS]}")
    check("最终回复由工具结果生成", any("给你找到了" in t for t in sent_texts()),
          f"出站={sent_texts()}")


async def case4_think():
    print("\n=== 验收4：内心思考步（只落日志、不发送）+ 人格一致 ===")
    SENT.clear(); FAKE.reset(); THINK_LOGS.clear()
    FAKE.classify_script = [{"action": "chat", "confidence": 0.95}]
    FAKE.think_result = {"think": "他今天累坏了，先安慰，别整活", "tone": "耐心安慰"}
    FAKE.chat_reply = "累了就先歇会儿，饭要吃、觉也要睡，别硬撑喵"
    await drive(private_event("今天真的累死了"))
    check("think 步真实调用", "think" in FAKE.kinds(), f"调用链={FAKE.kinds()}")
    think_logs = [m for m in THINK_LOGS if "内心思考" in m]
    check("思考只落日志（含独白与语气）", bool(think_logs) and "先安慰" in think_logs[0],
          f"日志={think_logs[:1]}")
    texts = sent_texts()
    check("思考内容未被发送给用户", all("内心思考" not in t and "先安慰，别整活" not in t for t in texts),
          f"出站={texts}")
    check("回复与思考一致（安慰口吻）", any("歇会儿" in t for t in texts), f"出站={texts}")
    if think_logs and texts:
        print(f"         样本 思考→回复: 「{think_logs[0]}」 → 「{texts[-1]}」")


async def case4b_role_persona():
    print("\n=== 验收4 配套：切大肥鱼角色后 NL 人格一致 ===")
    from bot import roles
    SENT.clear(); FAKE.reset()
    FAKE.classify_script = [{"action": "chat", "confidence": 0.95}]
    FAKE.chat_reply = "事已至此，先吃饭吧！白饭管够喵"
    roles.set_group_role(GROUP_B, 7)
    try:
        segs = [{"type": "at", "data": {"qq": str(BOT_QQ)}},
                {"type": "text", "data": {"text": " 饿了怎么办"}}]
        await drive(group_event("[CQ:at,qq=3346134945] 饿了怎么办", group=GROUP_B, segments=segs))
        chat_calls = [c for c in FAKE.calls if c[0] == "chat"]
        system = chat_calls[0][1] if chat_calls else ""
        marker = roles.ROLES[7]["system"][:16]
        check("NL 聊天系统提示使用大肥鱼人设", marker in system,
              f"人设标记={marker!r}; 出站={sent_texts()}")
        check("think 步同样走当前角色（调用链含 think）", "think" in FAKE.kinds(),
              f"调用链={FAKE.kinds()}")
    finally:
        roles._group_roles.pop(GROUP_B, None)
        roles._save_roles()


async def case5_confirm_and_errors():
    print("\n=== 验收5 配套：确认状态机 / 分类失败明确提示 / 低置信澄清 / restart 管理员门 ===")
    # 批量下载先复述确认
    SENT.clear(); FAKE.reset(); DOWNLOADS.clear()
    FAKE.classify_script = [{"action": "download", "ids": ["123456", "234567"], "format": "pdf", "confidence": 0.95}]
    segs = [{"type": "at", "data": {"qq": str(BOT_QQ)}},
            {"type": "text", "data": {"text": " 把123456和234567都下了"}}]
    await drive(group_event("[CQ:at,qq=3346134945] 把123456和234567都下了", segments=segs))
    texts = sent_texts()
    check("批量下载先复述确认、未执行", any("123456" in t and "确认" in t for t in texts) and DOWNLOADS == [],
          f"出站={texts}; 下载记录={DOWNLOADS}")
    # 用户回「确认」（无唤醒词，靠 has_pending 路由）
    await drive(group_event("确认"))
    check("确认后批量下载真正执行", any(d[0] == "batch" and d[2] == ["123456", "234567"] for d in DOWNLOADS),
          f"下载记录={DOWNLOADS}")

    # 分类失败 → 明确提示 ask_error（不装懂、不回退闲聊）
    SENT.clear(); FAKE.reset()
    FAKE.classify_script = ["RAISE"]
    await drive(private_event("嗯嗯嗯那个啥"))
    check("分类失败回明确错误提示", any(t in MESSAGES["ask_error"] for t in sent_texts()),
          f"出站={sent_texts()}")

    # 低置信 → 反问澄清
    SENT.clear(); FAKE.reset()
    FAKE.classify_script = [{"action": "chat", "confidence": 0.3}]
    await drive(private_event("那个那个东西"))
    check("低置信走澄清反问", any("搜漫画" in t and "闲聊" in t for t in sent_texts()),
          f"出站={sent_texts()}")

    # restart 管理员门
    SENT.clear(); FAKE.reset()
    await drive(group_event("/jm restart", user=999888, role="member"))
    texts = sent_texts()
    check("非管理员 restart 被拒", any(t in MESSAGES["restart_forbidden"] for t in texts),
          f"出站={texts}")
    SENT.clear()
    await drive(group_event("/jm restart", user=ADMIN_QQ, role="member"))
    texts = sent_texts()
    check("白名单私聊号（admins）restart 放行", any(t in MESSAGES["restart_ok"] for t in texts),
          f"出站={texts}")


async def case6_shadow():
    print("\n=== 附加：shadow 模式只记不发 ===")
    log_path = os.path.join(config.BASE_DIR, "nl_shadow.log")
    before = open(log_path, encoding="utf-8").read() if os.path.exists(log_path) else ""
    SENT.clear(); FAKE.reset()
    FAKE.classify_script = [{"action": "search", "query": "电锯人", "confidence": 0.9}]
    config.CONFIG["nl_mode"] = "shadow"
    await drive(private_event("搜电锯人"))
    config.CONFIG["nl_mode"] = "hybrid"
    after = open(log_path, encoding="utf-8").read() if os.path.exists(log_path) else ""
    check("shadow 只记录意图、零出站", sent_texts() == [] and len(after) > len(before)
          and "电锯人" in after[len(before):],
          f"出站={sent_texts()}; 新增日志={after[len(before):][:120]}")


async def main():
    print("=" * 60)
    print("  JM Bot v2 第三期离线验收")
    print("=" * 60)
    await case1_proactive()
    await case2_meme()
    await case3_tools_media()
    await case4_think()
    await case4b_role_persona()
    await case5_confirm_and_errors()
    await case6_shadow()
    # 清理验收产生的测试会话历史，避免污染生产 chat_history.json
    for sid in (GROUP_A, GROUP_B, ADMIN_QQ):
        ai_chat._chat_history.pop(sid, None)
    ai_chat._save_history_disk()
    total = _pass + _fail
    print(f"\n{'=' * 60}")
    print(f"  ACCEPTANCE RESULTS: {_pass} PASS, {_fail} FAIL, {total} TOTAL")
    print(f"{'=' * 60}")
    if _failures:
        print("\n  FAILURES:")
        for name, msg in _failures:
            print(f"    - {name}: {msg}")
    return _fail == 0


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
