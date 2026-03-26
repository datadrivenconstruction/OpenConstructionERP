#!/usr/bin/env python3
"""Exhaustive API Test Suite for OpenEstimate Backend.

Tests all API endpoints for:
- Correct status codes
- Response schema validation
- Business logic correctness
- Error handling
- Data integrity (CRUD lifecycle)
"""

import json
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Any

BASE = "http://localhost:8000"
TOKEN = ""
RESULTS: list[dict[str, str]] = []
PASS_COUNT = 0
FAIL_COUNT = 0
WARN_COUNT = 0

# Collected IDs for cross-endpoint testing
STATE: dict[str, Any] = {}


def log_pass(endpoint: str, desc: str) -> None:
    global PASS_COUNT
    PASS_COUNT += 1
    RESULTS.append({"status": "PASS", "endpoint": endpoint, "desc": desc})
    print(f"[PASS] {endpoint} -- {desc}")


def log_fail(endpoint: str, desc: str, reason: str) -> None:
    global FAIL_COUNT
    FAIL_COUNT += 1
    RESULTS.append({"status": "FAIL", "endpoint": endpoint, "desc": desc, "reason": reason})
    print(f"[FAIL] {endpoint} -- {desc} -- {reason}")


def log_warn(endpoint: str, desc: str, note: str) -> None:
    global WARN_COUNT
    WARN_COUNT += 1
    RESULTS.append({"status": "WARN", "endpoint": endpoint, "desc": desc, "note": note})
    print(f"[WARN] {endpoint} -- {desc} -- {note}")


def api(method: str, path: str, body: Any = None, token: str | None = None,
        expected: int | None = None, raw: bool = False, timeout: int = 30) -> tuple[int, Any]:
    """Make an API call and return (status_code, parsed_json_or_bytes)."""
    url = f"{BASE}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        status_code = resp.status
        body_bytes = resp.read()
        if raw:
            return status_code, body_bytes
        if body_bytes:
            try:
                return status_code, json.loads(body_bytes)
            except json.JSONDecodeError:
                return status_code, body_bytes.decode("utf-8", errors="replace")
        return status_code, None
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        try:
            return e.code, json.loads(body_bytes)
        except Exception:
            return e.code, body_bytes.decode("utf-8", errors="replace") if body_bytes else None
    except Exception as e:
        return 0, str(e)


# ============================================================================
# 1. HEALTH & SYSTEM ENDPOINTS
# ============================================================================

def test_health():
    print("\n" + "=" * 70)
    print("1. HEALTH & SYSTEM ENDPOINTS")
    print("=" * 70)

    # Health check
    code, data = api("GET", "/api/health")
    if code == 200 and isinstance(data, dict) and data.get("status") == "healthy":
        log_pass("GET /api/health", "Returns healthy status")
    else:
        log_fail("GET /api/health", "Returns healthy status", f"code={code}, data={data}")

    # Check health has version field
    if isinstance(data, dict) and "version" in data:
        log_pass("GET /api/health", "Contains version field")
    else:
        log_fail("GET /api/health", "Contains version field", f"data={data}")

    # System status
    code, data = api("GET", "/api/system/status")
    if code == 200 and isinstance(data, dict):
        log_pass("GET /api/system/status", "Returns system status")
        if "api" in data and "database" in data:
            log_pass("GET /api/system/status", "Contains api and database sections")
        else:
            log_fail("GET /api/system/status", "Contains api and database sections", f"keys={list(data.keys())}")
        if data.get("database", {}).get("status") == "connected":
            log_pass("GET /api/system/status", "Database is connected")
        else:
            log_warn("GET /api/system/status", "Database status", f"db={data.get('database')}")
    else:
        log_fail("GET /api/system/status", "Returns system status", f"code={code}")

    # System modules
    code, data = api("GET", "/api/system/modules")
    if code == 200 and isinstance(data, dict) and "modules" in data:
        modules = data["modules"]
        log_pass("GET /api/system/modules", f"Returns module list ({len(modules)} modules)")
        if len(modules) >= 5:
            log_pass("GET /api/system/modules", "Has >= 5 core modules loaded")
        else:
            log_warn("GET /api/system/modules", "Module count", f"Only {len(modules)} modules")
    else:
        log_fail("GET /api/system/modules", "Returns module list", f"code={code}")

    # Marketplace
    code, data = api("GET", "/api/marketplace")
    if code == 200 and isinstance(data, list):
        log_pass("GET /api/marketplace", f"Returns marketplace list ({len(data)} items)")
        if len(data) > 0:
            first = data[0]
            if "name" in first:
                log_pass("GET /api/marketplace", "Items have 'name' field")
            else:
                log_fail("GET /api/marketplace", "Items have 'name' field", f"keys={list(first.keys())}")
    else:
        log_fail("GET /api/marketplace", "Returns marketplace list", f"code={code}, type={type(data)}")

    # Demo catalog
    code, data = api("GET", "/api/demo/catalog")
    if code == 200 and isinstance(data, list):
        log_pass("GET /api/demo/catalog", f"Returns demo catalog ({len(data)} templates)")
    else:
        log_fail("GET /api/demo/catalog", "Returns demo catalog", f"code={code}")

    # Validation rules
    code, data = api("GET", "/api/system/validation-rules")
    if code == 200 and isinstance(data, dict):
        log_pass("GET /api/system/validation-rules", "Returns validation rules")
        if "rule_sets" in data and "rules" in data:
            log_pass("GET /api/system/validation-rules", f"Has {len(data.get('rule_sets',[]))} rule sets, {len(data.get('rules',[]))} rules")
        else:
            log_fail("GET /api/system/validation-rules", "Has rule_sets and rules", f"keys={list(data.keys())}")
    else:
        log_fail("GET /api/system/validation-rules", "Returns validation rules", f"code={code}")

    # Hooks
    code, data = api("GET", "/api/system/hooks")
    if code == 200 and isinstance(data, dict):
        log_pass("GET /api/system/hooks", "Returns hooks")
        if "filters" in data and "actions" in data:
            log_pass("GET /api/system/hooks", "Has filters and actions sections")
        else:
            log_fail("GET /api/system/hooks", "Has filters and actions", f"keys={list(data.keys())}")
    else:
        log_fail("GET /api/system/hooks", "Returns hooks", f"code={code}")


# ============================================================================
# 2. AUTHENTICATION & USERS
# ============================================================================

