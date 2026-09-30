"""JMComic 客户端封装 — 懒加载单例 + CDN 域名扩展 + 查询域逻辑（info/rank/random）"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent import futures as _futures

import jmcomic

from . import config

logger = logging.getLogger("jm_bot")

jmcomic.disable_jm_log()

# === 扩展图片 CDN 域名列表（增加冗余防止单点故障） ===
# jmcomic 内置 DOMAIN_IMAGE_LIST 仅含 jmapiproxy + jmapinodeudzn，
# 后者全部被 RST，所以追加所有已知可用域名提高下载成功率
from jmcomic import JmModuleConfig  # noqa: E402

_extra_image_domains = [
    "cdn-msp.jmapiproxy1.cc",
    "cdn-msp.jmapiproxy2.cc",
    "cdn-msp2.jmapiproxy2.cc",
    "cdn-msp3.jmapiproxy2.cc",
    "cdn-msp.jmapinodeudzn.net",
    "cdn-msp3.jmapinodeudzn.net",
]
JmModuleConfig.DOMAIN_IMAGE_LIST = list(dict.fromkeys(
    JmModuleConfig.DOMAIN_IMAGE_LIST + _extra_image_domains
))

_jm_client = None
_jm_client_lock = threading.Lock()


def get_jm_client():
    """懒加载 jmcomic 客户端（option.yml 优先，缺失时用默认配置）"""
    global _jm_client
    if _jm_client is None:
        with _jm_client_lock:
            if _jm_client is None:
                if _jm_client is None:
                    import os
                    if os.path.exists(config.OPTION_FILE):
                        option = jmcomic.create_option_by_file(config.OPTION_FILE)
                    else:
                        option = jmcomic.JmOption.default()
                    _jm_client = option.build_jm_client()
    return _jm_client


def do_info(album_id):
    """查询漫画详情；本子不存在时返回 "NOT_FOUND" 便于上层识别"""
    client = get_jm_client()
    try:
        album = client.get_album_detail(album_id)
    except Exception as e:
        if "not found" in str(e).lower() or "不存在" in str(e) or "下架" in str(e):
            return "NOT_FOUND"
        raise
    # page_count 可能为 0（JM API 不保证返回），
    # 此时对每个章节调 check_photo 获取真实图片数
    if getattr(album, 'page_count', 0) == 0:
        total = 0
        for photo in album:
            try:
                client.check_photo(photo)
                total += len(photo)
            except Exception:
                pass
        if total > 0:
            album.page_count = total
    return album


def do_rank(rank_type: str):
    client = get_jm_client()
    if rank_type == "week":
        return client.week_ranking(page=1)
    elif rank_type == "month":
        return client.month_ranking(page=1)
    else:
        return client.day_ranking(page=1)


def do_random(_random, mode: str = "", tag: str = ""):
    """随机推荐：每本从不同随机页各取 1 条，纯随机
    返回 (albums, error)，error 非 None 表示失败"""
    client = get_jm_client()
    order_map = {
        "top": jmcomic.JmMagicConstants.ORDER_BY_VIEW,
        "best": jmcomic.JmMagicConstants.ORDER_BY_SCORE,
        "new": jmcomic.JmMagicConstants.ORDER_BY_LATEST,
    }
    order_by = order_map.get(mode, jmcomic.JmMagicConstants.ORDER_BY_LATEST)

    # 第一步：获取第一页确定总数
    # 使用 +tag 语法精确匹配标签（search_tag 可能模糊匹配标题）
    if tag:
        first_page = client.search_site(f"+{tag}", page=1, order_by=order_by)
    else:
        first_page = client.search_site('', page=1, order_by=order_by)
    total = getattr(first_page, "total", 0)
    if total == 0:
        error_msg = "找不到匹配的漫画呢...换个标签试试？(◞‸◟)" if tag else "什么都没找到...服务器可能在摸鱼 (´•ω•`)"
        return None, error_msg
    page_count = max(1, (total + 79) // 80)  # ceil(total/80)
    max_page = min(page_count, config.RANDOM_MAX_PAGES) if page_count > 0 else 1
    num_picks = min(3, total)
    pages_to_fetch = _random.sample(range(1, max_page + 1), min(num_picks, max_page))
    picks = []
    for page in pages_to_fetch:
        if page == 1:
            items = list(first_page)
        else:
            if tag:
                items = list(client.search_site(f"+{tag}", page=page, order_by=order_by))
            else:
                items = list(client.search_site('', page=page, order_by=order_by))
        if items:
            picks.append(_random.choice(items))
    if not picks:
        return None, "这页是空的喵...再试一次？(◞‸◟)"
    # 并行获取详情（最多 3 个同步调用）
    ids_to_fetch = []
    for item in picks:
        aid = item[0] if isinstance(item, tuple) else item.id
        if aid not in ids_to_fetch:
            ids_to_fetch.append(aid)
    albums = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(client.get_album_detail, aid): aid for aid in ids_to_fetch}
        for future in _futures.as_completed(futures, timeout=config.RANDOM_TIMEOUT):
            aid = futures[future]
            try:
                albums.append(future.result())
            except Exception as e:
                logger.warning(f"随机推荐获取详情失败 {aid}: {e}")
    if not albums:
        return None, "获取详情失败喵...再试一次？(◞‸◟)"
    return albums, None
