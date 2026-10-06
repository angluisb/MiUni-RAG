from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urldefrag, urlparse, urlunparse

import requests


ROOT = Path(__file__).resolve().parents[1]
DISCOVERED_PDFS_PATH = ROOT / "data" / "sources" / "discovered_pdfs.json"
RAW_PDF_DIR = ROOT / "data" / "raw" / "pdfs"
PDF_METADATA_PATH = RAW_PDF_DIR / "metadata.json"

DEFAULT_MAX_PDFS = 100
DEFAULT_DELAY_SECONDS = 0.5
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_FILE_MB = 50
USER_AGENT = "MiUniRagScraper/0.1 (educational project)"

OFFICIAL_DOMAIN_ROOTS = {
    "unison.mx",
    "uson.mx",
}

REVIEW_REQUIRED_PATTERNS = [
    re.compile(r"(^|[-_/ .])cv($|[-_/ .])", re.IGNORECASE),
    re.compile(r"curriculum", re.IGNORECASE),
    re.compile(r"vitae", re.IGNORECASE),
    re.compile(r"semblanza", re.IGNORECASE),
]

OUT_OF_SCOPE_PATTERNS = [
    re.compile(r"contraloria\.unison\.mx", re.IGNORECASE),
    re.compile(r"c[oó]digo[-_/ .]?de[-_/ .]?(conducta|[eé]tica)", re.IGNORECASE),
    re.compile(r"presupuest", re.IGNORECASE),
    re.compile(r"fondo[-_/ .]?revolvente", re.IGNORECASE),
    re.compile(r"disposicion[-_/ .]?administrativa", re.IGNORECASE),
    re.compile(r"responsabilidades[-_/ .]?administrativas", re.IGNORECASE),
    re.compile(r"reglamentosydisposicionesadministrativas", re.IGNORECASE),
    re.compile(r"ley[-_/ .]?organica|ley[-_/ .]?org[aá]nica", re.IGNORECASE),
    re.compile(r"manual[-_/ .]?general[-_/ .]?de[-_/ .]?organizacion", re.IGNORECASE),
    re.compile(r"manual[-_/ .]?de[-_/ .]?organizacion", re.IGNORECASE),
    re.compile(r"mensaje[-_/ .]?de[-_/ .]?rectora", re.IGNORECASE),
    re.compile(r"mo[-_/ .]?dach", re.IGNORECASE),
    re.compile(r"mo[-_/ .]?dir[-_/ .]?servicios[-_/ .]?escolares", re.IGNORECASE),
    re.compile(r"pdi|plan[-_/ .]?de[-_/ .]?desarrollo|plandedesarrollo|pd25", re.IGNORECASE),
    re.compile(r"programa[-_/ .]?8m", re.IGNORECASE),
    re.compile(r"programa[-_/ .]?interno[-_/ .]?de[-_/ .]?protecci[oó]n[-_/ .]?civil", re.IGNORECASE),
    re.compile(r"jubilaci[oó]n", re.IGNORECASE),
    re.compile(r"auditoria[-_/ .]?interna", re.IGNORECASE),
]

STUDENT_USEFUL_NORMATIVITY_PATTERNS = [
    re.compile(r"admision|admisión", re.IGNORECASE),
    re.compile(r"beca", re.IGNORECASE),
    re.compile(r"certificado[-_/ .]?de[-_/ .]?pasante", re.IGNORECASE),
    re.compile(r"convocatoria", re.IGNORECASE),
    re.compile(r"colegiatura", re.IGNORECASE),
    re.compile(r"cuotas?", re.IGNORECASE),
    re.compile(r"derechos[-_/ .]?universitarios", re.IGNORECASE),
    re.compile(r"discapacidad", re.IGNORECASE),
    re.compile(r"exenci[oó]n", re.IGNORECASE),
    re.compile(r"ind[ií]gen", re.IGNORECASE),
    re.compile(r"inscripci[oó]n", re.IGNORECASE),
    re.compile(r"mapa[-_/ .]?curricular", re.IGNORECASE),
    re.compile(r"mecanismos[-_/ .]?de[-_/ .]?selecci[oó]n", re.IGNORECASE),
    re.compile(r"movilidad", re.IGNORECASE),
    re.compile(r"opciones[-_/ .]?y[-_/ .]?requisitos[-_/ .]?de[-_/ .]?titulaci[oó]n", re.IGNORECASE),
    re.compile(r"plan[-_/ .]?de[-_/ .]?estudios|planestudios", re.IGNORECASE),
    re.compile(r"pr[aá]cticas?[-_/ .]?profesionales?", re.IGNORECASE),
    re.compile(r"reglamento[-_/ .]?escolar", re.IGNORECASE),
    re.compile(r"servicio[-_/ .]?social", re.IGNORECASE),
    re.compile(r"titulaci[oó]n", re.IGNORECASE),
    re.compile(r"violencia[-_/ .]?de[-_/ .]?g[eé]nero", re.IGNORECASE),
]


