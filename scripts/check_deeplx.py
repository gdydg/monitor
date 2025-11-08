#!/usr/bin/env python3
"""
Utility script to verify the availability of DeeplX-compatible translation endpoints.

The script reads a CSV file that contains the base URLs of DeeplX servers (the part
before `/translate`) and performs a smoke test translation request against each entry.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence

import requests
from requests import Response


DEFAULT_TEST_TEXT = "Hello, world!"
DEFAULT_SOURCE_LANG = "EN"
DEFAULT_TARGET_LANG = "ZH"


@dataclass
class EndpointResult:
    name: str
    base_url: str
    full_url: str
    success: bool
    status_code: Optional[int]
    elapsed: float
    detail: str


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check availability of DeeplX translation endpoints listed in a CSV file."
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        default="deeplx_endpoints.csv",
        help="Path to CSV file containing DeeplX base URLs (default: %(default)s).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="HTTP request timeout in seconds (default: %(default)s).",
    )
    parser.add_argument(
        "--text",
        default=DEFAULT_TEST_TEXT,
        help="Sample text to translate (default: %(default)s).",
    )
    parser.add_argument(
        "--source-lang",
        default=DEFAULT_SOURCE_LANG,
        help="Source language code (default: %(default)s).",
    )
    parser.add_argument(
        "--target-lang",
        default=DEFAULT_TARGET_LANG,
        help="Target language code (default: %(default)s).",
    )
    parser.add_argument(
        "--json-output",
        help="Optional path to write detailed JSON results.",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Do not fail the script when some endpoints are unavailable.",
    )
    return parser.parse_args(argv)


def read_endpoints(csv_path: str) -> List[tuple[str, str]]:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        has_header = csv.Sniffer().has_header(sample)

        endpoints: List[tuple[str, str]] = []

        if has_header:
            reader = csv.DictReader(f)
            normalized_fieldnames = {name.strip().lower(): name for name in reader.fieldnames or []}
            base_field = normalized_fieldnames.get("base_url")
            if not base_field:
                raise ValueError(
                    "CSV must contain a 'base_url' column when a header row is present."
                )
            name_field = normalized_fieldnames.get("name")

            for row in reader:
                if not row:
                    continue
                raw_base = (row.get(base_field) or "").strip()
                if not raw_base or raw_base.startswith("#"):
                    continue
                name = (row.get(name_field) or "").strip() if name_field else ""
                if not name:
                    name = raw_base
                endpoints.append((name, raw_base))
        else:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                raw_base = row[0].strip()
                if not raw_base or raw_base.startswith("#"):
                    continue
                name = row[1].strip() if len(row) > 1 and row[1].strip() else raw_base
                endpoints.append((name, raw_base))

    if not endpoints:
        raise ValueError(f"No endpoints found in CSV file: {csv_path}")

    return endpoints


def build_payload(text: str, source_lang: str, target_lang: str) -> dict:
    return {
        "text": text,
        "source_lang": source_lang,
        "target_lang": target_lang,
    }


def check_endpoint(
    name: str,
    base_url: str,
    payload: dict,
    timeout: float,
) -> EndpointResult:
    normalized = base_url.rstrip("/")
    full_url = f"{normalized}/translate"

    start = time.perf_counter()
    detail = ""
    status_code: Optional[int] = None
    success = False

    try:
        response: Response = requests.post(
            full_url,
            json=payload,
            timeout=timeout,
            headers={"User-Agent": "deeplx-availability-check/1.0"},
        )
        status_code = response.status_code
        elapsed = time.perf_counter() - start

        if response.status_code == 200:
            try:
                data = response.json()
                # DeeplX responses commonly contain one of these keys.
                if any(key in data for key in ("data", "text", "result", "translation")):
                    success = True
                    detail = "OK"
                else:
                    success = True
                    detail = "OK (JSON format unexpected)"
            except ValueError:
                detail = "Non-JSON response"
        else:
            detail = f"HTTP {response.status_code}"
    except requests.exceptions.RequestException as exc:
        elapsed = time.perf_counter() - start
        detail = str(exc)

    return EndpointResult(
        name=name,
        base_url=base_url,
        full_url=full_url,
        success=success,
        status_code=status_code,
        elapsed=elapsed,
        detail=detail,
    )


def format_results(results: Sequence[EndpointResult]) -> str:
    name_width = max(len("Name"), *(len(r.name) for r in results))
    status_width = len("Status")
    time_width = len("Latency (s)")

    lines = []
    header = f"{'Name':<{name_width}}  {'Status':<{status_width}}  {'Latency (s)':>{time_width}}  Detail"
    lines.append(header)
    lines.append("-" * len(header))

    for result in results:
        status = "OK" if result.success else "FAIL"
        latency = f"{result.elapsed:.3f}"
        lines.append(
            f"{result.name:<{name_width}}  {status:<{status_width}}  {latency:>{time_width}}  {result.detail}"
        )

    return "\n".join(lines)


def write_summary(results: Sequence[EndpointResult]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    ok = sum(1 for r in results if r.success)
    total = len(results)

    lines = [
        f"# DeeplX Availability Check",
        "",
        f"- Total endpoints: {total}",
        f"- Available: {ok}",
        f"- Unavailable: {total - ok}",
        "",
        "| Name | Status | Latency (s) | Detail |",
        "| --- | --- | --- | --- |",
    ]

    for r in results:
        status = "✅" if r.success else "❌"
        latency = f"{r.elapsed:.3f}"
        detail = r.detail.replace("\n", " ")
        lines.append(f"| {r.name} | {status} | {latency} | {detail} |")

    with open(summary_path, "a", encoding="utf-8") as summary_file:
        summary_file.write("\n".join(lines))
        summary_file.write("\n")


def write_json(results: Sequence[EndpointResult], path: str) -> None:
    payload = [
        {
            "name": r.name,
            "base_url": r.base_url,
            "full_url": r.full_url,
            "success": r.success,
            "status_code": r.status_code,
            "latency_seconds": r.elapsed,
            "detail": r.detail,
        }
        for r in results
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    try:
        endpoints = read_endpoints(args.csv_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    payload = build_payload(args.text, args.source_lang, args.target_lang)

    results: List[EndpointResult] = []
    for name, base_url in endpoints:
        result = check_endpoint(name, base_url, payload=payload, timeout=args.timeout)
        results.append(result)

    print(format_results(results))

    write_summary(results)

    if args.json_output:
        try:
            write_json(results, args.json_output)
        except OSError as exc:
            print(f"[warning] Failed to write JSON output: {exc}", file=sys.stderr)

    overall_success = all(r.success for r in results)
    if not overall_success and not args.allow_partial:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
