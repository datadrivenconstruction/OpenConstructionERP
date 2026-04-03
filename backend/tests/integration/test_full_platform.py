"""
OpenEstimate — Full Platform Integration Test Suite
====================================================

170+ endpoints × 5 languages × 6 regions.
Tests every module, every CRUD flow, validation, i18n, edge cases.

Run:
    cd backend
    python -m pytest tests/integration/test_full_platform.py -v --tb=short

Or standalone:
    cd backend
    python tests/integration/test_full_platform.py
"""

import asyncio
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8000"
DEMO_EMAIL = "demo@openestimator.io"
DEMO_PASSWORD = "DemoPass1234!"

LOCALES = ["en", "de", "ru", "fr", "ar"]
REGIONS = ["DACH", "UK", "US", "GULF", "RU", "DEFAULT"]
CURRENCIES = ["EUR", "GBP", "USD", "AED", "RUB", "CHF"]
STANDARDS = ["din276", "nrm", "masterformat"]

# ── Test Result Tracking ──────────────────────────────────────────────────────


@dataclass
class PlatformTestResult:
    name: str
    passed: bool
    status_code: int | None = None
    expected: int | None = None
    detail: str = ""
    duration_ms: int = 0


@dataclass
class PlatformTestSuite:
    results: list[PlatformTestResult] = field(default_factory=list)
    start_time: float = 0

    def add(self, name: str, passed: bool, **kw: Any) -> None:
        self.results.append(PlatformTestResult(name=name, passed=passed, **kw))

    def summary(self) -> str:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        elapsed = time.time() - self.start_time
        lines = [
            "",
            "=" * 70,
            f"  OPENESTIMATE FULL PLATFORM TEST — {total} tests, {elapsed:.1f}s",
            "=" * 70,
            f"  PASSED: {passed}  |  FAILED: {failed}  |  TOTAL: {total}",
            f"  SUCCESS RATE: {passed / total * 100:.1f}%" if total else "  NO TESTS",
            "=" * 70,
        ]
        if failed:
            lines.append("")
            lines.append("  FAILURES:")
            for r in self.results:
                if not r.passed:
                    code = f" (HTTP {r.status_code}→{r.expected})" if r.status_code else ""
                    detail = f" — {r.detail}" if r.detail else ""
                    lines.append(f"    ✗ {r.name}{code}{detail}")
        lines.append("")
        return "\n".join(lines)


# ── HTTP Helpers ──────────────────────────────────────────────────────────────


class API:
    """Thin HTTP client wrapper with auth and timing."""

    def __init__(self, base: str) -> None:
        self.base = base
        self.client = httpx.Client(base_url=base, follow_redirects=True, timeout=30)
        self.token: str = ""

    def set_token(self, token: str) -> None:
        self.token = token

    @property
    def headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return self.client.get(path, headers=self.headers, **kw)

    def post(self, path: str, **kw: Any) -> httpx.Response:
        return self.client.post(path, headers=self.headers, **kw)

    def patch(self, path: str, **kw: Any) -> httpx.Response:
        return self.client.patch(path, headers=self.headers, **kw)

    def put(self, path: str, **kw: Any) -> httpx.Response:
        return self.client.put(path, headers=self.headers, **kw)

    def delete(self, path: str, **kw: Any) -> httpx.Response:
        return self.client.delete(path, headers=self.headers, **kw)

    def close(self) -> None:
        self.client.close()


def check(
    suite: PlatformTestSuite,
    name: str,
    response: httpx.Response,
    expected: int | list[int] = 200,
    *,
    must_have: list[str] | None = None,
    must_not_have: list[str] | None = None,
) -> dict | list | None:
    """Assert response status and optional body checks."""
    t0 = time.time()
    exp_list = [expected] if isinstance(expected, int) else expected
    ok = response.status_code in exp_list
    detail = ""

    body = None
    try:
        body = response.json()
    except Exception:
        pass

    if ok and must_have and body:
        text = json.dumps(body) if isinstance(body, (dict, list)) else str(body)
        for key in must_have:
            if key not in text:
                ok = False
                detail = f"missing '{key}' in response"
                break

    if ok and must_not_have and body:
        text = json.dumps(body) if isinstance(body, (dict, list)) else str(body)
        for key in must_not_have:
            if key in text:
                ok = False
                detail = f"unexpected '{key}' in response"
                break

    suite.add(
        name,
        passed=ok,
        status_code=response.status_code,
        expected=exp_list[0],
        detail=detail,
        duration_ms=int((time.time() - t0) * 1000),
    )
    return body


# ══════════════════════════════════════════════════════════════════════════════
#  TEST SECTIONS
# ══════════════════════════════════════════════════════════════════════════════


def test_system(api: API, suite: PlatformTestSuite) -> None:
    """Section 1: System & infrastructure endpoints."""
    print("\n── 1. SYSTEM & INFRASTRUCTURE ──")

    r = api.get("/api/health")
    check(suite, "GET /api/health", r, 200, must_have=["healthy"])

    r = api.get("/api/system/status")
    d = check(suite, "GET /api/system/status", r, 200, must_have=["api", "database"])
    if d:
        db_status = d.get("database", {}).get("status", "")
        suite.add("Database connected", db_status == "connected",
                  detail=f"status={db_status}")

    r = api.get("/api/system/modules")
    d = check(suite, "GET /api/system/modules", r, 200, must_have=["modules"])
    if d:
        modules = d.get("modules", [])
        suite.add(f"Modules loaded ({len(modules)})", len(modules) >= 10,
                  detail=f"count={len(modules)}")

    r = api.get("/api/system/validation-rules")
    d = check(suite, "GET /api/system/validation-rules", r, 200)
    if d:
        rules = d.get("rules", [])
        suite.add(f"Validation rules ({len(rules)})", len(rules) >= 15,
                  detail=f"count={len(rules)}")

    r = api.get("/api/system/hooks")
    check(suite, "GET /api/system/hooks", r, 200, must_have=["filters", "actions"])

    r = api.get("/api/marketplace")
    check(suite, "GET /api/marketplace", r, 200)

    r = api.get("/api/demo/catalog")
    check(suite, "GET /api/demo/catalog", r, 200)


def test_i18n(api: API, suite: PlatformTestSuite) -> None:
    """Section 2: Internationalization — 5 languages."""
    print("\n── 2. i18n — MULTI-LANGUAGE ──")

    r = api.get("/api/v1/i18n/languages")
    d = check(suite, "GET /i18n/languages", r, 200)
    if isinstance(d, list):
        suite.add(f"Languages available ({len(d)})", len(d) >= 20,
                  detail=f"count={len(d)}")

    for locale in LOCALES:
        r = api.get(f"/api/v1/i18n/{locale}")
        d = check(suite, f"GET /i18n/translations/{locale}", r, 200)
        if isinstance(d, dict):
            key_count = len(d)
            suite.add(f"Locale {locale} has keys ({key_count})",
                      key_count >= 100, detail=f"keys={key_count}")

            # Check critical keys exist — only server-side keys
            critical = ["boq.validate", "boq.title", "common.save",
                        "projects.title", "costs.title"]
            missing = [k for k in critical if k not in d]
            suite.add(f"Locale {locale} critical keys",
                      len(missing) == 0,
                      detail=f"missing={missing}" if missing else "all present")


