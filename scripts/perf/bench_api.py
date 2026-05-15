#!/usr/bin/env python3
"""Sequential benchmark runner for BirdXplorer API endpoints.

Hits each scenario in a JSON file repeatedly against a running API, writes
the raw latencies to a CSV, and prints a per-scenario summary (p50/p95/max).
Designed for single-user baseline measurement (qps = 1).

Usage:
    python scripts/perf/bench_api.py \
        --base-url http://localhost:8000 \
        --scenarios scripts/perf/scenarios.json \
        --iterations 5 \
        --output perf-results.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx


def load_scenarios(path: Path) -> List[Dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(
            f"scenarios file must contain a JSON array, got {type(raw).__name__}"
        )
    for item in raw:
        if "name" not in item or "path" not in item:
            raise ValueError(f"each scenario needs 'name' and 'path': {item!r}")
    return raw


def run_scenario(
    client: httpx.Client,
    scenario: Dict[str, Any],
    iterations: int,
) -> List[Dict[str, Any]]:
    method = scenario.get("method", "GET")
    path = scenario["path"]
    params = scenario.get("params") or {}
    results: List[Dict[str, Any]] = []
    for run_id in range(1, iterations + 1):
        start = time.perf_counter()
        try:
            response = client.request(method, path, params=params)
            duration_ms = (time.perf_counter() - start) * 1000.0
            results.append(
                {
                    "scenario": scenario["name"],
                    "run_id": run_id,
                    "method": method,
                    "path": path,
                    "status": response.status_code,
                    "duration_ms": round(duration_ms, 3),
                    "bytes": len(response.content),
                    "server_ms": response.headers.get("x-response-time-ms", ""),
                    "error": "",
                }
            )
        except httpx.HTTPError as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            results.append(
                {
                    "scenario": scenario["name"],
                    "run_id": run_id,
                    "method": method,
                    "path": path,
                    "status": 0,
                    "duration_ms": round(duration_ms, 3),
                    "bytes": 0,
                    "server_ms": "",
                    "error": str(exc),
                }
            )
    return results


def _percentile(sorted_vals: List[float], pct: float) -> float:
    if not sorted_vals:
        return float("nan")
    idx = max(0, min(len(sorted_vals) - 1, int(round(pct * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def summarize(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_scenario: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_scenario.setdefault(row["scenario"], []).append(row)

    out: List[Dict[str, Any]] = []
    for name, group in by_scenario.items():
        durations = sorted(
            float(r["duration_ms"]) for r in group if r["status"] not in (0,)
        )
        statuses = sorted({int(r["status"]) for r in group})
        if not durations:
            out.append(
                {
                    "scenario": name,
                    "runs": len(group),
                    "success": 0,
                    "statuses": statuses,
                    "p50_ms": None,
                    "p95_ms": None,
                    "max_ms": None,
                    "mean_ms": None,
                }
            )
            continue
        out.append(
            {
                "scenario": name,
                "runs": len(group),
                "success": len(durations),
                "statuses": statuses,
                "p50_ms": _percentile(durations, 0.5),
                "p95_ms": _percentile(durations, 0.95),
                "max_ms": durations[-1],
                "mean_ms": round(statistics.mean(durations), 3),
            }
        )
    return out


def write_csv(rows: List[Dict[str, Any]], output: Path) -> None:
    fieldnames = [
        "scenario",
        "run_id",
        "method",
        "path",
        "status",
        "duration_ms",
        "server_ms",
        "bytes",
        "error",
    ]
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--base-url", default="http://localhost:8000", help="API base URL"
    )
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=Path(__file__).parent / "scenarios.json",
        help="Path to scenarios JSON",
    )
    parser.add_argument(
        "--iterations", type=int, default=3, help="Timed runs per scenario"
    )
    parser.add_argument(
        "--warmup", type=int, default=1, help="Warmup (discarded) runs per scenario"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("perf-results.csv"),
        help="CSV output path for raw runs",
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="Per-request HTTP timeout (seconds)"
    )
    args = parser.parse_args(argv)

    scenarios = load_scenarios(args.scenarios)
    rows: List[Dict[str, Any]] = []
    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        for scenario in scenarios:
            if args.warmup > 0:
                run_scenario(client, scenario, args.warmup)
            rows.extend(run_scenario(client, scenario, args.iterations))

    write_csv(rows, args.output)
    summary = summarize(rows)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nRaw results written to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