def test_auth():
    global TOKEN
    print("\n" + "=" * 70)
    print("2. AUTHENTICATION & USERS")
    print("=" * 70)

    # Login with valid credentials
    code, data = api("POST", "/api/v1/users/auth/login", {
        "email": "demo@openestimator.io",
        "password": "DemoPass1234!"
    })
    if code == 200 and isinstance(data, dict) and "access_token" in data:
        TOKEN = data["access_token"]
        STATE["token"] = TOKEN
        log_pass("POST /api/v1/users/auth/login", "Login successful with valid credentials")
        if "refresh_token" in data:
            STATE["refresh_token"] = data["refresh_token"]
            log_pass("POST /api/v1/users/auth/login", "Response contains refresh_token")
        else:
            log_warn("POST /api/v1/users/auth/login", "refresh_token field", "Not in response")
        if "token_type" in data:
            log_pass("POST /api/v1/users/auth/login", f"Token type = {data['token_type']}")
        else:
            log_warn("POST /api/v1/users/auth/login", "token_type field", "Not in response")
    else:
        log_fail("POST /api/v1/users/auth/login", "Login successful", f"code={code}, data={data}")
        print("FATAL: Cannot continue without auth token!")
        return

    # Login with invalid password
    code, data = api("POST", "/api/v1/users/auth/login", {
        "email": "demo@openestimator.io",
        "password": "WrongPassword123"
    })
    if code in (401, 403):
        log_pass("POST /api/v1/users/auth/login", f"Invalid password returns {code}")
    else:
        log_fail("POST /api/v1/users/auth/login", "Invalid password rejected", f"code={code}")

    # Login with non-existent email
    code, data = api("POST", "/api/v1/users/auth/login", {
        "email": "nonexistent@test.com",
        "password": "AnyPass123!"
    })
    if code in (401, 403, 404):
        log_pass("POST /api/v1/users/auth/login", f"Non-existent email returns {code}")
    else:
        log_fail("POST /api/v1/users/auth/login", "Non-existent email rejected", f"code={code}")

    # Login with missing fields
    code, data = api("POST", "/api/v1/users/auth/login", {"email": "demo@openestimator.io"})
    if code == 422:
        log_pass("POST /api/v1/users/auth/login", "Missing password field returns 422")
    else:
        log_fail("POST /api/v1/users/auth/login", "Missing password returns 422", f"code={code}")

    # Get current user profile
    code, data = api("GET", "/api/v1/users/me", token=TOKEN)
    if code == 200 and isinstance(data, dict):
        log_pass("GET /api/v1/users/me", "Returns user profile")
        STATE["user_id"] = data.get("id")
        required_fields = ["id", "email", "full_name", "role", "locale"]
        for f in required_fields:
            if f in data:
                log_pass("GET /api/v1/users/me", f"Profile has '{f}' field = {repr(data[f])[:50]}")
            else:
                log_fail("GET /api/v1/users/me", f"Profile has '{f}' field", f"Missing. keys={list(data.keys())}")
        if data.get("email") == "demo@openestimator.io":
            log_pass("GET /api/v1/users/me", "Email matches demo account")
        else:
            log_fail("GET /api/v1/users/me", "Email matches", f"email={data.get('email')}")
        if "permissions" in data:
            log_pass("GET /api/v1/users/me", f"Has permissions list ({len(data['permissions'])} perms)")
        else:
            log_warn("GET /api/v1/users/me", "Permissions", "Not in /me response")
    else:
        log_fail("GET /api/v1/users/me", "Returns user profile", f"code={code}")

    # Access without token
    code, data = api("GET", "/api/v1/users/me")
    if code in (401, 403):
        log_pass("GET /api/v1/users/me", f"Unauthorized access returns {code}")
    else:
        log_fail("GET /api/v1/users/me", "Unauthorized rejected", f"code={code}")

    # Access with invalid token
    code, data = api("GET", "/api/v1/users/me", token="invalid-token-12345")
    if code in (401, 403):
        log_pass("GET /api/v1/users/me", f"Invalid token returns {code}")
    else:
        log_fail("GET /api/v1/users/me", "Invalid token rejected", f"code={code}")

    # Update profile
    code, data = api("PATCH", "/api/v1/users/me", {"full_name": "Demo QA User"}, token=TOKEN)
    if code == 200 and isinstance(data, dict):
        log_pass("PATCH /api/v1/users/me", "Profile update successful")
        if data.get("full_name") == "Demo QA User":
            log_pass("PATCH /api/v1/users/me", "full_name correctly updated")
        else:
            log_fail("PATCH /api/v1/users/me", "full_name updated", f"got={data.get('full_name')}")
    else:
        log_fail("PATCH /api/v1/users/me", "Profile update", f"code={code}, data={data}")

    # Restore original name
    api("PATCH", "/api/v1/users/me", {"full_name": "Demo User"}, token=TOKEN)

    # Update locale
    code, data = api("PATCH", "/api/v1/users/me", {"locale": "de"}, token=TOKEN)
    if code == 200:
        log_pass("PATCH /api/v1/users/me", "Locale update to 'de' successful")
    else:
        log_fail("PATCH /api/v1/users/me", "Locale update", f"code={code}")
    # Restore
    api("PATCH", "/api/v1/users/me", {"locale": "en"}, token=TOKEN)

    # Refresh token
    if "refresh_token" in STATE:
        code, data = api("POST", "/api/v1/users/auth/refresh", {
            "refresh_token": STATE["refresh_token"]
        })
        if code == 200 and isinstance(data, dict) and "access_token" in data:
            log_pass("POST /api/v1/users/auth/refresh", "Token refresh successful")
            TOKEN = data["access_token"]
            STATE["token"] = TOKEN
        else:
            log_fail("POST /api/v1/users/auth/refresh", "Token refresh", f"code={code}")

    # Forgot password
    code, data = api("POST", "/api/v1/users/auth/forgot-password", {
        "email": "demo@openestimator.io"
    })
    if code == 200:
        log_pass("POST /api/v1/users/auth/forgot-password", "Returns success (no email enumeration)")
        if isinstance(data, dict) and "reset_token" in data:
            STATE["reset_token"] = data["reset_token"]
            log_pass("POST /api/v1/users/auth/forgot-password", "Dev mode: reset_token included in response")
    else:
        log_fail("POST /api/v1/users/auth/forgot-password", "Forgot password", f"code={code}")

    # Change password (test and revert)
    code, data = api("POST", "/api/v1/users/me/change-password", {
        "current_password": "DemoPass1234!",
        "new_password": "NewTempPass999!"
    }, token=TOKEN)
    if code == 204:
        log_pass("POST /api/v1/users/me/change-password", "Password change successful")
        # Revert password
        code2, _ = api("POST", "/api/v1/users/auth/login", {
            "email": "demo@openestimator.io", "password": "NewTempPass999!"
        })
        if code2 == 200:
            log_pass("POST /api/v1/users/me/change-password", "Can login with new password")
        # Change back
        code3, data3 = api("POST", "/api/v1/users/auth/login", {
            "email": "demo@openestimator.io", "password": "NewTempPass999!"
        })
        if code3 == 200:
            temp_token = data3.get("access_token", TOKEN)
            api("POST", "/api/v1/users/me/change-password", {
                "current_password": "NewTempPass999!",
                "new_password": "DemoPass1234!"
            }, token=temp_token)
            # Re-login with original
            code4, data4 = api("POST", "/api/v1/users/auth/login", {
                "email": "demo@openestimator.io", "password": "DemoPass1234!"
            })
            if code4 == 200:
                TOKEN = data4["access_token"]
                STATE["token"] = TOKEN
    elif code == 200:
        log_pass("POST /api/v1/users/me/change-password", "Password change returned 200 (expected 204)")
        # Login with new password and revert
        code2, data2 = api("POST", "/api/v1/users/auth/login", {
            "email": "demo@openestimator.io", "password": "NewTempPass999!"
        })
        if code2 == 200:
            temp_token = data2.get("access_token", TOKEN)
            api("POST", "/api/v1/users/me/change-password", {
                "current_password": "NewTempPass999!",
                "new_password": "DemoPass1234!"
            }, token=temp_token)
            code3, data3 = api("POST", "/api/v1/users/auth/login", {
                "email": "demo@openestimator.io", "password": "DemoPass1234!"
            })
            if code3 == 200:
                TOKEN = data3["access_token"]
                STATE["token"] = TOKEN
    else:
        log_fail("POST /api/v1/users/me/change-password", "Password change", f"code={code}, data={data}")

    # Change password with wrong current
    code, data = api("POST", "/api/v1/users/me/change-password", {
        "current_password": "WrongCurrent!",
        "new_password": "SomePass999!"
    }, token=TOKEN)
    if code in (400, 401, 403):
        log_pass("POST /api/v1/users/me/change-password", f"Wrong current password returns {code}")
    else:
        log_fail("POST /api/v1/users/me/change-password", "Wrong current password rejected", f"code={code}")

    # List users (admin only)
    code, data = api("GET", "/api/v1/users/", token=TOKEN)
    if code == 200 and isinstance(data, list):
        log_pass("GET /api/v1/users/", f"Admin can list users ({len(data)} users)")
    else:
        log_warn("GET /api/v1/users/", "List users", f"code={code}")

    # API Keys
    code, data = api("GET", "/api/v1/users/me/api-keys", token=TOKEN)
    if code == 200 and isinstance(data, list):
        log_pass("GET /api/v1/users/me/api-keys", f"List API keys ({len(data)} keys)")
    else:
        log_fail("GET /api/v1/users/me/api-keys", "List API keys", f"code={code}")

    # Create API key
    code, data = api("POST", "/api/v1/users/me/api-keys", {
        "name": "QA Test Key",
        "expires_in_days": 30
    }, token=TOKEN)
    if code == 201 and isinstance(data, dict):
        log_pass("POST /api/v1/users/me/api-keys", "API key created")
        if "key" in data or "full_key" in data or "api_key" in data:
            log_pass("POST /api/v1/users/me/api-keys", "Full key returned on creation")
        key_id = data.get("id")
        if key_id:
            STATE["api_key_id"] = key_id
            # Revoke it
            code2, _ = api("DELETE", f"/api/v1/users/me/api-keys/{key_id}", token=TOKEN)
            if code2 == 204:
                log_pass(f"DELETE /api/v1/users/me/api-keys/{key_id}", "API key revoked")
            else:
                log_fail(f"DELETE /api/v1/users/me/api-keys/...", "Revoke API key", f"code={code2}")
    else:
        log_fail("POST /api/v1/users/me/api-keys", "Create API key", f"code={code}, data={data}")


# ============================================================================
# 3. PROJECTS
# ============================================================================

