"""Validate reviewed source metadata; dry-run by default, never reindex chunks."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import Config
from app.rag.document_metadata import (TEMPORAL_COLUMNS, DocumentMetadata, load_manifest,
                                       lock_source, prepare_update, update_canonical)
from app.rag.repository import RagRepository


def write_backup(path: Path, payload: dict):
    path = path.resolve()
    if any((parent / ".git").exists() for parent in (path.parent, *path.parents)):
        raise ValueError("Backup must be outside every Git workspace")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidentally overwriting the only rollback copy.
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def backfill_metadata(repository, manifest: dict, *, apply=False, backup: Path | None = None,
                      expected_database: str | None = None) -> dict:
    if apply and backup is None:
        raise ValueError("--apply requires --backup outside Git")
    if apply and not expected_database:
        raise ValueError("--apply requires --expected-database")
    # Validate the whole plan before connecting, including direct Python callers.
    manifest = {url: DocumentMetadata.model_validate(item) for url, item in manifest.items()}
    from app.rag.document_metadata import source_url
    for url in manifest:
        source_url(url)
    with repository.connect() as conn, conn.transaction():
        identity = conn.execute("SELECT current_database() AS database, "
                                "inet_server_addr()::text AS host, inet_server_port() AS port").fetchone()
        if expected_database is not None and identity["database"] != expected_database:
            raise ValueError("Connected database does not match --expected-database")
        plan = []
        # Acquire every source lock before row locks: interleaving them can
        # deadlock a reimport that checks a replacement in this same batch.
        for url in sorted(manifest):
            lock_source(conn, url)
        for url, declaration in sorted(manifest.items()):
            rows = conn.execute("SELECT id, referencia, " + ", ".join(TEMPORAL_COLUMNS) +
                                " FROM documentofuente WHERE referencia = %s ORDER BY id FOR UPDATE",
                                (url,)).fetchall()
            if len(rows) != 1:
                raise ValueError(f"Expected exactly one indexed source for {url}; found {len(rows)}")
            row = rows[0]
            changes = prepare_update(conn, row, declaration)
            plan.append((row, changes))
        affected = sum(bool(changes) for _, changes in plan)
        report = {"database": dict(identity), "dry_run": not apply,
                  "matched_sources": len(plan), "affected_rows": affected,
                  "metadata_only": True,
                  "sources": [{"source_url": row["referencia"], "source_id": str(row["id"]),
                               "changed_fields": list(changes)} for row, changes in plan]}
        if apply:
            write_backup(backup, {"version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                                 "database": dict(identity), "before": [row for row, _ in plan],
                                 "manifest": {url: item.model_dump(mode="json", exclude_unset=True)
                                              for url, item in manifest.items()}})
            for row, changes in plan:
                update_canonical(conn, row["id"], changes)
            report["backup"] = str(backup.resolve())
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="Versioned, reviewed source manifest JSON")
    parser.add_argument("--apply", action="store_true", help="Commit canonical metadata only (default: dry-run)")
    parser.add_argument("--backup", type=Path, help="New before-values JSON backup outside Git, required for --apply")
    parser.add_argument("--expected-database", help="Refuse a connection to any other database name")
    args = parser.parse_args(argv)
    if args.apply and args.backup is None:
        parser.error("--apply requires --backup outside Git")
    if args.apply and not args.expected_database:
        parser.error("--apply requires --expected-database")
    manifest = load_manifest(args.manifest)
    report = backfill_metadata(RagRepository(Config), manifest, apply=args.apply, backup=args.backup,
                               expected_database=args.expected_database)
    print(json.dumps(report, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
