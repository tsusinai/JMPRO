"""运行时资源 — 线程池 + 阻塞调用包装（超时防护 / IO 调度）"""
import asyncio
import concurrent.futures
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from . import config
from .messages import M

logger = logging.getLogger("jm_bot")

# executor: 下载+上传（实际并发由速率限制控制，避免 CDN 封禁）
# io_executor: 消息发送（轻量 IO，不阻塞命令处理）
# api_executor: 搜索/信息/排行/随机/AI（不阻塞消息发送）
# WARNING: raising these may trigger CDN bans or OS handle exhaustion
executor = ThreadPoolExecutor(max_workers=config.THREAD_DOWNLOAD)
io_executor = ThreadPoolExecutor(max_workers=config.THREAD_IO)
api_executor = ThreadPoolExecutor(max_workers=config.THREAD_API)


def shutdown():
    logger.info("正在关闭线程池...")
    executor.shutdown(wait=True)
    io_executor.shutdown(wait=True)
    api_executor.shutdown(wait=True)


def api_run(func, *args, timeout=None):
    """在 api_executor 线程池执行阻塞函数，带超时防护，不阻塞消息发送
    返回: 成功返回数据，失败返回 "[TIMEOUT]" 或 "[API_ERR]..." 前缀的字符串
    """
    if timeout is None:
        timeout = config.API_TIMEOUT
    fut = api_executor.submit(func, *args)
    try:
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return M("api_timeout")
    except Exception as e:
        return M("api_fail", what=str(e))


def is_api_error(result) -> bool:
    """检查 api_run / async_api_run 返回是否为错误"""
    return isinstance(result, str) and result.startswith("[")


def api_error_msg(result) -> str:
    """从 api_run 错误字符串中提取友好消息（去掉前缀标签）"""
    if isinstance(result, str) and result.startswith("[API_ERR] "):
        return result[10:]
    if isinstance(result, str) and result.startswith("[TIMEOUT] "):
        return result[10:]
    return str(result) if isinstance(result, str) else ""


async def async_api_run(func, *args, timeout=None, **kwargs):
    """协程版：在 api_executor 中运行阻塞函数，不占用 io_executor"""
    if timeout is None:
        timeout = config.API_TIMEOUT
    if kwargs:
        func = partial(func, **kwargs)
    try:
        return await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(api_executor, func, *args),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return M("api_timeout")
    except Exception as e:
        return M("api_fail", what=str(e))


async def io_call(fn, *args):
    """在 io_executor 中执行轻量阻塞调用（消息发送等）"""
    return await asyncio.get_running_loop().run_in_executor(io_executor, fn, *args)


async def download_call(fn, *args):
    """在 executor 中执行阻塞下载/上传调用"""
    return await asyncio.get_running_loop().run_in_executor(executor, fn, *args)
