"""Measure time to first text and full response for RAG or MiUni streaming HTTP."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import httpx

ROOT = Path(__file__).resolve().parents[1]


def measure(client, url, question, protocol):
    body = {"question": question} if protocol == "rag" else {"mensaje": question, "sesionId": None}
    started = perf_counter()
    first_text_ms = None
    chunks = 0
    parts = []
    session_id = None
    with client.stream("POST", url, json=body) as response:
        headers_ms = (perf_counter() - started) * 1000
        response.raise_for_status()
        session_id = response.headers.get("X-Session-Id")
        for text in response.iter_text():
            if not text:
                continue
            if first_text_ms is None:
                first_text_ms = (perf_counter() - started) * 1000
            chunks += 1
            parts.append(text)
    total_ms = (perf_counter() - started) * 1000
    answer = "".join(parts)
    if not answer.strip():
        raise ValueError("Empty stream")
    record = {
        "headers_ms": round(headers_ms, 2),
        "first_text_ms": round(first_text_ms, 2),
        "total_ms": round(total_ms, 2),
        "generation_after_first_text_ms": round(total_ms - first_text_ms, 2),
        "received_text_chunks": chunks,
        "characters": len(answer),
        "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
    }
    if protocol == "miuni":
        if not session_id:
            raise ValueError("Missing X-Session-Id")
        history_url = url.rsplit("/stream", 1)[0] + "/sessions/" + session_id
        history = client.get(history_url)
        history.raise_for_status()
        messages = history.json()
        saved = messages[-1] if messages else {}
        record["session_id"] = session_id
        record["answer_persisted"] = saved.get("rol") == "assistant" and saved.get("contenido") == answer
        if not record["answer_persisted"]:
            raise ValueError("Stream not persisted completely")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/v1/chat/stream")
    parser.add_argument("--protocol", choices=["rag", "miuni"], default="rag")
    parser.add_argument("--question", default="¿Para qué sirve la Oficina de la Abogacía General?")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--token-env", default="MIUNI_BENCHMARK_TOKEN",
                        help="Environment variable containing a MiUni JWT; never pass the token on the command line")
    parser.add_argument("--output", type=Path, default=ROOT / ".cache/chat-benchmark.json")
    args = parser.parse_args()
    if not 1 <= args.runs <= 20 or args.timeout <= 0 or not args.question.strip():
        parser.error("Use 1-20 runs, a positive timeout and a nonempty question")
    headers = {}
    if args.protocol == "miuni":
        token = os.getenv(args.token_env)
        if not token:
            parser.error(f"Missing environment variable {args.token_env}")
        headers["Authorization"] = f"Bearer {token}"
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "url": args.url, "protocol": args.protocol, "question": args.question,
        "notes": [
            "First request is cold only if the server has not loaded BGE-M3 yet.",
            "Received HTTP chunks are not model tokens. Total excludes history verification.",
            "MiUni runs create real test conversations for the authenticated account.",
            "Small sequential sample; not a concurrency test or a reliable p95 estimate.",
        ],
        "runs": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=headers, timeout=args.timeout, trust_env=False) as client:
        for index in range(args.runs):
            run_started = perf_counter()
            try:
                result = {"run": index + 1, "ok": True, **measure(
                    client, args.url, args.question, args.protocol)}
            except Exception as exc:
                result = {"run": index + 1, "ok": False, "error_type": type(exc).__name__,
                          "elapsed_ms": round((perf_counter() - run_started) * 1000, 2)}
                if isinstance(exc, httpx.HTTPStatusError):
                    result["status"] = exc.response.status_code
            report["runs"].append(result)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if all(run["ok"] for run in report["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
