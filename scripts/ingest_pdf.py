from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pdfplumber
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
PDF_METADATA_PATH = ROOT / "data" / "raw" / "pdfs" / "metadata.json"
PDF_CHUNKS_PATH = ROOT / "data" / "processed" / "chunks" / "pdf_chunks.jsonl"

DEFAULT_MAX_WORDS = 512
DEFAULT_OVERLAP_WORDS = 100
MIN_CHUNK_WORDS = 175


def load_metadata(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def clean_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "source"


def word_count(text: str) -> int:
    return len(text.split())


def trailing_words(text: str, count: int) -> str:
    if count <= 0:
        return ""

    words = text.split()
    return " ".join(words[-count:])


def split_oversized_paragraph(paragraph: str, max_words: int, overlap_words: int) -> list[str]:
    words = paragraph.split()
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = max(end - overlap_words, start + 1)

    return chunks


def split_paragraphs(text: str) -> list[str]:
    paragraphs = [clean_text(paragraph) for paragraph in re.split(r"\n{2,}", text)]
    if len(paragraphs) <= 1:
        paragraphs = [clean_text(paragraph) for paragraph in text.splitlines()]
    return [paragraph for paragraph in paragraphs if paragraph]


def content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def chunk_id(source_url: str, chunk_index: int) -> str:
    parsed = urlparse(source_url)
    base = slugify(f"{parsed.netloc}{parsed.path}")
    return f"{base}-{chunk_index:04d}"


def document_title(record: dict[str, Any]) -> str:
    original = record.get("original_filename") or record.get("filename") or "Documento PDF"
    title = Path(str(original)).stem
    title = re.sub(r"[-_]+", " ", title)
    return clean_text(title) or "Documento PDF"


def extract_pages_with_pdfplumber(path: Path) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            text = clean_text(text)
            if text:
                pages.append({"page": index, "text": text})
    return pages


def extract_pages_with_pypdf(path: Path) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    reader = PdfReader(str(path))
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = clean_text(text)
        if text:
            pages.append({"page": index, "text": text})
    return pages


def extract_pdf_pages(path: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        pages = extract_pages_with_pdfplumber(path)
        if pages:
            return pages, "pdfplumber"
    except Exception:
        pass

    pages = extract_pages_with_pypdf(path)
    return pages, "pypdf"


def page_paragraphs(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in pages:
        paragraphs = split_paragraphs(page["text"])
        for paragraph in paragraphs:
            rows.append({"page_start": page["page"], "page_end": page["page"], "text": paragraph})
    return rows


def pdf_chunks_from_pages(
    pages: list[dict[str, Any]],
    max_words: int,
    overlap_words: int,
) -> list[dict[str, Any]]:
    paragraphs = page_paragraphs(pages)
    if not paragraphs:
        return []

    overlap_words = min(overlap_words, max_words // 4)
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def current_text() -> str:
        return clean_text("\n\n".join(item["text"] for item in current))

    def flush_current() -> dict[str, Any] | None:
        text = current_text()
        if not text:
            current.clear()
            return None

        chunk = {
            "content": text,
            "page_start": min(item["page_start"] for item in current),
            "page_end": max(item["page_end"] for item in current),
        }
        current.clear()
        if word_count(text) >= MIN_CHUNK_WORDS:
            chunks.append(chunk)
        return chunk

    for paragraph in paragraphs:
        paragraph_words = word_count(paragraph["text"])
        if paragraph_words > max_words:
            previous = flush_current()
            prefix = trailing_words(previous["content"], overlap_words) if previous else ""
            for piece in split_oversized_paragraph(paragraph["text"], max_words, overlap_words):
                if prefix:
                    candidate = clean_text(f"{prefix}\n\n{piece}")
                    if word_count(candidate) <= max_words:
                        piece = candidate
                    prefix = ""
                if word_count(piece) >= MIN_CHUNK_WORDS:
                    chunks.append(
                        {
                            "content": piece,
                            "page_start": paragraph["page_start"],
                            "page_end": paragraph["page_end"],
                        }
                    )
            continue

        candidate = clean_text("\n\n".join([current_text(), paragraph["text"]]))
        if word_count(candidate) <= max_words:
            current.append(paragraph)
            continue

        previous = flush_current()
        prefix = trailing_words(previous["content"], overlap_words) if previous else ""
        if prefix:
            current.append(
                {
                    "page_start": previous["page_end"],
                    "page_end": previous["page_end"],
                    "text": prefix,
                }
            )
        current.append(paragraph)

        if word_count(current_text()) > max_words:
            current = [paragraph]

    final_text = current_text()
    if final_text:
        final_chunk = {
            "content": final_text,
            "page_start": min(item["page_start"] for item in current),
            "page_end": max(item["page_end"] for item in current),
        }
        if chunks and word_count(final_text) < MIN_CHUNK_WORDS:
            combined = clean_text(f"{chunks[-1]['content']}\n\n{final_text}")
            if word_count(combined) <= max_words:
                chunks[-1]["content"] = combined
                chunks[-1]["page_end"] = final_chunk["page_end"]
            else:
                chunks.append(final_chunk)
        else:
            chunks.append(final_chunk)

    return chunks


def build_chunks(
    metadata: list[dict[str, Any]],
    max_words: int,
    overlap_words: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for record in metadata:
        if record.get("download_status") not in {"downloaded", "already_downloaded"}:
            continue

        raw_pdf_path = record.get("raw_pdf_path")
        if not raw_pdf_path:
            continue

        path = ROOT / raw_pdf_path
        if not path.exists():
            continue

        pages, extractor = extract_pdf_pages(path)
        page_chunks = pdf_chunks_from_pages(pages, max_words=max_words, overlap_words=overlap_words)
        title = document_title(record)
        overlap = min(overlap_words, max_words // 4)

        for index, chunk in enumerate(page_chunks):
            content = chunk["content"]
            rows.append(
                {
                    "id": chunk_id(record["url"], index),
                    "source_type": "pdf",
                    "source_url": record["url"],
                    "document_title": title,
                    "category": record.get("category"),
                    "chunk_index": index,
                    "content": content,
                    "metadata": {
                        "institution": "Universidad de Sonora",
                        "domain": urlparse(record["url"]).netloc,
                        "section": record.get("category"),
                        "raw_pdf_path": raw_pdf_path,
                        "pdf_sha256": record.get("sha256"),
                        "content_word_count": word_count(content),
                        "content_sha256": content_sha256(content),
                        "chunking_strategy": "pdf_paragraph_sliding_window",
                        "chunk_max_words": max_words,
                        "chunk_overlap_words": overlap,
                        "chunk_min_words": MIN_CHUNK_WORDS,
                        "page_start": chunk["page_start"],
                        "page_end": chunk["page_end"],
                        "last_seen_at": record.get("last_seen_at"),
                        "last_downloaded_at": record.get("last_downloaded_at"),
                        "pdf_text_extractor": extractor,
                    },
                }
            )

    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False))
            file.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract MiUni PDFs and generate JSONL chunks.")
    parser.add_argument("--metadata", type=Path, default=PDF_METADATA_PATH)
    parser.add_argument("--output", type=Path, default=PDF_CHUNKS_PATH)
    parser.add_argument("--max-words", type=int, default=DEFAULT_MAX_WORDS)
    parser.add_argument("--overlap-words", type=int, default=DEFAULT_OVERLAP_WORDS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metadata = load_metadata(args.metadata)
    chunks = build_chunks(metadata, max_words=args.max_words, overlap_words=args.overlap_words)
    write_jsonl(args.output, chunks)

    print(f"PDF records read: {len(metadata)}")
    print(f"PDF chunks generated: {len(chunks)}")
    print(f"Output: {args.output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
