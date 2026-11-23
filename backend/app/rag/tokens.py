from __future__ import annotations

import logging
import re

import jieba

jieba.setLogLevel(logging.WARNING)

_CJK = r"\u4e00-\u9fa5"
# 支持 X50 / 5G / Pro14 / 3.5 这类型号与数字，避免商品型号在 BM25 里被整词丢弃
_TOKEN_RE = re.compile(rf"[{_CJK}]+|[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)?")
_STOPWORDS = {
    "的", "了", "和", "是", "在", "我", "有", "就", "不", "人", "都", "一", "一个", "上", "也",
    "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己", "这", "那",
    "什么", "怎么", "如何", "请问", "一下", "可以", "吗", "呢", "吧", "啊", "与", "及", "或",
    "the", "a", "an", "is", "are", "of", "to", "and", "or", "in", "on", "for", "with",
}


def tokens(text: str, drop_stopwords: bool = True) -> list[str]:
    raw = [t.strip().lower() for t in jieba.lcut(text) if t.strip()]
    result: list[str] = []
    for token in raw:
        if not _TOKEN_RE.fullmatch(token):
            continue
        if drop_stopwords and token in _STOPWORDS:
            continue
        result.append(token)
    return result


def tokenize_for_fts(text: str) -> str:
    """写入 FTS5 的预分词文本：中文按 jieba 切分，空格分隔供 unicode61 索引。"""
    return " ".join(tokens(text))


def build_fts_query(query: str) -> str:
    """把自然语言查询转成 FTS5 MATCH 表达式（OR 连接、双引号转义）。"""
    terms = tokens(query)
    if not terms:
        return ""
    escaped = [f'"{t.replace(chr(34), "")}"' for t in terms if len(t) <= 30]
    return " OR ".join(escaped[:20])


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：中文按字、英文按 4 字符，用于上下文预算。"""
    cjk = len(re.findall(rf"[{_CJK}]", text))
    other = len(text) - cjk
    return cjk + max(1, other // 4)
