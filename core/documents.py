"""Turn uploaded bytes into labelled text. Nothing is written to disk here."""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

MAX_TEXT_CHARS = 3_000_000
MAX_DOCX_UNCOMPRESSED = 300 * 1024 * 1024
ALLOWED_EXTENSIONS = {".docx", ".pdf", ".txt", ".md"}


class DocumentError(Exception):
    """A problem with an uploaded file, with a message safe to show the user."""


@dataclass
class Extracted:
    kind: str
    segments: list[dict]
    pages: int = 0

    @property
    def text(self) -> str:
        return "\n\n".join(s["text"] for s in self.segments)


def _extension(filename: str) -> str:
    return PurePosixPath(filename.replace("\\", "/")).suffix.lower()


def _docx_blocks(data: bytes):
    from docx import Document
    from docx.table import Table

    document = Document(io.BytesIO(data))
    for block in document.iter_inner_content():
        if isinstance(block, Table):
            for row in block.rows:
                cells, seen = [], set()
                for cell in row.cells:
                    if cell._tc in seen:  # merged cells repeat the same element
                        continue
                    seen.add(cell._tc)
                    value = " ".join(cell.text.split())
                    if value:
                        cells.append(value)
                if cells:
                    yield "row", " | ".join(cells)
        else:
            text = block.text.strip()
            if text:
                style = (block.style.name or "") if block.style is not None else ""
                yield ("heading" if style.lower().startswith(("heading", "title")) else "para"), text


def _extract_docx(data: bytes) -> Extracted:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if "word/document.xml" not in archive.namelist():
                raise DocumentError("This file isn't a valid Word document.")
            if sum(info.file_size for info in archive.infolist()) > MAX_DOCX_UNCOMPRESSED:
                raise DocumentError("This Word document is too large to open safely.")
    except zipfile.BadZipFile as exc:
        raise DocumentError("This file has a .docx name but isn't a valid Word document.") from exc

    try:
        blocks = list(_docx_blocks(data))
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError("This Word document couldn't be read. It may be damaged.") from exc

    segments: list[dict] = []
    label, lines = "Start", []
    for kind, text in blocks:
        if kind == "heading":
            if lines:
                segments.append({"label": label, "text": "\n".join(lines)})
            label, lines = text[:80], [text]
        else:
            lines.append(text)
    if lines:
        segments.append({"label": label, "text": "\n".join(lines)})
    return Extracted("docx", segments)


def _extract_pdf(data: bytes) -> Extracted:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    if not data.startswith(b"%PDF-"):
        raise DocumentError("This file has a .pdf name but isn't a valid PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DocumentError("This PDF is password protected. Remove the password and retry.")
        segments = []
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                segments.append({"label": f"Page {number}", "text": text})
        pages = len(reader.pages)
    except DocumentError:
        raise
    except (PyPdfError, ValueError, KeyError, IndexError, TypeError, OSError) as exc:
        raise DocumentError("This PDF couldn't be read. It may be damaged.") from exc
    if pages and sum(len(s["text"]) for s in segments) / pages < 20:
        raise DocumentError("This PDF looks scanned, so it has no readable text. Run OCR on it "
                            "first or upload a text-based copy.")
    return Extracted("pdf", segments, pages)


def _extract_text(data: bytes, kind: str) -> Extracted:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16", errors="replace")
    else:
        if b"\x00" in data[:4096]:
            raise DocumentError("This file doesn't look like plain text.")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")
    text = text.replace("\r\n", "\n").strip()
    return Extracted(kind, [{"label": "Start", "text": text}] if text else [])


def extract(filename: str, data: bytes) -> Extracted:
    extension = _extension(filename)
    if extension not in ALLOWED_EXTENSIONS:
        raise DocumentError("Unsupported file type. Upload a .docx, .pdf, .txt or .md file.")
    if not data:
        raise DocumentError("This file is empty.")
    if extension == ".docx":
        result = _extract_docx(data)
    elif extension == ".pdf":
        result = _extract_pdf(data)
    else:
        result = _extract_text(data, extension.lstrip("."))
    if not result.text.strip():
        raise DocumentError("No readable text was found in this file.")
    if len(result.text) > MAX_TEXT_CHARS:
        raise DocumentError("This document has more text than DocuMentor can handle "
                            "(about 3 million characters). Split it and upload the part you need.")
    return result


def guess_role(filename: str) -> str:
    name = filename.lower()
    if re.search(r"home ?work|(^|[^a-z])hw([^a-z]|$)|assign|worksheet|question|exam|quiz", name):
        return "homework"
    if "note" in name:
        return "notes"
    return "textbook"
