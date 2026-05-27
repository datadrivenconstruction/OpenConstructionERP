"""‌⁠‍One-shot: dump methods JSON for a single MatchGroup so we can see
what currencies/codes the matcher persisted.

Run:  python scripts/_inspect_group.py <session_id> [<group_key>]
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

BASE = "http://localhost:8000"


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _get(path: str, token: str) -> dict | list:
    req = urllib.request.Request(f"{BASE}{path}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if len(sys.argv) < 2:
        print("usage: _inspect_group.py <session_id> [<group_key>]")
        return 1
    session_id = sys.argv[1]
    auth = _post(
        "/api/v1/users/auth/login/",
        {"email": "demo@openestimator.io", "password": "DemoPass1234!"},
    )
    token = auth["access_token"]
    if len(sys.argv) >= 3:
        gk = sys.argv[2]
        path = f"/api/v1/match_elements/sessions/{session_id}/group?group_key={urllib.parse.quote(gk, safe='')}"
        detail = _get(path, token)
        print(json.dumps(detail, ensure_ascii=False, indent=2)[:4000])
        return 0
    list_resp = _get(
        f"/api/v1/match_elements/sessions/{session_id}/groups?limit=3",
        token,
    )
    if not isinstance(list_resp, dict):
        print(f"unexpected list response: {type(list_resp)}")
        return 1
    for grp in list_resp.get("groups", [])[:1]:
        gk = grp["group_key"]
        path = f"/api/v1/match_elements/sessions/{session_id}/group?group_key={urllib.parse.quote(gk, safe='')}"
        detail = _get(path, token)
        if isinstance(detail, dict):
            print("group_key:", gk)
            print("status:", detail.get("status"))
            methods = detail.get("methods", {})
            for name, candidates in methods.items():
                if not candidates:
                    print(f"  {name}: empty")
                    continue
                top = candidates[0]
                print(
                    f"  {name}: code={top.get('code')!r} "
                    f"unit_rate={top.get('unit_rate')} "
                    f"currency={top.get('currency')!r} "
                    f"region={top.get('region_code')!r}"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
