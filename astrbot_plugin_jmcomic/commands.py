"""
/jm 子命令处理器 — 从旧 jm_bot.py dispatch() 提取
使用 event.set_result() 模式（AstrBot 异步风格）
"""
import os
import re
import asyncio
import logging
from astrbot.api.event import AstrMessageEvent, MessageEventResult

from .messages import M, M_single
from .state import PDF_DIR, DOWNLOAD_DIR, ZIP_DIR

logger = logging.getLogger("jmcomic")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _format_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ═══════════════════════════════════════════
# 下载路由：单ID vs 批量
# ═══════════════════════════════════════════

async def handle_download_router(plugin, event: AstrMessageEvent, ids_str: str):
    """解析 /jm download <ids> 中的 ID 列表，路由到单ID或批量下载"""
    # 提取所有 4-8 位数字 ID
    ids = re.findall(r"\b(\d{4,8})\b", ids_str)
    # 也检查 format 标记
    fmt = "pdf"
    if "zip" in ids_str.lower():
        fmt = "zip"

    if not ids:
        event.set_result(MessageEventResult().message(M("invalid_id")))
        return

    if len(ids) == 1:
        await handle_download(plugin, event, ids[0], fmt)
    else:
        await handle_download_batch(plugin, event, ids, fmt)


# ═══════════════════════════════════════════
# 单本下载
# ═══════════════════════════════════════════

async def handle_download(plugin, event: AstrMessageEvent, album_id: str, fmt: str = "pdf"):
    from .download import download_single, _album_info

    album_id = album_id.strip()
    fmt = fmt.strip().lower() or "pdf"
    if fmt not in ("pdf", "zip"):
        fmt = "pdf"

    group_id = event.get_group_id() or 0

    # 去重
    if plugin.state.is_downloading(album_id):
        progress = await plugin.state.get_progress(album_id)
        if progress:
            from .download import _format_progress_bar, _format_eta
            done = progress["image_completed"]
            total = progress["image_total"]
            bar = _format_progress_bar(done, total)
            pct = int(done / total * 100) if total else 0
            speed_str = f" | {progress['speed']:.1f} KB/s" if progress["speed"] > 0 else ""
            eta_str = _format_eta(done, total, progress["speed"] * 1024, progress.get("bytes_downloaded", 0))
            text = M("download_duplicate", id=album_id, bar=bar, pct=pct,
                     done=done, total=total, speed=speed_str, eta=eta_str, switch="")
            event.set_result(MessageEventResult().message(text))
            return
        else:
            event.set_result(MessageEventResult().message(M("download_queued", id=album_id)))
            return

    # 速限
    remaining, blocked = plugin.state.check_rate_limit(group_id)
    if blocked:
        text = M("rate_global", s=int(remaining), g=plugin.state.GLOBAL_COOLDOWN)
        event.set_result(MessageEventResult().message(text))
        return

    # 获取信息
    try:
        info = await _album_info(album_id)
    except Exception:
        event.set_result(MessageEventResult().message(M("not_found", id=album_id)))
        return

    if not info:
        event.set_result(MessageEventResult().message(M("not_found", id=album_id)))
        return

    title = info.get("name", "未知")
    pages = info.get("pages", "?")
    photo_count = info.get("photo_count", "?")
    author = info.get("authors", "未知")
    size_str = f"{photo_count}章/{pages}页"

    # 确认
    text = M("download_confirm_detail", title=title, pages=pages, size=size_str, warning="")
    event.set_result(MessageEventResult().message(text))

    # 标记开始
    plugin.state.mark_rate_limit(group_id)
    plugin.state.mark_download_start(album_id)

    # 异步下载
    try:
        result = await download_single(album_id, fmt=fmt, state=plugin.state)
    except Exception as e:
        plugin.state.mark_download_done(album_id)
        event.set_result(MessageEventResult().message(M("download_crash")))
        return

    plugin.state.mark_download_done(album_id)

    # 处理结果
    await _report_result(plugin, event, result, album_id, info, fmt)


async def _report_result(plugin, event, result, album_id, info, fmt):
    """生成下载结果回复"""
    if result["status"] == "ok":
        title = result.get("title") or info.get("name", "未知")
        author = result.get("author") or info.get("authors", "未知")
        photo_count = result.get("photo_count", info.get("photo_count", "?"))

        report = M(
            "download_report",
            prefix=f"[{album_id}] ",
            title=title,
            author=author,
            photo_count=photo_count,
            image_count=result.get("image_count", "?"),
            total_size_str=result.get("total_size_str", ""),
            fmt=fmt.upper(),
            upload="",
        )
        event.set_result(MessageEventResult().message(report))

        # 相关推荐
        related = info.get("related_list", [])[:5]
        if related:
            items = "\n".join(
                M_single("download_related_item", id=r["id"], title=r["name"], author=r.get("author", ""))
                for r in related
            )
            event.set_result(MessageEventResult().message(M("download_related", items=items)))

    elif result["status"] == "cancelled":
        event.set_result(MessageEventResult().message(M("download_cancelled")))

    elif result["status"] == "partial":
        retry = result.get("retry_count", 0)
        failed = result.get("failed_images", 0)
        got = result.get("image_count", 0) - failed
        hint = M(f"hint_{result.get('error_type', 'unknown')}")
        event.set_result(MessageEventResult().message(
            M("download_partial", n=failed, r=retry, got=got, hint=hint)
        ))

    else:
        error = result.get("error", "未知错误")
        hint = M(f"hint_{result.get('error_type', 'unknown')}")
        event.set_result(MessageEventResult().message(
            M("download_fail", error=error, hint=hint)
        ))