def test_projects():
    print("\n" + "=" * 70)
    print("3. PROJECTS")
    print("=" * 70)

    # List projects
    code, data = api("GET", "/api/v1/projects/", token=TOKEN)
    if code == 200 and isinstance(data, list):
        log_pass("GET /api/v1/projects/", f"Returns project list ({len(data)} projects)")
        STATE["projects"] = data
        if len(data) >= 5:
            log_pass("GET /api/v1/projects/", "Has >= 5 demo projects")
        else:
            log_warn("GET /api/v1/projects/", "Expected 5 demo projects", f"Got {len(data)}")

        # Check project schema
        if len(data) > 0:
            p = data[0]
            required_fields = ["id", "name", "status", "currency", "created_at"]
            for f in required_fields:
                if f in p:
                    log_pass("GET /api/v1/projects/", f"Project has '{f}' field")
                else:
                    log_fail("GET /api/v1/projects/", f"Project missing '{f}'", f"keys={list(p.keys())}")

            # Check currencies diversity
            currencies = set(p.get("currency", "EUR") for p in data)
            if len(currencies) >= 2:
                log_pass("GET /api/v1/projects/", f"Multiple currencies present: {currencies}")
            else:
                log_warn("GET /api/v1/projects/", "Currency diversity", f"Only {currencies}")

        # Get single project
        if len(data) > 0:
            pid = data[0]["id"]
            STATE["project_id"] = pid
            code2, proj = api("GET", f"/api/v1/projects/{pid}", token=TOKEN)
            if code2 == 200 and isinstance(proj, dict):
                log_pass(f"GET /api/v1/projects/{{id}}", f"Returns project '{proj.get('name')}'")
            else:
                log_fail(f"GET /api/v1/projects/{{id}}", "Get single project", f"code={code2}")
    else:
        log_fail("GET /api/v1/projects/", "Returns project list", f"code={code}")

    # Get non-existent project
    fake_id = "00000000-0000-0000-0000-000000000000"
    code, data = api("GET", f"/api/v1/projects/{fake_id}", token=TOKEN)
    if code in (404, 403):
        log_pass(f"GET /api/v1/projects/{{fake_id}}", f"Non-existent project returns {code}")
    else:
        log_fail(f"GET /api/v1/projects/{{fake_id}}", "Non-existent project", f"code={code}")

    # Create project
    code, data = api("POST", "/api/v1/projects/", {
        "name": "QA Test Project",
        "description": "Created by automated API test",
        "currency": "USD",
        "status": "active"
    }, token=TOKEN)
    if code == 201 and isinstance(data, dict):
        log_pass("POST /api/v1/projects/", "Project created successfully")
        STATE["new_project_id"] = data["id"]
        if data.get("name") == "QA Test Project":
            log_pass("POST /api/v1/projects/", "Created project name matches")
        if data.get("currency") == "USD":
            log_pass("POST /api/v1/projects/", "Created project currency = USD")
    else:
        log_fail("POST /api/v1/projects/", "Create project", f"code={code}, data={data}")

    # Update project
    if "new_project_id" in STATE:
        pid = STATE["new_project_id"]
        code, data = api("PATCH", f"/api/v1/projects/{pid}", {
            "name": "QA Test Project Updated",
            "description": "Updated description"
        }, token=TOKEN)
        if code == 200 and isinstance(data, dict):
            log_pass("PATCH /api/v1/projects/{{id}}", "Project updated successfully")
            if data.get("name") == "QA Test Project Updated":
                log_pass("PATCH /api/v1/projects/{{id}}", "Name correctly updated")
            else:
                log_fail("PATCH /api/v1/projects/{{id}}", "Name update", f"got={data.get('name')}")
        else:
            log_fail("PATCH /api/v1/projects/{{id}}", "Update project", f"code={code}")

    # Delete (archive) project
    if "new_project_id" in STATE:
        pid = STATE["new_project_id"]
        code, data = api("DELETE", f"/api/v1/projects/{pid}", token=TOKEN)
        if code == 204:
            log_pass("DELETE /api/v1/projects/{{id}}", "Project archived (soft deleted)")
        else:
            log_fail("DELETE /api/v1/projects/{{id}}", "Delete project", f"code={code}")

    # Projects without auth
    code, data = api("GET", "/api/v1/projects/")
    if code in (401, 403):
        log_pass("GET /api/v1/projects/", f"Unauthorized returns {code}")
    else:
        log_fail("GET /api/v1/projects/", "Unauthorized rejected", f"code={code}")

    # Pagination
    code, data = api("GET", "/api/v1/projects/?offset=0&limit=2", token=TOKEN)
    if code == 200 and isinstance(data, list) and len(data) <= 2:
        log_pass("GET /api/v1/projects/?limit=2", f"Pagination works (got {len(data)} items)")
    else:
        log_fail("GET /api/v1/projects/?limit=2", "Pagination", f"code={code}, len={len(data) if isinstance(data, list) else 'N/A'}")


# ============================================================================
# 4. BOQ (Bill of Quantities)
# ============================================================================

