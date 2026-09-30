from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
CHUNKS_PATH = ROOT / "data" / "processed" / "chunks" / "html_chunks.jsonl"


def load_chunks(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo de chunks: {path}")

    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def word_count(text: str) -> int:
    return len(text.split())


def print_counter(title: str, counter: Counter, limit: int = 10) -> None:
    print(f"\n{title}")
    for key, count in counter.most_common(limit):
        print(f"  {key}: {count}")


def inspect(path: Path, sample: int, short_threshold: int) -> None:
    chunks = load_chunks(path)
    print(f"Chunks: {len(chunks)}")

    if not chunks:
        return

    counts = [word_count(row.get("content", "")) for row in chunks]
    print(f"Word count min: {min(counts)}")
    print(f"Word count max: {max(counts)}")
    print(f"Word count avg: {round(sum(counts) / len(counts), 1)}")

    print_counter("Categories", Counter(row.get("category") for row in chunks))
    print_counter(
        "Domains",
        Counter(urlparse(row.get("source_url", "")).netloc for row in chunks),
    )
    print_counter("Top sources", Counter(row.get("source_url") for row in chunks), limit=5)

    short_chunks = [
        row for row in chunks
        if word_count(row.get("content", "")) < short_threshold
    ]
    print(f"\nShort chunks (< {short_threshold} words): {len(short_chunks)}")
    for row in short_chunks[:5]:
        print(f"  {row.get('id')} ({word_count(row.get('content', ''))} words)")

    print(f"\nSample ({min(sample, len(chunks))} chunks)")
    for row in chunks[:sample]:
        content = row.get("content", "")
        preview = content[:350].replace("\n", " ")
        print(f"\n--- {row.get('id')}")
        print(f"Title: {row.get('document_title')}")
        print(f"URL: {row.get('source_url')}")
        print(f"Words: {word_count(content)}")
        print(preview)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect generated RAG HTML chunks.")
    parser.add_argument("--path", type=Path, default=CHUNKS_PATH)
    parser.add_argument("--sample", type=int, default=3)
    parser.add_argument("--short-threshold", type=int, default=80)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    inspect(args.path, sample=args.sample, short_threshold=args.short_threshold)


if __name__ == "__main__":
    main()