# ═══════════════════════════════════════════
# 批量下载
# ═══════════════════════════════════════════

async def handle_download_batch(plugin, event, ids: list, fmt: str = "pdf"):
    from .download import download_single

    group_id = event.get_group_id() or 0

    event.set_result(MessageEventResult().message(M("batch_start", n=len(ids))))

    ok, fail = 0, 0
    for aid in ids:
        if plugin.state.is_stop_requested("*"):
            break

        if plugin.state.is_downloading(aid):
            event.set_result(MessageEventResult().message(M("download_queued", id=aid)))
            continue

        plugin.state.mark_rate_limit(group_id)
        plugin.state.mark_download_start(aid)

        try:
            result = await download_single(aid, fmt=fmt, state=plugin.state)
        except Exception:
            result = {"status": "fail", "error": "未知错误"}

        plugin.state.mark_download_done(aid)

        if result["status"] in ("ok", "partial"):
            ok += 1
            title = result.get("title", "未知")
            if result.get("output_path") and os.path.exists(result["output_path"]):
                file_size = os.path.getsize(result["output_path"])
                event.set_result(MessageEventResult().message(
                    f"📦 [{aid}] {title} ({_format_size(file_size)})"
                ))
        else:
            fail += 1
            error = result.get("error", "未知错误")
            event.set_result(MessageEventResult().message(
                f"❌ [{aid}] 失败: {error[:100]}"
            ))

        # 失败重试一次
        if result["status"] == "fail" and not plugin.state.is_stop_requested("*"):
            logger.info(f"批量下载 {aid} 失败，重试...")
            plugin.state.mark_download_start(aid)
            try:
                result = await download_single(aid, fmt=fmt, state=plugin.state)
                if result["status"] in ("ok", "partial"):
                    fail -= 1
                    ok += 1
            except Exception:
                pass
            plugin.state.mark_download_done(aid)

    event.set_result(MessageEventResult().message(M("batch_done", ok=ok, total=len(ids))))


# ═══════════════════════════════════════════
# 搜索 / 分类 / 详情 / 排行 / 随机
# ═══════════════════════════════════════════

async def handle_search(plugin, event, query: str):
    from .download import _search_site
    try:
        results = await _search_site(query)
    except Exception:
        event.set_result(MessageEventResult().message(M("search_error")))
        return
    if not results:
        event.set_result(MessageEventResult().message(M("search_none", query=query)))
        return
    items = "\n".join(
        M_single("search_item", i=i + 1, id=r["id"], title=r["name"], author=r.get("author", ""))
        for i, r in enumerate(results[:5])
    )
    event.set_result(MessageEventResult().message(M("search_result", query=query, total=len(results), items=items)))


async def handle_category(plugin, event, tag: str):
    from .download import _search_site
    try:
        results = await _search_site(f"+{tag}")
    except Exception:
        event.set_result(MessageEventResult().message(M("category_error")))
        return
    if not results:
        event.set_result(MessageEventResult().message(M("category_none", query=tag)))
        return
    items = "\n".join(
        M_single("search_item", i=i + 1, id=r["id"], title=r["name"], author=r.get("author", ""))
        for i, r in enumerate(results[:5])
    )
    event.set_result(MessageEventResult().message(M("category_result", query=tag, total=len(results), items=items)))


async def handle_info(plugin, event, album_id: str):
    from .download import _album_info
    try:
        info = await _album_info(album_id)
    except Exception:
        event.set_result(MessageEventResult().message(M("info_error")))
        return
    if not info:
        event.set_result(MessageEventResult().message(M("not_found", id=album_id)))
        return
    text = M(
        "info_display", id=album_id,
        name=info.get("name", "未知"),
        authors=info.get("authors", "未知"),
        tags=", ".join(info.get("tags", [])[:5]) or "无",
        pages=info.get("pages", "?"),
        chapters=info.get("photo_count", "?"),
        likes=info.get("likes", "?"),
        views=info.get("views", "?"),
    )
    event.set_result(MessageEventResult().message(text))


async def handle_rank(plugin, event, period: str = "day"):
    from .download import _rank_site
    period = period.strip() or "day"
    if period not in ("day", "week", "month"):
        period = "day"
    label = {"day": "日榜", "week": "周榜", "month": "月榜"}.get(period, "日榜")
    try:
        results = await _rank_site(period)
    except Exception:
        event.set_result(MessageEventResult().message(M("rank_error")))
        return
    if not results:
        event.set_result(MessageEventResult().message(M("rank_empty", label=label)))
        return
    items = "\n".join(
        M_single("rank_item", i=i + 1, id=r["id"], title=r["name"], author=r.get("author", ""))
        for i, r in enumerate(results[:10])
    )
    event.set_result(MessageEventResult().message(M("rank_display", label=label, items=items)))