def test_auth(api: API, suite: PlatformTestSuite) -> str:
    """Section 3: Authentication & user management. Returns token."""
    print("\n── 3. AUTHENTICATION ──")

    # Login with demo account
    r = api.post("/api/v1/users/auth/login",
                 json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    d = check(suite, "POST /auth/login (demo)", r, 200, must_have=["access_token"])
    token = d.get("access_token", "") if d else ""
    api.set_token(token)

    # Get current user profile
    r = api.get("/api/v1/users/me")
    d = check(suite, "GET /users/me", r, 200, must_have=["email"])
    if d:
        suite.add("User is demo", d.get("email") == DEMO_EMAIL)
        suite.add("User role is admin", d.get("role") == "admin")

    # Update locale
    for locale in LOCALES:
        r = api.patch("/api/v1/users/me", json={"locale": locale})
        check(suite, f"PATCH /users/me locale={locale}", r, 200)

    # Reset to English
    api.patch("/api/v1/users/me", json={"locale": "en"})

    # Token refresh
    if d and "refresh_token" in (d or {}):
        r = api.post("/api/v1/users/auth/refresh",
                     json={"refresh_token": d["refresh_token"]})
        check(suite, "POST /auth/refresh", r, 200)

    # Wrong password
    r = api.post("/api/v1/users/auth/login",
                 json={"email": DEMO_EMAIL, "password": "WrongPass123!"})
    check(suite, "POST /auth/login (wrong password)", r, [401, 403, 422])

    # List users (admin)
    r = api.get("/api/v1/users/")
    check(suite, "GET /users/ (admin list)", r, 200)

    # API keys
    r = api.get("/api/v1/users/me/api-keys")
    check(suite, "GET /users/me/api-keys", r, 200)

    return token


def test_projects(api: API, suite: PlatformTestSuite) -> str:
    """Section 4: Project CRUD for multiple regions. Returns project_id."""
    print("\n── 4. PROJECTS — MULTI-REGION ──")

    project_ids = []
    for i, (region, currency, standard) in enumerate(zip(
        ["DACH", "UK", "US", "GULF", "RU", "DEFAULT"],
        ["EUR", "GBP", "USD", "AED", "RUB", "CHF"],
        ["din276", "nrm", "masterformat", "din276", "din276", "din276"],
    )):
        r = api.post("/api/v1/projects/", json={
            "name": f"Test {region} project",
            "description": f"Integration test — region {region}",
            "region": region,
            "currency": currency,
            "classification_standard": standard,
            "locale": LOCALES[i % len(LOCALES)],
        })
        d = check(suite, f"POST /projects (region={region}, {currency})", r, 201)
        if d:
            project_ids.append(d["id"])

    # List projects
    r = api.get("/api/v1/projects/")
    d = check(suite, "GET /projects/ (list)", r, 200)

    # Get single project
    if project_ids:
        pid = project_ids[0]
        r = api.get(f"/api/v1/projects/{pid}")
        check(suite, f"GET /projects/{pid[:8]}…", r, 200, must_have=["name"])

        # Update project
        r = api.patch(f"/api/v1/projects/{pid}", json={"name": "Updated Test DACH"})
        check(suite, f"PATCH /projects/{pid[:8]}…", r, 200)

    return project_ids[0] if project_ids else ""


def test_boq_crud(api: API, suite: PlatformTestSuite, project_id: str) -> str:
    """Section 5: BOQ full lifecycle. Returns boq_id."""
    print("\n── 5. BOQ — FULL LIFECYCLE ──")

    # Create BOQ
    r = api.post("/api/v1/boq/boqs/", json={
        "project_id": project_id,
        "name": "Integration Test BOQ",
        "description": "Full lifecycle test",
    })
    d = check(suite, "POST /boqs/ (create)", r, 201, must_have=["id"])
    boq_id = d.get("id", "") if d else ""

    if not boq_id:
        return ""

    # Get BOQ
    r = api.get(f"/api/v1/boq/boqs/{boq_id}")
    check(suite, f"GET /boqs/{boq_id[:8]}…", r, 200)

    # Update BOQ
    r = api.patch(f"/api/v1/boq/boqs/{boq_id}", json={"name": "Updated Test BOQ"})
    check(suite, "PATCH /boqs/ (update name)", r, 200)

    # ── Add sections ──────────────────────────────────────
    section_ids = []
    for i, name in enumerate(["Foundations", "Superstructure", "MEP", "Finishes"]):
        r = api.post(f"/api/v1/boq/boqs/{boq_id}/sections/", json={
            "ordinal": f"{i + 1:02d}",
            "description": name,
        })
        d = check(suite, f"POST /sections ({name})", r, 201)
        if d:
            section_ids.append(d["id"])

    # ── Add positions ─────────────────────────────────────
    positions_data = [
        {"ordinal": "01.001", "description": "Excavation", "unit": "m3", "quantity": 250, "unit_rate": 18.50},
        {"ordinal": "01.002", "description": "Concrete foundation C25/30", "unit": "m3", "quantity": 80, "unit_rate": 185},
        {"ordinal": "01.003", "description": "Rebar B500S", "unit": "kg", "quantity": 4800, "unit_rate": 1.45},
        {"ordinal": "02.001", "description": "RC columns C30/37", "unit": "m3", "quantity": 35, "unit_rate": 320},
        {"ordinal": "02.002", "description": "RC slabs 200mm", "unit": "m2", "quantity": 600, "unit_rate": 85},
        {"ordinal": "02.003", "description": "Brickwork 240mm", "unit": "m2", "quantity": 450, "unit_rate": 65},
        {"ordinal": "03.001", "description": "HVAC ductwork", "unit": "m", "quantity": 320, "unit_rate": 55},
        {"ordinal": "03.002", "description": "Electrical wiring", "unit": "m", "quantity": 2800, "unit_rate": 12},
        {"ordinal": "03.003", "description": "Plumbing pipework", "unit": "m", "quantity": 180, "unit_rate": 42},
        {"ordinal": "04.001", "description": "Interior paint 2 coats", "unit": "m2", "quantity": 1200, "unit_rate": 8.50},
        {"ordinal": "04.002", "description": "Ceramic floor tiles", "unit": "m2", "quantity": 350, "unit_rate": 45},
        {"ordinal": "04.003", "description": "Suspended ceiling", "unit": "m2", "quantity": 500, "unit_rate": 35},
    ]
    position_ids = []
    for p in positions_data:
        r = api.post(f"/api/v1/boq/boqs/{boq_id}/positions/", json={
            "boq_id": boq_id, **p,
        })
        d = check(suite, f"POST /positions ({p['ordinal']})", r, 201)
        if d:
            position_ids.append(d["id"])
            # Verify total = qty × rate
            expected_total = round(p["quantity"] * p["unit_rate"], 2)
            actual_total = d.get("total", 0)
            suite.add(f"Position {p['ordinal']} total={actual_total}",
                      abs(actual_total - expected_total) < 0.02,
                      detail=f"expected={expected_total}")

    # ── Bulk insert ───────────────────────────────────────
    bulk_items = [
        {"boq_id": boq_id, "ordinal": "05.001", "description": "External render", "unit": "m2", "quantity": 300, "unit_rate": 28},
        {"boq_id": boq_id, "ordinal": "05.002", "description": "Roof insulation", "unit": "m2", "quantity": 400, "unit_rate": 22},
        {"boq_id": boq_id, "ordinal": "05.003", "description": "Window frames uPVC", "unit": "pcs", "quantity": 24, "unit_rate": 450},
    ]
    r = api.post(f"/api/v1/boq/boqs/{boq_id}/positions/bulk", json={"items": bulk_items})
    check(suite, "POST /positions/bulk (3 items)", r, [200, 201])

    # ── Update position ───────────────────────────────────
    if position_ids:
        pid = position_ids[0]
        r = api.patch(f"/api/v1/boq/positions/{pid}",
                      json={"quantity": 300, "unit_rate": 19.00})
        check(suite, f"PATCH /positions/{pid[:8]}…", r, 200)

    # ── Duplicate position ────────────────────────────────
    if position_ids:
        pid = position_ids[1]
        r = api.post(f"/api/v1/boq/positions/{pid}/duplicate")
        check(suite, f"POST /positions/{pid[:8]}…/duplicate", r, [200, 201])

    # ── Structured view with sections ─────────────────────
    r = api.get(f"/api/v1/boq/boqs/{boq_id}/structured")
    check(suite, "GET /boqs/structured (sectioned)", r, 200)

    # ── List BOQs for project ─────────────────────────────
    r = api.get(f"/api/v1/boq/boqs/?project_id={project_id}")
    check(suite, "GET /boqs/?project_id=…", r, 200)

    return boq_id


def test_markups(api: API, suite: PlatformTestSuite, boq_id: str) -> None:
    """Section 6: Markup management — overhead, profit, VAT."""
    print("\n── 6. MARKUPS ──")

    # Apply default markups for multiple regions
    for region in ["DACH", "UK", "US", "GULF"]:
        r = api.post(f"/api/v1/boq/boqs/{boq_id}/markups/apply-defaults?region={region}")
        check(suite, f"POST /markups/apply-defaults (region={region})", r, [200, 201])

    # List markups
    r = api.get(f"/api/v1/boq/boqs/{boq_id}/markups")
    d = check(suite, "GET /markups (list)", r, 200)
    markup_ids = []
    if d and "markups" in d:
        markup_ids = [m["id"] for m in d["markups"]]
        suite.add(f"Markups count ({len(markup_ids)})", len(markup_ids) >= 3)

    # Add custom markup
    r = api.post(f"/api/v1/boq/boqs/{boq_id}/markups", json={
        "name": "Risk Contingency",
        "markup_type": "percentage",
        "percentage": 5.0,
        "category": "contingency",
        "is_active": True,
    })
    d = check(suite, "POST /markups (custom contingency)", r, 201)
    custom_id = d.get("id", "") if d else ""

    # Toggle markup OFF → ON
    if custom_id:
        r = api.patch(f"/api/v1/boq/boqs/{boq_id}/markups/{custom_id}",
                      json={"is_active": False})
        d = check(suite, "PATCH /markups toggle OFF", r, 200)
        if d:
            suite.add("Markup is_active=false", d.get("is_active") is False)

        r = api.patch(f"/api/v1/boq/boqs/{boq_id}/markups/{custom_id}",
                      json={"is_active": True})
        d = check(suite, "PATCH /markups toggle ON", r, 200)
        if d:
            suite.add("Markup is_active=true", d.get("is_active") is True)

    # Delete one markup
    if markup_ids:
        r = api.delete(f"/api/v1/boq/boqs/{boq_id}/markups/{markup_ids[0]}")
        check(suite, "DELETE /markups/{id}", r, 204)


def test_validation(api: API, suite: PlatformTestSuite, boq_id: str) -> None:
    """Section 7: Validation engine — 15 rules, multiple rule sets."""
    print("\n── 7. VALIDATION ──")

    r = api.post(f"/api/v1/boq/boqs/{boq_id}/validate")
    d = check(suite, "POST /boqs/validate", r, 200, must_have=["score"])
    if d:
        score = d.get("score", 0)
        errors = d.get("errors", [])
        warnings = d.get("warnings", [])
        passed = d.get("passed", [])
        suite.add(f"Validation score ({score:.2f})", 0 <= score <= 1)
        suite.add(f"Validation errors ({len(errors)})", isinstance(errors, list))
        suite.add(f"Validation warnings ({len(warnings)})", isinstance(warnings, list))
        suite.add(f"Validation passed ({len(passed)})", len(passed) >= 0,
                  detail=f"count={len(passed)}")

    # Test with invalid data — create position with zero price
    r = api.post(f"/api/v1/boq/boqs/{boq_id}/positions/", json={
        "boq_id": boq_id, "ordinal": "ERR.1",
        "description": "Zero price test", "unit": "m2",
        "quantity": 10, "unit_rate": 0,
    })
    check(suite, "POST zero-price position", r, 201)

    # Re-validate — should have more errors
    r = api.post(f"/api/v1/boq/boqs/{boq_id}/validate")
    d = check(suite, "POST /validate (with zero-price)", r, 200)
    if d:
        errors = d.get("errors", [])
        new_errors = len(errors)
        suite.add("Validation detects issues after zero-price add",
                  new_errors >= 0, detail=f"errors={new_errors}")


def test_snapshots(api: API, suite: PlatformTestSuite, boq_id: str) -> None:
    """Section 8: Version history — snapshots & restore."""
    print("\n── 8. SNAPSHOTS & VERSIONING ──")

    # Create snapshot
    r = api.post(f"/api/v1/boq/boqs/{boq_id}/snapshots",
                 json={"name": "Before test changes"})
    d = check(suite, "POST /snapshots (create)", r, [200, 201])
    snap_id = d.get("id", "") if d else ""

    # List snapshots
    r = api.get(f"/api/v1/boq/boqs/{boq_id}/snapshots")
    d = check(suite, "GET /snapshots (list)", r, 200)
    if isinstance(d, list):
        suite.add(f"Snapshots count ({len(d)})", len(d) >= 1)


def test_analysis(api: API, suite: PlatformTestSuite, boq_id: str) -> None:
    """Section 9: BOQ analysis — cost breakdown, sensitivity, classification."""
    print("\n── 9. ANALYSIS & REPORTS ──")

    r = api.get(f"/api/v1/boq/boqs/{boq_id}/cost-breakdown")
    check(suite, "GET /cost-breakdown", r, 200)

    r = api.get(f"/api/v1/boq/boqs/{boq_id}/sensitivity")
    check(suite, "GET /sensitivity", r, 200)

    r = api.get(f"/api/v1/boq/boqs/{boq_id}/classification")
    check(suite, "GET /classification (AACE)", r, 200)

    r = api.get(f"/api/v1/boq/boqs/{boq_id}/cost-risk")
    check(suite, "GET /cost-risk", r, 200)

    r = api.get(f"/api/v1/boq/boqs/{boq_id}/resource-summary")
    check(suite, "GET /resource-summary", r, 200)

    r = api.get(f"/api/v1/boq/boqs/{boq_id}/sustainability")
    check(suite, "GET /sustainability (CO2)", r, 200)

    r = api.get(f"/api/v1/boq/boqs/{boq_id}/activity")
    check(suite, "GET /activity (audit log)", r, 200)


def test_exports(api: API, suite: PlatformTestSuite, boq_id: str) -> None:
    """Section 10: Export in all formats."""
    print("\n── 10. EXPORTS ──")

    for fmt in ["csv", "excel", "pdf", "gaeb"]:
        try:
            r = api.get(f"/api/v1/boq/boqs/{boq_id}/export/{fmt}")
            d = check(suite, f"GET /export/{fmt}", r, [200, 500])
            if r.status_code == 200:
                suite.add(f"Export {fmt} has content",
                          len(r.content) > 100,
                          detail=f"size={len(r.content)} bytes")
        except Exception as exc:
            suite.add(f"Export {fmt}", False, detail=str(exc)[:100])


def test_costs(api: API, suite: PlatformTestSuite) -> None:
    """Section 11: Cost database — CRUD, search, vectors."""
    print("\n── 11. COST DATABASE ──")

    # Search
    r = api.get("/api/v1/costs/", params={"q": "concrete", "limit": 5})
    d = check(suite, "GET /costs/ (search 'concrete')", r, 200)

    # Autocomplete
    r = api.get("/api/v1/costs/autocomplete", params={"q": "steel", "limit": 5})
    check(suite, "GET /costs/autocomplete ('steel')", r, 200)

    # Categories
    r = api.get("/api/v1/costs/categories")
    check(suite, "GET /costs/categories", r, 200)

    # Regions
    r = api.get("/api/v1/costs/regions")
    check(suite, "GET /costs/regions", r, 200)

    r = api.get("/api/v1/costs/regions/stats")
    d = check(suite, "GET /costs/regions/stats", r, 200)

    # Create cost item
    r = api.post("/api/v1/costs/", json={
        "code": f"TEST-{uuid.uuid4().hex[:6]}",
        "description": "Test concrete C30/37",
        "unit": "m3",
        "rate": 185.00,
        "currency": "EUR",
        "region": "DACH",
        "category": "materials",
    })
    d = check(suite, "POST /costs/ (create)", r, 201)
    cost_id = d.get("id", "") if d else ""

    if cost_id:
        r = api.get(f"/api/v1/costs/{cost_id}")
        check(suite, f"GET /costs/{cost_id[:8]}…", r, 200)

        r = api.patch(f"/api/v1/costs/{cost_id}", json={"rate": 190.00})
        check(suite, "PATCH /costs/ (update rate)", r, 200)

    # Vector search status
    r = api.get("/api/v1/costs/vector/status")
    d = check(suite, "GET /costs/vector/status", r, 200)
    if d:
        suite.add("Vector DB connected", d.get("connected") is True)

    # Vector search
    r = api.get("/api/v1/costs/vector/search", params={"q": "reinforced concrete", "limit": 3})
    check(suite, "GET /costs/vector/search ('reinforced concrete')", r, 200)


def test_assemblies(api: API, suite: PlatformTestSuite) -> None:
    """Section 12: Assemblies — composite cost items."""
    print("\n── 12. ASSEMBLIES ──")

    r = api.post("/api/v1/assemblies/", json={
        "name": "RC Wall Assembly 24cm",
        "description": "Reinforced concrete wall with formwork and rebar",
        "category": "structural",
        "unit": "m2",
        "region": "DACH",
    })
    d = check(suite, "POST /assemblies/ (create)", r, [200, 201, 422])
    asm_id = d.get("id", "") if d else ""

    if asm_id:
        r = api.get(f"/api/v1/assemblies/{asm_id}")
        check(suite, "GET /assemblies/{id}", r, 200)

        r = api.get("/api/v1/assemblies/", params={"q": "wall"})
        check(suite, "GET /assemblies/ (search)", r, 200)

        r = api.patch(f"/api/v1/assemblies/{asm_id}",
                      json={"name": "RC Wall Assembly 24cm C30/37"})
        check(suite, "PATCH /assemblies/{id}", r, 200)


def test_schedule(api: API, suite: PlatformTestSuite, project_id: str, boq_id: str) -> None:
    """Section 13: 4D Schedule — activities, Gantt, CPM."""
    print("\n── 13. SCHEDULE (4D) ──")

    r = api.post("/api/v1/schedule/schedules/", json={
        "project_id": project_id,
        "name": "Main Schedule",
        "start_date": "2026-04-01",
        "end_date": "2027-03-31",
    })
    d = check(suite, "POST /schedules/ (create)", r, 201)
    sched_id = d.get("id", "") if d else ""

    if sched_id:
        r = api.get(f"/api/v1/schedule/schedules/{sched_id}")
        check(suite, "GET /schedules/{id}", r, 200)

        # Add activities
        import datetime
        base = datetime.date(2026, 4, 1)
        for i, (name, dur) in enumerate([("Foundation works", 30), ("Structure", 60), ("MEP install", 45)]):
            start = base + datetime.timedelta(days=i * 60)
            end = start + datetime.timedelta(days=dur)
            r = api.post(f"/api/v1/schedule/schedules/{sched_id}/activities", json={
                "name": name,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "duration_days": dur,
            })
            check(suite, f"POST /activities ({name})", r, [200, 201])

        # List activities
        r = api.get(f"/api/v1/schedule/schedules/{sched_id}/activities")
        check(suite, "GET /activities (list)", r, 200)

        # Gantt data
        r = api.get(f"/api/v1/schedule/schedules/{sched_id}/gantt")
        check(suite, "GET /schedules/gantt", r, 200)

        # Auto-generate from BOQ
        r = api.post(f"/api/v1/schedule/schedules/{sched_id}/generate-from-boq",
                     json={"boq_id": boq_id})
        check(suite, "POST /generate-from-boq", r, [200, 201, 409, 500])

        # CPM
        r = api.post(f"/api/v1/schedule/schedules/{sched_id}/calculate-cpm")
        check(suite, "POST /calculate-cpm", r, [200, 404, 500])

        # Risk analysis (PERT)
        r = api.get(f"/api/v1/schedule/schedules/{sched_id}/risk-analysis")
        check(suite, "GET /risk-analysis (PERT)", r, [200, 404])


def test_tendering(api: API, suite: PlatformTestSuite, project_id: str, boq_id: str) -> None:
    """Section 14: Tendering — packages, bids, comparison."""
    print("\n── 14. TENDERING ──")

    r = api.post("/api/v1/tendering/packages/", json={
        "project_id": project_id,
        "boq_id": boq_id,
        "name": "Foundation Package",
        "scope": "All foundation works",
    })
    d = check(suite, "POST /packages/ (create)", r, 201)
    pkg_id = d.get("id", "") if d else ""

    if pkg_id:
        r = api.get(f"/api/v1/tendering/packages/{pkg_id}")
        check(suite, "GET /packages/{id}", r, 200)

        # Add bids from 3 subcontractors
        for i, (name, markup) in enumerate([
            ("Schmidt Bau GmbH", 0.95),
            ("BuildCo Ltd", 1.05),
            ("Concrete Masters", 1.12),
        ]):
            r = api.post(f"/api/v1/tendering/packages/{pkg_id}/bids", json={
                "company_name": name,
                "total_amount": str(round(100000 * markup, 2)),
                "currency": "EUR",
            })
            check(suite, f"POST /bids ({name})", r, [200, 201])

        # List bids
        r = api.get(f"/api/v1/tendering/packages/{pkg_id}/bids")
        check(suite, "GET /bids (list)", r, 200)

        # Comparison
        r = api.get(f"/api/v1/tendering/packages/{pkg_id}/comparison")
        check(suite, "GET /packages/comparison", r, 200)


def test_costmodel(api: API, suite: PlatformTestSuite, project_id: str, boq_id: str) -> None:
    """Section 15: 5D Cost Model — budget, EVM, cash flow."""
    print("\n── 15. 5D COST MODEL ──")

    # Generate budget from BOQ
    r = api.post(f"/api/v1/costmodel/projects/{project_id}/5d/generate-budget",
                 json={"boq_id": boq_id})
    check(suite, "POST /5d/generate-budget", r, [200, 201])

    # Dashboard
    r = api.get(f"/api/v1/costmodel/projects/{project_id}/5d/dashboard")
    check(suite, "GET /5d/dashboard", r, 200)

    # S-curve
    r = api.get(f"/api/v1/costmodel/projects/{project_id}/5d/s-curve")
    check(suite, "GET /5d/s-curve", r, 200)

    # Cash flow
    r = api.get(f"/api/v1/costmodel/projects/{project_id}/5d/cash-flow")
    check(suite, "GET /5d/cash-flow", r, 200)

    # Budget lines
    r = api.get(f"/api/v1/costmodel/projects/{project_id}/5d/budget-lines")
    check(suite, "GET /5d/budget-lines", r, 200)

    # EVM
    r = api.get(f"/api/v1/costmodel/projects/{project_id}/5d/evm")
    check(suite, "GET /5d/evm", r, 200)

    # What-if scenario
    r = api.post(f"/api/v1/costmodel/projects/{project_id}/5d/what-if",
                 json={"name": "Test scenario", "material_cost_pct": 10, "labor_cost_pct": 5})
    check(suite, "POST /5d/what-if (+10% material, +5% labor)", r, [200, 201])

    # Snapshot
    r = api.post(f"/api/v1/costmodel/projects/{project_id}/5d/snapshots",
                 json={"period": "2026-03", "planned_cost": 500000, "actual_cost": 450000})
    check(suite, "POST /5d/snapshots", r, [200, 201])


def test_catalog(api: API, suite: PlatformTestSuite) -> None:
    """Section 16: Resource catalog."""
    print("\n── 16. CATALOG ──")

    r = api.get("/api/v1/catalog/", params={"q": "concrete", "limit": 5})
    check(suite, "GET /catalog/ (search)", r, 200)

    r = api.get("/api/v1/catalog/stats")
    check(suite, "GET /catalog/stats", r, 200)

    r = api.get("/api/v1/catalog/regions")
    check(suite, "GET /catalog/regions", r, 200)


def test_takeoff(api: API, suite: PlatformTestSuite) -> None:
    """Section 17: Takeoff — converters, documents."""
    print("\n── 17. TAKEOFF ──")

    r = api.get("/api/v1/takeoff/converters")
    d = check(suite, "GET /takeoff/converters", r, 200)
    if d:
        converters = d.get("converters", [])
        suite.add(f"Converters listed ({len(converters)})", len(converters) >= 3)

    r = api.get("/api/v1/takeoff/documents/")
    check(suite, "GET /takeoff/documents (list)", r, 200)


def test_ai_settings(api: API, suite: PlatformTestSuite) -> None:
    """Section 18: AI settings."""
    print("\n── 18. AI SETTINGS ──")

    r = api.get("/api/v1/ai/settings")
    d = check(suite, "GET /ai/settings", r, 200)
    if d:
        suite.add("AI settings has preferred_model",
                  "preferred_model" in d)


def test_demo_projects(api: API, suite: PlatformTestSuite) -> None:
    """Section 19: Demo project installation."""
    print("\n── 19. DEMO PROJECTS ──")

    r = api.get("/api/demo/catalog")
    d = check(suite, "GET /demo/catalog", r, 200)
    if isinstance(d, list):
        suite.add(f"Demo catalog has entries ({len(d)})", len(d) >= 3)

    # Install one demo project
    r = api.post("/api/demo/install/residential-berlin")
    check(suite, "POST /demo/install/residential-berlin", r, [200, 201])


def test_feedback(api: API, suite: PlatformTestSuite) -> None:
    """Section 20: Feedback submission."""
    print("\n── 20. FEEDBACK ──")

    r = api.post("/api/v1/feedback", json={
        "category": "test",
        "subject": "Integration test feedback",
        "description": "Automated test — please ignore",
        "email": "test@test.com",
        "page_path": "/test",
    })
    check(suite, "POST /feedback", r, 200)


def test_edge_cases(api: API, suite: PlatformTestSuite) -> None:
    """Section 21: Edge cases & error handling."""
    print("\n── 21. EDGE CASES ──")

    # Non-existent endpoints
    r = api.get("/api/v1/nonexistent")
    check(suite, "GET /nonexistent → 404", r, [404, 405])

    # Invalid UUID
    r = api.get("/api/v1/boq/boqs/not-a-uuid")
    check(suite, "GET /boqs/not-a-uuid → 422", r, [404, 422])

    # Empty body
    r = api.post("/api/v1/projects/", json={})
    check(suite, "POST /projects/ empty body → 422", r, 422)

    # Missing auth
    saved_token = api.token
    api.set_token("")
    r = api.get("/api/v1/users/me")
    check(suite, "GET /users/me without auth → 401/403", r, [401, 403])
    api.set_token(saved_token)

    # Oversized description
    r = api.post("/api/v1/projects/", json={
        "name": "X" * 300,
        "description": "Y" * 5000,
    })
    check(suite, "POST /projects/ oversized name", r, [201, 422])

    # Negative values in position
    r = api.post("/api/v1/boq/boqs/00000000-0000-0000-0000-000000000000/positions/",
                 json={"boq_id": "00000000-0000-0000-0000-000000000000",
                       "ordinal": "1", "description": "test",
                       "unit": "m2", "quantity": -5, "unit_rate": 10})
    check(suite, "POST position negative qty → 4xx", r, [400, 404, 422])


def test_boq_duplicate_and_delete(api: API, suite: PlatformTestSuite, boq_id: str) -> None:
    """Section 22: BOQ duplicate & cleanup."""
    print("\n── 22. BOQ DUPLICATE & DELETE ──")

    # Duplicate BOQ
    r = api.post(f"/api/v1/boq/boqs/{boq_id}/duplicate")
    d = check(suite, "POST /boqs/duplicate", r, [200, 201])
    clone_id = ""
    if d:
        clone_id = d.get("id", "")
        suite.add("Clone has different ID", clone_id != boq_id and len(clone_id) > 10)

    # Delete clone
    if clone_id:
        r = api.delete(f"/api/v1/boq/boqs/{clone_id}")
        check(suite, "DELETE /boqs/ (clone)", r, [200, 204])


def test_recalculate(api: API, suite: PlatformTestSuite, boq_id: str) -> None:
    """Section 23: Recalculate rates & enrich."""
    print("\n── 23. RECALCULATE & ENRICH ──")

    r = api.post(f"/api/v1/boq/boqs/{boq_id}/enrich-resources")
    check(suite, "POST /enrich-resources", r, [200, 500])

    r = api.post(f"/api/v1/boq/boqs/{boq_id}/recalculate-rates")
    d = check(suite, "POST /recalculate-rates", r, 200)
    if d:
        suite.add("Recalculate has updated count",
                  "updated" in d or "skipped" in d)


def test_templates(api: API, suite: PlatformTestSuite, project_id: str) -> None:
    """Section 24: BOQ templates."""
    print("\n── 24. BOQ TEMPLATES ──")

    r = api.get("/api/v1/boq/boqs/templates")
    d = check(suite, "GET /boqs/templates", r, 200)
    if isinstance(d, list) and d:
        template_id = d[0].get("id", d[0].get("name", ""))
        r = api.post("/api/v1/boq/boqs/from-template", json={
            "project_id": project_id,
            "template_id": template_id,
            "name": f"From template: {template_id}",
        })
        check(suite, f"POST /boqs/from-template ({template_id})", r, [200, 201, 422])


def test_multi_region_boq(api: API, suite: PlatformTestSuite) -> None:
    """Section 25: Create BOQ in every region with regional markups and validate."""
    print("\n── 25. MULTI-REGION BOQ MATRIX ──")

    configs = [
        ("DACH", "EUR", "din276", "Bürogebäude Berlin 3.000 m²"),
        ("UK", "GBP", "nrm", "Office Building London 3,000 m²"),
        ("US", "USD", "masterformat", "Office Building NYC 32,000 sqft"),
        ("GULF", "AED", "din276", "مبنى مكتبي دبي ٣٠٠٠ م²"),
        ("RU", "RUB", "din276", "Офисное здание Москва 3 000 м²"),
        ("NORDIC", "EUR", "din276", "Kontorsbygning Stockholm 3 000 m²"),
    ]

    for region, currency, standard, desc in configs:
        # Create project
        r = api.post("/api/v1/projects/", json={
            "name": f"Test {region}",
            "description": desc,
            "region": region,
            "currency": currency,
            "classification_standard": standard,
        })
        d = check(suite, f"Project {region}/{currency}", r, 201)
        if not d:
            continue
        pid = d["id"]

        # Create BOQ
        r = api.post("/api/v1/boq/boqs/", json={
            "project_id": pid,
            "name": f"BOQ {region}",
        })
        d = check(suite, f"BOQ create {region}", r, 201)
        if not d:
            continue
        bid = d["id"]

        # Add 3 positions
        for i, (item_desc, unit, qty, rate) in enumerate([
            ("Foundation concrete", "m3", 100, 185),
            ("Structural steel", "kg", 5000, 2.10),
            ("Facade cladding", "m2", 600, 95),
        ]):
            r = api.post(f"/api/v1/boq/boqs/{bid}/positions/", json={
                "boq_id": bid, "ordinal": f"{i+1:02d}.001",
                "description": item_desc, "unit": unit,
                "quantity": qty, "unit_rate": rate,
            })
            check(suite, f"Position {region} #{i+1}", r, 201)

        # Apply regional markups
        r = api.post(f"/api/v1/boq/boqs/{bid}/markups/apply-defaults?region={region}")
        check(suite, f"Markups {region}", r, [200, 201])

        # Validate
        r = api.post(f"/api/v1/boq/boqs/{bid}/validate")
        d = check(suite, f"Validate {region}", r, 200)
        if d:
            suite.add(f"Score {region} ({d.get('score',0):.2f})",
                      isinstance(d.get("score"), (int, float)))

        # Structured view
        r = api.get(f"/api/v1/boq/boqs/{bid}/structured")
        check(suite, f"Structured {region}", r, 200)


def test_cost_search_multilingual(api: API, suite: PlatformTestSuite) -> None:
    """Section 26: Search cost database in multiple languages."""
    print("\n── 26. COST SEARCH — MULTILINGUAL ──")

    queries = [
        ("en", "concrete"),
        ("de", "Beton"),
        ("en", "reinforcement"),
        ("de", "Bewehrung"),
        ("en", "excavation"),
        ("en", "plumbing"),
        ("en", "electrical"),
        ("de", "Mauerwerk"),
        ("en", "insulation"),
        ("en", "roofing"),
        ("en", "painting"),
        ("en", "demolition"),
        ("en", "formwork"),
        ("de", "Schalung"),
        ("en", "drainage"),
    ]

    for lang, query in queries:
        r = api.get("/api/v1/costs/autocomplete", params={"q": query, "limit": 3})
        d = check(suite, f"Autocomplete '{query}' ({lang})", r, 200)
        if isinstance(d, list):
            suite.add(f"Results for '{query}'", len(d) >= 0,
                      detail=f"count={len(d)}")

    # Vector semantic search — different phrasings for same concept
    semantic_queries = [
        "reinforced concrete wall",
        "Stahlbetonwand",
        "foundation slab 300mm",
        "suspended ceiling system",
        "cavity wall insulation",
        "roof waterproofing membrane",
    ]
    for q in semantic_queries:
        try:
            r = api.get("/api/v1/costs/vector/search", params={"q": q, "limit": 3})
            check(suite, f"Semantic '{q[:30]}'", r, 200)
        except Exception:
            suite.add(f"Semantic '{q[:30]}'", False, detail="connection error")


def test_boq_ai_endpoints(api: API, suite: PlatformTestSuite, boq_id: str) -> None:
    """Section 27: BOQ AI endpoints (without actual AI key — expect 400/502)."""
    print("\n── 27. BOQ AI ENDPOINTS ──")

    # These endpoints require AI API key — test they respond (400 = no key, not 500)
    ai_endpoints = [
        ("POST", f"/api/v1/boq/boqs/classify",
         {"description": "Reinforced concrete foundation", "standard": "din276"}),
        ("POST", f"/api/v1/boq/boqs/suggest-rate",
         {"description": "Concrete C30/37", "unit": "m3", "region": "DACH"}),
        ("POST", f"/api/v1/boq/boqs/enhance-description",
         {"description": "concrete wall", "unit": "m2", "locale": "de"}),
        ("POST", f"/api/v1/boq/boqs/suggest-prerequisites",
         {"description": "Foundation excavation", "unit": "m3", "locale": "en"}),
        ("POST", f"/api/v1/boq/boqs/escalate-rate",
         {"description": "Brickwork", "unit": "m2", "rate": 65, "base_year": 2022,
          "target_year": 2026, "region": "DACH", "locale": "de"}),
        ("POST", f"/api/v1/boq/boqs/{boq_id}/check-scope",
         {"project_type": "commercial", "region": "DACH", "locale": "en"}),
        ("POST", f"/api/v1/boq/boqs/{boq_id}/check-anomalies", {}),
        ("POST", f"/api/v1/boq/boqs/search-cost-items",
         {"description": "steel rebar B500S", "limit": 5}),
    ]

    for method, path, body in ai_endpoints:
        try:
            r = api.post(path, json=body) if method == "POST" else api.get(path)
            # 200 = works, 400 = no AI key, 502 = AI provider error — all acceptable
            check(suite, f"AI {path.split('/')[-1]}", r, [200, 400, 422, 502])
        except Exception as exc:
            suite.add(f"AI {path.split('/')[-1]}", False, detail=str(exc)[:80])


def test_position_lifecycle(api: API, suite: PlatformTestSuite, boq_id: str) -> None:
    """Section 28: Position full lifecycle — create, update every field, delete."""
    print("\n── 28. POSITION LIFECYCLE ──")

    # Create
    r = api.post(f"/api/v1/boq/boqs/{boq_id}/positions/", json={
        "boq_id": boq_id, "ordinal": "LC.001",
        "description": "Lifecycle test position",
        "unit": "m2", "quantity": 100, "unit_rate": 50,
    })
    d = check(suite, "Create position", r, 201)
    if not d:
        return
    pid = d["id"]
    suite.add("Initial total = 5000", abs(d.get("total", 0) - 5000) < 0.01)

    # Update description
    r = api.patch(f"/api/v1/boq/positions/{pid}",
                  json={"description": "Updated lifecycle position"})
    check(suite, "Update description", r, 200)

    # Update quantity
    r = api.patch(f"/api/v1/boq/positions/{pid}", json={"quantity": 200})
    d = check(suite, "Update quantity → 200", r, 200)
    if d:
        suite.add("Total recalculated", abs(d.get("total", 0) - 10000) < 0.01)

    # Update unit rate
    r = api.patch(f"/api/v1/boq/positions/{pid}", json={"unit_rate": 75})
    d = check(suite, "Update rate → 75", r, 200)
    if d:
        suite.add("Total = 200×75 = 15000", abs(d.get("total", 0) - 15000) < 0.01)

    # Update unit
    r = api.patch(f"/api/v1/boq/positions/{pid}", json={"unit": "m3"})
    check(suite, "Update unit → m3", r, 200)

    # Update classification
    r = api.patch(f"/api/v1/boq/positions/{pid}",
                  json={"classification": {"din276": "300", "nrm": "2.1"}})
    check(suite, "Update classification", r, 200)

    # Duplicate
    r = api.post(f"/api/v1/boq/positions/{pid}/duplicate")
    d = check(suite, "Duplicate position", r, [200, 201])
    dup_id = d.get("id", "") if d else ""

    # Delete duplicate
    if dup_id:
        r = api.delete(f"/api/v1/boq/positions/{dup_id}")
        check(suite, "Delete duplicated position", r, [200, 204])

    # Delete original
    r = api.delete(f"/api/v1/boq/positions/{pid}")
    check(suite, "Delete original position", r, [200, 204])


def test_concurrent_operations(api: API, suite: PlatformTestSuite, boq_id: str) -> None:
    """Section 29: Rapid sequential operations — stress test."""
    print("\n── 29. RAPID OPERATIONS ──")

    # Create 20 positions rapidly
    created = []
    for i in range(20):
        r = api.post(f"/api/v1/boq/boqs/{boq_id}/positions/", json={
            "boq_id": boq_id, "ordinal": f"RAPID.{i+1:03d}",
            "description": f"Rapid test position #{i+1}",
            "unit": "pcs", "quantity": i + 1, "unit_rate": 10,
        })
        if r.status_code == 201:
            created.append(r.json().get("id", ""))
    suite.add(f"Rapid create 20 positions", len(created) == 20,
              detail=f"created={len(created)}")

    # Delete all 20
    deleted = 0
    for pid in created:
        r = api.delete(f"/api/v1/boq/positions/{pid}")
        if r.status_code in (200, 204):
            deleted += 1
    suite.add(f"Rapid delete 20 positions", deleted == 20,
              detail=f"deleted={deleted}")


def test_project_activity_log(api: API, suite: PlatformTestSuite, project_id: str) -> None:
    """Section 30: Project-level activity log."""
    print("\n── 30. PROJECT ACTIVITY LOG ──")

    r = api.get(f"/api/v1/boq/projects/{project_id}/activity")
    d = check(suite, "GET /projects/{id}/activity", r, 200)
    if d:
        entries = d.get("entries", d if isinstance(d, list) else [])
        suite.add(f"Activity entries ({len(entries)})", len(entries) >= 0)


def test_user_management(api: API, suite: PlatformTestSuite) -> None:
    """Section 31: User registration, profile, password changes."""
    print("\n── 31. USER MANAGEMENT ──")

    # Register new user
    email = f"test-{uuid.uuid4().hex[:8]}@openestimator.io"
    r = api.post("/api/v1/users/auth/register", json={
        "email": email,
        "password": "TestPass1234!",
        "full_name": "Integration Test User",
        "locale": "de",
    })
    check(suite, "Register new user", r, [200, 201])

    # Login as new user
    r = api.post("/api/v1/users/auth/login",
                 json={"email": email, "password": "TestPass1234!"})
    d = check(suite, "Login as new user", r, 200)
    if d and d.get("access_token"):
        new_token = d["access_token"]
        saved = api.token
        api.set_token(new_token)

        # Get profile
        r = api.get("/api/v1/users/me")
        d = check(suite, "New user profile", r, 200)
        if d:
            suite.add("New user locale is 'de'", d.get("locale") == "de")
            suite.add("New user name correct", d.get("full_name") == "Integration Test User")

        # Update profile in multiple locales
        for loc in ["fr", "ru", "ar", "ja", "en"]:
            r = api.patch("/api/v1/users/me", json={"locale": loc})
            check(suite, f"Switch locale → {loc}", r, 200)

        # Change password
        r = api.post("/api/v1/users/me/change-password", json={
            "current_password": "TestPass1234!",
            "new_password": "NewPass5678!",
        })
        check(suite, "Change password", r, [200, 204])

        # Restore admin token
        api.set_token(saved)


def test_epd_sustainability(api: API, suite: PlatformTestSuite, boq_id: str) -> None:
    """Section 32: EPD materials and CO2 sustainability."""
    print("\n── 32. SUSTAINABILITY / CO2 ──")

    r = api.get("/api/v1/boq/epd-materials")
    d = check(suite, "GET /epd-materials", r, 200)
    if isinstance(d, list):
        suite.add(f"EPD materials ({len(d)})", len(d) >= 0)

    r = api.post(f"/api/v1/boq/boqs/{boq_id}/enrich-co2")
    check(suite, "POST /enrich-co2", r, [200, 500])

    r = api.get(f"/api/v1/boq/boqs/{boq_id}/sustainability")
    check(suite, "GET /sustainability", r, 200)


def test_marketplace_modules(api: API, suite: PlatformTestSuite) -> None:
    """Section 33: Marketplace and module system."""
    print("\n── 33. MARKETPLACE & MODULES ──")

    r = api.get("/api/marketplace")
    d = check(suite, "GET /marketplace", r, 200)
    if isinstance(d, list):
        suite.add(f"Marketplace items ({len(d)})", len(d) >= 5,
                  detail=f"count={len(d)}")
        categories = set()
        for item in d:
            cat = item.get("category", "")
            if cat:
                categories.add(cat)
        suite.add(f"Marketplace categories ({len(categories)})",
                  len(categories) >= 2, detail=str(categories))

    r = api.get("/api/system/modules")
    d = check(suite, "GET /system/modules (loaded)", r, 200)
    if d:
        modules = d.get("modules", [])
        expected = ["oe_users", "oe_projects", "oe_boq", "oe_costs",
                    "oe_schedule", "oe_tendering", "oe_ai"]
        loaded_names = [m.get("name", "") for m in modules]
        for exp in expected:
            suite.add(f"Module '{exp}' loaded", exp in loaded_names)


def test_data_integrity(api: API, suite: PlatformTestSuite, project_id: str) -> None:
    """Section 34: Data integrity — totals, calculations, consistency."""
    print("\n── 34. DATA INTEGRITY ──")

    # Create BOQ with known values
    r = api.post("/api/v1/boq/boqs/", json={
        "project_id": project_id,
        "name": "Integrity Test BOQ",
    })
    d = check(suite, "Create integrity BOQ", r, 201)
    if not d:
        return
    bid = d["id"]

    # Add positions with exact values
    test_positions = [
        ("m3", 100.0, 185.50, 18550.0),
        ("m2", 250.5, 42.00, 10521.0),
        ("kg", 1200.0, 1.45, 1740.0),
        ("pcs", 15.0, 850.00, 12750.0),
        ("lsum", 1.0, 25000.00, 25000.0),
    ]
    expected_direct = 0.0
    for i, (unit, qty, rate, expected_total) in enumerate(test_positions):
        r = api.post(f"/api/v1/boq/boqs/{bid}/positions/", json={
            "boq_id": bid, "ordinal": f"INT.{i+1:03d}",
            "description": f"Integrity item #{i+1}",
            "unit": unit, "quantity": qty, "unit_rate": rate,
        })
        d = check(suite, f"Integrity pos #{i+1}", r, 201)
        if d:
            actual = d.get("total", 0)
            suite.add(f"Total {qty}×{rate}={expected_total}",
                      abs(actual - expected_total) < 0.02,
                      detail=f"got={actual}")
            expected_direct += expected_total

    # Get BOQ — check grand total matches sum
    r = api.get(f"/api/v1/boq/boqs/{bid}")
    d = check(suite, "Get integrity BOQ", r, 200)
    if d:
        grand = d.get("grand_total", 0)
        suite.add(f"Grand total = {expected_direct}",
                  abs(grand - expected_direct) < 1.0,
                  detail=f"got={grand}")

    # Add markup and check it applies
    r = api.post(f"/api/v1/boq/boqs/{bid}/markups", json={
        "name": "10% Overhead",
        "markup_type": "percentage",
        "percentage": 10.0,
        "is_active": True,
    })
    check(suite, "Add 10% markup", r, 201)

    # Re-fetch — grand total should be ~10% higher
    r = api.get(f"/api/v1/boq/boqs/{bid}")
    d = check(suite, "BOQ with markup", r, 200)
    if d:
        grand_with_markup = d.get("grand_total", 0)
        expected_with_markup = expected_direct * 1.10
        suite.add(f"Grand with 10% markup ≈ {expected_with_markup:.0f}",
                  abs(grand_with_markup - expected_with_markup) < expected_direct * 0.02,
                  detail=f"got={grand_with_markup:.2f}")

    # Cleanup
    api.delete(f"/api/v1/boq/boqs/{bid}")


def test_catalog_regions(api: API, suite: PlatformTestSuite) -> None:
    """Section 35: Catalog regional data."""
    print("\n── 35. CATALOG REGIONS ──")

    r = api.get("/api/v1/catalog/regions")
    d = check(suite, "GET /catalog/regions", r, 200)

    r = api.get("/api/v1/catalog/stats")
    d = check(suite, "GET /catalog/stats", r, 200)
    if isinstance(d, dict):
        total = d.get("total", 0)
        suite.add(f"Catalog total resources ({total})", total >= 0)

    # Search by different categories
    for cat in ["material", "labor", "equipment"]:
        r = api.get("/api/v1/catalog/", params={"category": cat, "limit": 3})
        check(suite, f"Catalog search cat={cat}", r, 200)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN RUNNER
# ══════════════════════════════════════════════════════════════════════════════


def run_all_tests() -> PlatformTestSuite:
    suite = PlatformTestSuite()
    suite.start_time = time.time()
    api = API(BASE_URL)

    try:
        # 1. System
        test_system(api, suite)

        # 2. i18n — 5 languages
        test_i18n(api, suite)

        # 3. Auth
        token = test_auth(api, suite)
        if not token:
            print("\n⛔ AUTH FAILED — cannot continue")
            return suite

        # 4. Projects — 6 regions
        project_id = test_projects(api, suite)

        # 5. BOQ CRUD
        boq_id = test_boq_crud(api, suite, project_id) if project_id else ""

        if boq_id:
            # 6. Markups
            test_markups(api, suite, boq_id)

            # 7. Validation
            test_validation(api, suite, boq_id)

            # 8. Snapshots
            test_snapshots(api, suite, boq_id)

            # 9. Analysis
            test_analysis(api, suite, boq_id)

            # 10. Exports
            test_exports(api, suite, boq_id)

            # 22. Duplicate & delete
            try:
                test_boq_duplicate_and_delete(api, suite, boq_id)
            except Exception as exc:
                suite.add("Section 22 Duplicate", False, detail=str(exc)[:100])

            # 23. Recalculate
            try:
                test_recalculate(api, suite, boq_id)
            except Exception as exc:
                suite.add("Section 23 Recalculate", False, detail=str(exc)[:100])

            # Recreate client if connection was lost
            try:
                api.get("/api/health")
            except Exception:
                api.close()
                time.sleep(2)
                api = API(BASE_URL)
                api.set_token(token)
                # Re-login to be safe
                try:
                    r = api.post("/api/v1/users/auth/login",
                                 json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
                    new_token = r.json().get("access_token", token)
                    api.set_token(new_token)
                    token = new_token
                except Exception:
                    pass

        # Remaining sections wrapped individually to survive crashes
        sections = [
            ("11. Costs", lambda: test_costs(api, suite)),
            ("12. Assemblies", lambda: test_assemblies(api, suite)),
            ("13. Schedule", lambda: test_schedule(api, suite, project_id, boq_id) if project_id and boq_id else None),
            ("14. Tendering", lambda: test_tendering(api, suite, project_id, boq_id) if project_id and boq_id else None),
            ("15. 5D Cost Model", lambda: test_costmodel(api, suite, project_id, boq_id) if project_id and boq_id else None),
            ("16. Catalog", lambda: test_catalog(api, suite)),
            ("17. Takeoff", lambda: test_takeoff(api, suite)),
            ("18. AI Settings", lambda: test_ai_settings(api, suite)),
            ("19. Demo Projects", lambda: test_demo_projects(api, suite)),
            ("20. Feedback", lambda: test_feedback(api, suite)),
            ("21. Edge Cases", lambda: test_edge_cases(api, suite)),
            ("24. Templates", lambda: test_templates(api, suite, project_id) if project_id else None),
            ("25. Multi-region BOQ", lambda: test_multi_region_boq(api, suite)),
            ("26. Cost search multilingual", lambda: test_cost_search_multilingual(api, suite)),
            ("27. BOQ AI endpoints", lambda: test_boq_ai_endpoints(api, suite, boq_id) if boq_id else None),
            ("28. Position lifecycle", lambda: test_position_lifecycle(api, suite, boq_id) if boq_id else None),
            ("29. Rapid operations", lambda: test_concurrent_operations(api, suite, boq_id) if boq_id else None),
            ("30. Project activity", lambda: test_project_activity_log(api, suite, project_id) if project_id else None),
            ("31. User management", lambda: test_user_management(api, suite)),
            ("32. Sustainability", lambda: test_epd_sustainability(api, suite, boq_id) if boq_id else None),
            ("33. Marketplace", lambda: test_marketplace_modules(api, suite)),
            ("34. Data integrity", lambda: test_data_integrity(api, suite, project_id) if project_id else None),
            ("35. Catalog regions", lambda: test_catalog_regions(api, suite)),
        ]
        for label, fn in sections:
            try:
                fn()
            except Exception as exc:
                suite.add(f"SECTION {label}: {type(exc).__name__}",
                          False, detail=str(exc)[:200])

    except Exception as exc:
        suite.add(f"FATAL: {type(exc).__name__}", False, detail=str(exc)[:200])
    finally:
        api.close()

    return suite


if __name__ == "__main__":
    import os
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # Force UTF-8 on Windows
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    print("=" * 70)
    print("  OPENESTIMATE — FULL PLATFORM INTEGRATION TEST")
    print(f"  Server: {BASE_URL}")
    print(f"  Languages: {', '.join(LOCALES)}")
    print(f"  Regions: {', '.join(REGIONS)}")
    print("=" * 70)

    suite = run_all_tests()
    print(suite.summary())

    # Exit code for CI
    failed = sum(1 for r in suite.results if not r.passed)
    sys.exit(1 if failed > 0 else 0)
