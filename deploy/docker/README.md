# Docker deployment

Two ways to run OpenConstructionERP in containers live in this folder. Pick one.

## Option 1: single unified image (simplest)

One container, FastAPI serves the built React frontend, SQLite by default, no
external database needed.

```bash
docker build -t openconstructionerp -f deploy/docker/Dockerfile.unified .
docker run -d -p 8080:8080 -v oe_data:/data \
  -e JWT_SECRET=$(openssl rand -hex 32) \
  openconstructionerp
```

The app is then on http://localhost:8080. Data (SQLite database and the vector
store) lives in the `/data` volume. To use PostgreSQL instead of SQLite, pass
`-e DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname`.

`JWT_SECRET` is deliberately not baked into the image. Always pass your own, or
every container pulled from a registry would share one signing key.

## Option 2: split backend + nginx frontend

Two images: the API (`Dockerfile.backend`, listening on 8000) and an nginx
container that serves the static SPA and reverse-proxies the API
(`Dockerfile.frontend` + `nginx.conf`). Use this when you want nginx to handle
TLS termination, compression and caching in front of the API.

```bash
docker build -t oce-backend  -f deploy/docker/Dockerfile.backend  .
docker build -t oce-frontend -f deploy/docker/Dockerfile.frontend .
```

The frontend container expects to reach the backend at `http://backend:8000`,
so run both on a shared Docker network where the API container is named
`backend` (a small `docker-compose.yml` or a `--network` plus `--name backend`
does the job). Copy `deploy/docker/.env.example` and set at least `JWT_SECRET`
and your `DATABASE_URL`.

## What the reverse proxy has to get right

`nginx.conf` already handles these, and they are worth calling out for anyone
putting a different proxy (Caddy, Traefik, a cloud load balancer) in front of
the app:

- Upload size. Drawings and BIM files are large, so the body limit is raised to
  `2G`. The nginx default of `1M` rejects most takeoff and CAD uploads with a
  413 before the request ever reaches FastAPI.
- `.mjs` module workers. The PDF takeoff viewer loads pdf.js as an ES module
  worker. nginx-alpine has no MIME mapping for `.mjs` and would serve it as
  `application/octet-stream`, which the browser refuses to execute, leaving the
  viewer blank. The config serves `.mjs` as `application/javascript`.
- WebSocket upgrades. Live notifications and collaborative-lock presence run
  over WebSockets on `/api/v1/notifications/ws` and
  `/api/v1/collaboration_locks/presence`. Those paths need the HTTP/1.1 Upgrade
  handshake and long read timeouts, so they have their own proxy block ahead of
  the generic `/api/` proxy. The WebSocket clients send the JWT as a `?token=`
  query parameter, so that block passes the original path and query through
  unchanged.

If real-time features go quiet or the takeoff viewer is blank behind your own
proxy, those three settings are the first thing to check.

## Health check

Both images expose `GET /api/health`, which the container `HEALTHCHECK` polls.
A healthy response reports the version, the module count and whether the
database and the Alembic head match.