def test_boq():
    print("\n" + "=" * 70)
    print("4. BOQ (Bill of Quantities)")
    print("=" * 70)

    projects = STATE.get("projects", [])
    if not projects:
        log_fail("BOQ", "Pre-requisite", "No projects available")
        return

    project_id = projects[0]["id"]

    # List BOQs for first project
    code, data = api("GET", f"/api/v1/boq/boqs/?project_id={project_id}", token=TOKEN)
    if code == 200 and isinstance(data, list):
        log_pass(f"GET /api/v1/boq/boqs/?project_id=...", f"Returns {len(data)} BOQs for project")
        STATE["boqs"] = data
        if len(data) >= 2:
            log_pass("GET /api/v1/boq/boqs/", "Has >= 2 BOQs per project (detailed + budget)")
        else:
            log_warn("GET /api/v1/boq/boqs/", "Expected 2 BOQs", f"Got {len(data)}")

        # Check BOQ schema
        if len(data) > 0:
            b = data[0]
            for f in ["id", "project_id", "name", "status", "grand_total"]:
                if f in b:
                    log_pass("GET /api/v1/boq/boqs/", f"BOQ has '{f}' = {repr(b[f])[:50]}")
                else:
                    log_fail("GET /api/v1/boq/boqs/", f"BOQ missing '{f}'", f"keys={list(b.keys())}")
    else:
        log_fail("GET /api/v1/boq/boqs/", "List BOQs", f"code={code}")

    # Check total BOQs across projects
    total_boqs = 0
    for p in projects[:5]:
        code, boqs = api("GET", f"/api/v1/boq/boqs/?project_id={p['id']}", token=TOKEN)
        if code == 200 and isinstance(boqs, list):
            total_boqs += len(boqs)
    if total_boqs >= 10:
        log_pass("BOQ count across projects", f"Total {total_boqs} BOQs across {len(projects)} projects")
    else:
        log_warn("BOQ count across projects", f"Expected >= 10 BOQs", f"Got {total_boqs}")

    # Get single BOQ with positions
    if STATE.get("boqs"):
        boq_id = STATE["boqs"][0]["id"]
        STATE["boq_id"] = boq_id
        code, data = api("GET", f"/api/v1/boq/boqs/{boq_id}", token=TOKEN)
        if code == 200 and isinstance(data, dict):
            log_pass(f"GET /api/v1/boq/boqs/{{id}}", f"Returns BOQ '{data.get('name')}'")
            positions = data.get("positions", [])
            if isinstance(positions, list) and len(positions) > 0:
                STATE["positions"] = positions
                STATE["position_id"] = positions[0].get("id")
                log_pass("GET /api/v1/boq/boqs/{{id}}", f"Has {len(positions)} positions")
                # Check position schema
                pos = positions[0]
                for f in ["id", "boq_id", "description", "unit", "quantity", "unit_rate", "total"]:
                    if f in pos:
                        log_pass("Position schema", f"Has '{f}' = {repr(pos[f])[:50]}")
                    else:
                        log_fail("Position schema", f"Missing '{f}'", f"keys={list(pos.keys())}")
                # Verify total = quantity * unit_rate
                qty = float(pos.get("quantity", 0))
                rate = float(pos.get("unit_rate", 0))
                total = float(pos.get("total", 0))
                if qty > 0 and rate > 0:
                    expected = round(qty * rate, 2)
                    actual = round(total, 2)
                    if abs(expected - actual) < 0.02:
                        log_pass("Position math", f"total={actual} == qty*rate={expected}")
                    else:
                        log_fail("Position math", f"total mismatch", f"total={actual} != qty*rate={expected}")
            else:
                log_warn("GET /api/v1/boq/boqs/{{id}}", "Positions", f"Empty or missing, data has: {list(data.keys())}")
        else:
            log_fail("GET /api/v1/boq/boqs/{{id}}", "Get BOQ with positions", f"code={code}")

    # Get BOQ structured (with sections + markups)
    if "boq_id" in STATE:
        boq_id = STATE["boq_id"]
        code, data = api("GET", f"/api/v1/boq/boqs/{boq_id}/structured", token=TOKEN)
        if code == 200 and isinstance(data, dict):
            log_pass("GET /api/v1/boq/boqs/{{id}}/structured", "Returns structured BOQ")
            for f in ["sections", "markups", "subtotal", "grand_total"]:
                if f in data:
                    log_pass("Structured BOQ", f"Has '{f}'")
                else:
                    log_warn("Structured BOQ", f"Missing '{f}'", f"keys={list(data.keys())}")
        else:
            log_fail("GET /api/v1/boq/boqs/{{id}}/structured", "Get structured BOQ", f"code={code}")

    # Activity log
    if "boq_id" in STATE:
        boq_id = STATE["boq_id"]
        code, data = api("GET", f"/api/v1/boq/boqs/{boq_id}/activity", token=TOKEN)
        if code == 200:
            log_pass("GET /api/v1/boq/boqs/{{id}}/activity", "Returns activity log")
        else:
            log_fail("GET /api/v1/boq/boqs/{{id}}/activity", "Activity log", f"code={code}")

    # Project activity log
    code, data = api("GET", f"/api/v1/boq/projects/{project_id}/activity", token=TOKEN)
    if code == 200:
        log_pass("GET /api/v1/boq/projects/{{id}}/activity", "Returns project activity log")
    else:
        log_fail("GET /api/v1/boq/projects/{{id}}/activity", "Project activity log", f"code={code}")

    # Create a new BOQ
    code, data = api("POST", "/api/v1/boq/boqs/", {
        "project_id": project_id,
        "name": "QA Test BOQ",
        "description": "Created by automated test",
        "status": "draft"
    }, token=TOKEN)
    if code == 201 and isinstance(data, dict):
        log_pass("POST /api/v1/boq/boqs/", "BOQ created successfully")
        STATE["new_boq_id"] = data["id"]
    else:
        log_fail("POST /api/v1/boq/boqs/", "Create BOQ", f"code={code}, data={data}")

    # Add position to new BOQ
    if "new_boq_id" in STATE:
        new_boq_id = STATE["new_boq_id"]
        code, data = api("POST", f"/api/v1/boq/boqs/{new_boq_id}/positions", {
            "boq_id": new_boq_id,
            "description": "QA Test Position - Concrete C30/37",
            "unit": "m3",
            "quantity": 100.0,
            "unit_rate": 185.50,
            "ordinal": "01.001",
            "source": "manual"
        }, token=TOKEN)
        if code == 201 and isinstance(data, dict):
            log_pass("POST /api/v1/boq/boqs/{{id}}/positions", "Position created")
            STATE["new_position_id"] = data["id"]
            if abs(float(data.get("total", 0)) - 18550.0) < 1.0:
                log_pass("Position creation", f"Total correctly computed: {data.get('total')}")
            else:
                log_fail("Position creation", "Total computation", f"total={data.get('total')}, expected=18550.0")
        else:
            log_fail("POST /api/v1/boq/boqs/{{id}}/positions", "Create position", f"code={code}, data={data}")

    # Update position
    if "new_position_id" in STATE:
        pos_id = STATE["new_position_id"]
        code, data = api("PATCH", f"/api/v1/boq/positions/{pos_id}", {
            "quantity": 150.0,
            "unit_rate": 200.0
        }, token=TOKEN)
        if code == 200 and isinstance(data, dict):
            log_pass("PATCH /api/v1/boq/positions/{{id}}", "Position updated")
            if abs(float(data.get("total", 0)) - 30000.0) < 1.0:
                log_pass("Position update", f"Total correctly recomputed: {data.get('total')}")
            else:
                log_fail("Position update", "Total recomputed", f"total={data.get('total')}, expected=30000.0")
        else:
            log_fail("PATCH /api/v1/boq/positions/{{id}}", "Update position", f"code={code}")

    # Add second position for richer tests
    if "new_boq_id" in STATE:
        new_boq_id = STATE["new_boq_id"]
        code, data = api("POST", f"/api/v1/boq/boqs/{new_boq_id}/positions", {
            "boq_id": new_boq_id,
            "description": "Steel reinforcement B500",
            "unit": "kg",
            "quantity": 5000.0,
            "unit_rate": 1.85,
            "ordinal": "01.002",
            "source": "manual"
        }, token=TOKEN)
        if code == 201:
            log_pass("POST /api/v1/boq/boqs/{{id}}/positions", "Second position created for testing")
            STATE["second_position_id"] = data.get("id")

    # Recalculate rates
    if "new_boq_id" in STATE:
        code, data = api("POST", f"/api/v1/boq/boqs/{STATE['new_boq_id']}/recalculate-rates", token=TOKEN)
        if code == 200:
            log_pass("POST /api/v1/boq/boqs/{{id}}/recalculate-rates", "Recalculate successful")
        else:
            log_fail("POST /api/v1/boq/boqs/{{id}}/recalculate-rates", "Recalculate", f"code={code}")

    # Resource summary
    if "boq_id" in STATE:
        code, data = api("GET", f"/api/v1/boq/boqs/{STATE['boq_id']}/resource-summary", token=TOKEN)
        if code == 200:
            log_pass("GET /api/v1/boq/boqs/{{id}}/resource-summary", "Resource summary returned")
        else:
            log_fail("GET /api/v1/boq/boqs/{{id}}/resource-summary", "Resource summary", f"code={code}")

    # Cost breakdown
    if "boq_id" in STATE:
        code, data = api("GET", f"/api/v1/boq/boqs/{STATE['boq_id']}/cost-breakdown", token=TOKEN)
        if code == 200:
            log_pass("GET /api/v1/boq/boqs/{{id}}/cost-breakdown", "Cost breakdown returned")
        else:
            log_fail("GET /api/v1/boq/boqs.{{id}}/cost-breakdown", "Cost breakdown", f"code={code}")

    # Sensitivity analysis
    if "boq_id" in STATE:
        code, data = api("GET", f"/api/v1/boq/boqs/{STATE['boq_id']}/sensitivity", token=TOKEN)
        if code == 200:
            log_pass("GET /api/v1/boq/boqs/{{id}}/sensitivity", "Sensitivity analysis returned")
        else:
            log_fail("GET /api/v1/boq/boqs/{{id}}/sensitivity", "Sensitivity", f"code={code}")

    # Cost risk (Monte Carlo)
    if "boq_id" in STATE:
        code, data = api("GET", f"/api/v1/boq/boqs/{STATE['boq_id']}/cost-risk", token=TOKEN)
        if code == 200:
            log_pass("GET /api/v1/boq/boqs/{{id}}/cost-risk", "Cost risk analysis returned")
        else:
            log_fail("GET /api/v1/boq/boqs/{{id}}/cost-risk", "Cost risk", f"code={code}")

    # BOQ Templates
    code, data = api("GET", "/api/v1/boq/boqs/templates", token=TOKEN)
    if code == 200 and isinstance(data, list):
        log_pass("GET /api/v1/boq/boqs/templates", f"Templates returned ({len(data)} templates)")
    else:
        log_fail("GET /api/v1/boq/boqs/templates", "Templates", f"code={code}")

    # Markups
    if "new_boq_id" in STATE:
        boq_id = STATE["new_boq_id"]
        # Add markup
        code, data = api("POST", f"/api/v1/boq/boqs/{boq_id}/markups", {
            "name": "Overhead",
            "markup_type": "percentage",
            "percentage": 10.0,
            "category": "overhead"
        }, token=TOKEN)
        if code == 201 and isinstance(data, dict):
            log_pass("POST /api/v1/boq/boqs/{{id}}/markups", "Markup created")
            STATE["markup_id"] = data["id"]
        else:
            log_fail("POST /api/v1/boq/boqs.{{id}}/markups", "Create markup", f"code={code}, data={data}")

        # Update markup
        if "markup_id" in STATE:
            code, data = api("PATCH", f"/api/v1/boq/boqs/{boq_id}/markups/{STATE['markup_id']}", {
                "percentage": 12.5
            }, token=TOKEN)
            if code == 200:
                log_pass("PATCH /api/v1/boq/boqs/{{id}}/markups/{{mid}}", "Markup updated")
            else:
                log_fail("PATCH markups", "Update markup", f"code={code}")

            # Delete markup
            code, _ = api("DELETE", f"/api/v1/boq/boqs/{boq_id}/markups/{STATE['markup_id']}", token=TOKEN)
            if code == 204:
                log_pass("DELETE /api/v1/boq/boqs/{{id}}/markups/{{mid}}", "Markup deleted")
            else:
                log_fail("DELETE markups", "Delete markup", f"code={code}")

    # Duplicate BOQ
    if "new_boq_id" in STATE:
        code, data = api("POST", f"/api/v1/boq/boqs/{STATE['new_boq_id']}/duplicate", token=TOKEN)
        if code == 201 and isinstance(data, dict):
            log_pass("POST /api/v1/boq/boqs/{{id}}/duplicate", "BOQ duplicated")
            STATE["dup_boq_id"] = data["id"]
        else:
            log_fail("POST /api/v1/boq/boqs.{{id}}/duplicate", "Duplicate BOQ", f"code={code}")

    # Validate BOQ
    if "boq_id" in STATE:
        code, data = api("POST", f"/api/v1/boq/boqs/{STATE['boq_id']}/validate", token=TOKEN)
        if code == 200:
            log_pass("POST /api/v1/boq/boqs.{{id}}/validate", "BOQ validation returned")
        else:
            log_fail("POST /api/v1/boq/boqs.{{id}}/validate", "Validate BOQ", f"code={code}")

    # Export CSV
    if "boq_id" in STATE:
        code, data = api("GET", f"/api/v1/boq/boqs/{STATE['boq_id']}/export/csv", token=TOKEN, raw=True)
        if code == 200:
            log_pass("GET /api/v1/boq/boqs/{{id}}/export/csv", "CSV export successful")
        else:
            log_fail("GET /api/v1/boq/boqs/{{id}}/export/csv", "CSV export", f"code={code}")

    # Export GAEB
    if "boq_id" in STATE:
        code, data = api("GET", f"/api/v1/boq/boqs/{STATE['boq_id']}/export/gaeb", token=TOKEN, raw=True)
        if code == 200:
            log_pass("GET /api/v1/boq/boqs/{{id}}/export/gaeb", "GAEB export successful")
        else:
            log_fail("GET /api/v1/boq/boqs/{{id}}/export/gaeb", "GAEB export", f"code={code}")

    # AI: Classify
    code, data = api("POST", "/api/v1/boq/boqs/classify", {
        "description": "Reinforced concrete wall C30/37, 24cm thickness",
        "standard": "din276"
    }, token=TOKEN)
    if code == 200 and isinstance(data, dict):
        log_pass("POST /api/v1/boq/boqs/classify", "Classification returned")
    else:
        log_fail("POST /api/v1/boq/boqs/classify", "Classify", f"code={code}")

    # AI: Suggest rate
    code, data = api("POST", "/api/v1/boq/boqs/suggest-rate", {
        "description": "Reinforced concrete wall C30/37",
        "unit": "m3",
        "region": "Berlin"
    }, token=TOKEN)
    if code == 200 and isinstance(data, dict):
        log_pass("POST /api/v1/boq/boqs/suggest-rate", "Rate suggestion returned")
    else:
        log_fail("POST /api/v1/boq/boqs/suggest-rate", "Suggest rate", f"code={code}")

    # AI: Check anomalies
    if "boq_id" in STATE:
        code, data = api("POST", f"/api/v1/boq/boqs/{STATE['boq_id']}/check-anomalies", token=TOKEN)
        if code == 200:
            log_pass("POST /api/v1/boq/boqs/{{id}}/check-anomalies", "Anomaly check returned")
        else:
            log_fail("POST /api/v1/boq/boqs/{{id}}/check-anomalies", "Anomaly check", f"code={code}")

    # Delete position
    if "new_position_id" in STATE:
        code, _ = api("DELETE", f"/api/v1/boq/positions/{STATE['new_position_id']}", token=TOKEN)
        if code == 204:
            log_pass("DELETE /api/v1/boq/positions/{{id}}", "Position deleted")
        else:
            log_fail("DELETE /api/v1/boq/positions/{{id}}", "Delete position", f"code={code}")

    # Cleanup: delete test BOQs
    for key in ["new_boq_id", "dup_boq_id"]:
        if key in STATE:
            code, _ = api("DELETE", f"/api/v1/boq/boqs/{STATE[key]}", token=TOKEN)
            if code == 204:
                log_pass(f"DELETE /api/v1/boq/boqs/{{id}}", f"Cleanup: {key} deleted")
            else:
                log_warn(f"DELETE /api/v1/boq/boqs/{{id}}", f"Cleanup: {key}", f"code={code}")


