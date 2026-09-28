"""
JM Comic Bot — 禁漫天堂 AstrBot 插件
"""
import re
from astrbot.api import star, llm_tool
from astrbot.api.event import AstrMessageEvent, filter, MessageEventResult

from .messages import M, M_single
from .state import JMBotState
from . import commands as _commands
from . import agent_tools as _agent_tools


class Main(star.Star):
    """JM Comic Bot 插件"""

    def __init__(self, context: star.Context, config: dict | None = None):
        super().__init__(context, config)
        self.state = JMBotState()

    async def initialize(self):
        await self.state.restore_from_kv(self)

    async def terminate(self):
        await self.state.shutdown()

    # ── /jm 主入口（手动子命令路由） ──
    @filter.command("jm")
    async def jm(self, event: AstrMessageEvent):
        """禁漫天堂 Bot"""
        event.stop_event()  # 阻止 Agent 重复处理
        raw = event.message_str.strip()
        message_id = event.get_message_id()
        group_id = event.get_group_id() or 0

        # 去掉 /jm 前缀
        raw = re.sub(r"^/jm\s*", "", raw).strip()

        # ═══ 子命令路由 ═══
        # help
        if re.match(r"^help\b", raw):
            event.set_result(MessageEventResult().message(M("help_main")).use_t2i(False))
            return

        # ask (redirect to Agent)
        if re.match(r"^ask\b", raw):
            text = "直接 @本喵 说话就行啦~ 不用加 /jm ask 了喵~"
            event.set_result(MessageEventResult().message(text))
            return

        # cache clean
        m = re.match(r"^cache\s+clean\s*(\d*)$", raw)
        if m:
            days = m.group(1).strip() or "7"
            await _commands.handle_cache(self, event, "clean " + days)
            return

        # cache
        if raw == "cache":
            await _commands.handle_cache(self, event, "")
            return

        # stop
        if raw == "stop":
            await _commands.handle_stop(self, event)
            return

        # queue
        if raw == "queue":
            await _commands.handle_queue(self, event)
            return

        # category
        m = re.match(r"^category\s+(.+)$", raw)
        if m:
            await _commands.handle_category(self, event, m.group(1))
            return

        # random
        m = re.match(r"^random(\s+.*)?$", raw)
        if m:
            await _commands.handle_random(self, event, m.group(1) or "")
            return

        # search
        m = re.match(r"^search\s+(.+)$", raw)
        if m:
            await _commands.handle_search(self, event, m.group(1))
            return

        # info
        m = re.match(r"^info\s+(\d+)$", raw)
        if m:
            await _commands.handle_info(self, event, m.group(1))
            return

        # rank
        m = re.match(r"^rank\s*(day|week|month)?$", raw)
        if m:
            period = m.group(1) or "day"
            await _commands.handle_rank(self, event, period)
            return

        # download subcommand
        m = re.match(r"^download\s+(.+)$", raw)
        if m:
            ids_str = m.group(1)
            await _commands.handle_download_router(self, event, ids_str)
            return

        # /jm <ID> backward compat
        m = re.match(r"^(\d{4,8})$", raw)
        if m:
            await _commands.handle_download(self, event, m.group(1), "pdf")
            return

        # unknown
        event.set_result(MessageEventResult().message(M("help_main")).use_t2i(False))

    # ── LLM Tools（@llm_tool 不要 self，AstrBot 直接调 handler(event, **kwargs)）──
    @llm_tool(name="search_manga")
    async def tool_search_manga(event: AstrMessageEvent, query: str) -> str:
        """搜索 JMComic 漫画。

        Args:
            query(string): 搜索关键词，如 "电锯人"、"全彩"、"魔法少女"
        """
        return await _agent_tools.search_manga(event, query)

    @llm_tool(name="get_manga_info")
    async def tool_get_manga_info(event: AstrMessageEvent, album_id: str) -> str:
        """查看漫画详情，获取章节数、页数、标签、作者等信息。

        Args:
            album_id(string): 漫画数字 ID，如 "123456"
        """
        return await _agent_tools.get_manga_info(event, album_id)

    @llm_tool(name="get_rank")
    async def tool_get_rank(event: AstrMessageEvent, period: str = "day") -> str:
        """查看 JMComic 排行榜。

        Args:
            period(string): 排行周期 day/week/month，默认 day
        """
        return await _agent_tools.get_rank(event, period)

    @llm_tool(name="random_recommend")
    async def tool_random_recommend(event: AstrMessageEvent, tag: str = "") -> str:
        """随机推荐漫画（可指定标签）。

        Args:
            tag(string): 标签，如 "原神"、"全彩"、"无修正"，留空则完全随机
        """
        return await _agent_tools.random_recommend(event, tag)

    @llm_tool(name="download_manga")
    async def tool_download_manga(event: AstrMessageEvent, album_id: str) -> str:
        """下载漫画并上传到群文件。大文件可能需要较长时间。

        Args:
            album_id(string): 要下载的漫画数字 ID
        """
        return await _agent_tools.download_manga(event, album_id)
