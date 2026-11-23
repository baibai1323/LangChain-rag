from __future__ import annotations

from app.rag.prompt import (
    SYSTEM_PROMPT,
    build_context,
    build_messages,
    extract_citations,
    strip_invalid_citations,
)
from app.rag.retriever import RetrievedChunk


def make_hit(index: int, content: str = "商品内容", page: int = 1) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"c{index}",
        doc_id=f"d{index}",
        doc_name=f"文档{index}.md",
        page=page,
        content="子块",
        parent_content=content,
        score=0.5,
        source="hybrid",
    )


def test_build_context_numbers_from_one_and_keeps_alignment() -> None:
    hits = [make_hit(1, "第一段"), make_hit(2, "第二段")]
    context, selected = build_context(hits)
    assert selected == hits
    assert context.startswith("[1] 来源：文档1.md 第 1 页")
    assert "[2] 来源：文档2.md" in context
    assert "第一段" in context and "第二段" in context


def test_build_context_stops_when_budget_exhausted() -> None:
    hits = [make_hit(1, "很长" * 300), make_hit(2, "第二段")]
    context, selected = build_context(hits, budget=100)
    assert len(selected) == 1
    assert "文档2.md" not in context


def test_build_context_truncates_parent_body_to_900_chars() -> None:
    long_text = "甲" * 1200
    context, _ = build_context([make_hit(1, long_text)])
    assert "甲" * 900 in context
    assert long_text not in context


def test_build_messages_puts_system_first_and_keeps_last_six_history_items() -> None:
    history = [{"role": "user", "content": f"历史{i}"} for i in range(8)]
    messages = build_messages("现在的问题", "参考资料正文", history)
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == SYSTEM_PROMPT
    history_messages = messages[1:-1]
    assert [m["content"] for m in history_messages] == [f"历史{i}" for i in range(2, 8)]
    assert "现在的问题" in messages[-1]["content"]
    assert "参考资料正文" in messages[-1]["content"]


def test_system_prompt_forbids_reusing_history_citation_numbers() -> None:
    assert "禁止沿用历史对话里的编号" in SYSTEM_PROMPT


def test_extract_citations_returns_unique_in_range_and_in_order() -> None:
    assert extract_citations("结论[2]，补充[1]，重复[2]，越界[9]", total=3) == [2, 1]


def test_strip_invalid_citations_removes_out_of_range_only() -> None:
    cleaned = strip_invalid_citations("价格 3999[1]，保修[2]，活动[5]", total=2)
    assert cleaned == "价格 3999[1]，保修[2]，活动"
