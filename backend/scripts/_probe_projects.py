"""‌⁠‍One-shot probe: list projects + their region/currency/BIM-model state.

Run:  python scripts/_probe_projects.py
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://localhost:8000"


def _post(path: str, body: dict, token: str | None = None) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _get(path: str, token: str) -> list | dict:
    req = urllib.request.Request(f"{BASE}{path}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def main() -> int:
    auth = _post(
        "/api/v1/users/auth/login/",
        {"email": "demo@openestimator.io", "password": "DemoPass1234!"},
    )
    token = auth["access_token"]

    projects = _get("/api/v1/projects/", token)
    if not isinstance(projects, list):
        print(f"projects payload not a list: {type(projects)}", file=sys.stderr)
        return 1

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(f"projects: {len(projects)}\n")
    for p in projects:
        pid = (p.get("id") or "?")[:8]
        name = (p.get("name") or "?")[:50]
        region = p.get("region")
        ccy = p.get("currency")
        cat = p.get("cost_database_id") or p.get("active_catalogue_id")
        print(f"  {pid}  {name:50} region={region}  ccy={ccy}  cat={cat}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
