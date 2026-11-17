"""Reviewed source metadata and canonical, omission-preserving persistence."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


TEMPORAL_COLUMNS = ("temporal_status", "document_year", "academic_period", "effective_from",
                    "effective_to", "last_verified_at", "superseded_by")


def source_url(value: str) -> str:
    parsed = urlsplit(value)
    parsed.port  # Validate malformed port declarations as well as the hostname.
    if (value != value.strip() or parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.fragment or any(char.isspace() for char in value)):
        raise ValueError("Source/evidence URLs must be exact HTTP(S) URLs without credentials or fragments")
    return value


class ReviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewed_by: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=4000)
    verification_urls: list[str] = Field(min_length=1, max_length=20)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    quote: str | None = Field(default=None, min_length=1, max_length=4000)

    @field_validator("reviewed_by", "rationale", "quote")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Review evidence cannot be blank")
        return value

    @field_validator("verification_urls")
    @classmethod
    def valid_urls(cls, values):
        return [source_url(value) for value in values]


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always")
    source_id: UUID | None = None
    temporal_status: Literal["vigente", "reemplazado", "historico", "desconocido"] | None = None
    document_year: StrictInt | None = Field(default=None, ge=1000, le=9999)
    academic_period: str | None = Field(default=None, pattern=r"^[1-9][0-9]{3}-[12]$")
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    last_verified_at: datetime | None = None
    superseded_by: UUID | None = None
    evidence: ReviewEvidence | None = None

    @field_validator("effective_from", "effective_to", "last_verified_at", mode="before")
    @classmethod
    def timestamp_input(cls, value):
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError("Timestamps must be timezone-aware ISO8601 strings")
        return value

    @field_validator("effective_from", "effective_to", "last_verified_at")
    @classmethod
    def aware(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def valid_declaration(self):
        if "temporal_status" in self.model_fields_set and self.temporal_status is None:
            raise ValueError("temporal_status cannot be null; omit it to preserve classification")
        if "source_id" in self.model_fields_set and self.source_id is None:
            raise ValueError("source_id cannot be null")
        if self.temporal_status in ("vigente", "historico", "reemplazado"):
            if self.evidence is None or self.last_verified_at is None:
                raise ValueError("Verified classification requires review evidence and last_verified_at")
        validate_canonical(self.canonical_values())
        return self

    def canonical_values(self) -> dict:
        return {key: getattr(self, key) for key in TEMPORAL_COLUMNS if key in self.model_fields_set}


def validate_canonical(values: dict):
    start, end = values.get("effective_from"), values.get("effective_to")
    if start is not None and end is not None and start > end:
        raise ValueError("effective_from must not follow effective_to")
    replacement = values.get("superseded_by")
    status = values.get("temporal_status")
    if replacement is not None and status is not None and status != "reemplazado":
        raise ValueError("superseded_by requires reemplazado status")


class ManifestSource(DocumentMetadata):
    source_url: str

    @field_validator("source_url")
    @classmethod
    def exact_url(cls, value):
        return source_url(value)


class SourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    sources: list[ManifestSource]


def load_manifest(path: Path) -> dict[str, DocumentMetadata]:
    # Reject duplicate object keys rather than accepting JSON's last-value wins.
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate manifest key: {key}")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as handle:
        manifest = SourceManifest.model_validate(json.load(handle, object_pairs_hook=unique_object))
    result = {}
    for entry in manifest.sources:
        if entry.source_url in result:
            raise ValueError(f"Duplicate source URL: {entry.source_url}")
        result[entry.source_url] = DocumentMetadata.model_validate(
            entry.model_dump(exclude={"source_url"}, exclude_unset=True))
    return result


def metadata_for_chunks(chunks) -> DocumentMetadata:
    declarations = [DocumentMetadata.model_validate(chunk.metadata.get("document_metadata", {}))
                    for chunk in chunks]
    first = declarations[0] if declarations else DocumentMetadata()
    if any(item.model_dump(exclude_unset=True) != first.model_dump(exclude_unset=True)
           for item in declarations[1:]):
        raise ValueError("Inconsistent document metadata across source chunks")
    return first


def attach_manifest(rows: list[dict], manifest: dict[str, DocumentMetadata]) -> list[dict]:
    for row in rows:
        declaration = manifest.get(row["source_url"])
        if declaration is None:
            continue
        metadata = row.setdefault("metadata", {})
        previous = metadata.get("document_metadata")
        current = declaration.model_dump(mode="json", exclude_unset=True)
        if previous is not None and DocumentMetadata.model_validate(previous).model_dump(
                mode="json", exclude_unset=True) != current:
            raise ValueError(f"Inconsistent manifest and chunk metadata for {row['source_url']}")
        metadata["document_metadata"] = current
    return rows


def lock_source(conn, url: str):
    # Same lock identity as ChunkIndexer, including before parent-row creation.
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (url,))


def prepare_update(conn, row: dict, declaration: DocumentMetadata) -> dict:
    if declaration.source_id is not None and declaration.source_id != row["id"]:
        raise ValueError("Manifest source_id does not match the exact source URL")
    changes = declaration.canonical_values()
    merged = {key: row[key] for key in TEMPORAL_COLUMNS}
    merged.update(changes)
    validate_canonical(merged)
    if (merged.get("temporal_status") in ("vigente", "historico", "reemplazado")
            and "last_verified_at" in changes and merged["last_verified_at"] is None):
        raise ValueError("Cannot clear verification time from a verified classification")
    replacement = merged.get("superseded_by")
    if replacement is not None:
        if replacement == row["id"]:
            raise ValueError("A source cannot supersede itself")
        if not conn.execute("SELECT id FROM documentofuente WHERE id = %s FOR KEY SHARE",
                            (replacement,)).fetchone():
            raise ValueError("Replacement source identity does not exist")
    return {key: value for key, value in changes.items() if row[key] != value}


def update_canonical(conn, document_id, changes: dict):
    if not changes:
        return
    if not set(changes).issubset(TEMPORAL_COLUMNS):
        raise ValueError("Only canonical temporal columns may be updated")
    from psycopg import sql

    assignments = sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(key)) for key in changes)
    conn.execute(sql.SQL("UPDATE documentofuente SET {} WHERE id = %s").format(assignments),
                 (*changes.values(), document_id))
