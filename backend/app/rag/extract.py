from __future__ import annotations

import csv
import io
from pathlib import Path

from ..rag.splitter import normalize_text  # noqa: F401  统一归一化

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv", ".log", ".json"}


class UnsupportedFileType(ValueError):
    pass


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _extract_pdf(path: Path) -> list[tuple[int, str]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001  个别页面解析失败时跳过
            text = ""
        if text.strip():
            pages.append((index, text))
    return pages


def _extract_docx(path: Path) -> list[tuple[int, str]]:
    from docx import Document as DocxDocument

    document = DocxDocument(str(path))
    blocks: list[str] = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))
    return [(1, "\n".join(blocks))]


def _extract_csv(path: Path) -> list[tuple[int, str]]:
    text = _read_text_file(path)
    reader = csv.reader(io.StringIO(text))
    lines: list[str] = []
    header: list[str] = []
    for index, row in enumerate(reader):
        if index == 0:
            header = row
            continue
        if not any(cell.strip() for cell in row):
            continue
        if header and len(header) == len(row):
            lines.append("；".join(f"{h}: {v}" for h, v in zip(header, row) if v.strip()))
        else:
            lines.append(" | ".join(row))
    return [(1, "\n".join(lines))]


def extract_pages(path: Path, filename: str) -> list[tuple[int, str]]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileType(
            f"不支持的文件类型 {suffix or '(无扩展名)'}，当前支持：{', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    if suffix == ".pdf":
        pages = _extract_pdf(path)
    elif suffix == ".docx":
        pages = _extract_docx(path)
    elif suffix == ".csv":
        pages = _extract_csv(path)
    else:
        pages = [(1, _read_text_file(path))]
    pages = [(page, normalize_text(text)) for page, text in pages]
    return [(page, text) for page, text in pages if len(text) >= 10]
