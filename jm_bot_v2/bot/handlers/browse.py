"""浏览域命令 — /jm search、info、rank、category、random 及 ask 的数据动作执行"""
import asyncio
import logging

import jmcomic

from .. import config
from ..fsutils import format_size
from ..jm_client import do_info, do_rank, do_random, get_jm_client
from ..messaging import send_group_msg, send_group_reply
from ..messages import M, M_single
from ..runtime import api_executor, async_api_run, io_call

logger = logging.getLogger("jm_bot")

RANK_LABELS = {"day": "日榜", "week": "周榜", "month": "月榜"}


def _format_item_lines(items, max_n: int) -> list:
    """格式化漫画列表行（兼容 tuple 与对象两种结果形态）"""
    lines = []
    for i, item in enumerate(items, 1):
        if isinstance(item, tuple):
            aid, title = item[0], str(item[1])[:40]
            author = ""
        else:
            aid = getattr(item, "id", "?")
            title = str(getattr(item, "name", "未知"))[:40]
            author = str(getattr(item, "author", "未知"))
        lines.append(M_single("search_item", i=i, id=aid, title=title, author=author))
    return lines


def _total_of(result) -> int:
    """搜索结果的 total 字段，缺失时按可迭代长度兜底"""
    if hasattr(result, "total"):
        return getattr(result, "total", 0)
    if hasattr(result, '__iter__'):
        return len(list(result))
    return 0


async def cmd_search(group_id: int, query: str, reply_msg_id: int):
    """处理搜索命令"""
    query = query.strip()
    if len(query) < 1:
        await io_call(
            send_group_reply, group_id,
            M("search_empty_query"),
            reply_msg_id,
        )
        return

    logger.info(f"搜索: {query} (群 {group_id})")

    from ..handlers.download import _ack
    await _ack(group_id, reply_msg_id)
    result = await async_api_run(get_jm_client().search_site, query, page=1)

    if isinstance(result, str):
        logger.error(f"搜索异常: {result}")
        text = M("search_error")
    else:
        total = _total_of(result)
        items = list(result)[:5]
        if not items:
            text = M("search_none", query=query)
        else:
            text = M("search_result", total=total, query=query,
                     items="\n".join(_format_item_lines(items, 5)))

    await io_call(send_group_msg, group_id, text)


async def cmd_info(group_id: int, album_id: str, reply_msg_id: int):
    """处理详情命令"""
    logger.info(f"查询详情: {album_id} (群 {group_id})")

    from ..handlers.download import _ack
    await _ack(group_id, reply_msg_id)
    result = await async_api_run(do_info, album_id)

    if result == "NOT_FOUND":
        text = M("not_found", id=album_id)
    elif isinstance(result, str):
        logger.error(f"查询异常: {result}")
        text = M("info_error")
    else:
        tags = ", ".join(result.tags) if result.tags else "无"
        authors = ", ".join(result.authors) if result.authors else "未知"
        likes = getattr(result, "likes", 0) or 0
        views = getattr(result, "views", 0) or 0
        page_count = getattr(result, "page_count", 0) or 0
        try:
            chapter_count = len(result)
        except Exception:
            chapter_count = 0

        # page_count 可能为 0（JM API 不保证返回），尝试从章节累加
        if page_count == 0 and chapter_count > 0:
            try:
                total_pages = 0
                for photo in result:
                    try:
                        total_pages += len(photo)
                    except Exception:
                        pass
                if total_pages > 0:
                    page_count = total_pages
            except Exception:
                pass

        pages_str = f"{page_count}页" if page_count > 0 else "未知"
        chapters_str = f"{chapter_count}章" if chapter_count > 0 else ""

        text = M("info_display", id=result.id, name=result.name,
                authors=authors, tags=tags, pages=pages_str,
                chapters=chapters_str, likes=likes, views=views)

    await io_call(send_group_msg, group_id, text)


