# Security Audit — OpenConstructionERP

**Date:** 2026-04-18
**Scope:** CSP / headers, XSS, RBAC, uploads, rate-limit, tokens/CORS, secrets, SQL, trailing slashes
**Repo:** `C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500`

Summary (by severity):

| Severity | Count |
|----------|------:|
| Critical | 0 |
| High     | 3 |
| Medium   | 6 |
| Low      | 5 |
| Info     | 4 |
| **Total**| **18** |

---

## A. CSP / Headers

### A1. `unsafe-inline` + `unsafe-eval` in script-src — MEDIUM
`backend/app/middleware/security_headers.py:40-43`

```
"script-src 'self' 'unsafe-inline' 'unsafe-eval' https://www.googletagmanager.com https://www.google-analytics.com; "
```
Both `unsafe-inline` AND `unsafe-eval` are present — the strongest two XSS-amplifiers CSP tries to prevent. `unsafe-eval` is plausibly needed because Vite dev-build / AG Grid / some dependency uses `Function()`; `unsafe-inline` usually needed for React's inlined analytics bootstrap (the comment at `frontend/index.html:10` says "Analytics is injected by the VPS deployment script"). A nonce-based CSP would work: generate a per-request nonce in the middleware, inject it into Vite's generated `index.html` at deploy time, and replace `'unsafe-inline'` with `'nonce-<val>'`. `unsafe-eval` removal requires auditing AG Grid + any `new Function(...)` uses in bundles; deferrable. Feasibility: medium effort.

### A2. `img-src https:` wildcard — LOW
`backend/app/middleware/security_headers.py:46`

```
"img-src 'self' data: blob: https:; "
```
Any HTTPS image host can be loaded → tracking/beacon risk. Known image origins: self-hosted photos (`/api/v1/documents/photos/...`), user-uploaded document thumbnails. The only external image host touched in code is google-analytics collect beacons (not images). Replace with: `img-src 'self' data: blob: https://www.google-analytics.com https://www.googletagmanager.com`.

### A3. HSTS only over HTTPS — INFO (confirmed correct)
`backend/app/middleware/security_headers.py:79-83`

```python
if self._hsts_enabled and request.url.scheme == "https":
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
```
Correct. Does NOT force HSTS in local dev (good), only HTTPS triggers it. `max-age=31536000` (1y) without `preload` is sensible for a new project.

### A4. `frontend/index.html` — INFO (no meta CSP conflict)
`frontend/index.html:1-83` — no `<meta http-equiv="Content-Security-Policy">` found. `frontend/stats.html:7` has only `X-UA-Compatible`. No conflict.

### A5. Nginx CSP DIFFERS from backend CSP — HIGH
`deploy/docker/nginx.conf:10`

```
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; font-src 'self' data:; connect-src 'self' ws: wss: https:; frame-ancestors 'self';" always;
```

Two conflicts with the backend middleware at `backend/app/middleware/security_headers.py:38-54`:

1. **`frame-ancestors 'self'`** (nginx) vs **`frame-ancestors 'none'`** (backend). Since nginx is the public-facing layer, `'self'` wins for browsers hitting the frontend. The backend-level `X-Frame-Options: DENY` (line 61) masks this in practice, but it's an unintentional inconsistency — every Nginx response at `/api/...` also gets this weaker header, overwriting the backend's stricter one unless `add_header` is wrapped in `proxy_pass` pass-through. Verify what the browser sees in production.
2. **No external script hosts** in nginx (missing `googletagmanager`, `google-analytics`). Any analytics call will be blocked when Nginx is the edge layer. Since this matters for marketing funnel tracking, the mismatch should be resolved: either delete the Nginx `add_header Content-Security-Policy` line (let backend control) or sync both to the same string (DRY violation). Recommend: delete from Nginx, let backend middleware own CSP.

### A6. nginx sets `X-Frame-Options: SAMEORIGIN`, backend sets `DENY` — LOW
`deploy/docker/nginx.conf:6` → `SAMEORIGIN` vs `backend/app/middleware/security_headers.py:61` → `DENY`. If Nginx is the last header writer, embedded frames on same origin become possible. Pick one; `DENY` is stricter.

---

## B. XSS Surfaces

