# Security Audit Report

**Date**: 2026-04-09
**Scope**: Full backend security review
**Auditor**: Claude Code (automated)

---

## Executive Summary

**2 critical issues found and fixed. 5 medium issues documented. 7 areas passed.**

| Area | Findings | Status |
|------|----------|--------|
| Authentication bypass | 2 critical, 1 medium | 2 FIXED, 1 documented |
| SQL Injection | 0 | PASS |
| Data exposure | 2 medium | Documented |
| CORS configuration | 0 | PASS |
| Rate limiting | 1 medium | Documented |
| JWT security | 0 | PASS |
| Security headers | 0 | PASS |
| Path traversal (file serving) | 0 | PASS |
| Password security | 0 | PASS |

---

## 1. Authentication Bypass

### FINDING 1.1 -- Self-registration role escalation (CRITICAL -- FIXED)

**Severity**: CRITICAL
**Status**: FIXED
**File**: `backend/app/modules/users/service.py` line 163
**File**: `backend/app/modules/users/schemas.py` line 117

**Description**: The `UserCreate` schema accepts a `role` field with allowed values
`admin|manager|editor|viewer`. The `register()` service method used `data.role`
directly for non-first users. Any unauthenticated attacker could register with
`{"role": "admin"}` and gain full admin access.

**Attack**:
```bash
curl -X POST /api/v1/users/auth/register/ \
  -d '{"email":"attacker@evil.com","password":"Attack123","full_name":"X","role":"admin"}'
```

**Fix applied**: Changed `service.py` to always assign `"editor"` role for non-first
registrations, ignoring the client-supplied role. Admin promotion is only available
via the authenticated `PATCH /{user_id}` endpoint which requires `users.update`
permission.

```python
# BEFORE (vulnerable):
role = "admin" if user_count == 0 else data.role

# AFTER (fixed):
role = "admin" if user_count == 0 else "editor"
```

### FINDING 1.2 -- Unauthenticated data-modifying demo endpoints (CRITICAL -- FIXED)

**Severity**: CRITICAL
**Status**: FIXED
**File**: `backend/app/main.py` lines 566-645

**Description**: Three demo management endpoints had no authentication:
- `POST /api/demo/install/{demo_id}` -- creates projects + BOQ data
- `DELETE /api/demo/uninstall/{demo_id}` -- deletes projects
- `DELETE /api/demo/clear-all` -- deletes all demo projects

Any unauthenticated user could create or delete data in the database.

**Fix applied**: Added `Depends(get_current_user_id)` to all three endpoints.
The read-only `GET /api/demo/catalog` and `GET /api/demo/status` remain public
(they expose only static template metadata and boolean installed status).

### FINDING 1.3 -- Unauthenticated system info endpoints (MEDIUM)

**Severity**: MEDIUM
**Status**: Documented (not fixed -- may be intentional for monitoring)

The following endpoints require no authentication:
- `GET /api/system/status` -- reveals DB engine, AI providers, vector DB status, error messages
- `GET /api/system/modules` -- lists all loaded modules
- `GET /api/system/validation-rules` -- lists all validation rule sets
- `GET /api/system/hooks` -- lists all registered hooks/filters
- `GET /api/system/version-check` -- current version + update info
- `GET /api/v1/modules/` -- lists all modules with enabled/disabled status
- `GET /api/v1/modules/{name}` -- detailed module info

**Risk**: Information disclosure. An attacker can fingerprint the deployment,
identify which modules are installed, and learn the database engine and AI
provider configuration. The `system/status` endpoint on error can leak partial
database connection info via `str(exc)[:100]`.

**Recommendation**: Either require auth on these endpoints, or at minimum:
1. Remove `"error": str(exc)[:100]` from the system/status DB error case
2. Consider requiring auth for `system/status` and `system/hooks`

### FINDING 1.4 -- Photo file serving intentionally public (INFO)

**Severity**: INFO (documented per audit instructions)
**Status**: By design
**File**: `backend/app/modules/documents/router.py` line 329

The `GET /photos/{photo_id}/file/` endpoint serves photo files without
authentication. This is **intentionally public** (confirmed in audit
instructions). The endpoint does have path traversal protection (resolves
path and checks it starts within `PHOTO_BASE`).

Note: The document download endpoint `GET /{document_id}/download/` at line
582 DOES require auth via `CurrentUserId`. Only photos are public.

---

## 2. SQL Injection

**Status**: PASS

### Files scanned

