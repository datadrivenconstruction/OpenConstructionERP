# OpenConstructionERP HTTP API

A practical guide to the OpenConstructionERP REST API. The backend is a Python 3.12+ FastAPI application (Pydantic v2, async). Every business module exposes its own router, and all of them are served from a single origin under one version prefix.

## Base URL and version prefix

All application endpoints live under:

```
/api/v1/
```

Pick the base URL that matches how you are running the platform:

- Bundled app (the `openconstructionerp` command): `http://127.0.0.1:8080`
- API-only dev server (uvicorn, see below): `http://localhost:8000`

The routes are identical on both. Examples below use `http://localhost:8000`.

Every response carries an `X-API-Version` header with the running platform version, and an `X-Request-ID` header you can quote in a bug report to help us find the matching server log line.

## How endpoints are organised

The platform ships 190 modules (projects, costs, boq, users, takeoff, validation, and many more). Each module owns a `router.py`, and the module loader mounts it automatically at:

```
/api/v1/{module}/
```

So the module name is the first path segment. For example:

| Module   | Mount point           | A few endpoints                                   |
|----------|-----------------------|---------------------------------------------------|
| users    | `/api/v1/users/`      | `POST /auth/login/`, `GET /me/`, `GET /`          |
| projects | `/api/v1/projects/`   | `POST /`, `GET /`, `GET /{project_id}`            |
| costs    | `/api/v1/costs/`      | `GET /`, `GET /autocomplete`, `GET /{item_id}`    |
| boq      | `/api/v1/boq/`        | `POST /boqs/`, `GET /boqs/{boq_id}`               |

Multi-word modules mount with a hyphenated segment (for example `/api/v1/bi-dashboards/`); an underscore form (`/api/v1/bi_dashboards/`) is also kept as a compatibility mirror.

Slash handling is exact. Automatic slash redirects are turned off, so use the path as written, including any trailing slash. When in doubt, copy the path straight from the interactive docs.

## Interactive docs and the raw schema

In development the FastAPI app serves live, browsable documentation generated from the code:

- Swagger UI (try requests in the browser): `/api/docs`
- ReDoc (clean reference view): `/api/redoc`
- Raw OpenAPI schema (JSON): `/api/openapi.json`

For example, open `http://localhost:8000/api/docs`.

These three routes are intentionally disabled in production so the full endpoint map is not exposed publicly. If you need the schema in a locked-down environment, generate it from a development or staging instance.

## Health check

A public, unauthenticated health endpoint sits outside the version prefix:

```
GET /api/health
```

It returns a small JSON document you can poll from a load balancer or uptime monitor:

```json
{
  "status": "healthy",
  "version": "16.8.0",
  "env": "development",
  "instance_id": "0f3a1c8e",
  "build": "DDC-a1b2c3d",
  "signature": "...",
  "modules_discovered": 190,
  "modules_enabled": 190,
  "modules_loaded": 190,
  "workspace_id": "...",
  "database": "ok",
  "alembic_head_matches": true,
  "schema_heal_failed": false,
  "schema_matches_models": true,
  "data_repairs_failed": false,
  "data_repair_ledger_failed": false,
  "frontend_dist_present": true,
  "uptime_seconds": 42
}
```

`status` is `healthy` when the process is up, the database answers, the schema
and the boot-time data repairs landed, a servable frontend is present, and
every module the operator enabled is loaded. Seven things drop it to
`degraded`, they are not equally bad, and `status` does not say which one
fired, so it is not enough to act on by itself. Each cause publishes its own
field beside it, and those are what you read:

`database` other than `ok` means this process cannot reach its database and
nothing is usable. `frontend_dist_present` false means the API is up while
every UI route answers 404. `schema_heal_failed` true, `schema_matches_models`
false, `data_repairs_failed` true and `data_repair_ledger_failed` true each
mean the database is behind the code running against it, in the schema or in
the rows. And a module that is enabled and did not load leaves a working
installation missing one feature, which is why it degrades at all: told
healthy, somebody looking for that feature concludes their edition does not
have it and stops. That one publishes no field of its own, it is
`modules_enabled` above `modules_loaded`, and which module is missing is in
the boot log.