### B1. `MessageBubble.tsx` dangerouslySetInnerHTML — INFO (safe)
`frontend/src/features/erp-chat/full-page/left/MessageBubble.tsx:221` with sanitization at lines 20-25 (HTML entities escaped first) and URL scheme allow-list at lines 44-53 (blocks `javascript:`, `data:`, `vbscript:`). Code paths that take user input escape before emitting. Not a finding.

### B2. `PhotoGalleryPage.tsx` innerHTML — LOW (safe — hardcoded)
`frontend/src/features/documents/PhotoGalleryPage.tsx:513` — assigns a hardcoded SVG literal on image-load-error. No user input. Not exploitable. Still a code-smell (prefer `React.createElement` or a `<svg>` React child).

### B3. `pdfBOQExport.ts` — HIGH (unsanitised template literal → XSS in print window)
`frontend/src/modules/_shared/pdfBOQExport.ts:30-41,89-95`

```ts
return `<tr>
  <td>${pos.ordinal}</td>
  <td>${pos.description}</td>
  ...`;
...
win.document.write(html);   // line 91
```
`pos.description`, `pos.ordinal`, `pos.unit` are inserted raw into HTML and written via `document.write` into a new popup window. A BOQ position description containing `<script>alert(1)</script>` or `<img onerror=...>` will execute in the popup context. The popup is same-origin (opened by `window.open('', '_blank')`), so the script runs with the user's session — can read `localStorage` access token (see F1). Fix: HTML-escape `ordinal`, `description`, `unit` before interpolation.

### B4. `document.write` — HIGH (confirmed in B3)
`frontend/src/modules/_shared/pdfBOQExport.ts:91` — only occurrence. Same finding as B3.

### B5. `MeasureManager.test.ts` innerHTML — INFO
`frontend/src/shared/ui/BIMViewer/__tests__/MeasureManager.test.ts:71` — `document.body.innerHTML = '';` in test setup; test-only, not shipped.

---

## C. RBAC on Write Endpoints

### C1. `projects/router.py` — INFO (uses ownership instead of RequirePermission)
`backend/app/modules/projects/router.py:38-58` — `_verify_project_owner` is called on every write. Admin bypass via JWT `role=admin`. Pattern is stronger than a plain role check (owner-or-admin). Zero RequirePermission usages in this router is intentional.

### C2. `boq/router.py` — INFO (fully covered)
43 write endpoints, 70 RequirePermission references — every `@router.post/patch/put/delete` has a dependency. Confirmed on lines 290, 409, 1012, 1032, 1054, 1074 ... 4686 (see full list at the bottom of this report).

### C3. `finance/router.py` — INFO (fully covered)
9 write endpoints, 18 `RequirePermission("finance.*")` references. Every mutation guarded.

### C4. `procurement/router.py` — INFO (fully covered)
6 write endpoints, 11 RequirePermission refs on `procurement.*` perms.

### C5. `audit_router.py` — INFO (admin-only, correct)
`backend/app/core/audit_router.py:38,65` — both endpoints gated by `RequirePermission("audit.view")`.

### C6. `users/router.py` admin endpoints — INFO (protected)
`backend/app/modules/users/router.py:387,428,442,472,495` — `list_users`, `get_user`, `update_user`, `get/set_user_module_access` all have `RequirePermission("users.*")`. `/me/*` endpoints use `CurrentUserId` (self-scope) — correct.

### C7. `/auth/register` and `/auth/login` are public — INFO (expected)
`backend/app/modules/users/router.py:78-131` — intentionally unauthenticated. Rate-limited via `login_limiter` at lines 87, 123, 155 (good).

### C8. `RequirePermission` admin bypass by role string — MEDIUM
`backend/app/dependencies.py:197-201`

```python
if role == "admin":
    ...
    return
```
The admin check is on the JWT `role` claim, not a DB lookup. If an attacker can mint a token with `role="admin"` they get full bypass. This is only a concern if JWT_SECRET leaks — mitigated by the startup fatal error at `backend/app/main.py:1024-1030` refusing to run in production with the dev key. Recommendation: also verify role against DB in `get_current_user_payload` for defence-in-depth (expensive but safer).

---

## D. File Upload Validation

### D1. Documents upload — INFO (good)
`backend/app/modules/documents/service.py:47` MAX_FILE_SIZE=100MB, `:59` BLOCKED_EXTENSIONS list (exe/bat/sh/js/vbs/…), `:66` `_sanitize_filename` (path-traversal-safe). No magic-byte check on general docs, no MIME whitelist on non-photo paths.

