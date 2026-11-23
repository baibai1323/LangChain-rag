from __future__ import annotations

import re

from .retriever import RetrievedChunk
from .tokens import estimate_tokens

SYSTEM_PROMPT = """你是「云集优选」电商平台的智能客服助手，负责根据知识库资料回答用户关于商品的问题。

回答要求：
1. 只依据下方【参考资料】作答，不要编造资料中没有的价格、参数、库存、活动等信息。
2. 每个关键结论后必须标注引用编号，格式如 [1]、[2][3]；编号只能取自本次【参考资料】中实际出现的编号，禁止沿用历史对话里的编号，也不要编造编号。
3. 如果资料不足以回答，要明确说明“知识库中暂未找到相关信息”，并给出可操作建议（如联系人工客服）。
4. 回答使用简洁的中文，优先分点说明；涉及价格、规格、售后政策时逐条列清。
5. 不要输出“根据参考资料”之类的套话，直接给出答案。"""

REWRITE_PROMPT = """你是检索查询改写助手。请把用户的最新问题改写成一个独立、完整、适合知识库检索的中文查询。
要求：补全指代（它、这个、那个）和省略的主语；保留商品名、型号、数字等关键词；不要回答问题；只输出改写后的查询，不要任何解释。"""

TITLE_PROMPT = """请为下面这段对话生成一个不超过 12 个汉字的中文标题，概括用户想咨询的商品问题。
只输出标题本身，不要引号、不要标点结尾。"""


def build_context(hits: list[RetrievedChunk], budget: int = 3500) -> tuple[str, list[RetrievedChunk]]:
    blocks: list[str] = []
    used = 0
    selected: list[RetrievedChunk] = []
    for index, hit in enumerate(hits, start=1):
        source = f"来源：{hit.doc_name}"
        if hit.page:
            source += f" 第 {hit.page} 页"
        body = hit.parent_content[:900]
        block = f"[{index}] {source}\n{body}"
        cost = estimate_tokens(block)
        if used + cost > budget and selected:
            break
        blocks.append(block)
        selected.append(hit)
        used += cost
    return "\n\n".join(blocks), selected


def build_messages(
    question: str,
    context: str,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in (history or [])[-6:]:
        content = (item.get("content") or "").strip()
        if content:
            messages.append({"role": item["role"], "content": content[:1500]})
    user_content = (
        f"【参考资料】\n{context}\n\n"
        f"【用户问题】\n{question}\n\n"
        "请基于参考资料作答，并在结论后标注 [编号] 引用。"
    )
    messages.append({"role": "user", "content": user_content})
    return messages


_CITE_RE = re.compile(r"\[(\d{1,2})\]")


def extract_citations(answer: str, total: int) -> list[int]:
    seen: list[int] = []
    for match in _CITE_RE.finditer(answer):
        index = int(match.group(1))
        if 1 <= index <= total and index not in seen:
            seen.append(index)
    return seen


def strip_invalid_citations(answer: str, total: int) -> str:
    def repl(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return match.group(0) if 1 <= index <= total else ""

    return _CITE_RE.sub(repl, answer)
