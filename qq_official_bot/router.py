"""QQ 官方机器人指令路由与处理器
负责解析用户消息（群聊 @机器人 或 私聊消息），调度 JM 漫画 API 与 AI 服务，
并生成符合 QQ 官方开放平台规范的排版响应。
"""
import re
import asyncio
import logging
from typing import Optional

from .config import config

logger = logging.getLogger("qq_bot.router")

# 引入项目现有的 JM 客户端
import sys, os
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

# 正则指令解析
RE_SEARCH = re.compile(r"^(?:/jm\s+search|/搜|搜索)\s+(.+)$", re.IGNORECASE)
RE_INFO = re.compile(r"^(?:/jm\s+(?:info\s+)?|/详情\s+|/本子\s+)(\d{1,10})$", re.IGNORECASE)
RE_RANK = re.compile(r"^(?:/jm\s+rank|/排行|排行榜)(?:\s+(day|week|month|日榜|周榜|月榜))?$", re.IGNORECASE)
RE_RANDOM = re.compile(r"^(?:/jm\s+random|/随机|/随便看)$", re.IGNORECASE)
RE_ASK = re.compile(r"^(?:/jm\s+ask|/问|/chat|/聊聊)\s+(.+)$", re.IGNORECASE)
RE_HELP = re.compile(r"^(?:/jm\s+help|/help|/帮助|/菜单|帮助)$", re.IGNORECASE)


def get_jm_client():
    """获取 JMComic 客户端单例"""
    import jmcomic
    option_path = os.path.join(PARENT_DIR, "option.yml")
    if os.path.exists(option_path):
        opt = jmcomic.create_option_by_file(option_path)
    else:
        opt = jmcomic.JmOption.default()
    return opt.build_jm_client()


