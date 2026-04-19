# 00 — Runbook

> How to launch DokuFluss for the audit. Environment decisions. Credentials.

## Chosen audit environment

**VPS live instance** — `http://31.97.123.81:7777` (dev_mode=true)

### Why VPS and not local
- Local Docker Desktop on this machine is offline at audit time (`docker compose ps` fails with pipe error)
- VPS is up, healthy, responsive: `GET /api/v1/health` → 200 OK
- Demo user authenticates: `POST /auth/login admin@demo.de / Demo2026!` returns valid JWT
- Code under `backend/` and `frontend/` is treated as the canonical source; VPS container is assumed to be deployed from this tree (verified via health endpoint `version: 1.0.0`)

### Fallback: local docker compose

When Docker Desktop is available:

```bash
cd C:\Users\Artem\Desktop\Dokumentenklassifizierer
docker compose up -d          # full stack (13 services)
docker compose ps             # verify all healthy
docker compose logs -f app    # tail backend logs
```

Alembic on first boot:

```bash
docker compose exec app alembic upgrade head
docker compose exec app python -m app.seed    # demo data
```

Local ports:
- Backend API: http://localhost:8000
- Frontend dev (Vite): http://localhost:3000
- Meilisearch: http://localhost:7700
- MinIO console: http://localhost:9001
- Temporal UI: http://localhost:8080

---

## Credentials

| Environment | Role | Email | Password |
|-------------|------|-------|----------|
| VPS | admin (demo) | `admin@demo.de` | `Demo2026!` |
| VPS | user (demo) | `maria@demo.de` | `Demo2026!` |
| VPS | user (demo) | `thomas@demo.de` | `Demo2026!` |
| Local seed | same as above (if seeded) | | |

---

## Quick health probes

```bash
# API
curl -sS http://31.97.123.81:7777/api/v1/health | jq .

# Login (JWT)
curl -sS -X POST http://31.97.123.81:7777/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@demo.de","password":"Demo2026!"}' | jq .access_token

# Frontend
curl -sS http://31.97.123.81:7777/ -o /dev/null -w "%{http_code}\n"
```

---

## Phase 2 (Playwright) base URL

```
BASE_URL=http://31.97.123.81:7777
```

Playwright config `frontend/playwright.config.ts` may default to `http://localhost:3000` — override per-run:

```bash
cd frontend
BASE_URL=http://31.97.123.81:7777 npx playwright test --headed --project=chromium
```

For the audit screenshot sweep we use a dedicated script (`scripts/audit_screenshots.ts`) — see `01-ui-findings.md`.

---

## Useful make targets

```bash
make setup          # first-time build+migrate+seed
make dev            # docker compose up
make logs s=app     # follow app service
make test           # run all tests
make lint           # lint everything
make smoke-test     # end-to-end smoke
```

---

## Common pitfalls observed

1. `docker-compose.yml` still has `version:` key → warning but no break.
2. Meilisearch + Redis + S3 all marked `skipped (DEV_MODE)` in VPS health — dev mode means local FS storage and no search index. **Some search tests will fail** in Phase 3 against VPS.
3. First-run frontend on Windows occasionally needs `node_modules` rebuild with `npm ci`.
4. `deploy_to_vps.py` has hardcoded root SSH password — do NOT print or commit.

---

## What we deliberately will NOT do in this audit

- No deploy / push to prod
- No destructive DB ops
- No new dependencies beyond what's already in `package.json` / `requirements.txt`
- No migrations created
- No writes to remote systems (VPS is used read-mostly; any test data created is via API with demo org)
