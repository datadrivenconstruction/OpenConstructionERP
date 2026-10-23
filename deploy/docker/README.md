# Running OpenConstructionERP in Docker

This directory ships two container layouts. Both work, so pick the one that matches how you plan to run the app and then follow just that section.

## Layout 1: one unified image

This is the fastest way in. A single container runs FastAPI, and FastAPI serves the compiled React frontend itself. The app is PostgreSQL-only (SQLite support was removed in v6.6.0), so the container needs a `DATABASE_URL` pointing at a PostgreSQL server. The simplest path is the quickstart compose at the repo root, which starts this image together with PostgreSQL 16 in one command:

```bash
docker compose -f docker-compose.quickstart.yml up --build
```

To run the image standalone against a PostgreSQL you already have:

```bash
docker build -t openconstructionerp -f deploy/docker/Dockerfile.unified .
docker run -d -p 8080:8080 -v oe_data:/data \
  -e DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname \
  -e JWT_SECRET=$(openssl rand -hex 32) \
  openconstructionerp
```

After the container starts, the app responds on http://localhost:8080. Anything that has to survive a restart outside the database, like the vector store, gets written under the `/data` volume. If `DATABASE_URL` is missing or not a PostgreSQL URL, the entrypoint exits immediately with a message explaining both options above instead of crash-looping.

`JWT_SECRET` deliberately has no default baked into the image. Without that, every container launched from the same published image would sign tokens with one shared key, so always pass a secret you generated yourself.

## Layout 2: separate backend and nginx frontend

Here you build two images. The first is the API, which listens on port 8000. It comes out of the same `Dockerfile.unified` as the all-in-one image above, from its `api` target: same base, same dependencies, no frontend. The second is an nginx container (`Dockerfile.frontend` together with `nginx.conf`) that serves the static single-page app and reverse-proxies API traffic back to the backend. Reach for this layout when you want nginx out front to terminate TLS and take care of compression and caching.

```bash
docker build -t oce-backend  --target api -f deploy/docker/Dockerfile.unified  .
docker build -t oce-frontend -f deploy/docker/Dockerfile.frontend .
```

The two layouts used to live in two Dockerfiles that had to be kept in step by hand, and they drifted: a vector-store dependency was added to the all-in-one image and never to the API-only one, so `/match-elements` answered an empty `200` on every image built for this layout. They are one file with two targets now, and the dependency list is a single build argument both targets read.

The nginx container expects to find the API at `http://backend:8000`. That means the two containers have to sit on a shared Docker network and the API container has to be named `backend`. A small `docker-compose.yml`, or a `--network` flag plus `--name backend`, covers both needs. Copy `deploy/docker/.env.example`, then fill in at least `JWT_SECRET` and your `DATABASE_URL` before you bring the stack up.

## Settings any reverse proxy in front of the app must honor

`nginx.conf` already handles the three items below. We document them here because anyone substituting a different proxy (Caddy, Traefik, a cloud load balancer) has to reproduce them or the app misbehaves.

First is upload size. CAD files and drawings are large, so the request body limit is raised to `2g`. nginx ships with a `1M` default, and at that ceiling most takeoff and CAD uploads get rejected with a 413 before FastAPI ever sees them.

Second is `.mjs` module workers. The PDF takeoff viewer loads pdf.js as an ES module worker. nginx-alpine carries no MIME entry for `.mjs`, so by default it returns the file as `application/octet-stream`, the browser refuses to run it, and the viewer comes up blank. The config serves `.mjs` with the `application/javascript` content type instead.

Third is WebSocket upgrades. Live notifications and collaborative-lock presence run over WebSockets at `/api/v1/notifications/ws` and `/api/v1/collaboration_locks/presence`. Those routes need the HTTP/1.1 Upgrade handshake and long read timeouts, so they get their own proxy block placed ahead of the general `/api/` block. The WebSocket clients carry the JWT in a `?token=` query parameter, which is why that block forwards the original path and query string untouched.

Fourth is the allowed origin, and unlike the three above it is a setting on the app rather than on the proxy. The browser sends the address the user typed, so once the app answers on `https://erp.example.com` that host name has to appear in `ALLOWED_ORIGINS` or every API call after the page loads is refused. The refusal comes from the browser, which means the server log stays clean and the symptom is a blank screen rather than an error, so it is worth setting before you go looking for anything else. In the quickstart stack the variable is `OE_ALLOWED_ORIGINS`:

```bash
OE_BIND=127.0.0.1 OE_ALLOWED_ORIGINS=https://erp.example.com \
  docker compose -f docker-compose.quickstart.yml up -d
```

`OE_BIND=127.0.0.1` is worth pairing with it. It keeps the container on loopback so the only route in is through the proxy, instead of leaving port 8080 answering on the public interface next to the TLS you just set up. The app does not terminate TLS itself and is not intended to; 443 belongs to the proxy.

If real-time features stop working or the takeoff viewer comes up blank behind your own proxy, start your troubleshooting with these four settings.

## Health endpoint

Each image exposes `GET /api/health`, and the container `HEALTHCHECK` directive polls that route on a fixed interval. A healthy reply reports the running version, the loaded module count, and a flag for whether the database revision matches the current Alembic head.

## Other deployment targets

One isolated instance per company on the German cloud STACKIT (Kubernetes, managed PostgreSQL, object storage): see [deploy/terraform/stackit](../terraform/stackit/README.md).

Microsoft Azure (VM or Container Apps, Azure Database for PostgreSQL, Entra ID sign-in notes): see [docs/install/azure.md](../../docs/install/azure.md).
