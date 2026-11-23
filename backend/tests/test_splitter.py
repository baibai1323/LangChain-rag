from __future__ import annotations

from app.rag.splitter import normalize_text, split_page


def test_normalize_text_collapses_whitespace_and_fullwidth_space() -> None:
    raw = "第一行\r\n\r\n\r\n第二行　　有空格\t\t结束  "
    assert normalize_text(raw) == "第一行\n\n第二行 有空格 结束"


def test_split_page_returns_empty_for_too_short_text() -> None:
    assert split_page("太短") == []


def test_split_page_children_belong_to_parent() -> None:
    text = "星耀 X50 商品详情。\n\n" + "电池容量 5000mAh，支持 100W 快充。" * 30
    items = split_page(text)
    assert items, "长文本应至少切出一个父块"
    for item in items:
        assert set(item) == {"content", "parent_content"}
        assert item["content"] in item["parent_content"]
        assert len(item["content"]) <= 400 + 50


def test_split_page_produces_multiple_parents_for_long_text() -> None:
    paragraph = "这是用于测试父块切分的商品说明段落，包含价格、参数与售后信息。" * 20
    # 每段内容必须不同，否则按 parent_content 去重后只剩一个父块
    text = "\n\n".join(f"第{index}段：{paragraph}" for index in range(4))
    items = split_page(text)
    parents = {item["parent_content"] for item in items}
    assert len(parents) > 1
    assert all(len(parent) <= 1200 + 100 for parent in parents)
