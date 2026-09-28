"""
JM Bot Plugin 测试套件
独立测试（不依赖 AstrBot 运行时），覆盖辅助函数和边界情况
"""
import sys
import os
import json
import tempfile
import io

# 添加插件目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 测试计数器
_pass = 0
_fail = 0
_failures: list[str] = []


def ok(name: str):
    global _pass
    _pass += 1
    print(f"  PASS  {name}")


def fail(name: str, msg: str = ""):
    global _fail
    _fail += 1
    _failures.append(f"  FAIL  {name}: {msg}")
    print(f"  FAIL  {name}: {msg}")


def eq(name: str, actual, expected):
    if actual == expected:
        ok(name)
    else:
        fail(name, f"expected {expected!r}, got {actual!r}")


def true(name: str, cond):
    if cond:
        ok(name)
    else:
        fail(name, "expected truthy, got falsy")


def false(name: str, cond):
    if not cond:
        ok(name)
    else:
        fail(name, "expected falsy, got truthy")


def section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ═══════════════════════════════════════════
# Section 1: download.py 辅助函数
# ═══════════════════════════════════════════

def test_progress_bar():
    from download import _format_progress_bar

    eq("bar(0,0)", _format_progress_bar(0, 0), "[░░░░░░░░░░]")
    eq("bar(0,100)", _format_progress_bar(0, 100), "[░░░░░░░░░░]")
    eq("bar(50,100)", _format_progress_bar(50, 100), "[█████░░░░░]")
    eq("bar(100,100)", _format_progress_bar(100, 100), "[██████████]")
    eq("bar(101,100)", _format_progress_bar(101, 100), "[██████████]")
    eq("bar(5,0)", _format_progress_bar(5, 0), "[░░░░░░░░░░]")
    eq("bar(custom)" , _format_progress_bar(3, 10, width=5), "[██░░░]")

    # 边界
    true("bar(-1,100)", "[" in _format_progress_bar(-1, 100))
    true("bar(0,-1)", "[" in _format_progress_bar(0, -1))


def test_format_eta():
    from download import _format_eta

    eq("eta(0,0)", _format_eta(0, 0, 0, 0), "")
    eq("eta(0,100,0)", _format_eta(0, 100, 0, 0), "")
    eq("eta(100,100)", _format_eta(100, 100, 1024, 102400), "")
    eq("eta(completed>total)", _format_eta(200, 100, 1024, 102400), "")

    # 有速度但无已下载图片，ETA 不显示（需 done > 0 且有 bytes_downloaded）
    result = _format_eta(0, 100, 1024, 0)
    eq("eta(0 done no eta)", result, "")

    result = _format_eta(1, 100, 1024, 1024)
    true("eta(has eta)", "⏱" in result)

    # 负速度
    eq("eta(neg speed)", _format_eta(0, 100, -1, 0), "")


def test_format_size_static():
    from download import _format_size_static

    eq("fmt(0)", _format_size_static(0), "0.0 B")
    eq("fmt(500)", _format_size_static(500), "500.0 B")
    eq("fmt(1024)", _format_size_static(1024), "1.0 KB")
    eq("fmt(1536)", _format_size_static(1536), "1.5 KB")
    eq("fmt(1048576)", _format_size_static(1048576), "1.0 MB")
    eq("fmt(1073741824)", _format_size_static(1073741824), "1.0 GB")


def test_find_album_dir():
    from download import find_album_dir

    with tempfile.TemporaryDirectory() as tmpdir:
        # 精确匹配
        os.makedirs(os.path.join(tmpdir, "123456"), exist_ok=True)
        eq("find exact", find_album_dir(tmpdir, "123456"), os.path.join(tmpdir, "123456"))

        # JM 前缀匹配
        os.makedirs(os.path.join(tmpdir, "[JM123457] title"), exist_ok=True)
        eq("find prefix", find_album_dir(tmpdir, "123457"), os.path.join(tmpdir, "[JM123457] title"))

        # 无匹配 → 返回最新修改目录或 base_dir
        result = find_album_dir(tmpdir, "999999")
        true("find fallback", os.path.isdir(result) or result == tmpdir)


