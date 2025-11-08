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
from collections import deque
from dataclasses import dataclass
from typing import List, Optional, Sequence

import requests
from requests import Response


DEFAULT_TEST_TEXTS = ["Hello", "Good morning", "Testing"]
DEFAULT_SOURCE_LANG = "EN"
DEFAULT_TARGET_LANG = "ZH"


@dataclass
class SampleResult:
    text: str
    translation: Optional[str]
    success: bool
    detail: str


@dataclass
class EndpointResult:
    name: str
    base_url: str
    full_url: str
    success: bool
    status_code: Optional[int]
    elapsed: float
    detail: str
    samples: List[SampleResult]


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
        dest="texts",
        action="append",
        help=(
            "Sample text to translate. Provide multiple times to test several phrases "
            "(default: built-in sample list)."
        ),
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


def extract_translation(payload: object) -> Optional[str]:
    """
    Attempt to extract a translated string from a DeeplX-like response payload.
    Searches common fields recursively and returns the first non-empty string encountered.
    """

    queue: deque[object] = deque([payload])
    visited: set[int] = set()
    preferred_keys = ("data", "text", "result", "translation")

    while queue:
        current = queue.popleft()
        identifier = id(current)
        if identifier in visited:
            continue
        visited.add(identifier)

        if isinstance(current, str):
            stripped = current.strip()
            if stripped:
                return stripped
            continue

        if isinstance(current, dict):
            for key in preferred_keys:
                if key in current:
                    value = current[key]
                    if isinstance(value, str):
                        stripped_value = value.strip()
                        if stripped_value:
                            return stripped_value
                    else:
                        queue.append(value)

            for value in current.values():
                if isinstance(value, str):
                    stripped_value = value.strip()
                    if stripped_value:
                        return stripped_value
                elif isinstance(value, (dict, list)):
                    queue.append(value)
            continue

        if isinstance(current, list):
            for item in current:
                if isinstance(item, str):
                    stripped_item = item.strip()
                    if stripped_item:
                        return stripped_item
                elif isinstance(item, (dict, list)):
                    queue.append(item)

    return None


def is_translation_valid(source_text: str, translated_text: Optional[str]) -> bool:
    if not translated_text:
        return False

    normalized_source = "".join(source_text.split()).lower()
    normalized_translation = "".join(translated_text.split()).lower()

    if not normalized_translation:
        return False

    return normalized_source != normalized_translation


def check_endpoint(
    name: str,
    base_url: str,
    texts: Sequence[str],
    source_lang: str,
    target_lang: str,
    timeout: float,
) -> EndpointResult:
    normalized = base_url.rstrip("/")
    full_url = f"{normalized}/translate"

    start = time.perf_counter()
    detail = ""
    status_code: Optional[int] = None
    samples: List[SampleResult] = []
    total_samples = len(texts)
    completed_samples = 0
    last_exception: Optional[str] = None

    for sample_text in texts:
        payload = build_payload(sample_text, source_lang, target_lang)
        try:
            response: Response = requests.post(
                full_url,
                json=payload,
                timeout=timeout,
                headers={"User-Agent": "deeplx-availability-check/1.1"},
            )
            status_code = response.status_code
        except requests.exceptions.RequestException as exc:
            last_exception = str(exc)
            samples.append(
                SampleResult(
                    text=sample_text,
                    translation=None,
                    success=False,
                    detail=str(exc),
                )
            )
            break

        if response.status_code != 200:
            samples.append(
                SampleResult(
                    text=sample_text,
                    translation=None,
                    success=False,
                    detail=f"HTTP {response.status_code}",
                )
            )
            break

        try:
            data = response.json()
        except ValueError:
            samples.append(
                SampleResult(
                    text=sample_text,
                    translation=None,
                    success=False,
                    detail="Non-JSON response",
                )
            )
            break

        translation = extract_translation(data)
        if not is_translation_valid(sample_text, translation):
            detail_msg = (
                "Translation identical to source"
                if translation
                else "Missing translation field"
            )
            samples.append(
                SampleResult(
                    text=sample_text,
                    translation=translation,
                    success=False,
                    detail=detail_msg,
                )
            )
            break

        samples.append(
            SampleResult(
                text=sample_text,
                translation=translation,
                success=True,
                detail="OK",
            )
        )
        completed_samples += 1

    elapsed = time.perf_counter() - start
    success = completed_samples == total_samples

    if success:
        detail = f"All {total_samples} samples translated"
    else:
        failed_sample = next((sample for sample in samples if not sample.success), None)
        if failed_sample:
            translated_snippet = (
                f" -> {failed_sample.translation}" if failed_sample.translation else ""
            )
            detail = (
                f"Sample '{failed_sample.text}' failed: "
                f"{failed_sample.detail}{translated_snippet}"
            )
        elif last_exception:
            detail = f"Request failed: {last_exception}"
        else:
            detail = "Unknown failure"

    return EndpointResult(
        name=name,
        base_url=base_url,
        full_url=full_url,
        success=success,
        status_code=status_code,
        elapsed=elapsed,
        detail=detail,
        samples=samples,
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
        "| Name | Status | Latency (s) | Samples OK | Detail |",
        "| --- | --- | --- | --- | --- |",
    ]

    for r in results:
        status = "✅" if r.success else "❌"
        latency = f"{r.elapsed:.3f}"
        detail = r.detail.replace("\n", " ")
        sample_total = len(r.samples)
        samples_ok = sum(sample.success for sample in r.samples)
        sample_count = f"{samples_ok}/{sample_total}" if sample_total else "0/0"
        lines.append(f"| {r.name} | {status} | {latency} | {sample_count} | {detail} |")

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
            "samples": [
                {
                    "text": sample.text,
                    "translation": sample.translation,
                    "success": sample.success,
                    "detail": sample.detail,
                }
                for sample in r.samples
            ],
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

    texts = args.texts or DEFAULT_TEST_TEXTS

    results: List[EndpointResult] = []
    for name, base_url in endpoints:
        result = check_endpoint(
            name=name,
            base_url=base_url,
            texts=texts,
            source_lang=args.source_lang,
            target_lang=args.target_lang,
            timeout=args.timeout,
        )
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
