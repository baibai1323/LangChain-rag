from __future__ import annotations

import pytest

from app.rag.tokens import build_fts_query, estimate_tokens, tokenize_for_fts, tokens


def test_tokens_splits_chinese_and_drops_stopwords() -> None:
    result = tokens("这款手机的保修期是多久？")
    assert "手机" in result
    assert "保修期" in result
    assert "的" not in result
    assert "是" not in result
    assert all("？" not in token for token in result)


def test_tokens_keeps_product_model_numbers() -> None:
    result = tokens("X50 支持 5G 吗")
    assert "x50" in result
    assert "5g" in result


def test_tokens_keeps_decimal_numbers() -> None:
    assert "3.5" in tokens("充电功率 3.5 瓦")


def test_tokens_can_keep_stopwords_when_requested() -> None:
    result = tokens("这个手机", drop_stopwords=False)
    assert any(token in result for token in ("这个", "这"))


def test_build_fts_query_quotes_every_term_and_joins_with_or() -> None:
    query = build_fts_query("星耀 X50 电池")
    assert query.startswith('"')
    assert " OR " in query
    assert '"星耀"' in query
    assert '"x50"' in query


def test_build_fts_query_returns_empty_for_punctuation_only() -> None:
    assert build_fts_query("？？？！！！") == ""


def test_tokenize_for_fts_uses_single_spaces() -> None:
    text = tokenize_for_fts("星耀 X50 支持卫星通信")
    assert "  " not in text
    assert text == " ".join(tokens("星耀 X50 支持卫星通信"))


@pytest.mark.parametrize(
    ("text", "expected"),
    [("你好", 3), ("abcd", 1), ("你好abcd", 3)],
)
def test_estimate_tokens_counts_cjk_by_char_and_ascii_by_four(text: str, expected: int) -> None:
    assert estimate_tokens(text) == expected