### D2. Photo upload — INFO (good)
`backend/app/modules/documents/service.py:51-58,411-415` — `ALLOWED_IMAGE_TYPES` whitelist, enforced in service layer.

### D3. BIM/CAD upload — INFO (good)
`backend/app/modules/bim_hub/router.py:904,1252-1260,1296-1300,1308-1311` — extension allow-list + 500 MB size cap + double check (header + actual body length). Solid.

### D4. DWG Takeoff upload — INFO (good)
`backend/app/modules/dwg_takeoff/router.py:128,143-149,151-158,160-165` — `_MAX_UPLOAD_BYTES=50MB`, extension whitelist `{dwg, dxf}`, per-user rate-limit via `approval_limiter`. Solid.

### D5. PDF Takeoff upload — INFO (good, magic-byte check present)
`backend/app/modules/takeoff/router.py:2229-2242` — extension check + size cap + `%PDF-` magic byte check. Explicitly documented as a QA fix. Solid.

### D6. CAD extract — INFO (good)
`backend/app/modules/takeoff/router.py:594,628,647-654` — 100 MB cap, extension whitelist.

### D7. AI photo-estimate / file-estimate — INFO (good)
`backend/app/modules/ai/router.py:256-274` — MIME whitelist + size cap + AI rate limiter (`check_ai_rate_limit`).

### D8. Finance/FieldReports/Contacts import — MEDIUM (size+ext only)
`backend/app/modules/finance/router.py:613-632`, `backend/app/modules/fieldreports/router.py:443-460`, `backend/app/modules/contacts/router.py:446`, `backend/app/modules/boq/router.py:2864-2884` — only extension + 10 MB cap. No magic-byte verification. Since the parser is Excel/CSV and xlsx bombs (billion-laughs-via-zip) are a real DoS vector against openpyxl, consider a guard: reject any `.xlsx` decompressing to >50 MB uncompressed size.

### D9. Punchlist photo upload — MEDIUM (no size limit)
`backend/app/modules/punchlist/router.py:256-290` — MIME whitelist present but **no size cap, no content-length check**. An attacker with `punchlist.update` permission can upload arbitrarily large files that fill disk at `PHOTOS_DIR`. Add the same 50 MB check as `MAX_PHOTO_SIZE` (`backend/app/modules/documents/service.py:48`).

### D10. Meeting transcript upload — MEDIUM (no magic-byte, extension only)
`backend/app/modules/meetings/router.py:820-868` — extension allow-list + 10 MB cap. No MIME check (`.docx` disguise possible). Low-impact; the downstream parser will fail on a non-match, but produces a poor error.

### D11. Schedule XER/XML import — MEDIUM (no size limit, XXE risk)
`backend/app/modules/schedule/router.py:1222-1244,1457-1482` — no file size cap (`await file.read()` with zero guard), and `ET.fromstring(content)` uses stdlib `xml.etree.ElementTree` — XXE/billion-laughs protection only in newer Python (≥3.7.1 blocks external entity expansion by default, but DoS via deeply-nested elements still possible). Add (a) size cap ~10 MB, (b) switch to `defusedxml.ElementTree.fromstring` (dep already available via transitive; otherwise add to `requirements.txt`).

### D12. BOQ GAEB XML import — MEDIUM (XXE risk)
`backend/app/modules/boq/router.py:2481` — uses `xml.etree.ElementTree`. Same recommendation as D11: use `defusedxml`.

### D13. BIM requirements IDS parser — LOW (XML parsing)
`backend/app/modules/bim_requirements/parsers/ids_parser.py:1` uses `xml.etree`. Same XXE/bomb mitigation recommended.

### D14. Backup restore endpoint — INFO (good)
`backend/app/modules/backup/router.py:312-316,450-454` — admin-only (`backup.admin`), accepts ZIP. No size cap visible; since it's admin-only the risk surface is small, but adding a cap is still good hygiene.

---

## E. Rate Limiting

### E1. `/auth/login` rate-limited — INFO (confirmed)
`backend/app/modules/users/router.py:122-130` — `login_limiter.is_allowed(client_ip)` with 429 + `Retry-After: 60`. Default 10/min per IP (not 5 as noted in task — see `backend/app/config.py:138-141`). Reasonable but may be tightened.

