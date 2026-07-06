"""Stress Aurum API routes and assert the active Olist report contract."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from perf_contract import patch_llm_narrative, validate_report_contract


def percentile(values: list, pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * pct) - 1)
    return round(ordered[index], 4)


class ApiClient:
    def request(
        self,
        method: str,
        path: str,
        timeout: float,
        body: Optional[dict] = None,
    ) -> dict:
        raise NotImplementedError


class UrlApiClient(ApiClient):
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/") + "/"

    def request(
        self,
        method: str,
        path: str,
        timeout: float,
        body: Optional[dict] = None,
    ) -> dict:
        url = urljoin(self.base_url, path.lstrip("/"))
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        request = Request(url, data=data, headers=headers, method=method)
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                elapsed = time.perf_counter() - started
                return {
                    "ok": 200 <= response.status < 300,
                    "status": response.status,
                    "method": method,
                    "path": path,
                    "seconds": round(elapsed, 4),
                    "json": json.loads(raw.decode("utf-8")) if raw else {},
                    "error": None,
                }
        except HTTPError as exc:
            elapsed = time.perf_counter() - started
            raw = exc.read()
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else None
            except ValueError:
                payload = None
            return {
                "ok": False,
                "status": exc.code,
                "method": method,
                "path": path,
                "seconds": round(elapsed, 4),
                "json": payload,
                "error": str(exc),
            }
        except (TimeoutError, URLError, OSError) as exc:
            elapsed = time.perf_counter() - started
            return {
                "ok": False,
                "status": None,
                "method": method,
                "path": path,
                "seconds": round(elapsed, 4),
                "json": None,
                "error": str(exc),
            }


class InProcessApiClient(ApiClient):
    def request(
        self,
        method: str,
        path: str,
        timeout: float,
        body: Optional[dict] = None,
    ) -> dict:
        from fastapi.testclient import TestClient
        import api.main as api_main

        started = time.perf_counter()
        try:
            with TestClient(api_main.app) as client:
                response = client.request(method, path, json=body, timeout=timeout)
            elapsed = time.perf_counter() - started
            try:
                payload = response.json()
            except ValueError:
                payload = None
            return {
                "ok": 200 <= response.status_code < 300,
                "status": response.status_code,
                "method": method,
                "path": path,
                "seconds": round(elapsed, 4),
                "json": payload,
                "error": None if response.status_code < 400 else response.text,
            }
        except Exception as exc:
            elapsed = time.perf_counter() - started
            return {
                "ok": False,
                "status": None,
                "method": method,
                "path": path,
                "seconds": round(elapsed, 4),
                "json": None,
                "error": str(exc),
            }


def report_payload(payload: Any) -> Optional[dict]:
    return payload if isinstance(payload, dict) and "final_verdict" in payload else None


def find_run_id(payload: Any) -> Optional[str]:
    if isinstance(payload, dict) and payload.get("run_id") is not None:
        return str(payload["run_id"])
    return None


def burst(
    client: ApiClient,
    method: str,
    path: str,
    total: int,
    concurrency: int,
    timeout: float,
    body_prefix: Optional[str] = None,
) -> list:
    def one(index: int) -> dict:
        body = {"run_id": f"{body_prefix}_{index:03d}"} if body_prefix else None
        return client.request(method, path, timeout=timeout, body=body)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(one, index) for index in range(total)]
        return [future.result() for future in as_completed(futures)]


def endpoint_summary(results: list) -> dict:
    grouped = {}
    for result in results:
        key = f"{result['method']} {result['path']}"
        grouped.setdefault(key, []).append(result)

    summary = {}
    for key, items in grouped.items():
        latencies = [item["seconds"] for item in items]
        summary[key] = {
            "requests": len(items),
            "failures": sum(1 for item in items if not item["ok"]),
            "avg_seconds": round(mean(latencies), 4),
            "p95_seconds": percentile(latencies, 0.95),
            "statuses": sorted({item["status"] for item in items}, key=str),
        }
    return summary


def validate_reports(results: list) -> list:
    validations = []
    for result in results:
        payload = report_payload(result.get("json"))
        if not payload:
            continue
        ok, failures = validate_report_contract(payload)
        validations.append(
            {
                "endpoint": f"{result['method']} {result['path']}",
                "ok": ok,
                "failures": failures,
            }
        )
    return validations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--in-process", action="store_true")
    parser.add_argument("--requests", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--strict-contract", action="store_true")
    parser.add_argument("--allow-llm", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.allow_llm:
        patch_llm_narrative()

    client: ApiClient
    client = InProcessApiClient() if args.in_process else UrlApiClient(args.base_url)
    mode = "in_process" if args.in_process else args.base_url

    all_results = []
    health = client.request("GET", "/health", timeout=args.timeout)
    all_results.append(health)
    if not health["ok"]:
        summary = {
            "mode": mode,
            "status": "api_unavailable",
            "first_error": health,
        }
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return 2

    all_results.extend(
        burst(client, "GET", "/health", args.requests, args.concurrency, args.timeout)
    )

    concurrent_posts = burst(
        client,
        "POST",
        "/runs",
        max(1, args.concurrency),
        args.concurrency,
        args.timeout,
        body_prefix="stress_concurrent",
    )
    all_results.extend(concurrent_posts)

    latest_consistency = []
    run_ids = []
    for index in range(args.requests):
        run_id = f"stress_seq_{index + 1:03d}"
        post = client.request(
            "POST",
            "/runs",
            timeout=args.timeout,
            body={"run_id": run_id},
        )
        all_results.append(post)
        observed_run_id = find_run_id(post.get("json"))
        if observed_run_id:
            run_ids.append(observed_run_id)
            by_id = client.request(
                "GET",
                f"/reports/{observed_run_id}",
                timeout=args.timeout,
            )
            all_results.append(by_id)

        latest = client.request("GET", "/reports/latest", timeout=args.timeout)
        all_results.append(latest)
        latest_run_id = find_run_id(latest.get("json"))
        latest_consistency.append(
            {
                "posted_run_id": observed_run_id,
                "latest_run_id": latest_run_id,
                "consistent": bool(observed_run_id and latest_run_id == observed_run_id),
            }
        )

    all_results.extend(
        burst(
            client,
            "GET",
            "/reports/latest",
            args.requests,
            args.concurrency,
            args.timeout,
        )
    )

    validations = validate_reports(all_results)
    summary = {
        "mode": mode,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "llm_external_calls": "allowed" if args.allow_llm else "skipped/mocked",
        "endpoint_summary": endpoint_summary(all_results),
        "latest_report_consistency": {
            "checks": len(latest_consistency),
            "consistent": sum(1 for item in latest_consistency if item["consistent"]),
            "failures": [
                item for item in latest_consistency if not item["consistent"]
            ],
        },
        "run_ids_observed": run_ids,
        "contract_validations": validations,
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))

    endpoint_failures = sum(
        item["failures"] for item in summary["endpoint_summary"].values()
    )
    contract_failures = [
        failure
        for validation in validations
        for failure in validation["failures"]
    ]
    consistency_failures = summary["latest_report_consistency"]["failures"]
    if endpoint_failures or consistency_failures:
        return 1
    if args.strict_contract and contract_failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
