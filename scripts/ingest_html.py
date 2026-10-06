from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
RAW_HTML_METADATA_PATH = ROOT / "data" / "raw" / "html" / "metadata.json"
CHUNKS_PATH = ROOT / "data" / "processed" / "chunks" / "html_chunks.jsonl"

DEFAULT_MAX_WORDS = 512
DEFAULT_OVERLAP_WORDS = 100
MIN_CHUNK_WORDS = 175

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

MAIN_CONTAINER_SELECTORS = [
    "main",
    "article",
    ".entry-content",
    ".page-content",
    ".content",
    "#primary",
    "#content",
    ".site-content",
    ".elementor",
    ".wp-site-blocks",
]

OUT_OF_SCOPE_PAGE_PATTERNS = [
    re.compile(r"adquisiciones|arrendamientos|obras", re.IGNORECASE),
    re.compile(r"contralor[ií]a", re.IGNORECASE),
    re.compile(r"c[oó]digo[-_/ .]?de[-_/ .]?(conducta|[eé]tica)", re.IGNORECASE),
    re.compile(r"constituci[oó]n", re.IGNORECASE),
    re.compile(r"convenio|contrato[-_/ .]?colectivo|isssteson|staus|steus", re.IGNORECASE),
    re.compile(r"jubilaci[oó]n", re.IGNORECASE),
    re.compile(r"ley[-_/ .]?org[aá]nica", re.IGNORECASE),
    re.compile(r"manual[-_/ .]?de[-_/ .]?organizaci[oó]n", re.IGNORECASE),
    re.compile(r"pdi|plan[-_/ .]?de[-_/ .]?desarrollo", re.IGNORECASE),
    re.compile(r"transparencia", re.IGNORECASE),
]

STUDENT_USEFUL_PAGE_PATTERNS = [
    re.compile(r"admisi[oó]n", re.IGNORECASE),
    re.compile(r"beca", re.IGNORECASE),
    re.compile(r"calendario", re.IGNORECASE),
    re.compile(r"certificado[-_/ .]?de[-_/ .]?pasante", re.IGNORECASE),
    re.compile(r"componente[-_/ .]?curricular", re.IGNORECASE),
    re.compile(r"convocatoria", re.IGNORECASE),
    re.compile(r"colegiatura|cuotas?", re.IGNORECASE),
    re.compile(r"derechos[-_/ .]?universitarios", re.IGNORECASE),
    re.compile(r"eje[-_/ .]?de[-_/ .]?formaci[oó]n[-_/ .]?com[uú]n", re.IGNORECASE),
    re.compile(r"exenci[oó]n", re.IGNORECASE),
    re.compile(r"inscripci[oó]n", re.IGNORECASE),
    re.compile(r"mapa[-_/ .]?curricular", re.IGNORECASE),
    re.compile(r"movilidad", re.IGNORECASE),
    re.compile(r"oferta[-_/ .]?educativa", re.IGNORECASE),
    re.compile(r"plan[-_/ .]?de[-_/ .]?estudios|planestudios", re.IGNORECASE),
    re.compile(r"pr[aá]cticas?[-_/ .]?profesionales?", re.IGNORECASE),
    re.compile(r"reglamento[-_/ .]?escolar", re.IGNORECASE),
    re.compile(r"servicio[-_/ .]?social", re.IGNORECASE),
    re.compile(r"titulaci[oó]n", re.IGNORECASE),
    re.compile(r"violencia[-_/ .]?de[-_/ .]?g[eé]nero", re.IGNORECASE),
]


def load_metadata(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def clean_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"^(Skip to content|Saltar al contenido)\s+", "", value, flags=re.IGNORECASE)
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
    candidates = []
    for selector in MAIN_CONTAINER_SELECTORS:
        for element in soup.select(selector):
            text = clean_text(element.get_text(" ", strip=True))
            if text:
                candidates.append((len(text.split()), element))

    if candidates:
        return max(candidates, key=lambda item: item[0])[1]

    return soup.body or soup