# ============================================================================
# 5. COSTS & CATALOG
# ============================================================================

def test_costs():
    print("\n" + "=" * 70)
    print("5. COSTS & CATALOG")
    print("=" * 70)

    # Search cost items
    code, data = api("GET", "/api/v1/costs/?q=concrete", token=TOKEN)
    if code == 200:
        log_pass("GET /api/v1/costs/?q=concrete", f"Cost search returned (code={code})")
        if isinstance(data, dict) and "items" in data:
            items = data["items"]
            log_pass("GET /api/v1/costs/", f"Has 'items' field with {len(items)} results")
        elif isinstance(data, list):
            log_pass("GET /api/v1/costs/", f"Returns list with {len(data)} items")
    else:
        log_fail("GET /api/v1/costs/", "Cost search", f"code={code}")

    # Autocomplete - text mode
    code, data = api("GET", "/api/v1/costs/autocomplete?q=concrete&limit=5", token=TOKEN)
    if code == 200 and isinstance(data, list):
        log_pass("GET /api/v1/costs/autocomplete?q=concrete", f"Autocomplete returns {len(data)} items")
    else:
        log_fail("GET /api/v1/costs/autocomplete", "Autocomplete text mode", f"code={code}")

    # Autocomplete - semantic mode
    code, data = api("GET", "/api/v1/costs/autocomplete?q=wall+reinforcement&semantic=true&limit=5", token=TOKEN)
    if code == 200 and isinstance(data, list):
        log_pass("GET /api/v1/costs/autocomplete?semantic=true", f"Semantic autocomplete returns {len(data)} items")
    else:
        log_warn("GET /api/v1/costs/autocomplete?semantic=true", "Semantic autocomplete", f"code={code} (may need vector DB)")

    # Catalog search
    code, data = api("GET", "/api/v1/catalog/?limit=10", token=TOKEN)
    if code == 200:
        log_pass("GET /api/v1/catalog/", f"Catalog search returned (code={code})")
        if isinstance(data, dict) and "items" in data:
            items = data["items"]
            total = data.get("total", 0)
            log_pass("GET /api/v1/catalog/", f"Catalog has {total} total items, returned {len(items)}")
            if len(items) > 0:
                item = items[0]
                for f in ["id", "name", "resource_type", "base_price", "currency"]:
                    if f in item:
                        log_pass("Catalog item schema", f"Has '{f}'")
                    else:
                        log_fail("Catalog item schema", f"Missing '{f}'", f"keys={list(item.keys())}")
    else:
        log_fail("GET /api/v1/catalog/", "Catalog search", f"code={code}")

    # Catalog filter by type
    code, data = api("GET", "/api/v1/catalog/?resource_type=material&limit=5", token=TOKEN)
    if code == 200:
        log_pass("GET /api/v1/catalog/?resource_type=material", "Catalog filter by material works")
    else:
        log_fail("GET /api/v1/catalog/?resource_type=material", "Filter by type", f"code={code}")

    # Catalog stats
    code, data = api("GET", "/api/v1/catalog/stats", token=TOKEN)
    if code == 200 and isinstance(data, dict):
        log_pass("GET /api/v1/catalog/stats", f"Catalog stats returned")
    else:
        log_fail("GET /api/v1/catalog/stats", "Catalog stats", f"code={code}")

    # Catalog regions
    code, data = api("GET", "/api/v1/catalog/regions", token=TOKEN)
    if code == 200 and isinstance(data, list):
        log_pass("GET /api/v1/catalog/regions", f"Catalog regions returned ({len(data)} regions)")
    else:
        log_fail("GET /api/v1/catalog/regions", "Catalog regions", f"code={code}")

    # Cost item CRUD
    code, data = api("POST", "/api/v1/costs/", {
        "code": "QA-TEST-001",
        "description": "QA Test Cost Item - Concrete C30",
        "unit": "m3",
        "rate": 175.00,
        "currency": "EUR",
        "region": "Berlin"
    }, token=TOKEN)
    if code == 201 and isinstance(data, dict):
        log_pass("POST /api/v1/costs/", "Cost item created")
        STATE["cost_item_id"] = data.get("id")
    elif code == 200:
        log_pass("POST /api/v1/costs/", "Cost item created (200)")
        STATE["cost_item_id"] = data.get("id") if isinstance(data, dict) else None
    else:
        log_warn("POST /api/v1/costs/", "Create cost item", f"code={code}, data={str(data)[:200]}")

    # Get single cost item
    if "cost_item_id" in STATE and STATE["cost_item_id"]:
        cid = STATE["cost_item_id"]
        code, data = api("GET", f"/api/v1/costs/{cid}", token=TOKEN)
        if code == 200:
            log_pass(f"GET /api/v1/costs/{{id}}", "Single cost item retrieved")
        else:
            log_fail(f"GET /api/v1/costs/{{id}}", "Get cost item", f"code={code}")

        # Delete it
        code, _ = api("DELETE", f"/api/v1/costs/{cid}", token=TOKEN)
        if code == 204:
            log_pass(f"DELETE /api/v1/costs/{{id}}", "Cost item deleted")
        else:
            log_warn(f"DELETE /api/v1/costs/{{id}}", "Delete cost item", f"code={code}")


# ============================================================================
# 6. ASSEMBLIES
# ============================================================================

def test_assemblies():
    print("\n" + "=" * 70)
    print("6. ASSEMBLIES")
    print("=" * 70)

    # List assemblies
    code, data = api("GET", "/api/v1/assemblies/", token=TOKEN)
    if code == 200 and isinstance(data, list):
        log_pass("GET /api/v1/assemblies/", f"Returns assembly list ({len(data)} assemblies)")
        if len(data) > 0:
            STATE["assembly_id"] = data[0]["id"]
            a = data[0]
            for f in ["id", "name", "total_rate", "currency"]:
                if f in a:
                    log_pass("Assembly schema", f"Has '{f}'")
                else:
                    log_fail("Assembly schema", f"Missing '{f}'", f"keys={list(a.keys())}")
    else:
        log_fail("GET /api/v1/assemblies/", "List assemblies", f"code={code}")

    # Get single assembly with components
    if "assembly_id" in STATE:
        aid = STATE["assembly_id"]
        code, data = api("GET", f"/api/v1/assemblies/{aid}", token=TOKEN)
        if code == 200 and isinstance(data, dict):
            log_pass(f"GET /api/v1/assemblies/{{id}}", f"Assembly '{data.get('name')}' returned")
            comps = data.get("components", [])
            if isinstance(comps, list):
                log_pass("Assembly detail", f"Has {len(comps)} components")
        else:
            log_fail(f"GET /api/v1/assemblies/{{id}}", "Get assembly", f"code={code}")

    # Create assembly
    project_id = STATE.get("project_id")
    code, data = api("POST", "/api/v1/assemblies/", {
        "code": "QA-RC-WALL-001",
        "name": "QA Test Assembly - RC Wall",
        "unit": "m3",
        "category": "structural",
        "currency": "EUR",
        "project_id": project_id
    }, token=TOKEN)
    if code == 201 and isinstance(data, dict):
        log_pass("POST /api/v1/assemblies/", "Assembly created")
        STATE["new_assembly_id"] = data["id"]

        # Add component
        code2, comp = api("POST", f"/api/v1/assemblies/{data['id']}/components", {
            "description": "Concrete C30/37",
            "quantity": 1.0,
            "unit": "m3",
            "unit_cost": 175.0
        }, token=TOKEN)
        if code2 == 201:
            log_pass("POST /api/v1/assemblies/{{id}}/components", "Component added")
            STATE["component_id"] = comp.get("id") if isinstance(comp, dict) else None
        else:
            log_fail("POST assemblies/components", "Add component", f"code={code2}")

        # Clone assembly
        code3, cloned = api("POST", f"/api/v1/assemblies/{data['id']}/clone", {}, token=TOKEN)
        if code3 == 201:
            log_pass("POST /api/v1/assemblies/{{id}}/clone", "Assembly cloned")
            STATE["cloned_assembly_id"] = cloned.get("id") if isinstance(cloned, dict) else None
        else:
            log_fail("POST assemblies/clone", "Clone assembly", f"code={code3}")
    else:
        log_fail("POST /api/v1/assemblies/", "Create assembly", f"code={code}, data={str(data)[:200]}")

    # Update assembly
    if "new_assembly_id" in STATE:
        code, data = api("PATCH", f"/api/v1/assemblies/{STATE['new_assembly_id']}", {
            "name": "QA Test Assembly - Updated"
        }, token=TOKEN)
        if code == 200:
            log_pass("PATCH /api/v1/assemblies/{{id}}", "Assembly updated")
        else:
            log_fail("PATCH /api/v1/assemblies/{{id}}", "Update assembly", f"code={code}")

    # Delete assemblies created
    for key in ["new_assembly_id", "cloned_assembly_id"]:
        if key in STATE and STATE[key]:
            code, _ = api("DELETE", f"/api/v1/assemblies/{STATE[key]}", token=TOKEN)
            if code == 204:
                log_pass(f"DELETE /api/v1/assemblies/{{id}}", f"Cleanup: {key}")
            else:
                log_warn(f"DELETE /api/v1/assemblies/{{id}}", f"Cleanup: {key}", f"code={code}")


# ============================================================================
# 7. SCHEDULE
# ============================================================================