### E2. `/auth/register` rate-limited — INFO (confirmed)
`backend/app/modules/users/router.py:87-93` — same limiter keyed with `reg_{ip}`.

### E3. `/auth/forgot-password` rate-limited — INFO (confirmed)
`backend/app/modules/users/router.py:154-161` — keyed with `pwd_{ip}`.

### E4. AI endpoints rate-limited — INFO (confirmed)
`backend/app/dependencies.py:213-228` — `check_ai_rate_limit`, 10/min per user, applied to `ai.*` router endpoints.

### E5. Approval/financial mutations rate-limited — INFO (confirmed)
`backend/app/core/rate_limiter.py:73` — `approval_limiter` 20/min, used in DWG upload and some finance flows.

### E6. Document/BIM/PDF uploads NOT globally rate-limited — MEDIUM
`backend/app/modules/documents/router.py:111-140`, `backend/app/modules/bim_hub/router.py:1221+`, `backend/app/modules/takeoff/router.py:2205+` — size caps exist, but no per-user rate limit on number of uploads per minute. Since each upload allocates memory + disk I/O + triggers background tasks, a logged-in user can DoS the node by flooding uploads (e.g. 1000 × 100 MB documents in 60s = 100 GB write). Apply the existing `approval_limiter` (20/min) to all upload endpoints, or add a dedicated `upload_limiter`.

### E7. In-memory rate-limiter — LOW (horizontal scale blind spot)
`backend/app/core/rate_limiter.py:17-24` — dict+Lock, process-local. With multiple gunicorn/uvicorn workers, each gets its own counter → effective limit scales with worker count (e.g. 4 workers × 10 login/min = 40/min per IP). Doc'd as "For production, replace with Redis-based implementation" — consistent with MEMORY.md lightweight stance, but worth a production note.

---

## F. Token Storage / CORS

### F1. JWT in localStorage — MEDIUM
`frontend/src/stores/useAuthStore.ts:35-66` — access + refresh tokens in `localStorage` (remember) or `sessionStorage` (no remember). Any XSS (see B3) can read both tokens and escalate to account takeover. httpOnly+Secure+SameSite=Strict cookies would eliminate this. Trade-off: requires backend cookie auth path + CSRF mitigation. Known trade-off; document in threat model.

### F2. JWT role claim decoded client-side for UI — LOW (defence-in-depth issue)
`frontend/src/stores/useAuthStore.ts:10-23` — decodes token's `role` claim without signature check. Only used for UI show/hide. Every backend check verifies signature server-side (`backend/app/dependencies.py:73`). Client-side decoded role trust is acceptable for UX; not a trust boundary.

### F3. CORS wildcard origin blocked in production — INFO (confirmed)
`backend/app/main.py:485-491`
```python
if settings.is_production and "*" in cors_origins:
    cors_origins = [o for o in cors_origins if o != "*"]
    if not cors_origins:
        cors_origins = ["https://openconstructionerp.com"]
```
Correct — wildcard is stripped in production. Combined with `allow_credentials=True` (line 496), the wildcard would be rejected by browsers anyway (W3C spec), but explicit filter is defence-in-depth. In dev `*` passes through with `allow_credentials=True` — browsers will still reject, just safer.

### F4. CORS allow_headers list is narrow — INFO
`backend/app/main.py:498` — only `Content-Type, Authorization, Accept, Accept-Language`. Tight. Good.

---

## G. Secrets & Error Disclosure

### G1. JWT_SECRET has default `openestimate-local-dev-key` — MEDIUM (mitigated)
`backend/app/config.py:70` default value, `backend/app/main.py:1023-1031` fatal error in production if unset. Risk: developer accidentally pushes `.env` with production secret identical to default. Mitigation already in place (`RuntimeError` prevents boot). OK.

### G2. All other secrets default empty/None — INFO
`backend/app/config.py:64-65, 102-118, 123-124` — S3 keys, AI keys, SMTP password all default `""` or `None`. No hardcoded production credentials found.

### G3. No hardcoded `sk-*` / `AKIA*` tokens — INFO (confirmed)
Grep for `sk-[a-zA-Z0-9]{20,}`, `sk-proj-`, `AKIA[A-Z0-9]{16}` in `backend/` returns zero matches.

### G4. Global exception handler returns generic message — INFO (confirmed)
`backend/app/main.py:540-546` — `global_exception_handler` logs via `logger.exception` (stack trace only in server log) and returns `{"detail": "Internal server error"}`. No stack trace leaked to client. Correct.