def load_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def normalize_url(url: str) -> str | None:
    url, _fragment = urldefrag(url.strip())
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None

    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
    )
    return urlunparse(normalized)


def is_official_unison_host(host: str) -> bool:
    host = host.lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in OFFICIAL_DOMAIN_ROOTS)


def host_is_allowed(url: str, discovered_from: str | None = None) -> bool:
    host = urlparse(url).netloc.lower()
    if not is_official_unison_host(host):
        return False

    if discovered_from:
        source_host = urlparse(discovered_from).netloc.lower()
        return is_official_unison_host(source_host)

    return True


def needs_review(record: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in [
            record.get("url"),
            record.get("filename"),
            record.get("discovered_from"),
        ]
    )
    haystack = unquote(haystack)
    return any(pattern.search(haystack) for pattern in REVIEW_REQUIRED_PATTERNS)


def is_out_of_scope(record: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in [
            record.get("url"),
            record.get("filename"),
            record.get("discovered_from"),
            record.get("category"),
        ]
    )
    haystack = unquote(haystack)
    if str(record.get("category") or "").lower() == "normatividad":
        if not any(pattern.search(haystack) for pattern in STUDENT_USEFUL_NORMATIVITY_PATTERNS):
            return True

    return any(pattern.search(haystack) for pattern in OUT_OF_SCOPE_PATTERNS)


def slugify(value: str) -> str:
    value = unquote(value).lower()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "document"


