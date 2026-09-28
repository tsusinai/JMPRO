"""
Agent LLM Tools — JM Comic 工具（猫娘口吻返回值）
由 AstrBot Agent 在需要时自动调用，返回值直接可读、带角色风格
"""
import os
import logging

logger = logging.getLogger("jmcomic")


async def search_manga(event, query: str) -> str:
    """搜索 JMComic 漫画。当用户想找某类/某个漫画时调用。

    Args:
        query(string): 搜索关键词，如 "电锯人"、"全彩"、"魔法少女"
    """
    from .download import _search_site

    if not query or not query.strip():
        return "主人忘记说要搜什么了喵...告诉本喵关键词嘛~"

    try:
        results = await _search_site(query.strip())
    except Exception as e:
        logger.error(f"Agent search_manga 失败: {e}")
        return f"呜...本喵在书库里翻'{query}'的时候不小心摔倒了喵...(｡-́︿-̀｡) 主人稍等再试一次嘛~"

    if not results:
        return f"本喵把书架翻了个底朝天，也没找到和'{query}'相关的本子呢...主人换个关键词试试？(◞‸◟)"

    lines = [f"喵呜~ 本喵在书架深处找到了 {len(results)} 本和'{query}'有关的本子："]
    for i, r in enumerate(results[:5]):
        lines.append(f"  [{r['id']}] {r['name']} ({r.get('author', '未知')})")
    lines.append("主人想看哪本的详情？告诉本喵 ID 就行~ 下载的话也可以直接说哦")
    return "\n".join(lines)


async def get_manga_info(event, album_id: str) -> str:
    """查看漫画详情。当用户提到具体数字 ID 时调用。

    Args:
        album_id(string): 漫画数字 ID，如 "123456"
    """
    from .download import _album_info

    if not album_id or not album_id.strip():
        return "主人还没告诉本喵要看哪个 ID 呢..."

    try:
        info = await _album_info(album_id.strip())
    except Exception as e:
        logger.error(f"Agent get_manga_info 失败: {e}")
        return f"呜...本喵翻 [{album_id}] 的时候书页散了一地...(｡-́︿-̀｡) 等下再试试嘛~"

    if not info:
        return f"本喵找遍了也没看到 [{album_id}] 这本呢...主人是不是记错番号了？(◞‸◟)"

    tags = ", ".join(info.get("tags", [])[:5]) or "无"
    pages = info.get("pages", "?")
    photo_count = info.get("photo_count", "?")
    likes = info.get("likes", "?")
    views = info.get("views", "?")

    return (
        f"✨ 本喵从书架最深处抽出了这本！\n"
        f"[{album_id}]《{info.get('name', '未知')}》\n"
        f"✏️ {info.get('authors', '未知')} | 🏷️ {tags}\n"
        f"📄 {pages}页 | 📑 {photo_count}章 | ❤️ {likes} | 👀 {views}\n"
        f"主人想下载吗？说一声就行，本喵帮你全部吸出来~ 💦"
    )


async def get_rank(event, period: str = "day") -> str:
    """查看 JMComic 排行榜。

    Args:
        period(string): day/week/month，默认 day
    """
    from .download import _rank_site

    period = period.strip() or "day"
    if period not in ("day", "week", "month"):
        period = "day"

    label = {"day": "本日", "week": "本周", "month": "本月"}.get(period, "本日")

    try:
        results = await _rank_site(period)
    except Exception as e:
        logger.error(f"Agent get_rank 失败: {e}")
        return f"呜...{label}排行榜被大家冲坏了喵...(｡-́︿-̀｡) 晚点再试~"

    if not results:
        return f"{label}的榜单还空空的呢...大家都在禁欲吗？(◕‿◕)"

    lines = [f"🏆 这是{label}大家冲得最多的 TOP10，本喵整理好啦："]
    for i, r in enumerate(results[:10]):
        lines.append(f"  {i + 1}. [{r['id']}] {r['name']} ({r.get('author', '未知')})")
    lines.append("主人看中哪本了？告诉本喵 ID，马上帮你深入探索~")
    return "\n".join(lines)


