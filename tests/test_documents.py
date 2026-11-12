import io

import pytest
from pypdf import PdfWriter

from conftest import make_docx
from core import documents, retrieval
from core.documents import DocumentError, extract, guess_role


def test_docx_keeps_paragraphs_and_tables_in_order():
    data = make_docx("Intro line", table=[["1", "What is HTML?"], ["2", "What is CSS?"]])
    text = extract("bank.docx", data).text
    assert "Intro line" in text
    assert "1 | What is HTML?" in text and text.index("Intro") < text.index("What is CSS?")


def test_txt_and_utf16_are_read():
    assert extract("a.txt", b"hello").text == "hello"
    assert extract("a.txt", "héllo".encode("utf-16")).text == "héllo"


@pytest.mark.parametrize("name,data,message", [
    ("a.exe", b"x", "Unsupported"),
    ("a.docx", b"not a zip", "valid Word"),
    ("a.pdf", b"not a pdf", "valid PDF"),
    ("a.txt", b"", "empty"),
    ("a.txt", b"  \n ", "No readable"),
    ("a.txt", b"bin\x00ary", "plain text"),
])
def test_bad_files_get_clear_messages(name, data, message):
    with pytest.raises(DocumentError, match=message):
        extract(name, data)


def test_pdf_without_text_is_called_scanned():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(DocumentError, match="scanned"):
        extract("scan.pdf", buffer.getvalue())


def test_oversized_text_is_refused_not_cut(monkeypatch):
    monkeypatch.setattr(documents, "MAX_TEXT_CHARS", 5)
    with pytest.raises(DocumentError, match="more text"):
        extract("a.txt", b"too long")


@pytest.mark.parametrize("name,role", [
    ("Homework.docx", "homework"), ("hw.docx", "homework"), ("Notes.pdf", "notes"),
    ("Textbook.docx", "textbook"), ("WEB QUESTION BANK.docx", "homework"), ("shower.txt", "textbook"),
])
def test_role_guessing(name, role):
    assert guess_role(name) == role


def test_search_reaches_the_end_of_a_long_document():
    filler = "\n".join(f"Filler sentence number {i} about nothing in particular." for i in range(5000))
    segments = [{"label": "Book", "text": filler + "\nPhotosynthesis converts sunlight into energy."}]
    chunks = retrieval.chunk_segments(segments, "T")
    assert len(chunks) > 50
    hit = retrieval.Index(chunks).search("what is photosynthesis", 1)[0]
    assert "Photosynthesis" in hit["text"]


def test_chunking_handles_one_huge_line_and_keeps_all_text():
    words = " ".join(f"word{i}" for i in range(4000))
    chunks = retrieval.chunk_segments([{"label": "L", "text": words}], "T", size=500, overlap=50)
    joined = " ".join(c["text"] for c in chunks)
    assert all(len(c["text"]) <= 500 for c in chunks)
    assert "word0 " in joined and "word3999" in joined


def test_select_respects_budget_and_gives_each_query_context():
    chunks = [{"id": f"T{i}", "label": "x", "text": (w + " ") * 50}
              for i, w in enumerate(["alpha", "beta", "gamma", "delta"], start=1)]
    index = retrieval.Index(chunks)
    picked = retrieval.select(index, ["alpha", "delta"], 1, 10_000)
    assert {c["id"] for c in picked} == {"T1", "T4"}
    assert len(retrieval.select(index, ["alpha", "delta"], 1, 300)) == 1


def test_overview_samples_the_whole_document():
    chunks = [{"id": f"T{i}", "label": "x", "text": "y" * 100} for i in range(100)]
    picked = retrieval.overview(chunks, 1000)
    assert len(picked) == 10 and picked[-1]["id"] != "T9"
