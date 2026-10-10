"""Measure how fast the app comes up and how much memory it holds after boot.

Boots ``python -m app.cli serve`` ``--runs`` times per target, each target on
its own data directory, interleaving the targets. The first boot is a fresh install (database created, seeds run); the
later ones are warm restarts. For each boot it records the seconds from launch
to the first 200 on /api/health, to the first successful demo login, and the
resident memory of the whole process tree at health, +60 s and +120 s.

Writes one JSON object per boot to ``--out`` and a Markdown table to stdout.

Usage:
    python scripts/stability/cold_start_probe.py --target new=backend --target old=../old/backend --data-root /tmp/oe --out probe.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx
import psutil

DEMO_EMAIL = "demo@openconstructionerp.com"
DEMO_PASSWORD = "ColdStartProbe-2026!"


def tree_rss_mb(pid: int) -> float | None:
    try:
        root = psutil.Process(pid)
        procs = [root, *root.children(recursive=True)]
    except psutil.Error:
        return None
    total = 0
    for proc in procs:
        try:
            total += proc.memory_info().rss
        except psutil.Error:
            continue
    return round(total / 2**20, 1)


def stop(proc: subprocess.Popen[bytes]) -> None:
    try:
        children = psutil.Process(proc.pid).children(recursive=True)
    except psutil.Error:
        children = []
    proc.terminate()
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
    for child in children:
        try:
            child.kill()
        except psutil.Error:
            pass


def boot_once(
    backend: Path, data_dir: Path, port: int, label: str, timeout_s: float, log_dir: Path
) -> dict[str, object]:
    env = dict(os.environ)
    env.update({"DEMO_USER_PASSWORD": DEMO_PASSWORD, "SEED_DEMO": "true", "PYTHONUNBUFFERED": "1"})
    # The tree under test, not whatever ``pip install -e`` pointed at.
    env["PYTHONPATH"] = str(backend)
    base = f"http://127.0.0.1:{port}"
    result: dict[str, object] = {"label": label}
    with (log_dir / f"serve-{label}.log").open("w", encoding="utf8") as log:
        started = time.perf_counter()
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.cli", "serve", "--port", str(port), "--data-dir", str(data_dir)],
            cwd=backend,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            while True:
                if proc.poll() is not None:
                    result["error"] = f"server exited with {proc.returncode}"
                    return result
                if time.perf_counter() - started > timeout_s:
                    result["error"] = "never became healthy"
                    return result
                try:
                    if httpx.get(base + "/api/health", timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            healthy_at = time.perf_counter()
            result["health_s"] = round(healthy_at - started, 1)
            result["rss_health_mb"] = tree_rss_mb(proc.pid)
            while time.perf_counter() - started < timeout_s:
                try:
                    resp = httpx.post(
                        base + "/api/v1/users/auth/login/",
                        json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        result["login_s"] = round(time.perf_counter() - started, 1)
                        break
                    result["login_last_status"] = resp.status_code
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            for mark in (60, 120):
                time.sleep(max(0.0, healthy_at + mark - time.perf_counter()))
                result[f"rss_plus_{mark}s_mb"] = tree_rss_mb(proc.pid)
        finally:
            stop(proc)
    return result


KEYS = ["health_s", "login_s", "rss_health_mb", "rss_plus_60s_mb", "rss_plus_120s_mb"]


def table(name: str, rows: list[dict[str, object]]) -> None:
    print()
    print(f"**{name}**")
    print()
    print("| boot | " + " | ".join(KEYS) + " | error |")
    print("|---" * (len(KEYS) + 2) + "|")
    for row in rows:
        print(f"| {row['label']} | " + " | ".join(str(row.get(k, "")) for k in KEYS) + f" | {row.get('error', '')} |")
    warm = [r for r in rows[1:] if "error" not in r]
    if warm:
        med = {
            k: statistics.median(r[k] for r in warm if r.get(k) is not None)
            for k in KEYS
            if any(r.get(k) is not None for r in warm)
        }
        print("| warm median | " + " | ".join(str(med.get(k, "")) for k in KEYS) + " | |")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        action="append",
        required=True,
        help="name=backend_dir; several targets are booted in turn, so they share the runner's conditions",
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=4)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    targets = [(name, Path(path).resolve()) for name, _, path in (t.partition("=") for t in args.target)]
    log_dir = args.out.parent
    results: dict[str, list[dict[str, object]]] = {name: [] for name, _ in targets}
    # Interleaved: boot i of every target runs back to back, so a slow patch
    # of the runner hits all of them alike instead of skewing one.
    for i in range(args.runs):
        for name, backend in targets:
            data_dir = (args.data_root / name).resolve()
            data_dir.mkdir(parents=True, exist_ok=True)
            label = "fresh" if i == 0 else f"warm{i}"
            row = boot_once(backend, data_dir, args.port, f"{name}-{label}", args.timeout, log_dir)
            row["label"] = label
            print(json.dumps({"target": name, **row}), file=sys.stderr, flush=True)
            results[name].append(row)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf8")
    for name, rows in results.items():
        table(name, rows)
    return 0 if all("error" not in r for rows in results.values() for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