async def handle_random(plugin, event, flags: str = ""):
    from .download import _random_manga
    flags = flags.strip()
    mode = ""
    tag = ""
    bad_flags = []

    if flags:
        tag_match = re.search(r"(?:--tag|tag)[：:]\s*(\S+)", flags, re.IGNORECASE)
        if tag_match:
            tag = tag_match.group(1)
        for known in ("--top", "--best", "--new"):
            if known in flags:
                mode = known.lstrip("-")
                flags = flags.replace(known, "", 1)
                break
        remaining = flags.replace(tag_match.group(0) if tag_match else "", "").strip()
        if remaining and remaining not in ("--top", "--best", "--new"):
            bad_flags.append(remaining)

    if bad_flags:
        event.set_result(MessageEventResult().message(M("random_bad_flags", flags=" ".join(bad_flags))))
        return

    try:
        results = await _random_manga(mode=mode, tag=tag)
    except Exception:
        event.set_result(MessageEventResult().message(M("random_error")))
        return

    if not results:
        event.set_result(MessageEventResult().message(M("rank_empty", label="")))
        return

    items = ""
    for r in results[:3]:
        items += M_single(
            "random_result_item",
            id=r["id"], name=r.get("name", "未知"), authors=r.get("author", "未知"),
            tags=", ".join(r.get("tags", [])[:3]) or "无",
            pages=r.get("pages", "?"), chapters=r.get("photo_count", "?"),
        )
    event.set_result(MessageEventResult().message(M("random_result", items=items)))


# ═══════════════════════════════════════════
# 队列 / 停止 / 缓存 / 重启 / 角色
# ═══════════════════════════════════════════

async def handle_queue(plugin, event):
    progress_data = plugin.state.get_all_progress()
    queue_size = plugin.state.queue_size()

    if not progress_data and queue_size == 0:
        event.set_result(MessageEventResult().message(M("queue_empty")))
        return

    items = ""
    from .download import _format_progress_bar, _format_eta
    for aid, p in progress_data.items():
        done = p["image_completed"]
        total = p["image_total"]
        bar = _format_progress_bar(done, total)
        pct = int(done / total * 100) if total else 0
        speed_str = f" | {p['speed']:.1f} KB/s" if p["speed"] > 0 else ""
        eta_str = _format_eta(done, total, p["speed"] * 1024, p.get("bytes_downloaded", 0))
        items += M_single("queue_item_active", id=aid, bar=bar, pct=pct,
                          done=done, total=total, speed=speed_str, eta=eta_str) + "\n"

    for aid, fmt_val, _, _ in plugin.state._download_queue.copy():
        items += M_single("queue_item_waiting", id=aid) + "\n"

    event.set_result(MessageEventResult().message(M("queue_display", items=items.strip())))


async def handle_stop(plugin, event):
    progress_data = plugin.state.get_all_progress()
    if not progress_data:
        event.set_result(MessageEventResult().message(M("stop_none")))
        return
    n = len(progress_data)
    plugin.state.request_stop("*")
    plugin.state.reset_global_cooldown()
    await plugin.state.clear_queue()
    asyncio.create_task(_delayed_clear_stop(plugin.state))
    event.set_result(MessageEventResult().message(M("stop_ok", n=n)))


async def _delayed_clear_stop(state):
    await asyncio.sleep(5)
    state.clear_stop_requests()


async def handle_cache(plugin, event, sub: str = ""):
    from .utils import get_dir_info, get_free_space, format_size, clean_old_dirs

    sub = sub.strip()
    if sub and sub.startswith("clean"):
        await handle_cache_clean(plugin, event, sub.replace("clean", "").strip())
        return

    dl_bytes, dl_dirs, _ = get_dir_info(DOWNLOAD_DIR)
    pdf_bytes, _, pdf_files = get_dir_info(PDF_DIR)
    zip_bytes, _, zip_files = get_dir_info(ZIP_DIR)
    free = get_free_space(SCRIPT_DIR)

    text = M(
        "cache_status",
        dl_size=format_size(dl_bytes), dl_dirs=dl_dirs,
        pdf_size=format_size(pdf_bytes), pdf_files=pdf_files,
        zip_size=format_size(zip_bytes), zip_files=zip_files,
        free=format_size(free) if free >= 0 else "未知",
    )
    event.set_result(MessageEventResult().message(text))


async def handle_cache_clean(plugin, event, days_str: str = ""):
    from .utils import clean_old_dirs, format_size

    days = 7
    m = re.search(r"(\d+)", days_str)
    if m:
        days = int(m.group(1))

    removed, freed, errors = clean_old_dirs(DOWNLOAD_DIR, days)
    event.set_result(MessageEventResult().message(
        M("cache_clean", days=days, removed=removed, freed=format_size(freed))
    ))


