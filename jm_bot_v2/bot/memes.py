"""热梗词典检索模块。

加载并解析 Markdown 格式的梗词典（bot/data/meme_dict.md，源自社区大肥鱼知识库），
支持在对话时匹配热梗并生成注入上下文：梗用来接话，不是用来刷的。
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

# 词典解析条目存储
ENTRIES: list[dict] = []

# 注入行筛选关键词
_KEYWORDS = ("意思", "接法", "她的用法", "出处")
# 键首尾清理标点
_STRIP_PUNCT = " ，。、；：\"\"''「」\t\r\n"


def _extract_keys(title: str, body_lines: list[str]) -> list[str]:
    """从标题和正文中抽取检索键。"""
    raw_keys: list[str] = []

    # 1. 解析标题中的键
    for part in title.split("/"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            left, right = part.split("=", 1)
            raw_keys.append(left)
            # 提取右侧「」或""内的文本
            quotes = re.findall(r'[「"]([^「"」]+)[」"]', right)
            raw_keys.extend(quotes)
        elif "↔" in part:
            for sub in part.split("↔"):
                raw_keys.append(sub)
        else:
            raw_keys.append(part)

    # 2. 解析正文中加粗 token
    for line in body_lines:
        bold_tokens = re.findall(r"\*\*(.+?)\*\*", line)
        raw_keys.extend(bold_tokens)

    # 3. 清洗、过滤与保序去重
    cleaned_keys: list[str] = []
    seen: set[str] = set()
    for k in raw_keys:
        clean = k.strip(_STRIP_PUNCT)
        if not clean or "×" in clean or len(clean) < 2:
            continue
        if clean not in seen:
            seen.add(clean)
            cleaned_keys.append(clean)

    return cleaned_keys


def _build_inject(title: str, body_lines: list[str]) -> str:
    """提取正文关键行构造注入文本。"""
    picked: list[str] = []
    for line in body_lines:
        s = line.strip()
        if s.startswith("- "):
            content = s[2:].strip()
            if any(kw in content for kw in _KEYWORDS):
                picked.append(content)

    if picked:
        picked_text = "；".join(picked)
    else:
        # 无关键词行时，取前两行非空行
        fallback: list[str] = []
        for line in body_lines:
            s = line.strip()
            if s:
                if s.startswith("- "):
                    s = s[2:].strip()
                fallback.append(s)
                if len(fallback) == 2:
                    break
        picked_text = "；".join(fallback)

    if len(picked_text) > 220:
        picked_text = picked_text[:220]

    return f"梗「{title}」：{picked_text}"


def _parse_dict_text(md_text: str):
    """解析 Markdown 文本填充 ENTRIES。"""
    global ENTRIES
    ENTRIES.clear()

    lines = md_text.splitlines()
    current_title: str | None = None
    current_lines: list[str] = []

    def _commit_entry(title: str, b_lines: list[str]):
        keys = _extract_keys(title, b_lines)
        inject = _build_inject(title, b_lines)
        ENTRIES.append(
            {
                "title": title,
                "keys": keys,
                "inject": inject,
            }
        )

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            if current_title is not None:
                _commit_entry(current_title, current_lines)
            current_title = stripped[4:].strip()
            current_lines = []
        elif stripped.startswith("## "):
            if current_title is not None:
                _commit_entry(current_title, current_lines)
                current_title = None
                current_lines = []
        else:
            if current_title is not None:
                current_lines.append(line)

    if current_title is not None:
        _commit_entry(current_title, current_lines)


def _load():
    """模块导入时尝试从同级 data/meme_dict.md 加载词典。"""
    dict_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "meme_dict.md")
    if not os.path.isfile(dict_path):
        return
    try:
        with open(dict_path, "r", encoding="utf-8") as f:
            _parse_dict_text(f.read())
    except Exception as e:
        logger.warning("Failed to load meme dict from %s: %s", dict_path, e)
        ENTRIES.clear()


def _is_latin(s: str) -> bool:
    """判断字符串是否包含拉丁字母。"""
    return any(("a" <= c <= "z") or ("A" <= c <= "Z") for c in s)


def find_memes(text: str, max_entries: int = 2) -> list:
    """根据输入文本检索命中的梗注入项，按词典顺序返回最多 max_entries 条。"""
    if not text or not isinstance(text, str):
        return []

    text_lower = text.lower()
    matched_injects: list[str] = []

    for entry in ENTRIES:
        hit = False
        for k in entry["keys"]:
            if _is_latin(k):
                if k.lower() in text_lower:
                    hit = True
                    break
            else:
                if k in text:
                    hit = True
                    break
        if hit:
            matched_injects.append(entry["inject"])
            if len(matched_injects) >= max_entries:
                break

    return matched_injects


def meme_context(text: str, max_entries: int = 2) -> str:
    """获取格式化后的梗提示上下文（含标题行，调用方直接拼进系统提示），无命中返回空串。"""
    hits = find_memes(text, max_entries=max_entries)
    if not hits:
        return ""
    return "【热梗提示（接话参考，顺势用，别硬刷）】\n" + "\n".join(hits)


# 模块导入时执行加载
_load()