def test_count_downloaded_files():
    from download import _count_downloaded_files

    with tempfile.TemporaryDirectory() as tmpdir:
        album_dir = os.path.join(tmpdir, "123456")
        os.makedirs(album_dir)
        # 创建一些模拟文件
        for i in range(5):
            with open(os.path.join(album_dir, f"img_{i:03d}.jpg"), "wb") as f:
                f.write(b"x" * 1000)
        # 创建 photo.yml（应被排除）
        with open(os.path.join(album_dir, "photo.yml"), "w") as f:
            f.write("name: test")

        result = {"photo_count": 0, "image_count": 0, "total_size": 0, "total_size_str": ""}
        _count_downloaded_files("123456", tmpdir, result)

        eq("count images", result["image_count"], 5)
        # total_size includes .yml file too (10 bytes for "name: test")
        true("count size > 5000", result["total_size"] >= 5000)
        true("count size_str", len(result["total_size_str"]) > 0)


# ═══════════════════════════════════════════
# Section 2: messages.py 文案系统
# ═══════════════════════════════════════════

def test_messages():
    from messages import M, M_single

    # M() 随机选取变体
    text = M("ack")
    true("M(ack) returns text", isinstance(text, str) and len(text) > 0)

    # M() 带格式化参数
    text = M("download_confirm", id="123456", warning="")
    true("M(download_confirm)", "123456" in text)

    # M_single() 不随机
    text = M_single("search_item", i=1, id="123456", title="测试", author="作者")
    true("M_single(search_item)", "123456" in text and "测试" in text)

    # 不存在的 key 返回 key 本身
    text = M("nonexistent_key")
    eq("M(unknown)", text, "nonexistent_key")


def test_messages_safe_format():
    from messages import _safe_format

    # 正常替换
    eq("safe normal", _safe_format("{name}喵", name="本喵"), "本喵喵")

    # 花括号在参数中不被解析
    eq("safe braces", _safe_format("{msg}", msg="{not_a_placeholder}"), "{not_a_placeholder}")

    # 缺少参数留空或保留原样
    result = _safe_format("{name}{missing}", name="test")
    true("safe missing", "test" in result)


# ═══════════════════════════════════════════
# Section 3: utils.py 工具函数
# ═══════════════════════════════════════════

def test_format_size():
    from utils import format_size

    eq("fmt(0)", format_size(0), "0.0 B")
    eq("fmt(500)", format_size(500), "500.0 B")
    eq("fmt(1024)", format_size(1024), "1.0 KB")
    eq("fmt(1048576)", format_size(1048576), "1.0 MB")
    eq("fmt(1073741824)", format_size(1073741824), "1.0 GB")
    eq("fmt(1099511627776)", format_size(1099511627776), "1.0 TB")


def test_get_dir_info():
    from utils import get_dir_info

    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建文件
        with open(os.path.join(tmpdir, "test.txt"), "w") as f:
            f.write("hello" * 1000)  # 5KB

        total, subdirs, files = get_dir_info(tmpdir)
        eq("dir files", files, 1)
        eq("dir subdirs", subdirs, 0)
        true("dir total > 0", total > 0)

        # 不存在的目录
        total, subdirs, files = get_dir_info(os.path.join(tmpdir, "nonexistent"))
        eq("dir nonexist", total, 0)
        eq("dir nonexist subdirs", subdirs, 0)
        eq("dir nonexist files", files, 0)


def test_clean_old_dirs():
    from utils import clean_old_dirs

    with tempfile.TemporaryDirectory() as tmpdir:
        # 不存在目录
        removed, freed, errors = clean_old_dirs(os.path.join(tmpdir, "nonexistent"))
        eq("clean nonexist removed", removed, 0)
        eq("clean nonexist freed", freed, 0)
        true("clean nonexist errors", len(errors) > 0 and "不存在" in errors[0])

        # 空目录
        removed, freed, errors = clean_old_dirs(tmpdir, 7)
        eq("clean empty", removed, 0)