Watch the polarity, because it is not the same on every field. On
`schema_heal_failed`, `data_repairs_failed` and `data_repair_ledger_failed`,
`true` is the bad news; on `schema_matches_models` and `alembic_head_matches`
it is `false`. On all five, `null` means this deployment could not tell and is
not a fault, so alert on the exact value rather than on truthiness or a check
would fire on every deployment whose database is not PostgreSQL.

A pending migration does NOT degrade the status, which is deliberate. The
product never runs `alembic upgrade`; the schema moves through `create_all`
and the boot heal, so the stamp falls behind on an ordinary correct upgrade as
soon as a release adds a revision. Degrading on that lit the field permanently
for every upgraded install, and an aggregate with a permanently active cause
has stopped being a signal. `alembic_head_matches` is published as a fact
instead: `true` at head, `false` behind it, `null` when this deployment cannot
tell.

If you are polling this from a load balancer or an uptime monitor, treat both
`healthy` and `degraded` as up and alert on `database` and
`frontend_dist_present` separately. A check
that requires the literal `healthy` will take a working installation out of
rotation over a single missing module.

## Authentication

Most endpoints require a signed-in user. Two mechanisms are supported.

### JWT bearer token (users and interactive clients)

1. Log in with an email and password at `POST /api/v1/users/auth/login/`. The response is a token pair:

   ```json
   {
     "access_token": "eyJhbGci...",
     "refresh_token": "eyJhbGci...",
     "token_type": "bearer"
   }
   ```

2. Send the access token on every request as an `Authorization` header:

   ```
   Authorization: Bearer <access_token>
   ```

3. When the access token expires, exchange the refresh token for a fresh pair at `POST /api/v1/users/auth/refresh/` with body `{"refresh_token": "..."}`. You do not have to send the password again.

The current user profile and effective permissions are available at `GET /api/v1/users/me/`.

### API keys (headless and machine-to-machine access)

For scripts, integrations, and scheduled jobs that should not hold a user password, create an API key at `POST /api/v1/users/me/api-keys/` (you must be logged in to create one). The full key value is shown only once, in that creation response, so store it safely. List and revoke keys at `GET` and `DELETE /api/v1/users/me/api-keys/{id}`.

Send the key on endpoints that accept key auth using the `X-API-Key` header:

```
X-API-Key: <your_api_key>
```

## Two worked examples with curl

Set a base URL once:

```bash
BASE=http://localhost:8000
```

### 1. Log in and capture the access token

```bash
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/auth/login/" \
  -H "Content-Type: application/json" \
  -d '{"email": "demo@openconstructionerp.com", "password": "your-password"}' \
  | jq -r '.access_token')

echo "$TOKEN"
```

`jq` is only used here to pull the token out of the JSON response. If you do not have `jq`, copy the `access_token` value from the response by hand.

### 2. Call an authenticated endpoint with the bearer token

List the projects the signed-in user can see:

```bash
curl -s "$BASE/api/v1/projects/" \
  -H "Authorization: Bearer $TOKEN"
```

The same call with an API key instead of a bearer token looks like this:

```bash
curl -s "$BASE/api/v1/projects/" \
  -H "X-API-Key: $OCE_API_KEY"
```

## Response shapes

Request and response bodies are defined by Pydantic v2 schemas in each module's `schemas.py`. Because every route declares a response model, the fields and their types are validated on the way out and documented in the OpenAPI schema. Money values are serialised as strings to avoid floating-point rounding, and non-finite numbers (`NaN`, `Infinity`) are rejected in request bodies with a `422`.

Errors are returned as JSON. Validation problems come back as `422` with a `detail` array describing each field. Unexpected server errors return `500` with a generic message plus the `request_id` so the failure can be traced in the logs without leaking internals.

## Generating a typed client

The frontend does not hand-write API types. It generates them directly from the live OpenAPI schema:

```bash
# from the frontend/ directory, with a dev backend running on :8000
npm run api:generate
```

That command runs `openapi-typescript http://localhost:8000/api/openapi.json -o src/shared/lib/api-types.ts`, so the TypeScript types always match what the backend actually serves. You can point the same generator at your own instance to produce a typed client in any language its ecosystem supports.

## See also

- `backend/README.md` for installing and running the backend and the dev server.
- The interactive docs at `/api/docs` for the complete, always-current endpoint list.
