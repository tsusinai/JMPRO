"""下载域命令 — /jm download、批量、stop、queue、cache、cache clean"""
import asyncio
import logging
import os
import time

from .. import config, state
from ..downloader import download_single
from ..fsutils import (
    clean_old_dirs,
    format_size,
    get_dir_info,
    get_free_space,
)
from ..messaging import send_group_msg, send_group_reply
from ..messages import M, M_single
from ..napcat import upload_group_file, upload_private_file
from ..runtime import download_call, io_call

logger = logging.getLogger("jm_bot")


def _format_progress_bar(done: int, total: int, width: int = 10) -> tuple:
    """返回 (bar_str, pct) 如 ('[█████░░░░░]', 50)"""
    if total <= 0:
        return "[?]", 0
    pct = min(done * 100 // total, 100)
    filled = pct * width // 100
    bar = "[" + "█" * filled + "░" * (width - filled) + "]"
    return bar, pct


def _format_eta(image_done: int, image_total: int, speed: float, bytes_downloaded: int = 0) -> str:
    """返回 ETA 字符串，如 '约 2 分钟'，信息不足时返回 ''
    基于已下载字节数估算平均图片大小，而非直接用图片张数除以速度"""
    if speed <= 0 or image_total <= 0 or image_done <= 0:
        return ""
    remaining_images = image_total - image_done
    if remaining_images <= 0:
        return ""
    # 尚无字节数据则不估算，避免硬编码回退值误导
    if bytes_downloaded <= 0:
        return ""
    avg_bytes = bytes_downloaded / image_done
    remaining_bytes = remaining_images * avg_bytes
    eta_sec = int(remaining_bytes / speed)
    if eta_sec < 60:
        return f"约 {eta_sec}s"
    elif eta_sec < 3600:
        return f"约 {eta_sec // 60}min"
    else:
        return f"约 {eta_sec // 3600}h{(eta_sec % 3600) // 60}m"


def _queue_lines(exclude: str = "") -> list:
    """构造其他下载任务的队列摘要行"""
    lines = []
    for aid in state.downloading:
        if aid == exclude:
            continue
        prog = state.download_progress.get(aid, {})
        d = prog.get("image_completed", 0)
        t = prog.get("image_total", 0)
        if t > 0:
            bar, p = _format_progress_bar(d, t)
            lines.append(f"  [{aid}] {bar} {p}%")
        else:
            lines.append(f"  [{aid}] 排队中...")
    return lines


def _progress_text(prog: dict) -> tuple:
    """从进度 dict 构造 (bar, pct, speed_part, eta_part, switch_warn) 显示片段"""
    img_total = prog.get("image_total", 0)
    img_done = prog.get("image_completed", 0)
    if img_total > 0:
        bar, pct = _format_progress_bar(img_done, img_total)
    else:
        bar = f"图片: {img_done}/?"
        pct = "?"
    speed = prog.get("speed", 0)
    speed_part = f" | {format_size(int(speed))}/s" if speed > 0 else ""
    eta_part = ""
    if img_total > 0 and speed > 0:
        eta_str = _format_eta(img_done, img_total, speed, prog.get("bytes_downloaded", 0))
        if eta_str:
            eta_part = f" | ⏱ {eta_str}"
    switch_warn = ""
    if prog.get("domain_switches", 0) > 0:
        switch_warn = "\n" + M("download_progress_stall", n=prog['domain_switches'])
    return bar, pct, speed_part, eta_part, switch_warn


async def _ack(group_id, reply_msg_id):
    """立即确认收到命令，防止用户误以为 Bot 未启动"""
    await io_call(send_group_reply, group_id, M("ack"), reply_msg_id)


async def cmd_download(group_id: int, album_id: str, reply_msg_id: int, output_format: str = "pdf",
                       batch_prefix: str = "", skip_rate_checks: bool = False,
                       skip_confirm: bool = False):
    """处理下载命令"""
    # 停止冷却检查（同 ID 停止后 5s 内不允许重新启动）
    stop_ts = state.stop_times.get(album_id, 0)
    if stop_ts and time.time() - stop_ts < config.STOP_COOLDOWN:
        remaining = int(config.STOP_COOLDOWN - (time.time() - stop_ts))
        await io_call(
            send_group_reply, group_id,
            f"🛑 [{album_id}] 刚停下来呢...再等 {remaining}s 才能重新启动喵~",
            reply_msg_id,
        )
        return

    # 去重检查
    if album_id in state.downloading:
        if album_id in state.stop_requests:
            msg = f"🛑 [{album_id}] 正在停下中，请等人家拔出来再试喵~"
        else:
            prog = state.download_progress.get(album_id)
            if prog and (prog.get("image_total", 0) > 0 or prog.get("total", 0) > 0):
                bar, pct, speed_part, eta_part, switch_warn = _progress_text(prog)
                ch_total = prog.get("total", 0)
                ch_part = ""
                if ch_total > 0:
                    ch_part = f" | {prog['completed']}/{ch_total} 章节"
                msg = M("download_duplicate", id=album_id, bar=bar, pct=pct,
                        done=prog.get("image_completed", 0), total=prog.get("image_total", 0),
                        speed=speed_part, eta=eta_part, switch=switch_warn)
            else:
                msg = M("download_queued", id=album_id)

        # 附上完整队列
        queue_lines = _queue_lines(album_id)
        if queue_lines:
            msg += "\n\n📋 队列：\n" + "\n".join(queue_lines)

        await io_call(send_group_reply, group_id, msg, reply_msg_id)
        return

    # 速率限制（批次内跳过）
    if not skip_rate_checks:
        now = time.time()
        for gid in list(state.last_request):
            if now - state.last_request[gid] > 3600:
                del state.last_request[gid]
        last = state.last_request.get(group_id, 0)
        if now - last < config.RATE_LIMIT_SECONDS:
            remaining = int(config.RATE_LIMIT_SECONDS - (now - last))
            await io_call(
                send_group_reply, group_id,
                M("rate_group", s=remaining),
                reply_msg_id,
            )
            return

        # 全局冷却（跨群），降低 CDN 封锁概率
        since_last_global = now - state.last_download_global
        if since_last_global < config.GLOBAL_COOLDOWN_SECONDS:
            remaining = int(config.GLOBAL_COOLDOWN_SECONDS - since_last_global)
            await io_call(
                send_group_reply, group_id,
                M("rate_global", s=remaining, g=config.GLOBAL_COOLDOWN_SECONDS),
                reply_msg_id,
            )
            return

        # 磁盘配额检查
        free_bytes = get_free_space(config.BASE_DIR)
        if free_bytes >= 0 and free_bytes < config.DISK_CRITICAL_BYTES:
            await io_call(
                send_group_reply, group_id,
                M("disk_critical", free=format_size(free_bytes)),
                reply_msg_id,
            )
            return

    disk_warning = ""
    if not skip_rate_checks:
        free_bytes = get_free_space(config.BASE_DIR)
        if free_bytes >= 0 and free_bytes < config.DISK_WARN_BYTES:
            disk_warning = M("disk_warn", free=format_size(free_bytes))

    state.downloading.add(album_id)
    timeout_task = None
    _album_info = None  # 缓存 API 结果，供后续推荐复用
    logger.info(f"开始下载 {album_id} (群 {group_id}){f' {batch_prefix}' if batch_prefix else ''}")

    try:
        # 立即发送确认（不等待 API），秒回防止用户误以为未启动
        if not skip_confirm:
            confirm_msg = M("download_confirm", id=album_id, warning=disk_warning)

            # 如果已有排队中的下载，附上队列摘要
            queue_lines = _queue_lines(album_id)
            if queue_lines:
                confirm_msg += "\n\n📋 当前队列：\n" + "\n".join(queue_lines)

            await io_call(send_group_reply, group_id, confirm_msg, reply_msg_id)

        # 后台获取 info 用于相关推荐（失败不影响下载主流程）
        from ..jm_client import do_info
        from ..runtime import api_executor
        try:
            info = await asyncio.get_running_loop().run_in_executor(api_executor, do_info, album_id)
            if info == "NOT_FOUND":
                _album_info = None
            elif not isinstance(info, str) and info is not None:
                _album_info = info
        except Exception:
            _album_info = None

        # 超时提醒：短间隔检查，有进度变化时通知
        async def timeout_notifier():
            last_reported = (-1, -1, -1)  # (img_done, img_total, switches)，-1 确保首轮一定发送
            stale_ticks = 0           # 连续无变化计数，≥2 时发停滞提醒
            try:
                # 每 70s 检查一次进度（减少刷屏）
                intervals = [70] * 8  # 最多 560s ≈ 9min
                for interval in intervals:
                    await asyncio.sleep(interval)
                    if album_id not in state.downloading:
                        logger.info(f"进度通知退出: {album_id} 不在下载队列")
                        return
                    prog = state.download_progress.get(album_id)
                    if not prog:
                        # 尚无进度数据，首轮发送"准备中"消息
                        if last_reported == (-1, -1):
                            msg = M("download_progress_first")
                            await io_call(send_group_msg, group_id, msg)
                            last_reported = (0, 0, 0)
                        else:
                            logger.info(f"进度通知跳过: {album_id} 尚无进度数据")
                        continue
                    img_done = prog.get("image_completed", 0)
                    img_total = prog.get("image_total", 0)
                    switches = prog.get("domain_switches", 0)
                    # 图片总数尚未确定（API 不返回 page_count，需等 before_photo 累加）
                    if img_total == 0 and img_done == 0:
                        if last_reported == (-1, -1):
                            msg = M("download_progress_first")
                            await io_call(send_group_msg, group_id, msg)
                            last_reported = (0, 0, 0)
                        continue
                    if (img_done, img_total, switches) == last_reported:
                        stale_ticks += 1
                        if stale_ticks >= 2:
                            msg = M("download_progress_stuck", done=img_done, total=img_total)
                            await io_call(send_group_msg, group_id, msg)
                            stale_ticks = 0  # 重置避免刷屏
                        continue
                    stale_ticks = 0
                    last_reported = (img_done, img_total, switches)
                    if img_total > 0 or prog.get("total", 0) > 0:
                        prog_total = prog.get("image_total", 0)
                        if prog_total > 0:
                            bar, pct = _format_progress_bar(img_done, prog_total)
                            img_part = bar
                        else:
                            img_part = f"图片: {img_done}/?"
                            pct = "?"
                        ch_total = prog.get("total", 0)
                        ch_part = f"\n章节: {prog['completed']}/{ch_total}" if ch_total > 0 else ""
                        speed = prog.get("speed", 0)
                        speed_part = f" | {format_size(int(speed))}/s" if speed > 0 else ""
                        eta_part = ""
                        if prog_total > 0 and speed > 0:
                            eta_str = _format_eta(img_done, prog_total, speed,
                                                  prog.get("bytes_downloaded", 0))
                            if eta_str:
                                eta_part = f" | ⏱ {eta_str}"
                        switch_warn = ""
                        if switches > 0:
                            switch_warn = "\n" + M("download_progress_stall", n=switches)
                        msg = M("download_progress", bar=img_part, pct=pct if prog_total > 0 else "?",
                                done=img_done, total=prog_total, speed=speed_part, eta=eta_part,
                                ch=ch_part, switch=switch_warn)
                    else:
                        msg = M("download_progress_nochap")
                    ok = await io_call(send_group_msg, group_id, msg)
                    if ok:
                        logger.info(f"进度通知已发送: {album_id} ({img_done}/{img_total})")
                    else:
                        logger.warning(f"进度通知发送失败 (群{group_id})")
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        timeout_task = asyncio.create_task(timeout_notifier())

        def on_progress(completed: int, total: int, photo_name: str,
                        image_completed: int, image_total: int,
                        speed: float = 0.0, bytes_downloaded: int = 0,
                        domain_switches: int = 0):
            state.download_progress[album_id] = {
                "completed": completed,
                "total": total,
                "photo_name": photo_name,
                "image_completed": image_completed,
                "image_total": image_total,
                "speed": speed,
                "bytes_downloaded": bytes_downloaded,
                "domain_switches": domain_switches,
            }

        def check_cancelled():
            return album_id in state.stop_requests

        result = await download_call(
            download_single, album_id, on_progress, check_cancelled, output_format
        )

        upload_info = ""
        output_path = result.get("output_path") or result.get("pdf_path")
        if output_path:
            ext = "zip" if output_format == "zip" else "pdf"
            fname = f"{album_id}.{ext}"
            label = "ZIP" if output_format == "zip" else "PDF"
            try:
                fsize = os.path.getsize(output_path)
                fsize_str = format_size(fsize)
                logger.info(f"准备上传: {output_path} ({fsize_str})")
            except OSError:
                fsize = 0
                fsize_str = "?"
            # ZIP 超过 100MB 警告，QQ 群文件通常有大小限制
            if output_format == "zip" and fsize > 100 * 1024 * 1024:
                upload_info = M("upload_too_big", fmt=label, size=fsize_str, id=album_id)
            else:
                try:
                    if output_format == "zip":
                        upload_timeout = config.UPLOAD_TIMEOUT_ZIP
                    else:
                        # PDF 超时按文件大小动态计算
                        size_mb = fsize / (1024 * 1024) if fsize > 0 else 0
                        upload_timeout = min(
                            config.UPLOAD_TIMEOUT_PDF_BASE + int(size_mb * config.UPLOAD_TIMEOUT_PDF_PER_MB),
                            config.UPLOAD_TIMEOUT_PDF_MAX,
                        )
                    upload_func = upload_private_file if int(group_id) in state.private_chats else upload_group_file
                    ok, detail = await asyncio.wait_for(
                        download_call(upload_func, group_id, output_path, fname),
                        timeout=upload_timeout,
                    )
                except asyncio.TimeoutError:
                    ok, detail = False, f"上传超时（{fsize_str}），文件过大或网络不佳"
                if ok:
                    upload_info = M("upload_ok", fmt=label, size=fsize_str)
                else:
                    if output_format == "zip":
                        detail += M_single("hint_zip_too_big", id=album_id)
                    upload_info = M("upload_fail", fmt=label, detail=detail)
        else:
            label = "ZIP" if output_format == "zip" else "PDF"
            upload_info = M("upload_no_output", fmt=label)

        retries = result.get("retry_count", 0)
        if result["status"] == "cancelled":
            summary = M("download_cancelled")
        elif result["status"] == "ok":
            if retries > 0:
                summary = M("download_ok_retry", n=retries, count=result.get("image_count", 0))
            else:
                summary = M("download_ok")
        elif result["status"] == "partial":
            lost = result.get("failed_images", result.get("image_count", 0))
            et = result.get("error_type", "")
            hint = M_single("hint_cdn_partial") if et == "cdn_partial" else ""
            summary = M("download_partial", n=lost, r=retries, got=result.get("image_count", 0), hint=hint)
        else:
            et = result.get("error_type", "")
            if et == "not_found":
                hint = M_single("hint_not_found")
            elif et == "cdn_down":
                hint = M_single("hint_cdn_down")
            elif et == "unknown":
                hint = M_single("hint_unknown", error=result.get("error", "未知"))
            else:
                hint = ""
            summary = M("download_fail", error=result.get("error", "未知错误"), hint=hint)

        fmt_label = "ZIP" if output_format == "zip" else "PDF"
        upload_display = upload_info
        if not upload_info.startswith("📦"):
            upload_display = "😿 " + upload_info
        text = M("download_report", prefix=batch_prefix,
                 title=result.get("title", ""),
                 author=result.get("author", "未知"),
                 photo_count=result.get("photo_count", 0),
                 image_count=result.get("image_count", 0),
                 total_size_str=result.get("total_size_str", ""),
                 fmt=fmt_label, upload=upload_display) + "\n\n" + summary
        await io_call(send_group_reply, group_id, text, reply_msg_id)

        # 相关推荐：复用初次 API 调用获取的 related_list，附加到报告末尾
        if result["status"] == "ok" and _album_info is not None:
            try:
                related = getattr(_album_info, "related_list", None)
                if related and len(related) >= 1:
                    import random as _rnd
                    picks = _rnd.sample(related, min(3, len(related)))
                    items = []
                    for r in picks:
                        rid = r.get("id", "?")
                        rname = r.get("name", "未知")[:35]
                        rauthor = r.get("author", "")
                        items.append(M_single("download_related_item", id=rid, title=rname, author=rauthor))
                    text += "\n\n" + M("download_related", items="\n".join(items))
            except Exception:
                pass

        state.record_download_done(group_id)
        logger.info(f"下载完成 {album_id} (群 {group_id})")
        return result

    except Exception as e:
        logger.error(f"下载异常 {album_id}: {e}", exc_info=True)
        await io_call(
            send_group_reply, group_id,
            M("download_crash"),
            reply_msg_id,
        )
        return None
    finally:
        if timeout_task:
            timeout_task.cancel()
        state.downloading.discard(album_id)
        state.download_progress.pop(album_id, None)
        state.stop_requests.discard(album_id)
        # 冷却时间戳保留在 state.stop_times 中让 STOP_COOLDOWN 检查生效


async def cmd_download_batch(group_id: int, ids: list, reply_msg_id: int, output_format: str = "pdf"):
    """批量下载：顺序调用 cmd_download，共享冷却窗口"""
    # 去重
    ids = [aid for aid in ids if aid not in state.downloading]
    if not ids:
        await io_call(
            send_group_reply, group_id,
            M("all_queued"),
            reply_msg_id,
        )
        return

    total = len(ids)
    success_count = 0
    failed_ids = []

    await io_call(
        send_group_reply, group_id,
        M("batch_start", n=total),
        reply_msg_id,
    )

    for idx, album_id in enumerate(ids, 1):
        batch_prefix = f"[{idx}/{total}] "
        result = await cmd_download(
            group_id, album_id, reply_msg_id, output_format=output_format,
            batch_prefix=batch_prefix, skip_rate_checks=True,
        )
        if result and result.get("status") == "ok":
            success_count += 1
        elif result and result.get("status") != "cancelled":
            failed_ids.append(album_id)
        if result and result.get("status") == "cancelled":
            break

    # 失败项重试一次
    if failed_ids:
        logger.info(f"批量重试 {len(failed_ids)} 个失败项: {failed_ids}")
        for aid in failed_ids:
            retry_prefix = f"[🔄] "
            result = await cmd_download(
                group_id, aid, reply_msg_id, output_format=output_format,
                batch_prefix=retry_prefix, skip_rate_checks=True,
            )
            if result and result.get("status") == "ok":
                success_count += 1

    # 批次完成后设置全局冷却
    state.last_download_global = time.time()

    if total > 1:
        summary = M("batch_done", ok=success_count, total=total)
        if success_count < total:
            summary += f"\n有 {total - success_count} 个失败了，查看上面报告了解详情~"
        await io_call(send_group_msg, group_id, summary)


async def cmd_stop(group_id: int, reply_msg_id: int):
    """停止当前正在下载的任务"""
    logger.info(f"停止下载请求 (群 {group_id})")
    active = [aid for aid in state.downloading if aid not in state.stop_requests]
    if not active:
        await io_call(
            send_group_reply, group_id,
            M("stop_none"),
            reply_msg_id,
        )
        return
    # 标记所有进行中的下载为取消（不清除 downloading 防止竞态，由 finally 清理）
    now = time.time()
    count = len(active)
    for aid in active:
        state.stop_requests.add(aid)
        state.stop_times[aid] = now
    # 重置冷却限制，停止后可以立即重新下载（不同 ID）
    state.last_request.pop(group_id, None)
    state.last_download_global = 0
    await io_call(
        send_group_reply, group_id,
        M("stop_ok", n=count),
        reply_msg_id,
    )


async def cmd_queue(group_id: int, reply_msg_id: int):
    """查看下载队列"""
    logger.info(f"队列查询 (群 {group_id})")
    # 过滤掉已标记取消的
    active = [aid for aid in state.downloading if aid not in state.stop_requests]
    stopping = [aid for aid in state.downloading if aid in state.stop_requests]
    if not active and not stopping:
        text = M("queue_empty")
    else:
        item_lines = []
        for aid in active:
            prog = state.download_progress.get(aid, {})
            img_done = prog.get("image_completed", 0)
            img_total = prog.get("image_total", 0)
            speed = prog.get("speed", 0)
            if img_total > 0:
                bar, pct = _format_progress_bar(img_done, img_total)
                pct_str = bar
                speed_str = f" | {format_size(int(speed))}/s" if speed > 0 else ""
                eta_str = ""
                if speed > 0:
                    eta_str = _format_eta(img_done, img_total, speed,
                                          prog.get("bytes_downloaded", 0))
                    eta_str = f" | ⏱ {eta_str}" if eta_str else ""
                if img_done > 0:
                    item_lines.append(M_single("queue_item_active", id=aid, bar=pct_str,
                        pct=pct, done=img_done, total=img_total, speed=speed_str, eta=eta_str))
                else:
                    item_lines.append(M_single("queue_item_waiting", id=aid))
            else:
                item_lines.append(M_single("queue_item_waiting", id=aid))
        if stopping:
            for aid in stopping:
                item_lines.append(f"  🛑 [{aid}] 正在停下...")
        text = M("queue_display", items="\n".join(item_lines))

    await io_call(send_group_reply, group_id, text, reply_msg_id)


async def cmd_cache(group_id: int, reply_msg_id: int):
    """显示磁盘使用情况概览"""
    logger.info(f"缓存查询 (群 {group_id})")

    def do_cache_query():
        dl_size, dl_dirs, _ = get_dir_info(config.DOWNLOADS_DIR)
        pdf_size, _, pdf_files = get_dir_info(config.PDFS_DIR)
        zip_size, _, zip_files = get_dir_info(config.ZIPS_DIR)
        log_size = (
            os.path.getsize(config.ERROR_LOG_PATH)
            if os.path.exists(config.ERROR_LOG_PATH) else 0
        )
        total_size = dl_size + pdf_size + zip_size + log_size
        try:
            free = get_free_space(config.BASE_DIR)
            free_str = format_size(free) if free >= 0 else "无法获取"
        except Exception:
            free_str = "无法获取"

        return M("cache_status",
                dl_size=format_size(dl_size), dl_dirs=dl_dirs,
                pdf_size=format_size(pdf_size), pdf_files=pdf_files,
                zip_size=format_size(zip_size), zip_files=zip_files, free=free_str)

    text = await io_call(do_cache_query)
    await io_call(send_group_reply, group_id, text, reply_msg_id)


async def cmd_cache_clean(group_id: int, days: int, reply_msg_id: int):
    """清理超过 N 天的下载目录，保留 PDF"""
    logger.info(f"缓存清理: {days} 天 (群 {group_id})")

    def do_clean():
        removed, freed, errors = clean_old_dirs(config.DOWNLOADS_DIR, max_age_days=days)
        text = M("cache_clean", days=days, removed=removed, freed=format_size(freed))
        if errors:
            text += f"\n😿 有 {len(errors)} 团排不出来..."
        return text

    text = await io_call(do_clean)
    await io_call(send_group_reply, group_id, text, reply_msg_id)
