"""Immutable content-addressed, full-row preimages for opt-in source refreshes.

A saved preimage is NOT evidence that its surrounding DB transaction committed.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from uuid import UUID

from app.rag.document_metadata import source_url

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def validate_archive_directory(directory: Path) -> Path:
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Version archive directory must be absolute and outside the repository")
    resolved = directory.resolve()
    if resolved.is_relative_to(REPOSITORY_ROOT.resolve()):
        raise ValueError("Version archive directory must be outside the repository")
    if resolved.exists() and not resolved.is_dir():
        raise ValueError("Version archive directory is not a directory")
    return resolved


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def write_archive(directory: Path, snapshot: dict) -> Path:
    """Publish only complete fsynced files; never overwrite a prior preimage.

    Hard-link publication is atomic and exclusive on the supported local filesystems.
    Unsupported filesystems fail closed instead of weakening the guarantee.
    """
    directory = validate_archive_directory(directory)
    payload = canonical_bytes(snapshot)
    digest = hashlib.sha256(payload).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{digest}.json"

    def verify_existing():
        if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("Existing version archive digest mismatch")

    if target.exists():
        verify_existing()
    else:
        descriptor, temporary = tempfile.mkstemp(prefix=".preimage-", dir=directory)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                verify_existing()
        finally:
            Path(temporary).unlink(missing_ok=True)
    # POSIX needs directory fsync for durable publication. Windows does not expose
    # directory fsync through Python; file fsync above uses the OS flush primitive.
    # Also flush through the final link before returning, including existing
    # archives. Any I/O failure still aborts before DB mutations.
    with target.open("r+b") as stream:
        os.fsync(stream.fileno())
    if os.name != "nt":
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return target


def capture_preimage(conn, url: str, directory: Path, *, expected_source_id=None,
                     expected_temporal_status=None) -> Path:
    """Caller must already hold lock_source in this transaction."""
    source_url(url)
    documents = conn.execute(
        "SELECT id, temporal_status, to_jsonb(d) AS row FROM documentofuente d "
        "WHERE referencia = %s ORDER BY id FOR UPDATE", (url,)).fetchall()
    if len(documents) != 1:
        raise ValueError("Version archive requires exactly one existing canonical source URL")
    document = documents[0]
    if expected_source_id is not None and str(document["id"]) != str(UUID(str(expected_source_id))):
        raise ValueError("Refresh guard source identity changed")
    if expected_temporal_status is not None and document["temporal_status"] != expected_temporal_status:
        raise ValueError("Refresh guard temporal status changed")
    # Capture the union: stale chunks may have a broken/missing parent association,
    # and chunks attached to this parent may have a different URL. Nothing is lost.
    chunks = conn.execute(
        "SELECT to_jsonb(c) || jsonb_build_object('embedding', c.embedding::text) AS row "
        "FROM rag_chunk c WHERE source_url = %s OR documento_fuente_id = %s "
        "ORDER BY chunk_index, id FOR UPDATE", (url, document["id"])).fetchall()
    database = conn.execute(
        "SELECT current_database() AS database, current_schema() AS schema, "
        "inet_server_addr()::text AS server_address, inet_server_port() AS server_port").fetchone()
    preimage = {"document": document["row"], "chunks": [row["row"] for row in chunks]}
    snapshot = {"schema_version": 1, "kind": "source_preimage", "database": dict(database),
                "source_url": url, "source_id": str(document["id"]),
                "chunk_count": len(chunks), "preimage_sha256": hashlib.sha256(canonical_bytes(preimage)).hexdigest(),
                **preimage}
    return write_archive(directory, snapshot)


def load_refresh_guard(path: Path, selected_urls: list[str]) -> dict[str, dict]:
    """Validate a strict manifest; no database or filesystem writes."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(payload, dict) or set(payload) != {"version", "sources"}
            or type(payload["version"]) is not int or payload["version"] != 1
            or not isinstance(payload["sources"], list)):
        raise ValueError("Refresh guard must contain version: 1 and a sources list")
    guards = {}
    for item in payload["sources"]:
        if not isinstance(item, dict) or set(item) != {"source_url", "source_id", "temporal_status"}:
            raise ValueError("Refresh guard entries require source_url, source_id and temporal_status")
        if not isinstance(item["source_url"], str) or not isinstance(item["source_id"], str):
            raise ValueError("Refresh guard source_url and source_id must be strings")
        url = source_url(item["source_url"])
        UUID(item["source_id"])
        if item["temporal_status"] not in ("desconocido", "vigente", "historico", "reemplazado"):
            raise ValueError("Invalid refresh guard temporal_status")
        if url in guards:
            raise ValueError("Duplicate refresh guard source URL")
        guards[url] = item
    if any(url not in guards for url in selected_urls):
        raise ValueError("Each selected document requires exactly one refresh guard entry")
    return {url: guards[url] for url in selected_urls}


def read_archive(path: Path) -> dict:
    """Read a preimage for offline audit/recovery; verify both content hashes.

    This does not restore data or infer whether the index transaction committed.
    """
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Version archive must not be a symbolic link")
    raw = path.read_bytes()
    if path.name != hashlib.sha256(raw).hexdigest() + ".json":
        raise ValueError("Version archive filename digest mismatch")
    snapshot = json.loads(raw)
    if (not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1
            or snapshot.get("kind") != "source_preimage"
            or not isinstance(snapshot.get("document"), dict)
            or not isinstance(snapshot.get("chunks"), list)):
        raise ValueError("Unsupported version archive schema")
    preimage = {"document": snapshot["document"], "chunks": snapshot["chunks"]}
    if hashlib.sha256(canonical_bytes(preimage)).hexdigest() != snapshot.get("preimage_sha256"):
        raise ValueError("Version archive preimage digest mismatch")
    if (snapshot.get("chunk_count") != len(snapshot["chunks"])
            or snapshot.get("source_id") != snapshot["document"].get("id")
            or snapshot.get("source_url") != snapshot["document"].get("referencia")):
        raise ValueError("Version archive source/count mismatch")
    return snapshot