class CommandRouter:
    """命令路由管理器"""

    @classmethod
    async def dispatch(cls, raw_content: str, user_id: str, is_group: bool = True) -> str:
        """分发并处理消息"""
        text = raw_content.strip()
        # 清除常见的 @机器人 标记
        text = re.sub(r"<@!\d+>", "", text).strip()
        text = re.sub(r"^@\S+\s*", "", text).strip()

        if not text:
            return cls.help_text()

        # 1. 帮助菜单
        if RE_HELP.match(text) or text in ("/jm", "jm"):
            return cls.help_text()

        # 2. 漫画搜索
        m_search = RE_SEARCH.match(text)
        if m_search:
            keyword = m_search.group(1).strip()
            return await cls.handle_search(keyword)

        # 3. 漫画详情
        m_info = RE_INFO.match(text)
        if m_info:
            album_id = m_info.group(1).strip()
            return await cls.handle_info(album_id)

        # 4. 排行榜
        m_rank = RE_RANK.match(text)
        if m_rank:
            time_type = m_rank.group(1) or "day"
            return await cls.handle_rank(time_type)

        # 5. 随机推荐
        if RE_RANDOM.match(text):
            return await cls.handle_random()

        # 6. AI 问答 / 聊天
        m_ask = RE_ASK.match(text)
        if m_ask:
            question = m_ask.group(1).strip()
            return await cls.handle_ask(question, user_id)

        # 默认回退提示
        return "🤖 收到指令！请输入 /jm help 查看支持的漫画检索与功能菜单。"

    @classmethod
    async def handle_search(cls, keyword: str) -> str:
        """处理漫画搜索"""
        try:
            client = await asyncio.to_thread(get_jm_client)
            page = await asyncio.to_thread(client.search_site, keyword, 1)
            results = list(page.iter_album()) if page else []

            if not results:
                return f"🔍 搜索【{keyword}】未找到相关内容，请尝试换个关键词检索。"

            lines = [f"📚 关键词【{keyword}】搜索结果（前 {min(len(results), config.max_search_results)} 条）："]
            for i, album in enumerate(results[:config.max_search_results], 1):
                # 兼容不同字段
                aid = getattr(album, "album_id", getattr(album, "id", "未知ID"))
                title = getattr(album, "title", getattr(album, "name", "无标题"))
                author = getattr(album, "author", "未知作者")
                lines.append(f"{i}. [ID: {aid}] {title}")
                if author and author != "未知作者":
                    lines.append(f"   ✍️ 作者: {author}")

            lines.append("\n💡 发送【/jm <ID>】即可查看指定作品详细信息。")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return f"❌ 检索失败: {e}"

    @classmethod
    async def handle_info(cls, album_id: str) -> str:
        """处理漫画详情查询"""
        try:
            client = await asyncio.to_thread(get_jm_client)
            album = await asyncio.to_thread(client.get_album_detail, album_id)
            if not album:
                return f"⚠️ 未找到 ID 为 {album_id} 的作品信息。"

            title = getattr(album, "title", getattr(album, "name", "无标题"))
            author = getattr(album, "author", "未知作者")
            tags = getattr(album, "tags", []) or []
            page_count = getattr(album, "page_count", "未知")
            episode_count = getattr(album, "episode_count", len(getattr(album, "episode_list", [])))

            tag_str = "、".join(str(t) for t in tags[:8]) if tags else "暂无标签"

            lines = [
                f"📖 作品详情 [ID: {album_id}]",
                f"📌 标题: {title}",
                f"✍️ 作者: {author}",
                f"📄 章节数: {episode_count} 话 | 总页数: {page_count} 页",
                f"🏷️ 标签: {tag_str}",
            ]
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Get album detail failed: {e}")
            return f"❌ 查询作品详情失败: {e}"

    @classmethod
    async def handle_rank(cls, time_type: str) -> str:
        """处理排行榜查询"""
        try:
            client = await asyncio.to_thread(get_jm_client)
            # 转换参数
            time_map = {
                "day": "today", "日榜": "today",
                "week": "week", "周榜": "week",
                "month": "month", "月榜": "month"
            }
            tt = time_map.get(time_type.lower(), "today")
            page = await asyncio.to_thread(client.rank_site, tt)
            results = list(page.iter_album()) if page else []

            if not results:
                return f"📊 当前暂未获取到 {time_type} 排行榜数据。"

            lines = [f"🏆 JMComic 热门排行榜 ({time_type}) TOP 5:"]
            for i, album in enumerate(results[:5], 1):
                aid = getattr(album, "album_id", getattr(album, "id", "未知ID"))
                title = getattr(album, "title", getattr(album, "name", "无标题"))
                lines.append(f"{i}. [{aid}] {title}")

            lines.append("\n💡 发送【/jm <ID>】查看详情。")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Get rank failed: {e}")
            return f"❌ 获取排行榜失败: {e}"

    @classmethod
    async def handle_random(cls) -> str:
        """处理随机推荐"""
        try:
            client = await asyncio.to_thread(get_jm_client)
            # 随机推荐
            album = await asyncio.to_thread(client.get_album_detail, "random")
            if not album:
                return "🎲 随机推荐获取失败，请重试。"

            aid = getattr(album, "album_id", getattr(album, "id", "未知ID"))
            title = getattr(album, "title", getattr(album, "name", "无标题"))
            author = getattr(album, "author", "未知作者")
            return f"🎲 为您随机抽选推荐作品：\n📌 [{aid}] {title}\n✍️ 作者: {author}\n💡 发送【/jm {aid}】查看详情。"
        except Exception as e:
            logger.error(f"Random failed: {e}")
            return f"❌ 随机推荐获取失败: {e}"

    @classmethod
    async def handle_ask(cls, question: str, user_id: str) -> str:
        """处理 AI 对话助手"""
        if not config.ai_enabled or not config.ai_api_key:
            return "💬 AI 聊天助手未启用或未配置 API Key（请在 config.yaml 或环境变量中配置）。"

        try:
            import anthropic
            client = anthropic.AsyncAnthropic(
                api_key=config.ai_api_key,
                base_url=config.ai_base_url,
            )
            system_prompt = (
                "你是一个友善、可爱的二次元漫画助手。请用活泼亲切的口吻回答用户的提问。"
                "请严格遵守法律法规，保持内容健康积极，避免任何低俗或违规用语。"
            )
            response = await client.messages.create(
                model=config.ai_model,
                max_tokens=600,
                system=system_prompt,
                messages=[{"role": "user", "content": question}]
            )
            answer = ""
            for block in response.content:
                if block.type == "text":
                    answer += block.text
            return answer.strip() or "喵呜~ 本喵刚刚走神了，没听清主人说了什么呢。"
        except Exception as e:
            logger.error(f"AI chat failed: {e}")
            return f"😿 AI 思考超时或异常: {e}"

    @classmethod
    def help_text(cls) -> str:
        """生成帮助菜单"""
        return (
            "🐱【JM 漫画 QQ 官方机器人使用指南】\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🔍 /jm search <关键词>  : 搜索相关漫画作品\n"
            "📖 /jm <作品ID>         : 查询指定作品详细信息\n"
            "🏆 /jm rank [日榜/周榜] : 查看热门排行榜\n"
            "🎲 /jm random           : 随机发现热门作品\n"
            "💬 /jm ask <问题>       : 召唤 AI 助手趣味闲聊\n"
            "ℹ️ /jm help             : 显示此帮助菜单\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📌 提示：官方群聊中请 @机器人 发送指令。"
        )