async def cmd_rank(group_id: int, rank_type: str, reply_msg_id: int):
    """处理排行榜命令"""
    rank_type = rank_type or "day"
    label = RANK_LABELS.get(rank_type, "")

    logger.info(f"排行榜: {rank_type} (群 {group_id})")

    from ..handlers.download import _ack
    await _ack(group_id, reply_msg_id)
    result = await async_api_run(do_rank, rank_type)

    if isinstance(result, str):
        logger.error(f"排行榜异常: {result}")
        text = M("rank_error")
    else:
        items = list(result)[:10]
        if not items:
            text = M("rank_empty", label=label)
        else:
            item_lines = []
            for i, item in enumerate(items, 1):
                if isinstance(item, tuple):
                    aid, title = item[0], item[1][:40]
                    author = ""
                else:
                    aid = getattr(item, "id", "?")
                    title = getattr(item, "name", "未知")[:40]
                    author = getattr(item, "author", "未知")
                item_lines.append(M_single("rank_item", i=i, id=aid, title=title, author=author))
            text = M("rank_display", label=label, items="\n".join(item_lines))

    await io_call(send_group_msg, group_id, text)


async def cmd_category(group_id: int, query: str, reply_msg_id: int):
    """按标签筛选漫画"""
    query = query.strip()
    if len(query) < 1:
        await io_call(
            send_group_reply, group_id,
            M("category_empty_query"),
            reply_msg_id,
        )
        return

    logger.info(f"标签筛选: {query} (群 {group_id})")

    from ..handlers.download import _ack
    await _ack(group_id, reply_msg_id)
    result = await async_api_run(get_jm_client().search_tag, query, page=1)

    if isinstance(result, str):
        logger.error(f"标签筛选异常: {result}")
        text = M("category_error")
    else:
        total = _total_of(result)
        items = list(result)[:5]
        if not items:
            text = M("category_none", query=query)
        else:
            text = M("category_result", total=total, query=query,
                     items="\n".join(_format_item_lines(items, 5)))

    await io_call(send_group_msg, group_id, text)


async def cmd_random(group_id: int, reply_msg_id: int, mode: str = "", tag: str = ""):
    """随机推荐一本漫画，支持 --top/--best/--new 模式和 --tag 筛选"""
    labels = {"top": "人气", "best": "好评", "new": "最新"}
    extra = f" {labels.get(mode, '')}" if mode else ""
    extra += f" #{tag}" if tag else ""
    logger.info(f"随机推荐 (群 {group_id}){extra}")
    import random as _random

    from ..handlers.download import _ack
    await _ack(group_id, reply_msg_id)
    raw = await async_api_run(do_random, _random, mode, tag, timeout=config.RANDOM_TIMEOUT)
    # api_call 超时返回字符串，正常返回 (albums_list, error) 元组
    if isinstance(raw, str):
        logger.error(f"随机推荐异常: {raw}")
        text = M("random_error")
    else:
        albums, error = raw
        if error:
            logger.error(f"随机推荐异常: {error}")
            text = error if albums is None else M("random_error") + f" {error}"
        else:
            item_lines = []
            for album in albums:
                tags = ", ".join(album.tags[:5]) if album.tags else "无"
                authors = ", ".join(album.authors) if album.authors else "未知"
                page_count = getattr(album, "page_count", 0) or 0
                try:
                    chapter_count = len(album)
                except Exception:
                    chapter_count = 0
                item_lines.append(M("random_result_item", id=album.id, name=album.name,
                    authors=authors, tags=tags, pages=page_count, chapters=chapter_count))
            text = M("random_result", items="\n".join(item_lines))

    await io_call(send_group_msg, group_id, text)


def parse_random_flags(rest: str) -> tuple:
    """解析 --top/--best/--new 和 --tag X，支持任意顺序；返回 (mode, tag, unknown)"""
    mode = ""
    tag = ""
    unknown = []
    parts = rest.split()
    i = 0
    while i < len(parts):
        if parts[i] in ("--top", "--best", "--new"):
            mode = parts[i][2:]  # strip --
        elif parts[i] == "--tag" and i + 1 < len(parts):
            tag = parts[i + 1]
            i += 1  # skip tag value
        elif parts[i].startswith("tag:") or parts[i].startswith("tag："):
            # 支持 tag:xxx 或 tag：xxx 简写
            tag = parts[i].split(":", 1)[-1].split("：", 1)[-1]
        else:
            unknown.append(parts[i])
        i += 1
    return mode, tag, unknown


