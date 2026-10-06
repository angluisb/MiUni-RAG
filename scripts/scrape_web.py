from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
SEEDS_PATH = ROOT / "data" / "sources" / "web_seed_urls.json"
DISCOVERED_PAGES_PATH = ROOT / "data" / "sources" / "discovered_pages.json"
DISCOVERED_PDFS_PATH = ROOT / "data" / "sources" / "discovered_pdfs.json"
RAW_HTML_DIR = ROOT / "data" / "raw" / "html"
RAW_HTML_METADATA_PATH = RAW_HTML_DIR / "metadata.json"

DEFAULT_MAX_DEPTH = 2
DEFAULT_MAX_PAGES = 50
DEFAULT_DELAY_SECONDS = 0.5
REQUEST_TIMEOUT_SECONDS = 20

HIGH_PRIORITY_DOMAINS = {
    "serviciosescolares.unison.mx",
    "www.unison.mx",
    "unison.mx",
    "campushermosillo.unison.mx",
    "dae.unison.mx",
    "dise.unison.mx",
    "admision.unison.mx",
    "movilidad.unison.mx",
    "ofertaeducativa.unison.mx",
}

MEDIUM_PRIORITY_DOMAINS = {
    "planeacion.unison.mx",
}

EXCLUDED_HOST_PARTS = {
    "facebook.",
    "instagram.",
    "twitter.",
    "x.com",
    "youtube.",
    "youtu.be",
    "linkedin.",
    "wa.me",
    "whatsapp.",
    "google.",
}

USER_AGENT = "MiUniRagScraper/0.1 (educational project)"

PRIORITY_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
}

OFFICIAL_DOMAIN_ROOTS = {
    "unison.mx",
    "uson.mx",
}


@dataclass(frozen=True)
class QueueItem:
    url: str
    discovered_from: str | None
    depth: int
    category: str | None


def load_seeds(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        seeds = json.load(file)

    return sorted(
        seeds,
        key=lambda seed: PRIORITY_ORDER.get(str(seed.get("priority", "medium")).lower(), 1),
    )


def normalize_url(url: str, base_url: str | None = None) -> str | None:
    if base_url:
        url = urljoin(base_url, url)

    url, _fragment = urldefrag(url.strip())
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None

    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=path,
    )
    return urlunparse(normalized)


def is_official_unison_host(host: str) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in OFFICIAL_DOMAIN_ROOTS)


def host_is_allowed(url: str, discovered_from: str | None = None) -> bool:
    host = urlparse(url).netloc.lower()
    if any(part in host for part in EXCLUDED_HOST_PARTS):
        return False

    if host in HIGH_PRIORITY_DOMAINS or host in MEDIUM_PRIORITY_DOMAINS:
        return True

    if not is_official_unison_host(host):
        return False

    if discovered_from:
        source_host = urlparse(discovered_from).netloc.lower()
        return is_official_unison_host(source_host)

    return False


def is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def is_html_like_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    if is_pdf_url(url):
        return False

    ignored_extensions = (
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
        ".zip", ".rar", ".7z", ".doc", ".docx", ".xls", ".xlsx",
        ".ppt", ".pptx", ".mp4", ".mp3", ".avi", ".mov",
    )
    return not path.endswith(ignored_extensions)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def title_from_html(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return clean_text(soup.title.string)

    heading = soup.find(["h1", "h2"])
    if heading:
        return clean_text(heading.get_text(" ", strip=True))

    return None


def response_html(response: requests.Response) -> str:
    encoding = response.apparent_encoding or response.encoding or "utf-8"
    return response.content.decode(encoding, errors="replace")


def safe_html_filename(url: str) -> str:
    parsed = urlparse(url)
    slug = f"{parsed.netloc}{parsed.path}".strip("/")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug).strip("-").lower()
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"{slug or 'index'}-{digest}.html"


def pdf_filename(url: str) -> str:
    name = Path(urlparse(url).path).name
    if name:
        return name

    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"document-{digest}.pdf"


def extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        normalized = normalize_url(anchor["href"], base_url)
        if normalized:
            links.append(normalized)
    return links


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def scrape(max_depth: int, max_pages: int, delay_seconds: float) -> None:
    seeds = load_seeds(SEEDS_PATH)
    today = date.today().isoformat()

    queue: deque[QueueItem] = deque()
    for seed in seeds:
        normalized = normalize_url(seed["url"])
        if not normalized:
            continue

        queue.append(
            QueueItem(
                normalized,
                seed.get("discovered_from"),
                int(seed.get("depth", 0)),
                seed.get("category"),
            )
        )

    visited: set[str] = set()
    queued: set[str] = {item.url for item in queue}
    discovered_pages: dict[str, dict[str, Any]] = {}
    discovered_pdfs: dict[str, dict[str, Any]] = {}
    html_metadata: list[dict[str, Any]] = []

    RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": USER_AGENT})

    while queue and len(discovered_pages) < max_pages:
        item = queue.popleft()
        queued.discard(item.url)

        if item.url in visited:
            continue
        visited.add(item.url)

        if not host_is_allowed(item.url, item.discovered_from):
            continue

        if is_pdf_url(item.url):
            discovered_pdfs.setdefault(item.url, make_pdf_record(item, None, None, today))
            continue

        if not is_html_like_url(item.url):
            continue

        try:
            response = session.get(
                item.url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            discovered_pages[item.url] = {
                "url": item.url,
                "title": None,
                "status": None,
                "content_type": None,
                "discovered_from": item.discovered_from,
                "depth": item.depth,
                "category": item.category,
                "last_seen_at": today,
                "error": str(exc),
            }
            continue

        final_url = normalize_url(response.url) or item.url
        content_type = response.headers.get("content-type", "").split(";")[0].lower()
        if not host_is_allowed(final_url, item.discovered_from or item.url):
            time.sleep(delay_seconds)
            continue

        if "application/pdf" in content_type or is_pdf_url(final_url):
            discovered_pdfs.setdefault(
                final_url,
                make_pdf_record(item, final_url, response.status_code, today, content_type),
            )
            time.sleep(delay_seconds)
            continue

        if response.status_code >= 400 or "html" not in content_type:
            discovered_pages[final_url] = {
                "url": final_url,
                "title": None,
                "status": response.status_code,
                "content_type": content_type,
                "discovered_from": item.discovered_from,
                "depth": item.depth,
                "category": item.category,
                "last_seen_at": today,
            }
            time.sleep(delay_seconds)
            continue

        html = response_html(response)
        title = title_from_html(html)
        raw_path = RAW_HTML_DIR / safe_html_filename(final_url)
        raw_path.write_text(html, encoding="utf-8", errors="replace")

        page_record = {
            "url": final_url,
            "title": title,
            "status": response.status_code,
            "content_type": content_type,
            "discovered_from": item.discovered_from,
            "depth": item.depth,
            "category": item.category,
            "last_seen_at": today,
            "raw_html_path": str(raw_path.relative_to(ROOT)).replace("\\", "/"),
        }
        discovered_pages[final_url] = page_record
        html_metadata.append(page_record)

        if item.depth < max_depth:
            for link in extract_links(html, final_url):
                if link in visited or link in queued:
                    continue
                if not host_is_allowed(link, final_url):
                    continue

                if is_pdf_url(link):
                    discovered_pdfs.setdefault(
                        link,
                        make_pdf_record(
                            QueueItem(link, final_url, item.depth + 1, item.category),
                            None,
                            None,
                            today,
                            "application/pdf",
                        ),
                    )
                    continue

                if is_html_like_url(link):
                    queue.append(QueueItem(link, final_url, item.depth + 1, item.category))
                    queued.add(link)

        time.sleep(delay_seconds)

    write_json(DISCOVERED_PAGES_PATH, sorted(discovered_pages.values(), key=lambda row: row["url"]))
    write_json(DISCOVERED_PDFS_PATH, sorted(discovered_pdfs.values(), key=lambda row: row["url"]))
    write_json(RAW_HTML_METADATA_PATH, sorted(html_metadata, key=lambda row: row["url"]))

    print(f"Pages discovered: {len(discovered_pages)}")
    print(f"PDFs discovered: {len(discovered_pdfs)}")
    print(f"Raw HTML files: {len(html_metadata)}")
    print(f"Output: {DISCOVERED_PAGES_PATH.relative_to(ROOT)}")
    print(f"Output: {DISCOVERED_PDFS_PATH.relative_to(ROOT)}")
    print(f"Output: {RAW_HTML_METADATA_PATH.relative_to(ROOT)}")


def make_pdf_record(
    item: QueueItem,
    final_url: str | None,
    status: int | None,
    today: str,
    content_type: str | None = "application/pdf",
) -> dict[str, Any]:
    url = final_url or item.url
    return {
        "url": url,
        "filename": pdf_filename(url),
        "status": status,
        "content_type": content_type,
        "discovered_from": item.discovered_from,
        "depth": item.depth,
        "category": item.category,
        "last_seen_at": today,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover official MiUni RAG web sources.")
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scrape(
        max_depth=args.max_depth,
        max_pages=args.max_pages,
        delay_seconds=args.delay,
    )


if __name__ == "__main__":
    main()