def safe_pdf_filename(url: str) -> str:
    parsed = urlparse(url)
    source = f"{parsed.netloc}{parsed.path}"
    stem = slugify(source)
    if stem.endswith("-pdf"):
        stem = stem[:-4]
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"{stem}-{digest}.pdf"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def make_record(
    source: dict[str, Any],
    *,
    url: str,
    status: int | None,
    content_type: str | None,
    download_status: str,
    last_downloaded_at: str,
    raw_pdf_path: Path | None = None,
    content_length: int | None = None,
    sha256: str | None = None,
    skip_reason: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    record = {
        "url": url,
        "filename": raw_pdf_path.name if raw_pdf_path else safe_pdf_filename(url),
        "original_filename": source.get("filename"),
        "raw_pdf_path": str(raw_pdf_path.relative_to(ROOT)).replace("\\", "/") if raw_pdf_path else None,
        "status": status,
        "content_type": content_type,
        "content_length": content_length,
        "sha256": sha256,
        "discovered_from": source.get("discovered_from"),
        "depth": source.get("depth"),
        "category": source.get("category"),
        "last_seen_at": source.get("last_seen_at"),
        "last_downloaded_at": last_downloaded_at,
        "download_status": download_status,
    }
    if skip_reason:
        record["skip_reason"] = skip_reason
    if error:
        record["error"] = error
    return record


def download_pdf(
    session: requests.Session,
    source: dict[str, Any],
    timeout_seconds: int,
    max_file_mb: int,
    include_review_required: bool,
    today: str,
) -> dict[str, Any]:
    normalized = normalize_url(source["url"])
    if not normalized:
        return make_record(
            source,
            url=source["url"],
            status=None,
            content_type=None,
            download_status="failed_request",
            last_downloaded_at=today,
            error="invalid_url",
        )

    if not host_is_allowed(normalized, source.get("discovered_from")):
        return make_record(
            source,
            url=normalized,
            status=None,
            content_type=None,
            download_status="skipped_external_redirect",
            last_downloaded_at=today,
            skip_reason="host_not_allowed",
        )

    if is_out_of_scope(source):
        return make_record(
            source,
            url=normalized,
            status=None,
            content_type=source.get("content_type"),
            download_status="skipped_out_of_scope",
            last_downloaded_at=today,
            skip_reason="administrative_or_budget_document",
        )

    if needs_review(source) and not include_review_required:
        return make_record(
            source,
            url=normalized,
            status=None,
            content_type=source.get("content_type"),
            download_status="skipped_review_required",
            last_downloaded_at=today,
            skip_reason="possible_personal_document",
        )

    filename = safe_pdf_filename(normalized)
    output_path = RAW_PDF_DIR / filename
    if output_path.exists():
        content = output_path.read_bytes()
        return make_record(
            source,
            url=normalized,
            status=200,
            content_type="application/pdf",
            download_status="already_downloaded",
            last_downloaded_at=today,
            raw_pdf_path=output_path,
            content_length=len(content),
            sha256=sha256_bytes(content),
        )

    try:
        response = session.get(normalized, timeout=timeout_seconds, allow_redirects=True)
    except requests.Timeout as exc:
        return make_record(
            source,
            url=normalized,
            status=None,
            content_type=None,
            download_status="failed_timeout",
            last_downloaded_at=today,
            error=str(exc),
        )
    except requests.RequestException as exc:
        return make_record(
            source,
            url=normalized,
            status=None,
            content_type=None,
            download_status="failed_request",
            last_downloaded_at=today,
            error=str(exc),
        )

    final_url = normalize_url(response.url) or normalized
    content_type = response.headers.get("content-type", "").split(";")[0].lower()

    if not host_is_allowed(final_url, normalized):
        return make_record(
            source,
            url=final_url,
            status=response.status_code,
            content_type=content_type,
            download_status="skipped_external_redirect",
            last_downloaded_at=today,
            skip_reason="final_host_not_allowed",
        )

    if response.status_code >= 400:
        return make_record(
            source,
            url=final_url,
            status=response.status_code,
            content_type=content_type,
            download_status="failed_http",
            last_downloaded_at=today,
        )

    content = response.content
    max_bytes = max_file_mb * 1024 * 1024
    if len(content) > max_bytes:
        return make_record(
            source,
            url=final_url,
            status=response.status_code,
            content_type=content_type,
            download_status="skipped_too_large",
            last_downloaded_at=today,
            content_length=len(content),
            skip_reason=f"larger_than_{max_file_mb}_mb",
        )

    if content_type != "application/pdf" and not content.startswith(b"%PDF"):
        return make_record(
            source,
            url=final_url,
            status=response.status_code,
            content_type=content_type,
            download_status="skipped_not_pdf",
            last_downloaded_at=today,
            content_length=len(content),
        )

    output_path.write_bytes(content)
    return make_record(
        source,
        url=final_url,
        status=response.status_code,
        content_type=content_type or "application/pdf",
        download_status="downloaded",
        last_downloaded_at=today,
        raw_pdf_path=output_path,
        content_length=len(content),
        sha256=sha256_bytes(content),
    )


def download_pdfs(
    input_path: Path,
    metadata_path: Path,
    max_pdfs: int,
    delay_seconds: float,
    timeout_seconds: int,
    max_file_mb: int,
    include_review_required: bool,
) -> None:
    sources = load_json(input_path)
    today = date.today().isoformat()
    RAW_PDF_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": USER_AGENT})

    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for source in sources:
        if len(records) >= max_pdfs:
            break

        normalized = normalize_url(source.get("url", ""))
        if not normalized or normalized in seen_urls:
            continue
        seen_urls.add(normalized)

        records.append(
            download_pdf(
                session,
                source,
                timeout_seconds=timeout_seconds,
                max_file_mb=max_file_mb,
                include_review_required=include_review_required,
                today=today,
            )
        )
        time.sleep(delay_seconds)

    write_json(metadata_path, records)

    by_status: dict[str, int] = {}
    for record in records:
        status = record["download_status"]
        by_status[status] = by_status.get(status, 0) + 1

    print(f"PDF records processed: {len(records)}")
    for status, count in sorted(by_status.items()):
        print(f"  {status}: {count}")
    print(f"Output: {metadata_path.relative_to(ROOT)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download official MiUni RAG PDFs.")
    parser.add_argument("--input", type=Path, default=DISCOVERED_PDFS_PATH)
    parser.add_argument("--metadata", type=Path, default=PDF_METADATA_PATH)
    parser.add_argument("--max-pdfs", type=int, default=DEFAULT_MAX_PDFS)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-file-mb", type=int, default=DEFAULT_MAX_FILE_MB)
    parser.add_argument("--include-review-required", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    download_pdfs(
        input_path=args.input,
        metadata_path=args.metadata,
        max_pdfs=args.max_pdfs,
        delay_seconds=args.delay,
        timeout_seconds=args.timeout,
        max_file_mb=args.max_file_mb,
        include_review_required=args.include_review_required,
    )


if __name__ == "__main__":
    main()