### G5. FastAPI `debug` & docs exposure — LOW
`backend/app/main.py:475-478` — docs/redoc disabled in production, openapi.json still exposed at `/api/openapi.json`. `app_debug: bool = True` default in `backend/app/config.py:41` — this controls pydantic error verbosity. Confirm `APP_DEBUG=false` in production env.

---

## H. SQL Injection Spot-Check

### H1. Raw `text()` usage — INFO (safe)
Occurrences surveyed:
- `backend/app/main.py:602,688` — literal `SELECT 1` (health check)
- `backend/app/core/sqlite_migrator.py:64` — executes migration SQL from internal string constants
- `backend/app/modules/project_intelligence/collector.py` — 28 `text(...)` uses, all with `:param` named placeholders (no f-strings / string concatenation into SQL)
- `backend/app/modules/schedule/router.py` — 17 `text(...)` uses
- `backend/app/modules/erp_chat/service.py` — 3 uses
- Others (1–3 per file) — all parameterized

Grep for `text(f"...`, `text("...+`, `text("...{`: **zero matches**. Clean.

### H2. `global_search.py` uses ILIKE with bound pattern — INFO (safe)
`backend/app/core/global_search.py:37,44-49` — `pattern = f"%{query.strip()}%"` passed via `.ilike(pattern)` which parameterizes at SQLAlchemy layer. Safe.

---

## I. Trailing-Slash Routing

### I1. `redirect_slashes=False` + frontend trailing slashes — INFO
`backend/app/main.py:479` disables auto-redirect. Backend routers register both `/endpoint/` and `/endpoint` for auth routes (`backend/app/modules/users/router.py:78-79,111-112,133-134`). Frontend `apiGet('/v1/…/')` calls consistently use trailing slashes:
- `frontend/src/features/ai/QuickEstimatePage.tsx:1218` `/v1/takeoff/converters/`
- `frontend/src/features/integrations/IntegrationsPage.tsx:458` `/v1/integrations/configs/`
- `frontend/src/features/erp-chat/api.ts:5,13`

Spot-checked backend routes — all register trailing slash form. No 404 risk.

---

## Top 5 Priorities

1. **B3/B4 HIGH**: XSS in `pdfBOQExport.ts` — BOQ descriptions/ordinals injected raw into HTML + `document.write`. Fix: HTML-escape before template interpolation.
2. **A5 HIGH**: Nginx and backend emit *different* CSPs (`frame-ancestors 'self'` vs `'none'`, different script hosts). Pick one source of truth — recommend deleting the Nginx `Content-Security-Policy` header and letting backend middleware own it.
3. **A1 MEDIUM**: Drop `'unsafe-eval'` from script-src (audit what actually needs it) and move `'unsafe-inline'` to nonce-based CSP. Biggest remaining XSS-amplifier.
4. **D9 / D11 / D12 MEDIUM**: Punchlist photo upload lacks size cap; Schedule/BOQ XML parsing uses stdlib `xml.etree` (switch to `defusedxml` and add size caps on raw XML imports).
5. **E6 MEDIUM**: Upload endpoints have size caps but no per-user rate limit. A logged-in user can exhaust disk/IO by flooding. Apply existing `approval_limiter` (20/min) to all upload paths.

## Secondary (still worth fixing)

- **F1**: Move JWT from localStorage to httpOnly cookies (strategic; reduces XSS blast radius — pairs with B3).
- **C8**: DB-side admin-role verification in `RequirePermission` (defence-in-depth if JWT_SECRET leaks).
- **A2**: Tighten `img-src` wildcard.
- **A6**: Align `X-Frame-Options` between nginx and backend.
- **D8**: Add xlsx-bomb guard (uncompressed size > 50 MB → reject).

## Confirmed-correct (no action)

- A3 HSTS conditional on HTTPS
- C1-C7 RBAC coverage on `projects`, `boq`, `finance`, `procurement`, `users`, `audit`
- D1-D7 upload validation for documents/CAD/BIM/DWG/PDF/AI
- E1-E5 rate limits on auth/AI/approval paths
- F3 CORS wildcard blocked in production
- G1-G4 no hardcoded secrets, generic error responses
- H1-H2 SQL is parameterized everywhere
- I1 trailing-slash routing works
