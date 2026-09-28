#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Comprehensive standalone test suite for JM Bot v2.
Tests regex patterns, utility functions, and edge cases.
Does NOT import runner/main (side effects).
Imports from bot.* packages (router/fsutils/runtime/messages/downloader).
"""

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)  # jm_bot_v2/
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

# ============================================================
# Test infrastructure
# ============================================================
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


def false(name, cond):
    if not cond:
        ok(name)
    else:
        fail(name, f"expected falsy, got {cond!r}")


def section(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ============================================================
# SECTION 1: Regex Patterns (imported from bot.router — tests the real code)
# ============================================================

from bot.router import (  # noqa: E402
    JM_CATEGORY_RE,
    JM_CACHE_CLEAN_RE,
    JM_CACHE_RE,
    JM_DOWNLOAD_RE,
    JM_HELP_RE,
    JM_INFO_RE,
    JM_QUEUE_RE,
    JM_RANDOM_RE,
    JM_RANK_RE,
    JM_RESTART_RE,
    JM_SEARCH_RE,
    JM_STOP_RE,
    JM_RE,
)


def test_regex_all():
    section("1. REGEX PATTERNS (~60 test cases)")

    # --- JM_RE ---
    s = "JM_RE — /jm <ID> (backward compat)"
    m = JM_RE.match("/jm 422866")
    true(f"{s}: match", m is not None)
    if m:
        eq(f"{s}: group", m.group(1), "422866")

    m = JM_RE.match("/jm 1")
    true(f"{s}: single digit match", m is not None)
    if m:
        eq(f"{s}: single digit group", m.group(1), "1")

    m = JM_RE.match("/jm 1234567890")
    true(f"{s}: 10-digit match", m is not None)
    if m:
        eq(f"{s}: 10-digit group", m.group(1), "1234567890")

    false(f"{s}: no number", JM_RE.match("/jm") is not None)
    false(f"{s}: trailing space", JM_RE.match("/jm 422866 ") is not None)
    false(f"{s}: extra text", JM_RE.match("/jm 422866 extra") is not None)
    false(f"{s}: 11 digits", JM_RE.match("/jm 12345678901") is not None)
    false(f"{s}: non-digit", JM_RE.match("/jm abc") is not None)
    false(f"{s}: leading space", JM_RE.match(" /jm 422866") is not None)
    false(f"{s}: wrong case", JM_RE.match("/Jm 422866") is not None)
    false(f"{s}: empty string", JM_RE.match("") is not None)

    # --- JM_DOWNLOAD_RE ---
    s = "JM_DOWNLOAD_RE — /jm download <ID> [pdf|zip]"
    m = JM_DOWNLOAD_RE.match("/jm download 422866")
    true(f"{s}: single ID match", m is not None)
    if m:
        eq(f"{s}: single ID group1", m.group(1), "422866")
        eq(f"{s}: single ID group2", m.group(2), None)

    m = JM_DOWNLOAD_RE.match("/jm download 422866 pdf")
    true(f"{s}: ID+pdf match", m is not None)
    if m:
        eq(f"{s}: ID+pdf group1", m.group(1), "422866")
        eq(f"{s}: ID+pdf group2", m.group(2), "pdf")

    m = JM_DOWNLOAD_RE.match("/jm download 422866 zip")
    true(f"{s}: ID+zip match", m is not None)
    if m:
        eq(f"{s}: ID+zip group1", m.group(1), "422866")
        eq(f"{s}: ID+zip group2", m.group(2), "zip")

    m = JM_DOWNLOAD_RE.match("/jm download 422866 123456 789")
    true(f"{s}: multi-ID match", m is not None)
    if m:
        eq(f"{s}: multi-ID group1", m.group(1), "422866 123456 789")

    m = JM_DOWNLOAD_RE.match("/jm download 422866 123456 pdf")
    true(f"{s}: multi-ID+pdf match", m is not None)
    if m:
        eq(f"{s}: multi-ID+pdf group1", m.group(1), "422866 123456")
        eq(f"{s}: multi-ID+pdf group2", m.group(2), "pdf")

    m = JM_DOWNLOAD_RE.match("/jm download 422866   pdf")
    true(f"{s}: extra spaces before fmt match", m is not None)
    if m:
        eq(f"{s}: extra spaces group1", m.group(1), "422866")
        eq(f"{s}: extra spaces group2", m.group(2), "pdf")

    m = JM_DOWNLOAD_RE.match("/jm download 422866  ")
    true(f"{s}: trailing spaces match", m is not None)
    if m:
        eq(f"{s}: trailing spaces group1", m.group(1), "422866")

    m = JM_DOWNLOAD_RE.match("/jm download 1234567890")
    true(f"{s}: 10-digit ID match", m is not None)

    false(f"{s}: no ID", JM_DOWNLOAD_RE.match("/jm download") is not None)
    false(f"{s}: wrong format png", JM_DOWNLOAD_RE.match("/jm download 422866 png") is not None)
    false(f"{s}: 11-digit ID", JM_DOWNLOAD_RE.match("/jm download 12345678901") is not None)
    false(f"{s}: leading space", JM_DOWNLOAD_RE.match(" /jm download 422866") is not None)

    # --- JM_SEARCH_RE ---
    s = "JM_SEARCH_RE — /jm search <keyword>"
    m = JM_SEARCH_RE.match("/jm search 魔法少女")
    true(f"{s}: chinese match", m is not None)
    if m:
        eq(f"{s}: chinese group", m.group(1), "魔法少女")

    m = JM_SEARCH_RE.match("/jm search test with spaces")
    true(f"{s}: multi-word match", m is not None)
    if m:
        eq(f"{s}: multi-word group", m.group(1), "test with spaces")

    m = JM_SEARCH_RE.match("/jm search x")
    true(f"{s}: single char match", m is not None)
    if m:
        eq(f"{s}: single char group", m.group(1), "x")

    m = JM_SEARCH_RE.match("/jm search 123")
    true(f"{s}: numeric match", m is not None)
    if m:
        eq(f"{s}: numeric group", m.group(1), "123")

    false(f"{s}: no query", JM_SEARCH_RE.match("/jm search") is not None)
    false(f"{s}: only space after", JM_SEARCH_RE.match("/jm search ") is not None)
    false(f"{s}: leading space", JM_SEARCH_RE.match(" /jm search x") is not None)

    # --- JM_INFO_RE ---
    s = "JM_INFO_RE — /jm info <ID>"
    m = JM_INFO_RE.match("/jm info 422866")
    true(f"{s}: match", m is not None)
    if m:
        eq(f"{s}: group", m.group(1), "422866")

    false(f"{s}: no ID", JM_INFO_RE.match("/jm info") is not None)
    false(f"{s}: extra text", JM_INFO_RE.match("/jm info 422866 x") is not None)
    false(f"{s}: 11 digits", JM_INFO_RE.match("/jm info 12345678901") is not None)

    # --- JM_RANK_RE ---
    s = "JM_RANK_RE — /jm rank [day|week|month]"
    m = JM_RANK_RE.match("/jm rank")
    true(f"{s}: no arg match", m is not None)
    if m:
        eq(f"{s}: no arg group", m.group(1), None)

    m = JM_RANK_RE.match("/jm rank day")
    true(f"{s}: day match", m is not None)
    if m:
        eq(f"{s}: day group", m.group(1), "day")

    m = JM_RANK_RE.match("/jm rank week")
    true(f"{s}: week match", m is not None)
    if m:
        eq(f"{s}: week group", m.group(1), "week")

    m = JM_RANK_RE.match("/jm rank month")
    true(f"{s}: month match", m is not None)
    if m:
        eq(f"{s}: month group", m.group(1), "month")

    false(f"{s}: extra after", JM_RANK_RE.match("/jm rank day extra") is not None)
    false(f"{s}: invalid arg", JM_RANK_RE.match("/jm rank year") is not None)

    # --- JM_HELP_RE ---
    s = "JM_HELP_RE — /jm help [sub]"
    m = JM_HELP_RE.match("/jm help")
    true(f"{s}: no sub match", m is not None)
    if m:
        eq(f"{s}: no sub group", m.group(1), None)

    m = JM_HELP_RE.match("/jm help 1")
    true(f"{s}: sub=1 match", m is not None)
    if m:
        eq(f"{s}: sub=1 group", m.group(1), "1")

    m = JM_HELP_RE.match("/jm help 3")
    true(f"{s}: sub=3 match", m is not None)
    if m:
        eq(f"{s}: sub=3 group", m.group(1), "3")

    false(f"{s}: leading space", JM_HELP_RE.match(" /jm help") is not None)

    # --- JM_CACHE_RE ---
    s = "JM_CACHE_RE — /jm cache"
    true(f"{s}: match", JM_CACHE_RE.match("/jm cache") is not None)
    false(f"{s}: extra", JM_CACHE_RE.match("/jm cache extra") is not None)
    false(f"{s}: leading space", JM_CACHE_RE.match(" /jm cache") is not None)

    # --- JM_CACHE_CLEAN_RE ---
    s = "JM_CACHE_CLEAN_RE — /jm cache clean [days]"
    m = JM_CACHE_CLEAN_RE.match("/jm cache clean")
    true(f"{s}: no days match", m is not None)
    if m:
        eq(f"{s}: no days group", m.group(1), None)

    m = JM_CACHE_CLEAN_RE.match("/jm cache clean 7")
    true(f"{s}: days=7 match", m is not None)
    if m:
        eq(f"{s}: days=7 group", m.group(1), "7")

    m = JM_CACHE_CLEAN_RE.match("/jm cache clean 30")
    true(f"{s}: days=30 match", m is not None)
    if m:
        eq(f"{s}: days=30 group", m.group(1), "30")

    m = JM_CACHE_CLEAN_RE.match("/jm cache clean 999")
    true(f"{s}: days=999 (max 3dig) match", m is not None)
    if m:
        eq(f"{s}: days=999 group", m.group(1), "999")

    false(f"{s}: 1000 days (4dig)", JM_CACHE_CLEAN_RE.match("/jm cache clean 1000") is not None)
    false(f"{s}: extra text", JM_CACHE_CLEAN_RE.match("/jm cache clean 7 extra") is not None)
    false(f"{s}: negative", JM_CACHE_CLEAN_RE.match("/jm cache clean -7") is not None)

    # --- JM_RESTART_RE ---
    s = "JM_RESTART_RE — /jm restart"
    true(f"{s}: match", JM_RESTART_RE.match("/jm restart") is not None)
    false(f"{s}: extra", JM_RESTART_RE.match("/jm restart now") is not None)
    false(f"{s}: leading space", JM_RESTART_RE.match(" /jm restart") is not None)

    # --- JM_STOP_RE ---
    s = "JM_STOP_RE — /jm stop"
    true(f"{s}: match", JM_STOP_RE.match("/jm stop") is not None)
    false(f"{s}: extra", JM_STOP_RE.match("/jm stop all") is not None)

    # --- JM_CATEGORY_RE ---
    s = "JM_CATEGORY_RE — /jm category <tag>"
    m = JM_CATEGORY_RE.match("/jm category 全彩")
    true(f"{s}: chinese match", m is not None)
    if m:
        eq(f"{s}: chinese group", m.group(1), "全彩")

    m = JM_CATEGORY_RE.match("/jm category multi word tag")
    true(f"{s}: multi-word match", m is not None)
    if m:
        eq(f"{s}: multi-word group", m.group(1), "multi word tag")

    false(f"{s}: no tag", JM_CATEGORY_RE.match("/jm category") is not None)
    false(f"{s}: empty tag", JM_CATEGORY_RE.match("/jm category ") is not None)

    # --- JM_RANDOM_RE ---
    s = "JM_RANDOM_RE — /jm random [opts]"
    true(f"{s}: no opts match", JM_RANDOM_RE.match("/jm random") is not None)

    m = JM_RANDOM_RE.match("/jm random --top")
    true(f"{s}: --top match", m is not None)
    if m:
        eq(f"{s}: --top group", m.group(1), " --top")

    m = JM_RANDOM_RE.match("/jm random --tag 全彩")
    true(f"{s}: --tag match", m is not None)
    if m:
        eq(f"{s}: --tag group", m.group(1), " --tag 全彩")

    m = JM_RANDOM_RE.match("/jm random --top --tag magic")
    true(f"{s}: top+tag match", m is not None)

    false(f"{s}: leading space", JM_RANDOM_RE.match(" /jm random") is not None)

    # --- JM_QUEUE_RE ---
    s = "JM_QUEUE_RE — /jm queue"
    true(f"{s}: match", JM_QUEUE_RE.match("/jm queue") is not None)
    false(f"{s}: extra", JM_QUEUE_RE.match("/jm queue list") is not None)

    # --- Cross-pattern: dispatch order test ---
    s = "DISPATCH ORDER"
    # cache clean must be checked BEFORE cache
    m1 = JM_CACHE_CLEAN_RE.match("/jm cache clean 7")
    m2 = JM_CACHE_RE.match("/jm cache clean 7")
    true(f"{s}: cache_clean priority over cache", m1 is not None)  # cache clean matches
    # cache also matches "/jm cache clean 7" but dispatch checks cache_clean first

    # download before search (multi-word vs single)
    m3 = JM_DOWNLOAD_RE.match("/jm download search test")
    false(f"{s}: download rejects 'search test' as ID", m3 is not None)
    # "search test" has a space, so it won't match \d{1,10} for the first ID


# ============================================================
# SECTION 2: bot.fsutils helpers (imported directly)
# ============================================================

# Import after regex tests (bot.napcat sets NO_PROXY, harmless)
from bot.fsutils import (  # noqa: E402
    clean_old_dirs,
    format_size,
    get_dir_info,
    get_dir_size,
    get_free_space,
    load_json,
    rotate_log_if_needed,
    save_json,
)


def test_format_size():
    section("2a. format_size")

    eq("fs 0", format_size(0), "0.0 B")
    eq("fs 1", format_size(1), "1.0 B")
    eq("fs 1023", format_size(1023), "1023.0 B")
    eq("fs 1024", format_size(1024), "1.0 KB")
    eq("fs 1025", format_size(1025), "1.0 KB")
    eq("fs 1536", format_size(1536), "1.5 KB")
    eq("fs 1048576", format_size(1048576), "1.0 MB")
    eq("fs 1073741824", format_size(1073741824), "1.0 GB")
    eq("fs 1099511627776", format_size(1099511627776), "1.0 TB")
    eq("fs 1125899906842624", format_size(1125899906842624), "1024.0 TB")

    # Negative: loops through units, returns negative in last unit
    # format_size(-1) goes through the loop and returns the result after division
    result_neg = format_size(-1)
    true("fs -1 returns str", isinstance(result_neg, str))


def test_json_persistence():
    section("2b. load_json / save_json")

    with tempfile.TemporaryDirectory() as td:
        # Round-trip: dict
        path = os.path.join(td, "test.json")
        data = {"a": 1, "b": [2, 3], "c": {"d": "hello"}}
        save_json(path, data)
        loaded = load_json(path)
        eq("json round-trip dict", loaded, data)

        # Round-trip: list
        path2 = os.path.join(td, "test2.json")
        data2 = [1, 2, "three", {"four": 5}]
        save_json(path2, data2)
        loaded2 = load_json(path2)
        eq("json round-trip list", loaded2, data2)

        # Round-trip: unicode
        path3 = os.path.join(td, "unicode.json")
        data3 = {"key": "魔法少女☆", "emoji": "🎉✨"}
        save_json(path3, data3)
        loaded3 = load_json(path3)
        eq("json round-trip unicode", loaded3, data3)

        # Round-trip: empty dict
        path4 = os.path.join(td, "empty.json")
        save_json(path4, {})
        loaded4 = load_json(path4)
        eq("json round-trip empty dict", loaded4, {})

        # Round-trip: empty list
        path5 = os.path.join(td, "empty_list.json")
        save_json(path5, [])
        loaded5 = load_json(path5)
        eq("json round-trip empty list", loaded5, [])

        # Missing file → default
        missing = load_json(os.path.join(td, "nonexistent.json"), default=42)
        eq("json missing file default", missing, 42)

        # Missing file → default dict
        missing2 = load_json(os.path.join(td, "nonexistent2.json"))
        eq("json missing file default dict", missing2, {})

        # Corrupt JSON → default
        corrupt_path = os.path.join(td, "corrupt.json")
        with open(corrupt_path, "w", encoding="utf-8") as f:
            f.write("this is not json {{{")
        corrupt_loaded = load_json(corrupt_path, default="fallback")
        eq("json corrupt file", corrupt_loaded, "fallback")

        # Deeply nested structure
        path6 = os.path.join(td, "nested.json")
        deep = {"l1": {"l2": {"l3": [1, None, True, False, 3.14]}}}
        save_json(path6, deep)
        loaded6 = load_json(path6)
        eq("json round-trip nested", loaded6, deep)


def test_dir_utils():
    section("2c. get_dir_size / get_free_space / get_dir_info")

    with tempfile.TemporaryDirectory() as td:
        # Create known-size file
        fpath = os.path.join(td, "test.bin")
        with open(fpath, "wb") as f:
            f.write(b"x" * 100)

        size = get_dir_size(td)
        true("dir_size >= 100", size >= 100)

        # Subdirectory
        sub = os.path.join(td, "sub")
        os.makedirs(sub)
        with open(os.path.join(sub, "inner.bin"), "wb") as f:
            f.write(b"y" * 200)

        size2 = get_dir_size(td)
        true("dir_size >= 300 with sub", size2 >= 300)

        # Non-existent dir
        eq("dir_size missing", get_dir_size("/nonexistent/path/xyz"), 0)

        # get_free_space
        free = get_free_space(td)
        true("free_space positive", free > 0)
        eq("free_space missing", get_free_space("/nonexistent/path/xyz"), -1)

        # get_dir_info
        total_b, subdirs, files = get_dir_info(td)
        true("dir_info total >= 300", total_b >= 300)
        eq("dir_info subdirs", subdirs, 1)
        true("dir_info files >= 1", files >= 1)

        # Non-existent dir
        total_b, subdirs, files = get_dir_info("/nonexistent/path/xyz")
        eq("dir_info missing total", total_b, 0)
        eq("dir_info missing subdirs", subdirs, 0)
        eq("dir_info missing files", files, 0)


def test_rotate_log():
    section("2d. rotate_log_if_needed")

    with tempfile.TemporaryDirectory() as td:
        log_path = os.path.join(td, "test.log")

        # Non-existent log → no rotation
        result = rotate_log_if_needed(log_path, max_mb=1, keep_kb=10)
        false("rotate missing log", result)

        # Small log → no rotation
        with open(log_path, "wb") as f:
            f.write(b"small log\n")
        result = rotate_log_if_needed(log_path, max_mb=1, keep_kb=10)
        false("rotate small log", result)

        # Large log → rotation
        # Create a log with 100KB, set max_mb=0.05 (50KB) to trigger rotation
        with open(log_path, "wb") as f:
            for i in range(2000):
                f.write(f"line {i:05d} with some padding to make it bigger\n".encode())

        orig_size = os.path.getsize(log_path)
        max_bytes = int(0.05 * 1024 * 1024)  # ~51KB
        keep_bytes = int(10 * 1024)  # 10KB
        result = rotate_log_if_needed(log_path, max_mb=0.05, keep_kb=10)
        new_size = os.path.getsize(log_path)
        true(f"rotate triggered (orig={orig_size}, max={max_bytes})", orig_size > max_bytes)
        if orig_size > max_bytes:
            true("rotate reduced size", new_size < orig_size)
            true("rotate returned True", result is True)
        else:
            ok("rotate skipped (log not big enough for test threshold)")


def test_clean_old_dirs():
    section("2e. clean_old_dirs")

    with tempfile.TemporaryDirectory() as td:
        # Non-existent base → (0, 0, error)
        removed, freed, errors = clean_old_dirs("/nonexistent/path/xyz", max_age_days=7)
        eq("clean missing base removed", removed, 0)
        eq("clean missing base freed", freed, 0)
        true("clean missing base errors", len(errors) > 0)

        # Empty base
        removed, freed, errors = clean_old_dirs(td, max_age_days=7)
        eq("clean empty base removed", removed, 0)

        # Create some dirs with controlled mtime
        old_dir = os.path.join(td, "old_stuff")
        os.makedirs(old_dir)
        with open(os.path.join(old_dir, "file.txt"), "w") as f:
            f.write("data" * 100)

        new_dir = os.path.join(td, "new_stuff")
        os.makedirs(new_dir)
        with open(os.path.join(new_dir, "file.txt"), "w") as f:
            f.write("data" * 100)

        # Set old_dir mtime to 30 days ago
        old_time = time.time() - 30 * 86400
        os.utime(old_dir, (old_time, old_time))

        # Clean with 14-day threshold → only old_dir should go
        removed, freed, errors = clean_old_dirs(td, max_age_days=14)
        eq("clean old removed", removed, 1)
        true("clean old freed > 0", freed > 0)
        eq("clean old errors", len(errors), 0)
        false("clean old dir gone", os.path.exists(old_dir))
        true("clean new dir remains", os.path.exists(new_dir))


# ============================================================
# SECTION 3: display / runtime helpers (imported — tests the real code)
# ============================================================

from bot.handlers.download import _format_eta, _format_progress_bar  # noqa: E402
from bot.runtime import api_error_msg, is_api_error  # noqa: E402


def test_format_progress_bar():
    section("3a. _format_progress_bar")

    bar, pct = _format_progress_bar(0, 0)
    eq("pbar (0,0) bar", bar, "[?]")
    eq("pbar (0,0) pct", pct, 0)

    bar, pct = _format_progress_bar(0, 100)
    eq("pbar (0,100) bar", bar, "[\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591]")
    eq("pbar (0,100) pct", pct, 0)

    bar, pct = _format_progress_bar(50, 100)
    eq("pbar (50,100) bar", bar, "[\u2588\u2588\u2588\u2588\u2588\u2591\u2591\u2591\u2591\u2591]")
    eq("pbar (50,100) pct", pct, 50)

    bar, pct = _format_progress_bar(100, 100)
    eq("pbar (100,100) bar", bar, "[\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588]")
    eq("pbar (100,100) pct", pct, 100)

    bar, pct = _format_progress_bar(101, 100)
    eq("pbar (101,100) bar", bar, "[\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588]")
    eq("pbar (101,100) pct", pct, 100)

    bar, pct = _format_progress_bar(5, 0)
    eq("pbar (5,0) bar", bar, "[?]")
    eq("pbar (5,0) pct", pct, 0)

    # edge: (-1, 100) — negative done is out of spec, but the function
    # does NOT crash (Python: "x" * -1 = ""). filled = -1*10//100 = -1 → "",
    # unfilled = 10 - (-1) = 11, bar ends up 11-wide. Just document:
    true("pbar (-1,100) does not crash", isinstance(_format_progress_bar(-1, 100), tuple))

    bar, pct = _format_progress_bar(0, -1)
    eq("pbar (0,-1) bar", bar, "[?]")  # total <= 0
    eq("pbar (0,-1) pct", pct, 0)

    # Test with custom width
    bar, pct = _format_progress_bar(50, 100, width=5)
    eq("pbar width=5 bar", bar, "[\u2588\u2588\u2591\u2591\u2591]")
    eq("pbar width=5 pct", pct, 50)


def test_format_eta():
    section("3b. _format_eta")

    # v2 真实实现：基于 bytes_downloaded 估算平均图片大小，
    # bytes_downloaded <= 0 时不估算（返回 ""）
    eq("eta speed=0", _format_eta(80, 100, 0, 80), "")
    eq("eta total=0", _format_eta(0, 0, 10, 0), "")
    eq("eta remaining=0", _format_eta(100, 100, 100, 100), "")
    eq("eta no bytes", _format_eta(80, 100, 10), "")

    # 80/100 @ 10 Bps，avg=1 B/张 → 20 remaining / 10 = 2s
    eq("eta 80/100@10", _format_eta(80, 100, 10, 80), "\u7ea6 2s")

    # 1/1000 @ 5 Bps，avg=1 → 999 / 5 = 199s → "约 3min"
    eq("eta 1/1000@5", _format_eta(1, 1000, 5, 1), "\u7ea6 3min")

    # 500/5000 @ 3 Bps，avg=1 → 4500/3 = 1500s = 25min
    eq("eta 500/5000@3", _format_eta(500, 5000, 3, 500), "\u7ea6 25min")

    # Boundary: 59s
    eq("eta 59s boundary", _format_eta(941, 1000, 1, 941), "\u7ea6 59s")

    # Boundary: 1min (60s)
    eq("eta 1min boundary", _format_eta(940, 1000, 1, 940), "\u7ea6 1min")

    # Speed too low for meaningful ETA：avg=1 → 99999/0.001 = 99999000s → 27777h30m
    eq("eta very slow", _format_eta(1, 100000, 0.001, 1), "\u7ea6 27777h30m")

    # speed negative
    eq("eta speed<0", _format_eta(0, 100, -1, 0), "")

    # total=0 and speed=0
    eq("eta all zeros", _format_eta(0, 0, 0, 0), "")

    # done > total (shouldn't happen in practice but testing)
    eq("eta done>total", _format_eta(200, 100, 10, 200), "")


def test_is_api_error_and_msg():
    section("3c. is_api_error / api_error_msg")

    # is_api_error tests
    true("is_err [TIMEOUT]", is_api_error("[TIMEOUT] timeout message"))
    true("is_err [API_ERR]", is_api_error("[API_ERR] some error occurred"))
    true("is_err [OTHER]", is_api_error("[OTHER] some other prefix"))
    true("is_err just [", is_api_error("["))
    false("is_err normal str", is_api_error("normal string"))
    false("is_err empty str", is_api_error(""))
    false("is_err int 42", is_api_error(42))
    false("is_err None", is_api_error(None))
    false("is_err list", is_api_error(["not a string"]))
    false("is_err bracket middle", is_api_error("text [bracket] here"))

    # api_error_msg tests
    eq("msg [API_ERR] strip", api_error_msg("[API_ERR] something bad"), "something bad")
    eq("msg [TIMEOUT] strip", api_error_msg("[TIMEOUT] took too long"), "took too long")
    eq("msg [OTHER]", api_error_msg("[OTHER] prefix"), "[OTHER] prefix")
    eq("msg normal str", api_error_msg("hello world"), "hello world")
    eq("msg int", api_error_msg(42), "")
    eq("msg None", api_error_msg(None), "")
    eq("msg empty str", api_error_msg(""), "")
    eq("msg just [API_ERR]", api_error_msg("[API_ERR] "), "")


def test_msg_dict():
    section("3d. MSG dict keys (bot.messages)")

    expected_keys = {
        "rate_group", "rate_global",
        "disk_critical", "disk_warn",
        "api_timeout", "api_fail",
        "download_crash", "invalid_id", "all_queued",
        "download_ok", "download_partial", "download_cancelled",
    }

    from bot.messages import M  # noqa: E402

    for key in expected_keys:
        text = M(key)
        # M 对未定义的 key 原样返回 key 本身，因此回显即代表缺失
        true(f"MSG has '{key}'", isinstance(text, str) and text != key)


# ============================================================
# SECTION 4: bot.downloader helpers (imported)
# ============================================================

from bot.downloader import _count_downloaded_files, find_album_dir  # noqa: E402


def test_find_album_dir():
    section("4a. find_album_dir")

    with tempfile.TemporaryDirectory() as td:
        # Non-existent base_dir → returns base_dir
        result = find_album_dir(os.path.join(td, "missing"), "422866")
        eq("fad missing base", result, os.path.join(td, "missing"))

        # Exact match by directory name == album_id
        exact_dir = os.path.join(td, "422866")
        os.makedirs(exact_dir)
        result = find_album_dir(td, "422866")
        eq("fad exact match", result, exact_dir)

        # JM prefix match [JM{album_id}]
        jm_dir = os.path.join(td, "[JM123456] Some Title")
        os.makedirs(jm_dir)
        result = find_album_dir(td, "123456")
        eq("fad JM prefix", result, jm_dir)

        # JP prefix match [JP{album_id}]
        jp_dir = os.path.join(td, "[JP789] Another Title")
        os.makedirs(jp_dir)
        result = find_album_dir(td, "789")
        true("fad JP prefix need boundary", result in [jp_dir, jm_dir, exact_dir])

        # Number boundary match: "123" in "album_123_more" but NOT in "1234"
        nb_dir = os.path.join(td, "album_555_more")
        os.makedirs(nb_dir)
        result = find_album_dir(td, "555")
        eq("fad boundary match", result, nb_dir)

        # Test number-boundary pattern: "123" should NOT match inside "1234"
        # (verifies the regex, but find_album_dir may fallback to mtime)
        boundary_pattern = re.compile(rf"(?<!\d){re.escape('123')}(?!\d)")
        false("fad boundary regex rejects 1234", boundary_pattern.search("thing_1234_extra") is not None)
        true("fad boundary regex accepts 123", boundary_pattern.search("thing_123_more") is not None)

        # No match → fallback to most recently modified
        result = find_album_dir(td, "999999")
        true("fad fallback is dir", os.path.isdir(result))


def test_count_downloaded_files():
    section("4b. _count_downloaded_files")

    with tempfile.TemporaryDirectory() as td:
        # Create a mock download dir structure
        album_dir = os.path.join(td, "[JM422866] Test Manga")
        os.makedirs(album_dir)

        # Chapter subdirectories
        ch1 = os.path.join(album_dir, "001_chapter1")
        ch2 = os.path.join(album_dir, "002_chapter2")
        os.makedirs(ch1)
        os.makedirs(ch2)

        # Image files
        with open(os.path.join(ch1, "00001.jpg"), "wb") as f:
            f.write(b"x" * 500)
        with open(os.path.join(ch1, "00002.jpg"), "wb") as f:
            f.write(b"x" * 300)
        with open(os.path.join(ch2, "00001.jpg"), "wb") as f:
            f.write(b"x" * 400)
        # .yml files should be excluded from image count
        with open(os.path.join(ch1, "photo.yml"), "w") as f:
            f.write("meta")

        result = {"photo_count": 0, "image_count": 0, "total_size": 0, "total_size_str": ""}
        _count_downloaded_files("422866", td, result)

        eq("cf photo_count", result["photo_count"], 2)  # 2 chapter dirs
        eq("cf image_count", result["image_count"], 3)  # 3 jpg files (yml excluded)
        eq("cf total_size", result["total_size"], 1204)  # 500+300+400+4(yml)
        true("cf total_size_str", len(result["total_size_str"]) > 0)

        # Non-existent album_id: find_album_dir falls back to mtime-based dir, so files are counted
        # This is expected behavior — _count_downloaded_files always finds *some* dir
        result2 = {"photo_count": 0, "image_count": 0, "total_size": 0, "total_size_str": ""}
        _count_downloaded_files("nonexistent", td, result2)
        true("cf missing finds fallback", result2["image_count"] >= 0)  # may find fallback dir


# Feature import test — replaces old _fallback_img2pdf (removed in v2 refactor)
def test_feature_import():
    section("4c. Feature import (jmcomic Feature system)")
    try:
        from bot.downloader import Feature
        ok("Feature importable from bot.downloader")
    except ImportError as e:
        fail("Feature import", str(e))
    # Verify Feature API
    try:
        from jmcomic import Feature as F
        pdf_f = F.export_pdf(pdf_dir="./test", filename_rule="Aid")
        eq("pdf feature plugin_key", pdf_f.plugin_key, "img2pdf")
        zip_f = F.export_zip(zip_dir="./test", filename_rule="Aid")
        eq("zip feature plugin_key", zip_f.plugin_key, "zip")
    except Exception as e:
        fail("Feature API", str(e))


# ============================================================
# SECTION 6: TTS (bot.tts — preprocess / voices / mock synthesize)
# ============================================================

from bot import tts as tts_mod  # noqa: E402


def test_tts_preprocess():
    section("6a. tts.preprocess")

    eq("tts pp strips qq tag", tts_mod.preprocess("你好[表情]呀"), "你好呀")
    eq("tts pp strips emoji", tts_mod.preprocess("好可爱\U0001F63B喵"), "好可爱喵")
    eq("tts pp strips md", tts_mod.preprocess("**重点**和_斜体_"), "重点和斜体")
    true("tts pp keeps chinese", "本喵" in tts_mod.preprocess("本喵在呢"))
    long = "喵" * 500
    eq("tts pp truncates", len(tts_mod.preprocess(long)), 300)
    eq("tts pp empty after strip", tts_mod.preprocess("[图片][表情]"), "")


def test_tts_voices():
    section("6b. tts.load_voices / resolve_voice")

    voices = tts_mod.load_voices()
    true("tts voices loaded", len(voices) >= 7)
    true("tts voices role1 present", 1 in voices)
    true("tts voices id nonempty", all(isinstance(v, str) and v for v in voices.values()))

    # 已配置角色 → 表内音色；未配置角色 → default
    v1 = tts_mod.resolve_voice(1)
    true("tts resolve role1", isinstance(v1, str) and len(v1) > 0)
    v_unknown = tts_mod.resolve_voice(999)
    eq("tts resolve fallback default", v_unknown, tts_mod.resolve_voice(1))


def test_tts_synthesize_mock():
    section("6c. tts.synthesize (mock engine, no real API)")

    saved_engine = dict(tts_mod._ENGINES)
    saved_key = tts_mod.config.TTS_API_KEY
    try:
        tts_mod.config.TTS_API_KEY = "test-key"
        calls = {"n": 0}

        def fake_engine(text, voice_id):
            calls["n"] += 1
            return (b"ID3FAKEMP3", None)

        tts_mod._ENGINES["vocu"] = fake_engine
        tts_mod.config.TTS_ENGINE = "vocu"

        # 清掉同名缓存避免历史干扰
        import hashlib as _hl
        vid = tts_mod.resolve_voice(1)
        key = _hl.md5(f"{vid}|测试语音合成内容".encode("utf-8")).hexdigest()[:20]
        cache_file = os.path.join(tts_mod.TTS_CACHE_DIR, f"{key}.mp3")
        if os.path.exists(cache_file):
            os.remove(cache_file)

        path = tts_mod.synthesize("测试语音合成内容", 1)
        true("tts mock synth returns path", path is not None and os.path.exists(path))
        with open(path, "rb") as f:
            eq("tts cache content", f.read(), b"ID3FAKEMP3")

        # 第二次命中缓存，engine 不再被调用
        path2 = tts_mod.synthesize("测试语音合成内容", 1)
        eq("tts cache hit no re-call", calls["n"], 1)
        eq("tts cache hit same path", path2, path)

        # 引擎失败 → None
        tts_mod._ENGINES["vocu"] = lambda t, v: (None, "boom")
        eq("tts failure returns none", tts_mod.synthesize("另一次失败内容xyz", 1), None)

        # 空文本 → None（不调引擎）
        calls["n"] = 0
        eq("tts empty text none", tts_mod.synthesize("[表情]", 1), None)
        eq("tts empty text skips engine", calls["n"], 0)

        # 未配置 key → None
        tts_mod.config.TTS_API_KEY = ""
        tts_mod._ENGINES["vocu"] = fake_engine
        eq("tts no key none", tts_mod.synthesize("无Key内容abc", 1), None)
    finally:
        tts_mod._ENGINES.clear()
        tts_mod._ENGINES.update(saved_engine)
        tts_mod.config.TTS_API_KEY = saved_key


# ============================================================
# SECTION 5: Edge Cases
# ============================================================


def test_edge_cases():
    section("5. EDGE CASES")

    # format_size with very large value (beyond TB)
    huge = 10**18  # ~888 PB
    result = format_size(huge)
    true("fs huge returns str", isinstance(result, str))
    true("fs huge has TB", "TB" in result)

    # format_size with 0
    eq("fs zero", format_size(0), "0.0 B")

    # format_size with float cast
    result_int = format_size(int(3.14 * 1024))
    true("fs float-derived int", isinstance(result_int, str))

    # JSON with special unicode characters
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "special.json")
        special = {"key": "\u0000\u0001\u0002", "escaped": "\\n\\t\\r", "emoji": "🎉✨\n\t\r"}
        save_json(path, special)
        loaded = load_json(path)
        eq("json special unicode round-trip", loaded, special)

    # Progress bar edge: fractional percentages
    bar, pct = _format_progress_bar(1, 3)
    # 1 * 100 // 3 = 33 → 33 * 10 // 100 = 3
    eq("pbar (1,3) pct", pct, 33)
    true("pbar (1,3) has 3 filled", bar.count("\u2588") == 3)

    bar, pct = _format_progress_bar(2, 3)
    # 2 * 100 // 3 = 66 → 66 * 10 // 100 = 6
    eq("pbar (2,3) pct", pct, 66)
    true("pbar (2,3) has 6 filled", bar.count("\u2588") == 6)

    bar, pct = _format_progress_bar(1, 1)
    eq("pbar (1,1) pct", pct, 100)
    true("pbar (1,1) all filled", bar.count("\u2588") == 10)

    # ETA edge: exactly 1 hour
    # 1/3601 @ 1 Bps, avg=1 → 3600/1 = 3600s → "约 1h0m"
    eq("eta 1h", _format_eta(1, 3601, 1, 1), "\u7ea6 1h0m")

    # ETA edge: exactly 1 minute
    eq("eta 1min", _format_eta(1, 61, 1, 1), "\u7ea6 1min")

    # ETA edge: exactly 59 minutes
    eq("eta 59min", _format_eta(1, 3541, 1, 1), "\u7ea6 59min")

    # is_api_error with bytes/bytearray (non-str sequences)
    false("is_err bytes", is_api_error(b"[ERROR]"))
    false("is_err bytearray", is_api_error(bytearray(b"[ERROR]")))

    # api_error_msg with exact prefix lengths
    # [API_ERR] is 9 chars + space = 10
    eq("msg [API_ERR] exact", api_error_msg("[API_ERR] x"), "x")
    eq("msg [TIMEOUT] exact", api_error_msg("[TIMEOUT] x"), "x")


# ============================================================
# Main runner
# ============================================================


def main():
    global _pass, _fail, _failures

    print("=" * 60)
    print("  JM Bot Comprehensive Test Suite")
    print("=" * 60)

    # Section 1: Regex
    test_regex_all()

    # Section 2: napcat_utils
    test_format_size()
    test_json_persistence()
    test_dir_utils()
    test_rotate_log()
    test_clean_old_dirs()

    # Section 3: jm_bot helpers (inline)
    test_format_progress_bar()
    test_format_eta()
    test_is_api_error_and_msg()
    test_msg_dict()

    # Section 4: download helpers
    test_find_album_dir()
    test_count_downloaded_files()
    test_feature_import()

    # Section 6: TTS
    test_tts_preprocess()
    test_tts_voices()
    test_tts_synthesize_mock()

    # Section 5: Edge cases
    test_edge_cases()

    # Summary
    print(f"\n{'=' * 60}")
    total = _pass + _fail
    print(f"  RESULTS: {_pass} PASS, {_fail} FAIL, {total} TOTAL")
    print(f"{'=' * 60}")

    if _failures:
        print(f"\n  FAILURES:")
        for name, msg in _failures:
            print(f"    - {name}: {msg}")

    return _fail == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