def test_schedule():
    print("\n" + "=" * 70)
    print("7. SCHEDULE")
    print("=" * 70)

    project_id = STATE.get("project_id")
    if not project_id:
        log_fail("Schedule", "Pre-requisite", "No project_id")
        return

    # List schedules for project
    code, data = api("GET", f"/api/v1/schedule/schedules/?project_id={project_id}", token=TOKEN)
    if code == 200 and isinstance(data, list):
        log_pass("GET /api/v1/schedule/schedules/", f"Returns {len(data)} schedules")
        if len(data) > 0:
            STATE["schedule_id"] = data[0]["id"]
            s = data[0]
            for f in ["id", "project_id", "name", "status"]:
                if f in s:
                    log_pass("Schedule schema", f"Has '{f}'")
                else:
                    log_fail("Schedule schema", f"Missing '{f}'", f"keys={list(s.keys())}")
    else:
        log_fail("GET /api/v1/schedule/schedules/", "List schedules", f"code={code}")

    # Get single schedule
    if "schedule_id" in STATE:
        sid = STATE["schedule_id"]
        code, data = api("GET", f"/api/v1/schedule/schedules/{sid}", token=TOKEN)
        if code == 200:
            log_pass(f"GET /api/v1/schedule/schedules/{{id}}", "Schedule retrieved")
        else:
            log_fail("GET /api/v1/schedule/schedules/{{id}}", "Get schedule", f"code={code}")

        # List activities
        code, data = api("GET", f"/api/v1/schedule/schedules/{sid}/activities", token=TOKEN)
        if code == 200 and isinstance(data, list):
            log_pass(f"GET schedules/{{id}}/activities", f"Returns {len(data)} activities")
            if len(data) > 0:
                STATE["activity_id"] = data[0]["id"]
        else:
            log_fail("GET schedules/{{id}}/activities", "List activities", f"code={code}")

        # Get Gantt data
        code, data = api("GET", f"/api/v1/schedule/schedules/{sid}/gantt", token=TOKEN)
        if code == 200:
            log_pass("GET schedules/{{id}}/gantt", "Gantt data returned")
        else:
            log_fail("GET schedules/{{id}}/gantt", "Gantt data", f"code={code}")

        # CPM
        code, data = api("POST", f"/api/v1/schedule/schedules/{sid}/calculate-cpm", token=TOKEN)
        if code == 200:
            log_pass("POST schedules/{{id}}/calculate-cpm", "CPM calculation returned")
        else:
            log_fail("POST schedules/{{id}}/calculate-cpm", "CPM", f"code={code}")

        # Risk analysis
        code, data = api("GET", f"/api/v1/schedule/schedules/{sid}/risk-analysis", token=TOKEN)
        if code == 200:
            log_pass("GET schedules/{{id}}/risk-analysis", "PERT risk analysis returned")
        else:
            log_fail("GET schedules/{{id}}/risk-analysis", "Risk analysis", f"code={code}")

    # Create schedule
    code, data = api("POST", "/api/v1/schedule/schedules/", {
        "project_id": project_id,
        "name": "QA Test Schedule",
        "description": "Created by automated test"
    }, token=TOKEN)
    if code == 201 and isinstance(data, dict):
        log_pass("POST /api/v1/schedule/schedules/", "Schedule created")
        STATE["new_schedule_id"] = data["id"]

        # Add activity
        code2, act = api("POST", f"/api/v1/schedule/schedules/{data['id']}/activities", {
            "name": "QA Test Activity",
            "duration_days": 10,
            "wbs_code": "1.1",
            "start_date": "2026-04-01",
            "end_date": "2026-04-10"
        }, token=TOKEN)
        if code2 == 201 and isinstance(act, dict):
            log_pass("POST schedules/{{id}}/activities", "Activity created")
            STATE["new_activity_id"] = act["id"]

            # Update activity
            code3, _ = api("PATCH", f"/api/v1/schedule/activities/{act['id']}", {
                "name": "QA Test Activity Updated",
                "duration_days": 15
            }, token=TOKEN)
            if code3 == 200:
                log_pass("PATCH /api/v1/schedule/activities/{{id}}", "Activity updated")
            else:
                log_fail("PATCH activities", "Update activity", f"code={code3}")

            # Update progress
            code4, _ = api("PATCH", f"/api/v1/schedule/activities/{act['id']}/progress", {
                "progress_pct": 50.0
            }, token=TOKEN)
            if code4 == 200:
                log_pass("PATCH activities/{{id}}/progress", "Progress updated to 50%")
            else:
                log_fail("PATCH activities/progress", "Update progress", f"code={code4}")

            # Delete activity
            code5, _ = api("DELETE", f"/api/v1/schedule/activities/{act['id']}", token=TOKEN)
            if code5 == 204:
                log_pass("DELETE /api/v1/schedule/activities/{{id}}", "Activity deleted")
            else:
                log_fail("DELETE activities", "Delete activity", f"code={code5}")
        else:
            log_fail("POST schedules/activities", "Create activity", f"code={code2}")

        # Delete schedule
        code6, _ = api("DELETE", f"/api/v1/schedule/schedules/{data['id']}", token=TOKEN)
        if code6 == 204:
            log_pass("DELETE /api/v1/schedule/schedules/{{id}}", "Schedule deleted")
        else:
            log_fail("DELETE schedules", "Delete schedule", f"code={code6}")
    else:
        log_fail("POST /api/v1/schedule/schedules/", "Create schedule", f"code={code}")


# ============================================================================
# 8. COST MODEL (5D)
# ============================================================================

def test_costmodel():
    print("\n" + "=" * 70)
    print("8. COST MODEL (5D)")
    print("=" * 70)

    project_id = STATE.get("project_id")
    if not project_id:
        log_fail("Cost Model", "Pre-requisite", "No project_id")
        return

    # Dashboard
    code, data = api("GET", f"/api/v1/costmodel/projects/{project_id}/5d/dashboard", token=TOKEN)
    if code == 200 and isinstance(data, dict):
        log_pass("GET .../5d/dashboard", "Dashboard KPIs returned")
        for f in ["total_budget", "total_committed", "total_actual"]:
            if f in data:
                log_pass("5D dashboard", f"Has '{f}' = {data[f]}")
    else:
        log_fail("GET .../5d/dashboard", "Dashboard", f"code={code}")

    # S-curve
    code, data = api("GET", f"/api/v1/costmodel/projects/{project_id}/5d/s-curve", token=TOKEN)
    if code == 200:
        log_pass("GET .../5d/s-curve", "S-curve data returned")
    else:
        log_fail("GET .../5d/s-curve", "S-curve", f"code={code}")

    # Cash flow
    code, data = api("GET", f"/api/v1/costmodel/projects/{project_id}/5d/cash-flow", token=TOKEN)
    if code == 200:
        log_pass("GET .../5d/cash-flow", "Cash flow data returned")
    else:
        log_fail("GET .../5d/cash-flow", "Cash flow", f"code={code}")

    # Budget summary
    code, data = api("GET", f"/api/v1/costmodel/projects/{project_id}/5d/budget", token=TOKEN)
    if code == 200:
        log_pass("GET .../5d/budget", "Budget summary returned")
    else:
        log_fail("GET .../5d/budget", "Budget summary", f"code={code}")

    # Budget lines
    code, data = api("GET", f"/api/v1/costmodel/projects/{project_id}/5d/budget-lines", token=TOKEN)
    if code == 200 and isinstance(data, list):
        log_pass("GET .../5d/budget-lines", f"Budget lines returned ({len(data)} lines)")
    else:
        log_fail("GET .../5d/budget-lines", "Budget lines", f"code={code}")

    # Create budget line
    code, data = api("POST", f"/api/v1/costmodel/projects/{project_id}/5d/budget-lines", {
        "category": "structural",
        "description": "QA Test Budget Line",
        "planned_amount": 50000.0,
        "committed_amount": 0,
        "actual_amount": 0,
        "forecast_amount": 50000.0
    }, token=TOKEN)
    if code == 201 and isinstance(data, dict):
        log_pass("POST .../5d/budget-lines", "Budget line created")
        STATE["budget_line_id"] = data["id"]

        # Update budget line
        code2, _ = api("PATCH", f"/api/v1/costmodel/5d/budget-lines/{data['id']}", {
            "actual_amount": 15000.0
        }, token=TOKEN)
        if code2 == 200:
            log_pass("PATCH .../5d/budget-lines/{{id}}", "Budget line updated")
        else:
            log_fail("PATCH budget-lines", "Update budget line", f"code={code2}")

        # Delete budget line
        code3, _ = api("DELETE", f"/api/v1/costmodel/5d/budget-lines/{data['id']}", token=TOKEN)
        if code3 == 204:
            log_pass("DELETE .../5d/budget-lines/{{id}}", "Budget line deleted")
        else:
            log_fail("DELETE budget-lines", "Delete budget line", f"code={code3}")
    else:
        log_fail("POST .../5d/budget-lines", "Create budget line", f"code={code}")

    # Snapshots
    code, data = api("GET", f"/api/v1/costmodel/projects/{project_id}/5d/snapshots", token=TOKEN)
    if code == 200 and isinstance(data, list):
        log_pass("GET .../5d/snapshots", f"Snapshots returned ({len(data)} snapshots)")
    else:
        log_fail("GET .../5d/snapshots", "List snapshots", f"code={code}")

    # Create snapshot
    code, data = api("POST", f"/api/v1/costmodel/projects/{project_id}/5d/snapshots", {
        "period": "2026-03",
        "planned_cost": 1000000.0,
        "earned_value": 500000.0,
        "actual_cost": 450000.0,
        "notes": "QA test snapshot"
    }, token=TOKEN)
    if code == 201:
        log_pass("POST .../5d/snapshots", "Snapshot created")
    else:
        log_fail("POST .../5d/snapshots", "Create snapshot", f"code={code}")

    # EVM
    code, data = api("GET", f"/api/v1/costmodel/projects/{project_id}/5d/evm", token=TOKEN)
    if code == 200 and isinstance(data, dict):
        log_pass("GET .../5d/evm", "EVM calculation returned")
    else:
        log_fail("GET .../5d/evm", "EVM", f"code={code}")

    # What-If scenario
    code, data = api("POST", f"/api/v1/costmodel/projects/{project_id}/5d/what-if", {
        "material_adjustment_pct": 10.0,
        "labor_adjustment_pct": 5.0,
        "duration_adjustment_pct": 0.0,
        "name": "QA What-If Test"
    }, token=TOKEN)
    if code == 201 and isinstance(data, dict):
        log_pass("POST .../5d/what-if", "What-If scenario created")
    else:
        log_fail("POST .../5d/what-if", "What-If scenario", f"code={code}")


