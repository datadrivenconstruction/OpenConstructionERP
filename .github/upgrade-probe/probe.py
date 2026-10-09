"""Upgrade probe for the temporary upgrade-test workflow. Standard library only.

Subcommands:
  wait     poll /api/health then demo login, print seconds to each
  seed     log in as demo, create project + BOQ + position + invoice, snapshot GETs
  verify   compare the snapshot against the upgraded server, demo projects, version
  frontend fetch / and every local asset index.html names
  logscan  count ERROR / Traceback / CRITICAL lines in a log, print excerpts
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request

DEMO_EMAIL = "demo@openconstructionerp.com"
DEMO_PASSWORD = "DemoPass1234!"
VOLATILE = {"updated_at", "last_accessed_at", "etag", "version_counter", "uptime_seconds"}


def call(base, method, path, body=None, token=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw and raw[:1] in b"[{" else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw[:2000]


def login(base):
    st, js = call(base, "POST", "/api/v1/users/auth/login/", {"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    if st == 200 and isinstance(js, dict) and js.get("access_token"):
        return js["access_token"]
    return None


def must(st, js, what, ok=(200, 201)):
    if st not in ok:
        print(f"FAIL {what}: HTTP {st} {json.dumps(js)[:3000] if not isinstance(js, bytes) else js!r}")
        sys.exit(1)
    return js


def cmd_wait(a):
    t0 = time.monotonic()
    health_at = login_at = None
    last = None
    while time.monotonic() - t0 < a.timeout:
        try:
            st, js = call(a.base, "GET", "/api/health", timeout=10)
            last = (st, js)
            if st == 200 and health_at is None:
                health_at = time.monotonic() - t0
                print(f"health 200 after {health_at:.1f}s: status={js.get('status')} version={js.get('version')}")
            if health_at is not None and login(a.base):
                login_at = time.monotonic() - t0
                print(f"demo login OK after {login_at:.1f}s")
                break
        except Exception as exc:  # connection refused while booting
            last = repr(exc)
        time.sleep(3)
    if a.timing_file:
        with open(a.timing_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"label": a.label, "health_s": health_at, "login_s": login_at}) + "\n")
    if login_at is None:
        print(f"FAIL: no health+login within {a.timeout}s; last={str(last)[:2000]}")
        sys.exit(1)


def cmd_seed(a):
    tok = login(a.base)
    assert tok, "demo login failed"
    st, projects = call(a.base, "GET", "/api/v1/projects/?limit=500", token=tok)
    projects = must(st, projects, "list projects")
    plist = projects if isinstance(projects, list) else projects.get("items", [])
    p = must(
        *call(
            a.base,
            "POST",
            "/api/v1/projects/",
            {"name": "Upgrade probe project", "currency": "EUR", "region": "DE", "description": "upgrade-test"},
            tok,
        ),
        "create project",
    )
    b = must(
        *call(a.base, "POST", "/api/v1/boq/boqs/", {"project_id": p["id"], "name": "Upgrade probe BOQ"}, tok),
        "create boq",
    )
    pos = must(
        *call(
            a.base,
            "POST",
            f"/api/v1/boq/boqs/{b['id']}/positions/",
            {
                "boq_id": b["id"],
                "ordinal": "01.001",
                "description": "Concrete C30/37 walls",
                "unit": "m3",
                "quantity": "12.5",
                "unit_rate": "187.35",
            },
            tok,
        ),
        "create position",
    )
    inv = must(
        *call(
            a.base,
            "POST",
            "/api/v1/finance/",
            {
                "project_id": p["id"],
                "invoice_direction": "receivable",
                "invoice_number": "UPG-0001",
                "invoice_date": "2026-10-01",
                "currency_code": "EUR",
                "amount_subtotal": "1000.10",
                "tax_amount": "190.02",
                "amount_total": "1190.12",
                "notes": "upgrade-test",
            },
            tok,
        ),
        "create invoice",
    )
    snap = {
        "demo_project_count": len(plist),
        "ids": {"project": p["id"], "boq": b["id"], "position": pos["id"], "invoice": inv["id"]},
        "get": snapshot(a.base, tok, p["id"], b["id"], inv["id"]),
    }
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(snap, fh, indent=1, sort_keys=True)
    print(f"seeded: demo projects before={len(plist)} ids={snap['ids']}")
    print("position as created:", json.dumps({k: pos.get(k) for k in ("quantity", "unit_rate", "total")}))
    print("invoice as created:", json.dumps({k: inv.get(k) for k in ("amount_subtotal", "tax_amount", "amount_total")}))
    if len(plist) == 0:
        print("FAIL: no demo projects visible before the upgrade")
        sys.exit(1)


def snapshot(base, tok, pid, bid, iid):
    out = {}
    for key, path in (
        ("project", f"/api/v1/projects/{pid}"),
        ("boq", f"/api/v1/boq/boqs/{bid}"),
        ("invoice", f"/api/v1/finance/{iid}"),
    ):
        st, js = call(base, "GET", path, token=tok)
        out[key] = must(st, js, f"GET {path}")
    return out


def diff(old, new, path=""):
    out = []
    if isinstance(old, dict) and isinstance(new, dict):
        for k in old:
            if k in VOLATILE:
                continue
            if k not in new:
                out.append(f"{path}.{k}: missing after upgrade (was {json.dumps(old[k])[:120]})")
            else:
                out += diff(old[k], new[k], f"{path}.{k}")
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            out.append(f"{path}: list length {len(old)} -> {len(new)}")
        for i, (o, n) in enumerate(zip(old, new)):
            out += diff(o, n, f"{path}[{i}]")
    elif old != new:
        out.append(f"{path}: {json.dumps(old)[:200]} -> {json.dumps(new)[:200]}")
    return out


def cmd_verify(a):
    with open(a.snap, encoding="utf-8") as fh:
        snap = json.load(fh)
    failures = []
    st, h = call(a.base, "GET", "/api/health")
    print("health:", json.dumps(h, sort_keys=True)[:4000])
    if st != 200:
        failures.append(f"health HTTP {st}")
    if a.expect_version and h.get("version") != a.expect_version:
        failures.append(f"version {h.get('version')!r} != expected {a.expect_version!r}")
    if h.get("status") != "healthy":
        failures.append(f"health status {h.get('status')!r}")
    print(
        "alembic_head_matches =",
        h.get("alembic_head_matches"),
        "| arrived_populated_unstamped =",
        h.get("arrived_populated_unstamped"),
    )
    tok = login(a.base)
    if not tok:
        failures.append("demo login failed after upgrade")
    else:
        ids = snap["ids"]
        new = snapshot(a.base, tok, ids["project"], ids["boq"], ids["invoice"])
        d = diff(snap["get"], new)
        print(f"data diff before->after upgrade: {len(d)} difference(s)")
        for line in d[:80]:
            print("  ", line)
        if d:
            failures.append(f"{len(d)} field difference(s) in the probe data")
        st, projects = call(a.base, "GET", "/api/v1/projects/?limit=500", token=tok)
        plist = projects if isinstance(projects, list) else projects.get("items", [])
        print(f"projects visible: before={snap['demo_project_count'] + 1} (incl. probe) after={len(plist)}")
        if len(plist) < snap["demo_project_count"] + 1:
            failures.append("fewer projects visible after upgrade")
    if failures:
        print("FAIL:", "; ".join(failures))
        sys.exit(1)
    print("verify OK")


def cmd_frontend(a):
    st, html = call(a.base, "GET", "/")
    if isinstance(html, (dict, list)):
        html = json.dumps(html).encode()
    html = html.decode("utf-8", "replace") if isinstance(html, bytes) else str(html)
    if st != 200 or "<html" not in html.lower():
        print(f"FAIL: / returned {st}: {html[:300]}")
        sys.exit(1)
    refs = re.findall(r'(?:src|href)="([^"]+)"', html)
    local = [r for r in refs if not r.startswith(("http://", "https://", "data:", "//", "#"))]
    bad = []
    for r in local:
        url = "/" + r.lstrip("/") if not r.startswith("/") else r
        req = urllib.request.Request(a.base + url)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                if resp.status != 200 or not body:
                    bad.append((r, resp.status, len(body)))
                elif r.endswith(".js") and body.lstrip()[:15].lower().startswith(b"<!doctype"):
                    bad.append((r, "html-fallback", len(body)))
        except urllib.error.HTTPError as e:
            bad.append((r, e.code, 0))
    print(f"frontend: index.html OK, {len(local)} local asset(s) referenced, {len(bad)} bad")
    for b in bad:
        print("   BAD", b)
    if not local or bad:
        sys.exit(1)


def cmd_logscan(a):
    pat = re.compile(r"\bERROR\b|Traceback|CRITICAL|\berror\b.*Exception")
    with open(a.log, encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    hits = [i for i, line in enumerate(lines) if pat.search(line)]
    print(f"logscan {a.log}: {len(lines)} lines, {len(hits)} ERROR/Traceback/CRITICAL line(s)")
    shown = 0
    for i in hits:
        if shown >= 40:
            break
        print(f"--- line {i + 1}")
        print("".join(lines[max(0, i - 2) : i + 6])[:3000])
        shown += 1
    if hits and not a.report_only:
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wait")
    w.add_argument("--timeout", type=int, default=900)
    w.add_argument("--label", default="")
    w.add_argument("--timing-file", default="")
    s = sub.add_parser("seed")
    s.add_argument("--out", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--snap", required=True)
    v.add_argument("--expect-version", default="")
    sub.add_parser("frontend")
    lg = sub.add_parser("logscan")
    lg.add_argument("log")
    lg.add_argument("--report-only", action="store_true")
    a = ap.parse_args()
    {"wait": cmd_wait, "seed": cmd_seed, "verify": cmd_verify, "frontend": cmd_frontend, "logscan": cmd_logscan}[
        a.cmd
    ](a)


if __name__ == "__main__":
    main()