All files using `from sqlalchemy import text`:
- `backend/app/main.py`
- `backend/app/core/sqlite_migrator.py`
- `backend/app/modules/project_intelligence/collector.py`
- `backend/app/modules/project_intelligence/advisor.py`
- `backend/app/modules/project_intelligence/actions.py`
- `backend/app/modules/bim_hub/router.py`
- `backend/app/modules/meetings/router.py`
- `backend/app/modules/punchlist/router.py`
- `backend/app/modules/takeoff/router.py`
- `backend/app/modules/documents/service.py`

### Results

**All raw SQL queries use parameterized bindings** (`:param` with params dict).

The one f-string SQL in `collector.py` line 233:
```python
f"FROM oe_boq_position WHERE boq_id IN ({placeholders})"
```
constructs `placeholders` from `f":bid{i}"` (bind parameter names from a
loop counter) -- **safe**. The actual values are passed via the `params` dict.

The SQLite migrator (`sqlite_migrator.py` line 61) builds DDL via f-string:
```python
sql = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type} ...'
```
Table/column names come from SQLAlchemy model metadata (developer-controlled),
not user input -- **safe**.

No instances of `text("..." + variable)` or `text(f"...{user_input}...")` found.

---

## 3. Data Exposure

### FINDING 3.1 -- UserResponse does NOT leak password hash (PASS)

**File**: `backend/app/modules/users/schemas.py` line 174

`UserResponse` schema includes: `id, email, full_name, role, locale, is_active,
last_login_at, timezone, measurement_system, paper_size, number_format,
date_format, currency_code, created_at, updated_at`.

No `password_hash`, `hashed_password`, or `metadata_` fields exposed. **PASS**.

### FINDING 3.2 -- Photo file_path properly blanked (PASS)

**File**: `backend/app/modules/documents/router.py` line 176

The `_photo_to_response()` helper explicitly sets `file_path=""` -- never
exposes the server filesystem path. **PASS**.

### FINDING 3.3 -- DocumentResponse does NOT include file_path (PASS)

The `DocumentResponse` schema does not have a `file_path` field. The
`_doc_to_response()` helper does not map the ORM `file_path` into the response. **PASS**.

### FINDING 3.4 -- System status error leak (MEDIUM)

**Severity**: MEDIUM
**File**: `backend/app/main.py` line 419

```python
result["database"] = {"status": "error", "error": str(exc)[:100]}
```

Database exception messages can contain connection strings, hostnames, or
credentials in some edge cases. Truncating to 100 chars helps but does not
eliminate the risk.

**Recommendation**: Replace with a generic error message:
```python
result["database"] = {"status": "error"}
```

### FINDING 3.5 -- PhotoResponse schema has file_path field (LOW)

**Severity**: LOW
**File**: `backend/app/modules/documents/schemas.py` line 123

The `PhotoResponse` schema declares `file_path: str = ""`. While the router
always sends `""`, the schema itself documents the field's existence. If any
future code path forgets to blank it, server paths would leak.

**Recommendation**: Remove `file_path` from `PhotoResponse` entirely, or add
a validator that forces it to `""`.

---

## 4. CORS Configuration

**Status**: PASS

**File**: `backend/app/main.py` lines 214-229

- In production: wildcard `*` origins are explicitly blocked (lines 216-221)
- Falls back to `https://openconstructionerp.com` if all origins are wildcards
- `allow_credentials=True` is set (required for JWT bearer auth)
- Allowed methods are explicitly listed (no blanket `*`)
- Allowed headers are explicitly listed

**Development default** (`config.py` line 43):
`allowed_origins = "http://localhost:5173"` -- appropriate for local Vite dev server.

---

## 5. Rate Limiting

### FINDING 5.1 -- Login rate limiting (PASS)

**File**: `backend/app/modules/users/router.py` lines 95-102
**File**: `backend/app/core/rate_limiter.py`

Login endpoint uses `login_limiter.is_allowed(client_ip)` with configurable
`LOGIN_RATE_LIMIT` (default: 10 per minute per IP). Returns HTTP 429 with
`Retry-After: 60` header. **PASS**.

### FINDING 5.2 -- Feedback endpoint has no rate limiting (MEDIUM)

**Severity**: MEDIUM
**File**: `backend/app/main.py` line 674

`POST /api/v1/feedback` has no authentication and no rate limiting. An
attacker can flood the database with spam feedback entries.

**Recommendation**: Add `api_limiter.is_allowed(client_ip)` check, or require
authentication.

### FINDING 5.3 -- AI rate limiting (PASS)

**File**: `backend/app/dependencies.py` lines 207-222

AI endpoints use `check_ai_rate_limit` dependency which checks
`ai_limiter.is_allowed(user_id)`. Default: 10 requests per minute per user.