def execute_action(action: dict) -> str:
    """执行意图分类后的动作，返回格式化数据文本（供 chat 域 /jm ask 使用）"""
    import random as _random
    client = get_jm_client()
    act = action.get("action", "chat")

    def _format_items(items, max_n=5):
        """格式化漫画列表为文本"""
        item_list = list(items)[:max_n]
        if not item_list:
            return None
        lines = []
        for i, item in enumerate(item_list, 1):
            if isinstance(item, tuple):
                aid, title = item[0], str(item[1])[:50]
                author = ""
            else:
                aid = getattr(item, "id", "?")
                title = str(getattr(item, "name", "未知"))[:50]
                author = str(getattr(item, "author", ""))
            lines.append(f"  {i}. [{aid}] {title}" + (f" ({author})" if author else ""))
        return "\n".join(lines)

    if act == "search":
        query = action.get("query", "")
        result = client.search_site(query, page=1)
        items_text = _format_items(result)
        if not items_text:
            return f"搜索 \"{query}\" 未找到任何漫画"
        total = getattr(result, "total", 0)
        return f"搜索 \"{query}\" 共 {total} 条，前 5 条：\n{items_text}"

    elif act == "info":
        aid = action.get("id", "")
        info = do_info(aid)
        if info == "NOT_FOUND":
            return f"漫画 [{aid}] 不存在或已下架"
        if isinstance(info, str):
            return f"获取详情失败: {info}"
        tags = ", ".join(info.tags[:5]) if info.tags else "无"
        authors = ", ".join(info.authors) if info.authors else "未知"
        likes = getattr(info, "likes", 0) or 0
        views = getattr(info, "views", 0) or 0
        page_count = getattr(info, "page_count", 0) or 0
        try:
            chapter_count = len(info)
        except Exception:
            chapter_count = 0
        return (
            f"漫画 [{info.id}] {info.name}\n"
            f"作者: {authors}\n标签: {tags}\n"
            f"页数: {page_count}, 章节: {chapter_count}\n"
            f"点赞: {likes}, 浏览: {views}"
        )

    elif act == "rank":
        rank_type = action.get("type", "day")
        result = do_rank(rank_type)
        if isinstance(result, str):
            return f"获取排行榜失败: {result}"
        items_text = _format_items(result, 10)
        if not items_text:
            return "暂无排行数据"
        label = RANK_LABELS.get(rank_type, "")
        return f"JM {label}TOP10：\n{items_text}"

    elif act == "random":
        mode = action.get("mode", "")
        tag = action.get("tag", "")
        raw = do_random(_random, mode, tag)
        if isinstance(raw, str):
            return f"随机推荐失败: {raw}"
        albums, error = raw
        if error:
            return f"随机推荐失败: {error}"
        if not albums:
            return "未找到符合条件的漫画"
        lines = [f"随机推荐 {len(albums)} 本："]
        for album in albums:
            tags_str = ", ".join(album.tags[:3]) if album.tags else "无"
            a = ", ".join(album.authors) if album.authors else "未知"
            pc = getattr(album, "page_count", 0) or 0
            try:
                cc = len(album)
            except Exception:
                cc = 0
            lines.append(f"  [{album.id}] {album.name} ({a}) | {pc}页 {cc}章 | {tags_str}")
        return "\n".join(lines)

    elif act == "category":
        tag = action.get("tag", "")
        result = client.search_tag(tag, page=1)
        items_text = _format_items(result)
        if not items_text:
            return f"标签 \"{tag}\" 未找到漫画"
        total = getattr(result, "total", 0)
        return f"标签 \"{tag}\" 共 {total} 条，前 5 条：\n{items_text}"

    else:
        return ""  # chat