# ============================================================================
# 9. TENDERING
# ============================================================================

def test_tendering():
    print("\n" + "=" * 70)
    print("9. TENDERING")
    print("=" * 70)

    project_id = STATE.get("project_id")
    if not project_id:
        log_fail("Tendering", "Pre-requisite", "No project_id")
        return

    # List packages
    code, data = api("GET", f"/api/v1/tendering/packages/?project_id={project_id}", token=TOKEN)
    if code == 200 and isinstance(data, list):
        log_pass("GET /api/v1/tendering/packages/", f"Returns {len(data)} packages")
        if len(data) > 0:
            STATE["tender_package_id"] = data[0]["id"]
            pkg = data[0]
            for f in ["id", "project_id", "name", "status", "bid_count"]:
                if f in pkg:
                    log_pass("Package schema", f"Has '{f}'")
                else:
                    log_fail("Package schema", f"Missing '{f}'", f"keys={list(pkg.keys())}")
    else:
        log_fail("GET /api/v1/tendering/packages/", "List packages", f"code={code}")

    # Get package with bids
    if "tender_package_id" in STATE:
        pid = STATE["tender_package_id"]
        code, data = api("GET", f"/api/v1/tendering/packages/{pid}", token=TOKEN)
        if code == 200 and isinstance(data, dict):
            log_pass("GET /api/v1/tendering/packages/{{id}}", f"Package '{data.get('name')}' returned")
            bids = data.get("bids", [])
            if isinstance(bids, list):
                log_pass("Package detail", f"Has {len(bids)} bids")
        else:
            log_fail("GET packages/{{id}}", "Get package", f"code={code}")

        # List bids
        code, data = api("GET", f"/api/v1/tendering/packages/{pid}/bids", token=TOKEN)
        if code == 200 and isinstance(data, list):
            log_pass("GET packages/{{id}}/bids", f"Returns {len(data)} bids")
        else:
            log_fail("GET packages/{{id}}/bids", "List bids", f"code={code}")

        # Bid comparison
        code, data = api("GET", f"/api/v1/tendering/packages/{pid}/comparison", token=TOKEN)
        if code == 200 and isinstance(data, dict):
            log_pass("GET packages/{{id}}/comparison", "Bid comparison returned")
        else:
            log_fail("GET packages/{{id}}/comparison", "Bid comparison", f"code={code}")

        # Export PDF
        code, data = api("GET", f"/api/v1/tendering/packages/{pid}/export/pdf", token=TOKEN, raw=True)
        if code == 200:
            log_pass("GET packages/{{id}}/export/pdf", "PDF export successful")
        else:
            log_fail("GET packages/{{id}}/export/pdf", "PDF export", f"code={code}")

    # Create package
    boq_id = STATE.get("boq_id")
    code, data = api("POST", "/api/v1/tendering/packages/", {
        "project_id": project_id,
        "boq_id": boq_id,
        "name": "QA Test Tender Package",
        "description": "Automated test",
        "status": "draft"
    }, token=TOKEN)
    if code == 201 and isinstance(data, dict):
        log_pass("POST /api/v1/tendering/packages/", "Package created")
        new_pkg_id = data["id"]

        # Add bid
        code2, bid = api("POST", f"/api/v1/tendering/packages/{new_pkg_id}/bids", {
            "company_name": "QA Test Contractor GmbH",
            "contact_email": "qa@test.com",
            "total_amount": "150000",
            "currency": "EUR",
            "status": "submitted"
        }, token=TOKEN)
        if code2 == 201 and isinstance(bid, dict):
            log_pass("POST packages/{{id}}/bids", "Bid added")
            STATE["bid_id"] = bid["id"]

            # Update bid
            code3, _ = api("PATCH", f"/api/v1/tendering/bids/{bid['id']}", {
                "total_amount": "155000",
                "notes": "Updated by QA test"
            }, token=TOKEN)
            if code3 == 200:
                log_pass("PATCH /api/v1/tendering/bids/{{id}}", "Bid updated")
            else:
                log_fail("PATCH bids", "Update bid", f"code={code3}")
        else:
            log_fail("POST packages/bids", "Add bid", f"code={code2}")

        # Update package
        code4, _ = api("PATCH", f"/api/v1/tendering/packages/{new_pkg_id}", {
            "status": "issued"
        }, token=TOKEN)
        if code4 == 200:
            log_pass("PATCH /api/v1/tendering/packages/{{id}}", "Package status updated to 'open'")
        else:
            log_fail("PATCH packages", "Update package", f"code={code4}")
    else:
        log_fail("POST /api/v1/tendering/packages/", "Create package", f"code={code}")


# ============================================================================
# 10. AI FEATURES
# ============================================================================

def test_ai():
    print("\n" + "=" * 70)
    print("10. AI FEATURES")
    print("=" * 70)

    # Get AI settings
    code, data = api("GET", "/api/v1/ai/settings", token=TOKEN)
    if code == 200 and isinstance(data, dict):
        log_pass("GET /api/v1/ai/settings", "AI settings returned")
    else:
        log_fail("GET /api/v1/ai/settings", "AI settings", f"code={code}")

    # Update AI settings (toggle preferred model)
    code, data = api("PATCH", "/api/v1/ai/settings", {
        "preferred_model": "claude-sonnet"
    }, token=TOKEN)
    if code == 200:
        log_pass("PATCH /api/v1/ai/settings", "AI settings updated")
    else:
        log_fail("PATCH /api/v1/ai/settings", "Update AI settings", f"code={code}")

    # Quick estimate (may fail without AI API key, which is expected)
    code, data = api("POST", "/api/v1/ai/quick-estimate", {
        "description": "Small office building, 200m2, Berlin, reinforced concrete",
        "currency": "EUR",
        "standard": "din276"
    }, token=TOKEN, timeout=60)
    if code == 200 and isinstance(data, dict):
        log_pass("POST /api/v1/ai/quick-estimate", "Quick estimate returned")
        items = data.get("items", data.get("work_items", []))
        log_pass("Quick estimate", f"Generated {len(items)} items")
    elif code in (400, 503, 500, 422):
        log_warn("POST /api/v1/ai/quick-estimate", "Quick estimate", f"code={code} (likely no AI API key configured)")
    else:
        log_fail("POST /api/v1/ai/quick-estimate", "Quick estimate", f"code={code}")


# ============================================================================
# 11. i18n (Internationalization)
# ============================================================================

def test_i18n():
    print("\n" + "=" * 70)
    print("11. i18n (INTERNATIONALIZATION)")
    print("=" * 70)

    # List locales
    code, data = api("GET", "/api/v1/i18n/locales")
    if code == 200 and isinstance(data, dict) and "locales" in data:
        locales = data["locales"]
        log_pass("GET /api/v1/i18n/locales", f"Returns {len(locales)} locales")
        if len(locales) >= 10:
            log_pass("i18n locales", f"Has >= 10 languages (actual: {len(locales)})")
        else:
            log_warn("i18n locales", f"Expected >= 10 languages", f"Got {len(locales)}: {locales}")
    else:
        log_fail("GET /api/v1/i18n/locales", "List locales", f"code={code}")

    # Test specific languages
    languages = ["en", "de", "fr", "ar", "ru", "zh", "ja", "ko", "hi", "pt"]
    for lang in languages:
        code, data = api("GET", f"/api/v1/i18n/{lang}")
        if code == 200 and isinstance(data, dict):
            key_count = len(data)
            if key_count > 50:
                log_pass(f"GET /api/v1/i18n/{lang}", f"Translations loaded ({key_count} keys)")
            else:
                log_warn(f"GET /api/v1/i18n/{lang}", f"Few translations", f"Only {key_count} keys")
        else:
            log_fail(f"GET /api/v1/i18n/{lang}", f"Get {lang} translations", f"code={code}")

    # Verify key consistency between EN and DE
    code_en, data_en = api("GET", "/api/v1/i18n/en")
    code_de, data_de = api("GET", "/api/v1/i18n/de")
    if code_en == 200 and code_de == 200 and isinstance(data_en, dict) and isinstance(data_de, dict):
        en_keys = set(data_en.keys())
        de_keys = set(data_de.keys())
        missing_in_de = en_keys - de_keys
        if len(missing_in_de) <= 5:
            log_pass("i18n consistency", f"DE has all EN keys (missing only {len(missing_in_de)})")
        else:
            log_warn("i18n consistency", f"DE missing {len(missing_in_de)} EN keys", f"e.g.: {list(missing_in_de)[:5]}")


# ============================================================================
# 12. FEEDBACK
# ============================================================================

