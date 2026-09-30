from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
RAW_HTML_METADATA_PATH = ROOT / "data" / "raw" / "html" / "metadata.json"
CHUNKS_PATH = ROOT / "data" / "processed" / "chunks" / "html_chunks.jsonl"

DEFAULT_MAX_WORDS = 900
DEFAULT_OVERLAP_WORDS = 120
MIN_CHUNK_WORDS = 40

REMOVE_SELECTORS = [
    "script",
    "style",
    "noscript",
    "svg",
    "canvas",
    "iframe",
    "form",
    "nav",
    "footer",
    "header",
    ".menu",
    ".navbar",
    ".nav",
    ".sidebar",
    ".widget",
    ".search",
    ".breadcrumb",
    "#wpadminbar",
]


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


def remove_noise(soup: BeautifulSoup) -> None:
    for selector in REMOVE_SELECTORS:
        for element in soup.select(selector):
            element.decompose()


def extract_title(soup: BeautifulSoup, fallback: str | None) -> str:
    heading = soup.find("h1")
    if heading:
        text = clean_text(heading.get_text(" ", strip=True))
        if text:
            return text

    if soup.title and soup.title.string:
        text = clean_text(soup.title.string)
        if text:
            return text

    return fallback or "Documento HTML"


def main_container(soup: BeautifulSoup):
    for selector in ["main", "article", "#content", ".content", ".entry-content", ".site-content"]:
        element = soup.select_one(selector)
        if element:
            return element
    return soup.body or soup


def extract_structured_text(html: str, fallback_title: str | None) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    remove_noise(soup)

    title = extract_title(soup, fallback_title)
    container = main_container(soup)

    parts: list[str] = []
    for element in container.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th"], recursive=True):
        text = clean_text(element.get_text(" ", strip=True))
        if not text:
            continue

        if element.name in {"h1", "h2", "h3", "h4"}:
            parts.append(f"\n{text}\n")
        else:
            parts.append(text)

    if not parts:
        parts = [clean_text(container.get_text(" ", strip=True))]

    text = clean_text("\n".join(parts))
    return title, text


def word_chunks(text: str, max_words: int, overlap_words: int) -> list[str]:
    words = text.split()
    if not words:
        return []

    if len(words) <= max_words:
        return [" ".join(words)]

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunk_words = words[start:end]
        if len(chunk_words) >= MIN_CHUNK_WORDS:
            chunks.append(" ".join(chunk_words))

        if end == len(words):
            break
        start = max(end - overlap_words, start + 1)

    return chunks


def chunk_id(source_url: str, chunk_index: int) -> str:
    parsed = urlparse(source_url)
    base = slugify(f"{parsed.netloc}{parsed.path}")
    return f"{base}-{chunk_index:04d}"


def build_chunks(
    metadata: list[dict[str, Any]],
    max_words: int,
    overlap_words: int,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []

    for page in metadata:
        raw_path = ROOT / page["raw_html_path"]
        if not raw_path.exists():
            continue

        html = raw_path.read_text(encoding="utf-8", errors="replace")
        title, text = extract_structured_text(html, page.get("title"))
        page_chunks = word_chunks(text, max_words=max_words, overlap_words=overlap_words)

        for index, content in enumerate(page_chunks):
            chunks.append(
                {
                    "id": chunk_id(page["url"], index),
                    "source_type": "html",
                    "source_url": page["url"],
                    "document_title": title,
                    "category": page.get("category"),
                    "chunk_index": index,
                    "content": content,
                    "metadata": {
                        "institution": "Universidad de Sonora",
                        "domain": urlparse(page["url"]).netloc,
                        "section": page.get("category"),
                        "last_seen_at": page.get("last_seen_at"),
                        "raw_html_path": page.get("raw_html_path"),
                    },
                }
            )

    return chunks


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False))
            file.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean raw MiUni HTML and generate JSONL chunks.")
    parser.add_argument("--max-words", type=int, default=DEFAULT_MAX_WORDS)
    parser.add_argument("--overlap-words", type=int, default=DEFAULT_OVERLAP_WORDS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metadata = load_metadata(RAW_HTML_METADATA_PATH)
    chunks = build_chunks(
        metadata,
        max_words=args.max_words,
        overlap_words=args.overlap_words,
    )
    write_jsonl(CHUNKS_PATH, chunks)

    print(f"HTML pages read: {len(metadata)}")
    print(f"Chunks generated: {len(chunks)}")
    print(f"Output: {CHUNKS_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
