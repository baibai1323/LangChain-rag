from __future__ import annotations

import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import settings

SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", ". ", " ", ""]

_parent_splitter = RecursiveCharacterTextSplitter(
    chunk_size=settings.parent_size,
    chunk_overlap=100,
    separators=SEPARATORS,
    keep_separator=True,
)
_child_splitter = RecursiveCharacterTextSplitter(
    chunk_size=settings.chunk_size,
    chunk_overlap=settings.chunk_overlap,
    separators=SEPARATORS,
    keep_separator=True,
)


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_page(text: str) -> list[dict[str, str]]:
    """按页切分：父块用于补全上下文，子块用于向量/BM25 检索（父子分块）。"""
    text = normalize_text(text)
    if len(text) < 10:
        return []
    items: list[dict[str, str]] = []
    for parent in _parent_splitter.split_text(text):
        parent = parent.strip()
        if not parent:
            continue
        children = [c.strip() for c in _child_splitter.split_text(parent)]
        children = [c for c in children if len(c) >= 10] or [parent]
        for child in children:
            items.append({"content": child, "parent_content": parent})
    return items
