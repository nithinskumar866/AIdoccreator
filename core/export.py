"""Build real Word documents from results: headings, lists, tables and inline formatting."""
from __future__ import annotations

import io
import re

from docx import Document
from docx.shared import Pt

from .services import final_items, final_notes

CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
INLINE = re.compile(r"(\*\*.+?\*\*|__.+?__|\*[^*\s][^*]*?\*|`[^`]+`)")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
RULE = re.compile(r"^\s*([-*_])\1{2,}\s*$")


def _clean(text: str) -> str:
    return CONTROL_CHARS.sub("", text or "")


def add_inline(paragraph, text: str) -> None:
    for part in INLINE.split(_clean(text)):
        if not part:
            continue
        if (part.startswith("**") and part.endswith("**")) or (part.startswith("__") and part.endswith("__")):
            paragraph.add_run(part[2:-2]).bold = True
        elif part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Consolas"
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            paragraph.add_run(part[1:-1]).italic = True
        else:
            paragraph.add_run(part)


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def add_markdown(document, text: str) -> None:
    lines = _clean(text).splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or RULE.match(line):
            i += 1
            continue
        heading = HEADING.match(line)
        if heading:
            document.add_heading(_clean(heading.group(2)).replace("*", ""), level=min(len(heading.group(1)), 4))
            i += 1
            continue
        if line.strip().startswith("|") and i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1]):
            header = _table_cells(line)
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_table_cells(lines[i]))
                i += 1
            table = document.add_table(rows=1, cols=len(header))
            table.style = "Table Grid"
            for cell, value in zip(table.rows[0].cells, header):
                cell.paragraphs[0].add_run(value).bold = True
            for row in rows:
                cells = table.add_row().cells
                for cell, value in zip(cells, row):
                    add_inline(cell.paragraphs[0], value)
            continue
        bullet = BULLET.match(line)
        if bullet:
            add_inline(document.add_paragraph(style="List Bullet"), bullet.group(1))
        else:
            add_inline(document.add_paragraph(), line)
        i += 1


def _question_meta(item: dict, tags: bool) -> str:
    if not tags:
        return ""
    parts = []
    if item.get("marks"):
        parts.append(f"{item['marks']} mark{'s' if item['marks'] != 1 else ''}")
    if item.get("difficulty"):
        parts.append(item["difficulty"])
    return f"  ({', '.join(parts)})" if parts else ""


def _homework(document, data: dict, answers: bool, tags: bool) -> None:
    from .services import strip_number

    number = 0
    questions = []
    for item in final_items(data):
        if item["type"] != "question":
            document.add_heading(_clean(item["text"]), level=2)
            continue
        number += 1
        questions.append((number, item))
        lines = item["text"].split("\n")
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(8)
        paragraph.add_run(f"{number}. ").bold = True
        add_inline(paragraph, strip_number(lines[0]))
        meta = _question_meta(item, tags)
        if meta:
            paragraph.add_run(meta).italic = True
        for option in lines[1:]:
            add_inline(document.add_paragraph(), f"    {option}")
        for position, option in enumerate(item.get("options") or []):
            add_inline(document.add_paragraph(), f"    {'abcdefgh'[position]}) {option}")
    if answers:
        document.add_page_break()
        document.add_heading("Answer key", level=1)
        for number, item in questions:
            paragraph = document.add_paragraph()
            paragraph.add_run(f"{number}. ").bold = True
            answer = item.get("answer") or "No answer has been generated for this question yet."
            first, *rest = answer.split("\n")
            add_inline(paragraph, first)
            if rest:
                add_markdown(document, "\n".join(rest))


def export_docx(result: dict, answers: bool = False, tags: bool = False) -> io.BytesIO:
    document = Document()
    document.styles["Normal"].font.name = "Calibri"
    document.styles["Normal"].font.size = Pt(11)
    data = result["data"]
    if result["type"] == "notes_correction":
        document.add_heading(_clean(data["documents"]["notes"]), level=0)
        add_markdown(document, final_notes(data))
    else:
        document.add_heading(_clean(result["title"]), level=0)
        _homework(document, data, answers, tags)
    document.core_properties.author = "DocuMentor"
    document.core_properties.title = _clean(result["title"])[:200]
    buffer = io.BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return buffer