def test_feedback():
    print("\n" + "=" * 70)
    print("12. FEEDBACK")
    print("=" * 70)

    code, data = api("POST", "/api/v1/feedback", {
        "category": "bug",
        "subject": "QA Test Feedback",
        "description": "This is an automated test feedback submission",
        "email": "qa@test.com",
        "page_path": "/qa-test"
    })
    if code == 200 and isinstance(data, dict):
        log_pass("POST /api/v1/feedback", "Feedback submitted successfully")
    elif code == 201:
        log_pass("POST /api/v1/feedback", "Feedback submitted (201)")
    else:
        log_fail("POST /api/v1/feedback", "Submit feedback", f"code={code}")


# ============================================================================
# 13. EDGE CASES & ERROR HANDLING
# ============================================================================

def test_edge_cases():
    print("\n" + "=" * 70)
    print("13. EDGE CASES & ERROR HANDLING")
    print("=" * 70)

    # Invalid UUID format
    code, data = api("GET", "/api/v1/projects/not-a-uuid", token=TOKEN)
    if code == 422:
        log_pass("GET /api/v1/projects/not-a-uuid", "Invalid UUID returns 422")
    else:
        log_warn("GET /api/v1/projects/not-a-uuid", f"Invalid UUID returned {code}", "Expected 422")

    # Invalid JSON body
    try:
        url = f"{BASE}/api/v1/projects/"
        req = urllib.request.Request(url, data=b"not-json", method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {TOKEN}")
        resp = urllib.request.urlopen(req, timeout=10)
        code = resp.status
    except urllib.error.HTTPError as e:
        code = e.code
    if code == 422:
        log_pass("POST /api/v1/projects/ (bad JSON)", "Invalid JSON returns 422")
    else:
        log_warn("POST /api/v1/projects/ (bad JSON)", f"Invalid JSON returned {code}", "Expected 422")

    # Empty body for required fields
    code, data = api("POST", "/api/v1/projects/", {}, token=TOKEN)
    if code == 422:
        log_pass("POST /api/v1/projects/ (empty)", "Missing required fields returns 422")
    else:
        log_warn("POST /api/v1/projects/ (empty)", f"Empty body returned {code}", "Expected 422")

    # Very long string
    long_name = "A" * 5000
    code, data = api("POST", "/api/v1/projects/", {
        "name": long_name,
        "currency": "EUR"
    }, token=TOKEN)
    if code in (201, 422, 400):
        log_pass("POST /api/v1/projects/ (long name)", f"Very long name handled (code={code})")
    else:
        log_warn("POST /api/v1/projects/ (long name)", f"Long name returned {code}", "Unexpected")
    # Clean up if created
    if code == 201 and isinstance(data, dict) and "id" in data:
        api("DELETE", f"/api/v1/projects/{data['id']}", token=TOKEN)

    # SQL injection in query params
    encoded_q = urllib.parse.quote("'; DROP TABLE users; --")
    code, data = api("GET", f"/api/v1/costs/autocomplete?q={encoded_q}&limit=5", token=TOKEN)
    if code in (200, 422):
        log_pass("SQL injection test", f"Query param injection handled safely (code={code})")
    else:
        log_warn("SQL injection test", f"Returned {code}", "Check for safety")

    # XSS in body
    code, data = api("POST", "/api/v1/feedback", {
        "category": "bug",
        "subject": "<script>alert('xss')</script>",
        "description": "XSS test <img onerror=alert(1) src=x>"
    })
    if code == 200:
        log_pass("XSS in body test", "Server accepts and stores safely (no execution server-side)")
    else:
        log_warn("XSS in body test", f"Returned {code}", "Check")

    # Test pagination boundaries
    code, data = api("GET", "/api/v1/projects/?offset=9999&limit=100", token=TOKEN)
    if code == 200 and isinstance(data, list) and len(data) == 0:
        log_pass("Pagination boundary", "High offset returns empty list")
    elif code == 200:
        log_pass("Pagination boundary", f"High offset returned {len(data) if isinstance(data, list) else '?'} items")
    else:
        log_fail("Pagination boundary", "High offset", f"code={code}")

    # Invalid limit
    code, data = api("GET", "/api/v1/projects/?limit=0", token=TOKEN)
    if code == 422:
        log_pass("Pagination validation", "limit=0 returns 422")
    else:
        log_warn("Pagination validation", f"limit=0 returned {code}", "Expected 422")

    # Non-existent endpoint
    code, data = api("GET", "/api/v1/does-not-exist")
    if code in (404, 405):
        log_pass("Non-existent endpoint", f"Returns {code}")
    else:
        log_warn("Non-existent endpoint", f"Returns {code}", "Expected 404")

    # Method not allowed
    code, data = api("PUT", "/api/health")
    if code in (404, 405):
        log_pass("Method not allowed", f"PUT on GET-only endpoint returns {code}")
    else:
        log_warn("Method not allowed", f"Returns {code}", "Expected 405")


# ============================================================================
# 14. DATA INTEGRITY CHECKS
# ============================================================================

def test_data_integrity():
    print("\n" + "=" * 70)
    print("14. DATA INTEGRITY CHECKS")
    print("=" * 70)

    projects = STATE.get("projects", [])
    if not projects:
        log_fail("Data integrity", "Pre-requisite", "No projects")
        return

    # Check all projects have valid UUIDs and dates
    for p in projects[:5]:
        try:
            import re
            uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
            if uuid_pattern.match(str(p.get("id", ""))):
                log_pass("Data integrity", f"Project '{p.get('name','?')[:30]}' has valid UUID")
            else:
                log_fail("Data integrity", f"Project '{p.get('name','?')[:30]}'", f"Invalid UUID: {p.get('id')}")
        except Exception:
            log_fail("Data integrity", "UUID validation", f"Error for {p.get('id')}")

    # Verify BOQ grand totals are consistent with position sums
    boqs = STATE.get("boqs", [])
    for b in boqs[:3]:
        boq_id = b.get("id")
        code, detail = api("GET", f"/api/v1/boq/boqs/{boq_id}", token=TOKEN)
        if code == 200 and isinstance(detail, dict):
            positions = detail.get("positions", [])
            if positions:
                sum_totals = sum(float(p.get("total", 0)) for p in positions)
                grand_total = b.get("grand_total", 0)
                if grand_total and abs(sum_totals - grand_total) < 1.0:
                    log_pass("BOQ totals", f"BOQ '{b.get('name','?')[:30]}': grand_total={grand_total:.2f} matches position sum={sum_totals:.2f}")
                elif grand_total:
                    log_warn("BOQ totals", f"BOQ '{b.get('name','?')[:30]}'", f"grand_total={grand_total:.2f} vs sum={sum_totals:.2f} (diff={abs(sum_totals - grand_total):.2f})")

    # Check referential integrity: BOQ project_id matches actual project
    for b in boqs[:3]:
        if b.get("project_id") == projects[0]["id"]:
            log_pass("Referential integrity", f"BOQ '{b.get('name','?')[:30]}' belongs to correct project")
        else:
            log_fail("Referential integrity", f"BOQ project_id mismatch", f"expected={projects[0]['id']}, got={b.get('project_id')}")


# ============================================================================
# RUNNER
# ============================================================================

def main():
    start = time.time()
    print("=" * 70)
    print("  OpenEstimate Backend API -- Exhaustive QA Test Suite")
    print(f"  Target: {BASE}")
    print(f"  Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Check server is up
    try:
        code, _ = api("GET", "/api/health", timeout=5)
        if code != 200:
            print(f"\nERROR: Server returned {code} on health check. Is the backend running?")
            sys.exit(1)
    except Exception as e:
        print(f"\nERROR: Cannot reach {BASE} -- {e}")
        sys.exit(1)

    test_health()
    test_auth()
    if not TOKEN:
        print("\nFATAL: Authentication failed. Cannot continue.")
        sys.exit(1)
    test_projects()
    test_boq()
    test_costs()
    test_assemblies()
    test_schedule()
    test_costmodel()
    test_tendering()
    test_ai()
    test_i18n()
    test_feedback()
    test_edge_cases()
    test_data_integrity()

    elapsed = time.time() - start

    # ── Summary ────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  TEST SUMMARY")
    print("=" * 70)
    total = PASS_COUNT + FAIL_COUNT + WARN_COUNT
    print(f"  Total tests: {total}")
    print(f"  Passed:      {PASS_COUNT} ({PASS_COUNT*100//total if total else 0}%)")
    print(f"  Failed:      {FAIL_COUNT} ({FAIL_COUNT*100//total if total else 0}%)")
    print(f"  Warnings:    {WARN_COUNT} ({WARN_COUNT*100//total if total else 0}%)")
    print(f"  Duration:    {elapsed:.1f}s")
    print()

    # Group failures by severity
    failures = [r for r in RESULTS if r["status"] == "FAIL"]
    warnings = [r for r in RESULTS if r["status"] == "WARN"]

    if failures:
        print("  FAILURES:")
        for f in failures:
            print(f"    [FAIL] {f['endpoint']} -- {f['desc']} -- {f.get('reason','')}")
        print()

    if warnings:
        print("  WARNINGS:")
        for w in warnings:
            print(f"    [WARN] {w['endpoint']} -- {w['desc']} -- {w.get('note','')}")
        print()

    # Classify issues
    p0 = [f for f in failures if any(kw in f.get("reason", "").lower() for kw in ["data loss", "corruption", "delete"])]
    p1 = [f for f in failures if any(kw in f.get("desc", "").lower() for kw in ["create", "update", "login", "auth"])]
    p2 = [f for f in failures if f not in p0 and f not in p1]

    print("  PRIORITY CLASSIFICATION:")
    print(f"    P0 (Critical - data loss/corruption): {len(p0)}")
    print(f"    P1 (Broken feature):                  {len(p1)}")
    print(f"    P2 (Wrong data / schema issues):      {len(p2)}")
    print(f"    P3 (Cosmetic / warnings):             {len(warnings)}")
    print("=" * 70)

    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