async def random_recommend(event, tag: str = "") -> str:
    """随机推荐漫画。

    Args:
        tag(string): 可选标签，如 "原神"、"全彩"、"无修正"，留空完全随机
    """
    from .download import _random_manga

    tag_filter = tag.strip() if tag else ""

    try:
        results = await _random_manga(mode="", tag=tag_filter)
    except Exception as e:
        logger.error(f"Agent random_recommend 失败: {e}")
        return f"呜...本喵闭眼乱摸结果撞到书架了...(｡-́︿-̀｡) 再试一次嘛~"

    if not results:
        hint = f"带'{tag_filter}'标签的" if tag_filter else ""
        return f"本喵在书库里摸了半天，{hint}什么都摸不到呢...换个姿势再来？"

    tag_hint = f"带'{tag_filter}'标签的" if tag_filter else ""
    lines = [f"🎲 本喵闭着眼睛在书架上摸索...摸到了3本{tag_hint}好货："]
    for r in results[:3]:
        tags = ", ".join(r.get("tags", [])[:3]) or "无"
        lines.append(
            f"  ✨ [{r['id']}] {r.get('name', '未知')}"
            f" ({r.get('author', '未知')})"
            f" | {r.get('pages', '?')}页 | {tags}"
        )
    lines.append("主人看上哪本了？告诉本喵，马上帮你深入了解~")
    return "\n".join(lines)


async def download_manga(event, album_id: str) -> str:
    """下载漫画并上传群文件。用户要求下载时直接执行。

    Args:
        album_id(string): 漫画数字 ID
    """
    from .download import download_single

    if not album_id or not album_id.strip():
        return "主人还没说要下载哪本呢..."

    album_id = album_id.strip()

    try:
        result = await download_single(album_id, fmt="pdf", state=None)
    except Exception as e:
        return f"呜...下载 [{album_id}] 的时候本喵被插坏了...(｡-́︿-̀｡) {e}"

    if result["status"] == "ok":
        title = result.get("title", "未知")
        size = result.get("total_size_str", "")
        count = result.get("image_count", "?")

        # 上传文件（群聊或私聊）
        output_path = result.get("output_path", "")
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        logger.info(f"[JM Agent] upload debug: output_path={output_path}, exists={os.path.exists(output_path) if output_path else False}, group_id={group_id}, user_id={user_id}")
        upload_msg = ""
        if output_path and os.path.exists(output_path):
            if group_id:
                ok, detail = _upload_to_group(group_id, output_path, f"{album_id}.pdf")
                if ok:
                    upload_msg = f" | 已上传群文件 ✅"
                else:
                    upload_msg = f" | 上传失败: {detail}"
            elif user_id:
                ok, detail = _upload_to_private(user_id, output_path, f"{album_id}.pdf")
                if ok:
                    upload_msg = f" | 已私发文件 ✅"
                else:
                    upload_msg = f" | 私发失败: {detail}"
            else:
                upload_msg = " | 无法上传：无 group_id 也无 user_id"
        else:
            upload_msg = f" | 文件未生成(output_path={output_path!r}, exists={bool(output_path and os.path.exists(output_path))})"

        return (
            f"✨ 全部吸出来了喵！《{title}》"
            f" | {count}张 | {size}{upload_msg}"
        )
    elif result["status"] == "cancelled":
        return "好啦好啦~ 本喵停下来了喵~"
    else:
        error = result.get("error", "未知错误")
        return f"呜...下载失败了喵...(｡-́︿-̀｡) {error}"


def _upload_to_group(group_id: int, file_path: str, file_name: str) -> tuple:
    """通过 NapCat HTTP API 上传文件到 QQ 群"""
    import requests
    napcat_url = "http://127.0.0.1:3002"
    token = "O~3GVdp9kwlCH.Zg"
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{napcat_url}/upload_group_file",
                headers={"Authorization": f"Bearer {token}"},
                json={"group_id": group_id, "file": file_path, "name": file_name},
                timeout=600,
            )
            resp.raise_for_status()
            data = resp.json()
            ok = data.get("retcode") == 0 or data.get("status") == "ok"
            return ok, data.get("message", "ok")
        except Exception as e:
            if attempt < 2:
                import time
                time.sleep(2 * (attempt + 1))
            else:
                return False, str(e)
    return False, "未知错误"


def _upload_to_private(user_id: str, file_path: str, file_name: str) -> tuple:
    """通过 NapCat HTTP API 上传文件到 QQ 私聊"""
    import requests
    napcat_url = "http://127.0.0.1:3002"
    token = "O~3GVdp9kwlCH.Zg"
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{napcat_url}/upload_private_file",
                headers={"Authorization": f"Bearer {token}"},
                json={"user_id": int(user_id), "file": file_path, "name": file_name},
                timeout=600,
            )
            resp.raise_for_status()
            data = resp.json()
            ok = data.get("retcode") == 0 or data.get("status") == "ok"
            return ok, data.get("message", "ok")
        except Exception as e:
            if attempt < 2:
                import time
                time.sleep(2 * (attempt + 1))
            else:
                return False, str(e)
    return False, "未知错误"
