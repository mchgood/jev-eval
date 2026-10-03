"""Validate datasets, inspect requests, run Jev or rescore saved responses."""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from .backend import JevBackend, error_details, request_for
from .metrics import answer_from, summarize
from .reporting import write_reports
from .schema import load_cases


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for command in ("validate", "dry-run", "run"):
        s = sub.add_parser(command)
        s.add_argument("--data", type=Path, default=Path("data/smoke.xlsx"))
        s.add_argument("--domain", choices=["music", "navigation"])
        s.add_argument("--primitive", choices=["choice", "noul", "score"])
        s.add_argument("--split", choices=["dev", "calibration", "test"])
        s.add_argument("--out", type=Path)
        if command == "run":
            s.add_argument("--model", default=os.getenv("JEV_MODEL", "jev-1.13.0"))
            s.add_argument("--timeout", type=float, default=30)
            s.add_argument("--threshold", type=float, default=0.5)
    s = sub.add_parser("report")
    s.add_argument("--results", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--threshold", type=float, default=0.5)
    a = p.parse_args()
    if hasattr(a, "threshold") and not 0 <= a.threshold <= 1:
        p.error("threshold must be between 0 and 1")
    if a.command == "report":
        rows = [json.loads(x) for x in a.results.read_text().splitlines() if x.strip()]
        manifest_path = a.results.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        write_reports(a.out, summarize(rows, a.threshold, manifest))
        return
    cases = [
        c
        for c in load_cases(a.data)
        if (not a.domain or c.domain == a.domain)
        and (not a.primitive or c.question["type"] == a.primitive)
        and (not a.split or c.split == a.split)
    ]
    if not cases:
        p.error("No cases match the selected filters")
    if a.command == "validate":
        print(f"Validated {len(cases)} cases")
        return
    if a.command == "dry-run":
        text = "\n".join(
            json.dumps({"id": c.id, **request_for(c)}, ensure_ascii=False) for c in cases
        )
        if a.out:
            a.out.parent.mkdir(parents=True, exist_ok=True)
            a.out.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        return
    if not os.getenv("TYPESAFE_API_KEY"):
        p.error("Set TYPESAFE_API_KEY; dry-run works without a key")
    if a.timeout <= 0:
        p.error("timeout must be positive")
    out = a.out or Path("results") / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    out.mkdir(parents=True, exist_ok=False)
    backend = JevBackend(a.model, a.timeout)
    rows = []
    manifest = {
        "model": a.model,
        "dataset_sha256": hashlib.sha256(
            json.dumps(
                [c.model_dump() for c in load_cases(a.data)], sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest(),
        "dataset_path": str(a.data),
        "threshold": a.threshold,
        "cases": [c.id for c in cases],
        "search_backend": "mock",
        "started_at": datetime.now(UTC).isoformat(),
        "retries": 0,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    run_start = perf_counter()
    try:
        with (out / "results.jsonl").open("w", encoding="utf-8") as f:
            for case in cases:
                row = {"case": case.model_dump(), "request": request_for(case)}
                start = perf_counter()
                try:
                    row["raw"] = backend.evaluate(case)
                    answer_from(row["raw"], case.question["type"])
                    row["status"] = "ok"
                except Exception as exc:  # noqa: BLE001 - preserve per-case failures
                    row.update(status="error", **error_details(exc))
                row["latency_ms"] = (perf_counter() - start) * 1000
                f.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                f.flush()
                rows.append(row)
                print(
                    f"{case.id}: {row['status']}"
                    + (
                        f" ({row['error_type']}, HTTP {row.get('http_status', 'n/a')}): "
                        f"{row.get('error_message', '')}"
                        if row["status"] == "error"
                        else ""
                    ),
                    flush=True,
                )
    finally:
        backend.close()
        manifest.update(
            ended_at=datetime.now(UTC).isoformat(),
            elapsed_seconds=perf_counter() - run_start,
            completed_cases=len(rows),
        )
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        write_reports(out, summarize(rows, a.threshold, manifest))
    print(f"Report: {out / 'report.html'}")
    if any(r["status"] != "ok" for r in rows):
        raise SystemExit(1)