### FINDING 5.4 -- In-memory rate limiter resets on restart (LOW)

**Severity**: LOW
**File**: `backend/app/core/rate_limiter.py`

Rate limits use in-memory `dict` storage. A server restart clears all limits.
Horizontal scaling (multiple workers) means each process has independent
counters. An attacker could bypass limits by exploiting restarts.

**Recommendation**: Document this. For production, the Redis-based rate limiter
mentioned in the code comments should be implemented.

---

## 6. JWT Security

**Status**: PASS

### Token configuration

| Setting | Value | Assessment |
|---------|-------|------------|
| Algorithm | HS256 | Acceptable for single-service arch |
| Access token expiry | 60 minutes | Reasonable |
| Refresh token expiry | 30 days | Standard |
| Reset token expiry | 15 minutes | Good |
| Default dev secret | `openestimate-local-dev-key` | Blocked in production (see below) |

### Production secret validation (PASS)

**File**: `backend/app/main.py` lines 718-726

On startup, if `jwt_secret` is an insecure default AND `app_env == "production"`,
the app raises `RuntimeError` and refuses to start. In development, a warning
is logged.

### Token type validation (PASS)

- Refresh endpoint checks `payload.get("type") != "refresh"` (line 264)
- Reset password checks `payload.get("type") != "reset"` (line 346)
- Token reuse across types is prevented

### Password change invalidates tokens (PASS)

**File**: `backend/app/dependencies.py` lines 108-139

`get_current_user_payload()` checks `iat` vs `password_changed_at`. Tokens
issued before a password change are rejected. Excellent defense against
stolen token persistence.

---

## 7. Security Headers

**Status**: PASS

**File**: `backend/app/middleware/security_headers.py`

| Header | Value | Assessment |
|--------|-------|------------|
| X-Frame-Options | DENY | Prevents clickjacking |
| X-Content-Type-Options | nosniff | Prevents MIME sniffing |
| Referrer-Policy | same-origin | Prevents referrer leakage |
| Permissions-Policy | geolocation=(), microphone=(), camera=() | Restricts browser features |
| Content-Security-Policy | Restrictive (see below) | Prevents XSS |
| HSTS | max-age=31536000; includeSubDomains | HTTPS enforcement (only over HTTPS) |

CSP allows `'unsafe-inline'` and `'unsafe-eval'` for script-src, which is
necessary for the React SPA but weakens XSS protection. This is standard
for SPAs and is mitigated by other controls.

---

## 8. Path Traversal (File Serving)

**Status**: PASS

All file-serving endpoints implement path traversal protection:

- **Photos** (`documents/router.py` line 338-344): Resolves path, checks
  `startswith(PHOTO_BASE)`, rejects symlinks
- **Documents** (`documents/router.py` line 590-600): Resolves path, checks
  `startswith(UPLOAD_BASE)`, rejects symlinks
- **Takeoff** (`takeoff/router.py` line 1965-1972): Resolves path, checks
  `startswith(allowed_base)`, rejects symlinks
- **BIM geometry** (`bim_hub/router.py` line 716-749): Constructs path from
  DB model fields (project_id/model_id), never from user input

---

## 9. Password Security

**Status**: PASS

- Bcrypt with 12 rounds (`service.py` line 60)
- Password strength validation: 8+ chars, at least one letter + one digit
- Common password blocklist (24 entries)
- Timing-safe comparison for non-existent users (dummy bcrypt check, line 195)
- HTML sanitization on `full_name` field (prevents stored XSS)

---

## Summary of Changes Made

| File | Change | Severity Fixed |
|------|--------|----------------|
| `backend/app/modules/users/service.py` | Hardcoded `"editor"` role for self-registration | CRITICAL |
| `backend/app/main.py` | Added auth to `POST /api/demo/install`, `DELETE /api/demo/uninstall`, `DELETE /api/demo/clear-all` | CRITICAL |
| `backend/app/main.py` | Added import for `Depends` and `get_current_user_id` | Supporting change |

## Remaining Recommendations (by priority)

1. **MEDIUM**: Add auth or rate limiting to `POST /api/v1/feedback`
2. **MEDIUM**: Add auth to `GET /api/system/status` or remove error detail from DB check
3. **MEDIUM**: Consider auth for `GET /api/v1/modules/` and system introspection endpoints
4. **LOW**: Remove `file_path` field from `PhotoResponse` schema entirely
5. **LOW**: Implement Redis-backed rate limiter for production multi-worker deployments
6. **LOW**: Remove `role` field from `UserCreate` schema (it is now ignored in the service layer, but its presence in the schema is misleading)
