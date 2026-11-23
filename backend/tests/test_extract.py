"""文件解析：编码回退、CSV 表头映射、类型校验与短文本过滤。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.extract import SUPPORTED_EXTENSIONS, UnsupportedFileType, extract_pages


def test_reads_utf8_text(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("星耀 X50 支持双卡双待，售价 3999 元。", encoding="utf-8")
    pages = extract_pages(path, "a.txt")
    assert pages == [(1, "星耀 X50 支持双卡双待，售价 3999 元。")]


def test_reads_gbk_text(tmp_path: Path) -> None:
    path = tmp_path / "gbk.txt"
    path.write_bytes("云帆 Pro 14 笔记本重 1.39kg，支持 100W 快充。".encode("gbk"))
    pages = extract_pages(path, "gbk.txt")
    assert pages and "云帆 Pro 14" in pages[0][1]


def test_markdown_and_json_treated_as_text(tmp_path: Path) -> None:
    md = tmp_path / "p.md"
    md.write_text("# 价格\n\n- 12GB+256GB：3999 元\n- 16GB+1TB：4999 元", encoding="utf-8")
    assert "3999" in extract_pages(md, "p.md")[0][1]

    data = tmp_path / "p.json"
    data.write_text('{"name": "静界 Air", "noise": "45dB"}', encoding="utf-8")
    assert "静界 Air" in extract_pages(data, "p.json")[0][1]


def test_csv_maps_header_to_fields(tmp_path: Path) -> None:
    path = tmp_path / "sku.csv"
    path.write_text("名称,价格,库存\n星耀X50,3999,120\n云帆Pro14,5999,30\n", encoding="utf-8")
    text = extract_pages(path, "sku.csv")[0][1]
    assert "名称: 星耀X50；价格: 3999；库存: 120" in text
    assert "名称: 云帆Pro14；价格: 5999；库存: 30" in text


def test_csv_column_mismatch_keeps_raw_row(tmp_path: Path) -> None:
    path = tmp_path / "raw.csv"
    path.write_text("名称,价格\n星耀X50,3999,现货\n", encoding="utf-8")
    text = extract_pages(path, "raw.csv")[0][1]
    assert "星耀X50 | 3999 | 现货" in text


def test_unsupported_extension_raises(tmp_path: Path) -> None:
    path = tmp_path / "x.exe"
    path.write_bytes(b"binary")
    with pytest.raises(UnsupportedFileType):
        extract_pages(path, "x.exe")


def test_short_text_is_filtered(tmp_path: Path) -> None:
    path = tmp_path / "short.txt"
    path.write_text("太短", encoding="utf-8")
    assert extract_pages(path, "short.txt") == []


def test_supported_extensions_cover_docs(tmp_path: Path) -> None:
    assert {".pdf", ".docx", ".txt", ".md", ".csv"}.issubset(SUPPORTED_EXTENSIONS)