def extract_structured_text(html: str, fallback_title: str | None) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    remove_noise(soup)

    title = extract_title(soup, fallback_title)
    container = main_container(soup)
    container_text = clean_text(container.get_text(" ", strip=True))

    parts: list[str] = []
    for element in container.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th"], recursive=True):
        text = clean_text(element.get_text(" ", strip=True))
        if not text:
            continue

        if element.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            parts.append(f"\n{text}\n")
        else:
            parts.append(text)

    if not parts:
        parts = [container_text]

    text = clean_text("\n".join(parts))
    if len(text.split()) < MIN_CHUNK_WORDS and len(container_text.split()) > len(text.split()):
        text = container_text

    body = soup.body or soup
    body_text = clean_text(body.get_text(" ", strip=True))
    if len(text.split()) < MIN_CHUNK_WORDS and len(body_text.split()) > len(text.split()):
        text = body_text

    return title, text


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
    paragraphs = [clean_text(paragraph) for paragraph in re.split(r"\n+", text)]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    return paragraphs or [clean_text(text)]


def word_chunks(text: str, max_words: int, overlap_words: int) -> list[str]:
    words = text.split()
    if not words:
        return []

    if len(words) <= max_words:
        return [" ".join(words)]

    overlap_words = min(overlap_words, max_words // 4)
    paragraphs = split_paragraphs(text)
    chunks: list[str] = []

    current: list[str] = []

    def flush_current() -> str:
        chunk = clean_text("\n\n".join(current))
        current.clear()
        if chunk and word_count(chunk) >= MIN_CHUNK_WORDS:
            chunks.append(chunk)
        return chunk

    for paragraph in paragraphs:
        paragraph_words = word_count(paragraph)
        if paragraph_words > max_words:
            previous = flush_current()
            prefix = trailing_words(previous, overlap_words)
            for piece in split_oversized_paragraph(paragraph, max_words, overlap_words):
                if prefix:
                    candidate = clean_text(f"{prefix}\n\n{piece}")
                    if word_count(candidate) <= max_words:
                        piece = candidate
                    prefix = ""
                if word_count(piece) >= MIN_CHUNK_WORDS:
                    chunks.append(piece)
            continue

        candidate_parts = [*current, paragraph]
        candidate = clean_text("\n\n".join(candidate_parts))
        if word_count(candidate) <= max_words:
            current.append(paragraph)
            continue

        previous = flush_current()
        prefix = trailing_words(previous, overlap_words)
        current = [prefix, paragraph] if prefix else [paragraph]

        if word_count(clean_text("\n\n".join(current))) > max_words:
            current = [paragraph]

    final_chunk = clean_text("\n\n".join(current))
    if final_chunk:
        if chunks and word_count(final_chunk) < MIN_CHUNK_WORDS:
            combined = clean_text(f"{chunks[-1]}\n\n{final_chunk}")
            if word_count(combined) <= max_words:
                chunks[-1] = combined
            else:
                chunks.append(final_chunk)
        else:
            chunks.append(final_chunk)

    return chunks


def chunk_id(source_url: str, chunk_index: int) -> str:
    parsed = urlparse(source_url)
    base = slugify(f"{parsed.netloc}{parsed.path}")
    return f"{base}-{chunk_index:04d}"


def content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def page_is_out_of_scope(page: dict[str, Any], title: str) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in [
            page.get("url"),
            page.get("title"),
            page.get("category"),
            title,
        ]
    )
    category = str(page.get("category") or "").lower()
    if category == "normatividad":
        if not any(pattern.search(haystack) for pattern in STUDENT_USEFUL_PAGE_PATTERNS):
            return True

    return any(pattern.search(haystack) for pattern in OUT_OF_SCOPE_PAGE_PATTERNS)


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
        if page_is_out_of_scope(page, title):
            continue

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
                        "content_word_count": word_count(content),
                        "content_sha256": content_sha256(content),
                        "chunking_strategy": "paragraph_sliding_window",
                        "chunk_max_words": max_words,
                        "chunk_overlap_words": min(overlap_words, max_words // 4),
                        "chunk_min_words": MIN_CHUNK_WORDS,
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
