"""Benchmark Aurum's Olist pipeline without changing runtime/demo logic."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from perf_contract import patch_llm_narrative, validate_report_contract
from src.data_loader import DataLoader
from src.generate_data import build_historical_runs
from src.report_builder import REPORT_PATH, build_report


DATA_DIR = ROOT / "data"
RAW_CSV = DATA_DIR / "raw" / "raw_orders.csv"


def _windows_rss_bytes(pid: int) -> Optional[int]:
    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
    if not handle:
        return None
    try:
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), ctypes.sizeof(counters)
        ):
            return None
        return int(counters.WorkingSetSize)
    finally:
        kernel32.CloseHandle(handle)


def _linux_rss_bytes(pid: int) -> Optional[int]:
    status = Path(f"/proc/{pid}/status")
    if not status.exists():
        return None
    for line in status.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2:
                return int(parts[1]) * 1024
    return None


def process_rss_bytes(pid: int) -> Optional[int]:
    return _windows_rss_bytes(pid) if os.name == "nt" else _linux_rss_bytes(pid)


def measure_subprocess(command: list, timeout: int) -> dict:
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    peak_rss = 0
    timed_out = False
    while process.poll() is None:
        if time.perf_counter() - started > timeout:
            process.kill()
            timed_out = True
            break
        rss = process_rss_bytes(process.pid)
        if rss:
            peak_rss = max(peak_rss, rss)
        time.sleep(0.05)

    stdout, stderr = process.communicate()
    elapsed = time.perf_counter() - started
    return {
        "command": " ".join(command),
        "returncode": process.returncode,
        "timed_out": timed_out,
        "seconds": round(elapsed, 4),
        "peak_rss_mb": round(peak_rss / 1_048_576, 2) if peak_rss else None,
        "stdout_bytes": len(stdout.encode("utf-8")),
        "stderr_bytes": len(stderr.encode("utf-8")),
        "stdout_tail": stdout[-3000:],
        "stderr_tail": stderr[-3000:],
    }


def summarize(values: list) -> dict:
    return {
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "avg": round(mean(values), 4),
        "pstdev": round(pstdev(values), 4) if len(values) > 1 else 0.0,
    }


def load_report() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def contract_result(report: dict, runtime_text: str = "", multiplier: float = 1.0) -> dict:
    ok, failures = validate_report_contract(
        report,
        runtime_text=runtime_text,
        expected_loss_multiplier=multiplier,
    )
    return {"ok": ok, "failures": failures}


def scale_raw_orders(source: Path, target: Path, factor: int) -> tuple:
    raw = pd.read_csv(source)
    frames = []
    for index in range(factor):
        part = raw.copy()
        if index:
            suffix = f"s{index + 1}"
            line_parts = part["invoice_no"].astype(str).str.rsplit("_", n=1, expand=True)
            part["invoice_no"] = line_parts[0] + "_" + suffix + "_" + line_parts[1]
            part["customer_id"] = part["customer_id"].astype(str) + "_" + suffix
        frames.append(part)
    scaled = pd.concat(frames, ignore_index=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    scaled.to_csv(target, index=False)
    expected_revenue = float((scaled["quantity"] * scaled["unit_price"]).sum())
    return len(scaled), expected_revenue


def make_scaled_dataset(factor: int, temp_root: Path) -> tuple:
    data_dir = temp_root / f"olist_{factor}x"
    raw_target = data_dir / "raw" / "raw_orders.csv"
    raw_rows, expected_revenue = scale_raw_orders(RAW_CSV, raw_target, factor)
    historical = build_historical_runs(raw_rows, expected_revenue)
    hist_target = data_dir / "historical" / "historical_runs.csv"
    hist_target.parent.mkdir(parents=True, exist_ok=True)
    historical.to_csv(hist_target, index=False)
    return data_dir, {
        "raw_orders": raw_rows,
        "historical_runs": len(historical),
        "expected_revenue": round(expected_revenue, 2),
    }


def benchmark_report_core(data_dir: Path, run_id: str) -> tuple:
    stage_seconds = {}

    started = time.perf_counter()
    loader = DataLoader(data_dir=data_dir)
    stage_seconds["load_data"] = round(time.perf_counter() - started, 4)
    try:
        started = time.perf_counter()
        report = build_report(loader, run_id=run_id)
        stage_seconds["build_report"] = round(time.perf_counter() - started, 4)
    finally:
        close_started = time.perf_counter()
        loader.close()
        stage_seconds["close_session"] = round(time.perf_counter() - close_started, 4)
    return report, stage_seconds


def measure_scale(factor: int, temp_root: Path) -> dict:
    data_dir, dataset = make_scaled_dataset(factor, temp_root)
    tracemalloc.start()
    started = time.perf_counter()
    report, stage_seconds = benchmark_report_core(
        data_dir,
        run_id=f"benchmark_scale_{factor}x",
    )
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed = time.perf_counter() - started
    encoded = json.dumps(report, default=str).encode("utf-8")
    return {
        "scale": f"{factor}x",
        "dataset": dataset,
        "seconds": round(elapsed, 4),
        "stage_seconds": stage_seconds,
        "tracemalloc_current_mb": round(current / 1_048_576, 2),
        "tracemalloc_peak_mb": round(peak / 1_048_576, 2),
        "report_json_bytes": len(encoded),
        "contract": contract_result(report, multiplier=float(factor)),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--include-10x", action="store_true")
    parser.add_argument("--strict-contract", action="store_true")
    parser.add_argument("--allow-llm", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.allow_llm:
        patch_llm_narrative()

    generate_command = [sys.executable, "-m", "src.generate_data"]
    demo_command = [sys.executable, "-m", "src.run_demo"]
    repeated_runs = []

    for index in range(args.runs):
        generate = measure_subprocess(generate_command, timeout=args.timeout)
        run_demo = measure_subprocess(demo_command, timeout=args.timeout)
        report = load_report()
        repeated_runs.append(
            {
                "run": index + 1,
                "generate_data": generate,
                "run_demo": run_demo,
                "report_json_bytes": REPORT_PATH.stat().st_size,
                "contract": contract_result(report, runtime_text=run_demo["stdout_tail"]),
            }
        )

    with tempfile.TemporaryDirectory(prefix="aurum_olist_scale_") as temp_name:
        temp_root = Path(temp_name)
        scales = [1, 2, 5] + ([10] if args.include_10x else [])
        scale_results = [measure_scale(factor, temp_root) for factor in scales]

    summary = {
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "cwd": str(ROOT),
            "llm_external_calls": "allowed" if args.allow_llm else "skipped/mocked",
        },
        "commands": {
            "generate_data": " ".join(generate_command),
            "run_demo": " ".join(demo_command),
        },
        "repeated_runs": repeated_runs,
        "stability": {
            "generate_data_seconds": summarize(
                [item["generate_data"]["seconds"] for item in repeated_runs]
            ),
            "run_demo_seconds": summarize(
                [item["run_demo"]["seconds"] for item in repeated_runs]
            ),
        },
        "scale_results": scale_results,
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))

    if args.strict_contract:
        failures = [
            failure
            for item in repeated_runs
            for failure in item["contract"]["failures"]
        ]
        failures.extend(
            failure
            for item in scale_results
            for failure in item["contract"]["failures"]
        )
        if failures:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
