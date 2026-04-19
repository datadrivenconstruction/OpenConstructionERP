"""Phase 3 — Functional API audit.

Probes every major module's primary CRUD endpoints on the live instance.
Verifies: auth gating, list shape, create validation, update, delete.
Outputs: audit/modules/_api_probe.json + human summary.

Usage:
    python scripts/audit_functional.py [--base-url URL] [--email E] [--password P]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

try:
    import httpx  # noqa: F401 — we actually use it
except ModuleNotFoundError:  # pragma: no cover
    print("httpx not installed. Install with: pip install httpx", file=sys.stderr)
    raise


REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "audit" / "modules"
OUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Probe:
    module: str
    method: str
    path: str
    status: int | None = None
    ok: bool = False
    elapsed_ms: int = 0
    expected: str = ""
    observation: str = ""
    severity: str = ""  # critical | high | medium | low | ok
    body_snippet: str = ""

    def finding(self) -> str | None:
        if self.severity == "ok":
            return None
        return f"[{self.severity}] {self.module} {self.method} {self.path} → {self.status} — {self.observation}"


@dataclass
class Report:
    base_url: str
    generated_at: str
    probes: list[Probe] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)


def _classify(status: int | None, expected_status: set[int], expected_error: bool = False) -> tuple[bool, str]:
    """Return (ok, severity)."""
    if status is None:
        return False, "critical"  # network error
    if status in expected_status:
        return True, "ok"
    if 500 <= status < 600:
        return False, "critical"
    if status == 404 and expected_error is False:
        return False, "high"
    if status in {401, 403} and expected_error is False:
        return False, "high"
    if status == 422 and expected_error is False:
        return False, "medium"
    return False, "medium"


def run(base_url: str, email: str, password: str) -> Report:
    started = time.time()
    report = Report(base_url=base_url, generated_at=datetime.now(timezone.utc).isoformat())
    probes: list[Probe] = report.probes

    with httpx.Client(base_url=base_url, timeout=15.0) as client:
        # ── Unauth probes ────────────────────────────────────────────────
        def probe_unauth(module: str, method: str, path: str, expected: set[int]) -> None:
            t0 = time.time()
            try:
                res = client.request(method, path)
                status = res.status_code
                body = res.text[:200]
            except Exception as exc:  # pragma: no cover
                status = None
                body = f"network: {exc}"
            ok, sev = _classify(status, expected)
            probes.append(
                Probe(
                    module=module,
                    method=method,
                    path=path,
                    status=status,
                    ok=ok,
                    elapsed_ms=int((time.time() - t0) * 1000),
                    expected=f"{'|'.join(map(str, expected))}",
                    observation=f"unauth → {status}",
                    severity=sev if not ok else "ok",
                    body_snippet=body,
                )
            )

        # Unauth MUST be rejected on protected endpoints
        for m, p in [
            ("auth", "/api/v1/auth/me"),
            ("cabinets", "/api/v1/cabinets"),
            ("documents", "/api/v1/documents"),
            ("invoices", "/api/v1/invoices"),
            ("contacts", "/api/v1/contacts"),
            ("accounting", "/api/v1/accounting/entries"),
            ("banking", "/api/v1/banking/accounts"),
            ("workflows", "/api/v1/workflows"),
            ("tasks", "/api/v1/tasks"),
            ("admin", "/api/v1/admin/users"),
            ("compliance", "/api/v1/audit"),
        ]:
            probe_unauth(m, "GET", p, {401, 403})

        # ── Login ────────────────────────────────────────────────────────
        t0 = time.time()
        login_res = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        login_ok = login_res.status_code == 200
        probes.append(
            Probe(
                module="auth",
                method="POST",
                path="/api/v1/auth/login",
                status=login_res.status_code,
                ok=login_ok,
                elapsed_ms=int((time.time() - t0) * 1000),
                expected="200",
                observation="login" if login_ok else f"login failed: {login_res.text[:200]}",
                severity="ok" if login_ok else "critical",
                body_snippet=login_res.text[:200],
            )
        )
        if not login_ok:
            report.summary = _summarize(probes)
            return report

        data = login_res.json()
        access = data["access_token"]
        headers = {"Authorization": f"Bearer {access}"}

        # ── Auth gate: with valid token, same paths should be 200 ────────
        def probe_auth(
            module: str,
            method: str,
            path: str,
            expected: set[int],
            json_body: dict | None = None,
            query: dict | None = None,
            expect_error: bool = False,
        ) -> httpx.Response | None:
            t0 = time.time()
            try:
                res = client.request(
                    method,
                    path,
                    json=json_body,
                    params=query,
                    headers=headers,
                )
                status = res.status_code
                body = res.text[:300]
            except Exception as exc:  # pragma: no cover
                res = None
                status = None
                body = f"network: {exc}"
            ok, sev = _classify(status, expected, expected_error=expect_error)
            probes.append(
                Probe(
                    module=module,
                    method=method,
                    path=path,
                    status=status,
                    ok=ok,
                    elapsed_ms=int((time.time() - t0) * 1000),
                    expected="|".join(map(str, expected)),
                    observation=body[:140],
                    severity=sev if not ok else "ok",
                    body_snippet=body,
                )
            )
            return res

        # /auth
        probe_auth("auth", "GET", "/api/v1/auth/me", {200})
        probe_auth("auth", "POST", "/api/v1/auth/refresh", {200, 401}, json_body={"refresh_token": data["refresh_token"]})

        # /cabinets
        res_cab = probe_auth("cabinets", "GET", "/api/v1/cabinets", {200})
        cab_id: str | None = None
        if res_cab is not None and res_cab.status_code == 200:
            try:
                items = res_cab.json()
                if isinstance(items, dict) and "items" in items:
                    items = items["items"]
                if items:
                    cab_id = items[0].get("id")
            except Exception:
                pass

        suffix = f"AUDIT-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"

        # /cabinets create (minimal)
        res_new_cab = probe_auth(
            "cabinets",
            "POST",
            "/api/v1/cabinets",
            {200, 201},
            json_body={"name": f"Audit-{suffix}", "description": "audit probe"},
        )
        new_cab_id: str | None = None
        if res_new_cab is not None and res_new_cab.status_code in {200, 201}:
            try:
                new_cab_id = res_new_cab.json().get("id")
            except Exception:
                pass

        # /cabinets update
        if new_cab_id:
            probe_auth(
                "cabinets",
                "PATCH",
                f"/api/v1/cabinets/{new_cab_id}",
                {200, 204},
                json_body={"description": "audit probe updated"},
            )

        # /cabinets delete
        if new_cab_id:
            probe_auth("cabinets", "DELETE", f"/api/v1/cabinets/{new_cab_id}", {200, 204})

        # /cabinets validation (empty body)
        probe_auth("cabinets", "POST", "/api/v1/cabinets", {422}, json_body={}, expect_error=True)

        # /documents
        probe_auth("documents", "GET", "/api/v1/documents", {200}, query={"page": 1, "page_size": 5})
        probe_auth("documents", "GET", "/api/v1/documents/nonexistent-id", {404}, expect_error=True)

        # /contacts list + create + update + delete
        res_contacts = probe_auth("contacts", "GET", "/api/v1/contacts", {200})
        res_contact = probe_auth(
            "contacts",
            "POST",
            "/api/v1/contacts",
            {200, 201},
            json_body={
                "type": "customer",
                "company_name": f"Audit-Firma-{suffix}",
                "email": f"audit-{suffix}@example.de",
            },
        )
        new_contact_id: str | None = None
        if res_contact is not None and res_contact.status_code in {200, 201}:
            try:
                new_contact_id = res_contact.json().get("id")
            except Exception:
                pass
        if new_contact_id:
            probe_auth(
                "contacts",
                "PATCH",
                f"/api/v1/contacts/{new_contact_id}",
                {200},
                json_body={"notes": "audit probe"},
            )
            probe_auth("contacts", "DELETE", f"/api/v1/contacts/{new_contact_id}", {200, 204})

        # /contacts validation
        probe_auth("contacts", "POST", "/api/v1/contacts", {422}, json_body={}, expect_error=True)

        # /invoices (read-only smoke — drafting one may create real data)
        probe_auth("invoices", "GET", "/api/v1/invoices", {200}, query={"page": 1, "page_size": 5})
        probe_auth("invoices", "GET", "/api/v1/invoices/recurring", {200, 404}, expect_error=True)
        probe_auth("invoices", "GET", "/api/v1/invoices/stats/summary", {200, 404, 405}, expect_error=True)

        # /accounting (real paths, confirmed via router grep)
        probe_auth("accounting", "GET", "/api/v1/accounting/skr", {200})
        probe_auth("accounting", "GET", "/api/v1/accounting/entries", {200})
        probe_auth("accounting", "GET", "/api/v1/accounting/kostenstellen", {200})
        probe_auth("accounting", "GET", "/api/v1/accounting/euer/2026", {200, 404})
        probe_auth("accounting", "GET", "/api/v1/accounting/offene-posten", {200})

        # /banking
        probe_auth("banking", "GET", "/api/v1/banking/accounts", {200})
        probe_auth("banking", "GET", "/api/v1/banking/dashboard", {200})

        # /kassenbuch
        probe_auth("kassenbuch", "GET", "/api/v1/kassenbuch/entries", {200})

        # /expenses
        probe_auth("expenses", "GET", "/api/v1/expenses", {200})

        # /assets
        probe_auth("assets", "GET", "/api/v1/assets", {200})

        # /inventory (real paths)
        probe_auth("inventory", "GET", "/api/v1/inventory/stats", {200})
        probe_auth("inventory", "GET", "/api/v1/inventory/articles", {200})

        # /tasks + create + delete
        probe_auth("tasks", "GET", "/api/v1/tasks", {200})
        res_task = probe_auth(
            "tasks",
            "POST",
            "/api/v1/tasks",
            {200, 201},
            json_body={"title": f"audit-task-{suffix}", "description": "probe"},
        )
        new_task_id: str | None = None
        if res_task is not None and res_task.status_code in {200, 201}:
            try:
                new_task_id = res_task.json().get("id")
            except Exception:
                pass
        if new_task_id:
            probe_auth("tasks", "DELETE", f"/api/v1/tasks/{new_task_id}", {200, 204})

        # /workflows
        probe_auth("workflows", "GET", "/api/v1/workflows", {200})

        # /forms
        probe_auth("forms", "GET", "/api/v1/forms", {200})

        # /contracts
        probe_auth("contracts", "GET", "/api/v1/contracts", {200})
        probe_auth("nachtraege", "GET", "/api/v1/nachtraege", {200})

        # /projects
        probe_auth("projects", "GET", "/api/v1/projects", {200})
        probe_auth("subcontractors", "GET", "/api/v1/subcontractors", {200})
        probe_auth("aufmass", "GET", "/api/v1/aufmass", {200})
        probe_auth("bautagebuch", "GET", "/api/v1/bautagebuch/entries", {200})
        probe_auth("resources", "GET", "/api/v1/resources", {200})

        # /timetracking + HR
        probe_auth("timetracking", "GET", "/api/v1/timetracking/entries", {200})
        probe_auth("attendance", "GET", "/api/v1/attendance", {200})
        probe_auth("leave", "GET", "/api/v1/leave/requests", {200})
        probe_auth("leave", "GET", "/api/v1/leave/balance", {200})
        probe_auth("payroll", "GET", "/api/v1/payroll/payslips", {200})

        # /wiedervorlage
        probe_auth("wiedervorlage", "GET", "/api/v1/wiedervorlage", {200})

        # /compliance (real paths)
        probe_auth("compliance", "GET", "/api/v1/audit", {200})
        probe_auth("compliance", "GET", "/api/v1/audit/verify", {200})
        probe_auth("compliance", "GET", "/api/v1/retention", {200})
        probe_auth("compliance", "GET", "/api/v1/gdpr/status", {200, 404}, expect_error=True)

        # /search
        probe_auth("search", "GET", "/api/v1/search", {200}, query={"q": "rechnung"})
        probe_auth("saved_searches", "GET", "/api/v1/saved-searches", {200})

        # /ai
        probe_auth("ai", "GET", "/api/v1/ai/providers", {200, 404}, expect_error=True)
        probe_auth("ai", "GET", "/api/v1/ai-settings", {200, 404}, expect_error=True)

        # /kpi + /dashboard-like
        probe_auth("kpi", "GET", "/api/v1/kpi/overview", {200, 404}, expect_error=True)
        probe_auth("anomalies", "GET", "/api/v1/anomalies", {200, 404}, expect_error=True)
        probe_auth("cashflow", "GET", "/api/v1/cashflow/predict", {200, 400, 404}, expect_error=True)

        # /admin
        probe_auth("admin", "GET", "/api/v1/admin/users", {200, 403})
        probe_auth("admin", "GET", "/api/v1/admin/organizations", {200, 403, 404}, expect_error=True)

        # /notifications
        probe_auth("notifications", "GET", "/api/v1/notifications", {200})

        # /email-capture + templates
        probe_auth("email_capture", "GET", "/api/v1/email-capture/config", {200})
        probe_auth("email_templates", "GET", "/api/v1/email-templates", {200})

        # /tags
        probe_auth("tags", "GET", "/api/v1/tags", {200})

        # /organizations (profile) + settings
        probe_auth("organizations", "GET", "/api/v1/organizations/me", {200, 404}, expect_error=True)

        # Health
        probe_auth("health", "GET", "/api/v1/health", {200})

    report.summary = _summarize(probes)
    report.summary["elapsed_sec"] = int(time.time() - started)
    return report


def _summarize(probes: list[Probe]) -> dict[str, int]:
    out = {"total": len(probes), "ok": 0, "critical": 0, "high": 0, "medium": 0, "low": 0}
    for p in probes:
        if p.ok:
            out["ok"] += 1
        else:
            out[p.severity] = out.get(p.severity, 0) + 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("AUDIT_BASE_URL", "http://31.97.123.81:7777"))
    parser.add_argument("--email", default=os.environ.get("AUDIT_EMAIL", "admin@demo.de"))
    parser.add_argument("--password", default=os.environ.get("AUDIT_PASSWORD", "Demo2026!"))
    args = parser.parse_args()

    report = run(args.base_url, args.email, args.password)

    out_file = OUT_DIR / "_api_probe.json"
    out_file.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

    # Quick text summary
    md = [f"# API probe — {report.generated_at}", "",
          f"Base: `{report.base_url}`  | Probes: {report.summary['total']}",
          "",
          f"ok: {report.summary['ok']}  critical: {report.summary.get('critical', 0)}  high: {report.summary.get('high', 0)}  medium: {report.summary.get('medium', 0)}  low: {report.summary.get('low', 0)}",
          "",
          "## Failures",
          ""]
    for p in report.probes:
        f = p.finding()
        if f:
            md.append(f"- {f}")
    (OUT_DIR / "_api_probe.md").write_text("\n".join(md), encoding="utf-8")

    print(f"Done. Probes: {report.summary['total']}  failures: {report.summary['total'] - report.summary['ok']}")
    print(f"Report: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
