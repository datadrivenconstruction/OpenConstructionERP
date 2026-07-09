# Deploy — AI Civil Architecture (ACAP)

Two targets: **Docker Desktop (local prod-style)** now, **VPS (Batam)** later.

## 1. Local (Docker Desktop) — current

Bring up the seeded stack (Postgres keeps its volume, so AHSP coefficients +
Batam prices survive recreate):

```bash
# secrets (once):
echo "POSTGRES_PASSWORD=$(openssl rand -base64 24)" >  .env
echo "JWT_SECRET=$(openssl rand -hex 32)"           >> .env
# add OPENCODE_API_KEY / GEMINIGEN_API_KEY to .env for layout-gen / render.

docker compose -f docker-compose.quickstart.yml -f docker-compose.acap-local.yml up -d --build
```

The unified image (`Dockerfile.unified`) builds the Vite frontend, which peaks
high — if `npm run build` OOMs (`cannot allocate memory`), raise Docker
Desktop's memory (Settings → Resources) to ≥ 12 GB, or deploy the API alone via
`Dockerfile.backend` (Python only, no frontend compile) and serve the frontend
separately.

## 2. VPS (Batam) — pending

`docker-compose.prod.yml` ships the prod topology (Postgres + backend +
frontend + optional qdrant). To finish the VPS deploy you (Ali) provide:

- a server + domain + DNS A-record,
- Traefik (or Caddy) in front for HTTPS / Let's Encrypt,
- the `.env` secrets above + `S3_*` (MinIO) + `ALLOWED_ORIGINS=https://<domain>`.

Then `docker compose -f docker-compose.prod.yml up -d`, and smoke-test the full
chain over HTTPS (layout → RAB → timeline → render).

## 3. Backups (data-loss guard — not optional)

```bash
scripts/backup.sh                 # gzipped pg_dump → ./backups, keeps newest 14
scripts/restore.sh <dump.sql.gz>  # restore into the live (or a named) DB
scripts/restore-drill.sh          # PROVE a backup restores (into a scratch DB), no prod touch
```

Nightly cron:

```cron
0 2 * * *  cd /path/to/repo && scripts/backup.sh >> /var/log/acap-backup.log 2>&1
```

The restore drill has been run and passes (68 AHSP rows round-tripped). Run it
after any Postgres major-version bump.