def test_get_free_space():
    from utils import get_free_space

    free = get_free_space("C:\\")
    true("free space C:", free > 0 or free == -1)


# ═══════════════════════════════════════════
# Section 4: personas.py
# ═══════════════════════════════════════════

def test_personas():
    from personas import PERSONAS, get_persona_config

    eq("persona count", len(PERSONAS), 7)

    for i in range(7):
        cfg = get_persona_config(i)
        true(f"persona {i} has name", len(cfg["name"]) > 0)
        true(f"persona {i} has prompt", len(cfg["system_prompt"]) > 0)

    # 超出范围回退到 1
    cfg = get_persona_config(99)
    eq("persona fallback", cfg["name"], PERSONAS[1]["name"])


# ═══════════════════════════════════════════
# Section 5: state.py
# ═══════════════════════════════════════════

def test_state_rate_limit():
    from state import JMBotState
    import time

    s = JMBotState()
    remaining, blocked = s.check_rate_limit(123)
    false("fresh no block", blocked)

    s.mark_rate_limit(123)
    remaining, blocked = s.check_rate_limit(123)
    true("after mark blocked", blocked)

    # 重置全局
    s.reset_global_cooldown()
    s._last_group_time[123] = 0
    remaining, blocked = s.check_rate_limit(123)
    false("after reset no block", blocked)


def test_state_download():
    from state import JMBotState

    s = JMBotState()
    false("fresh not downloading", s.is_downloading("123"))
    s.mark_download_start("123")
    true("after start downloading", s.is_downloading("123"))
    s.mark_download_done("123")
    false("after done not downloading", s.is_downloading("123"))


def test_state_queue():
    from state import JMBotState
    import asyncio

    async def _test():
        s = JMBotState()
        eq("queue init 0", s.queue_size(), 0)
        await s.enqueue("111", "pdf", 1, 0)
        await s.enqueue("222", "pdf", 1, 0)
        eq("queue size 2", s.queue_size(), 2)
        item = await s.dequeue()
        eq("queue deq id", item[0], "111")
        eq("queue size 1 after deq", s.queue_size(), 1)
        await s.clear_queue()
        eq("queue size 0 after clear", s.queue_size(), 0)

    asyncio.run(_test())


def test_state_stop():
    from state import JMBotState

    s = JMBotState()
    false("fresh no stop", s.is_stop_requested("123"))
    s.request_stop("123")
    true("stop specific", s.is_stop_requested("123"))
    s.clear_stop_requests()
    false("after clear no stop", s.is_stop_requested("123"))

    s.request_stop("*")
    true("stop all", s.is_stop_requested("456"))


# ═══════════════════════════════════════════
# 运行
# ═══════════════════════════════════════════

def main():
    global _pass, _fail, _failures
    _pass = 0
    _fail = 0
    _failures = []

    print("JM Bot Plugin 测试套件")
    print("=" * 60)

    try:
        section("1. download.py 辅助函数")
        test_progress_bar()
        test_format_eta()
        test_format_size_static()
        test_find_album_dir()
        test_count_downloaded_files()
    except ImportError as e:
        print(f"  SKIP: jmcomic 未安装 ({e})")

    section("2. messages.py 文案系统")
    test_messages()
    test_messages_safe_format()

    section("3. utils.py 工具函数")
    test_format_size()
    test_get_dir_info()
    test_clean_old_dirs()
    test_get_free_space()

    section("4. personas.py")
    test_personas()

    section("5. state.py")
    test_state_rate_limit()
    test_state_download()
    test_state_queue()
    test_state_stop()

    print(f"\n{'=' * 60}")
    print(f"  结果: {_pass} PASS, {_fail} FAIL (共 {_pass + _fail})")
    print(f"{'=' * 60}")

    if _failures:
        print("\n失败列表:")
        for f in _failures:
            print(f)
        sys.exit(1)
    else:
        print("\n  All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
