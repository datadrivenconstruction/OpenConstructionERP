# Construction AI OS HTTP API

A practical guide to the Construction AI OS REST API. The backend is a Python 3.12+ FastAPI application (Pydantic v2, async). Every business module exposes its own router, and all of them are served from a single origin under one version prefix.

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

The platform ships 193 modules (projects, costs, boq, users, takeoff, validation, and many more). Each module owns a `router.py`, and the module loader mounts it automatically at:

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

These three routes are intentionally disabled in production (`APP_ENV=production`, as in `docker-compose.prod.yml`) so the full endpoint map is not exposed publicly; there they answer 404. The pip install (`openconstructionerp`) and the Docker quickstart run with `APP_ENV=development`, so the docs are on by default there, for example at `http://127.0.0.1:8080/api/docs`. To get the schema for a production server, run the same version locally (`pip install openconstructionerp==<version>`, then `openconstructionerp`) and download `http://127.0.0.1:8080/api/openapi.json`, or read it from a staging instance that is not set to production.

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
  "schema_heal_incomplete": false,
  "schema_heal_skipped_count": 0,
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

`schema_heal_incomplete` true is the one schema signal that does NOT degrade
the status, and it is the one to alert on for an external PostgreSQL. The
boot-time schema repair runs each statement on its own, so a database role
that may read and write rows but may not change the schema has every statement
refused one by one while the repair as a whole succeeds. `schema_heal_failed`
then stays `false`, and requests that read a column the release added fail.
`schema_heal_skipped_count` says how many statements were refused. Which ones,
and the exact SQL to run as the owner of the tables, are in one ERROR line in
the boot log and in `GET /api/system/upgrade/status` (admin only); this
endpoint is unauthenticated and names nothing. No restart is needed after
running that SQL, but the field describes this start's repair and clears on
the next one. It does not degrade `status`, because a restart cannot give the
role the right it is missing, and a watchdog that restarts on `degraded` would
only loop.

Watch the polarity, because it is not the same on every field. On
`schema_heal_failed`, `schema_heal_incomplete`, `data_repairs_failed` and
`data_repair_ledger_failed`, `true` is the bad news; on `schema_matches_models`
and `alembic_head_matches` it is `false`. On all six, `null` means this
deployment could not tell and is not a fault, so alert on the exact value
rather than on truthiness or a check would fire on every deployment whose
database is not PostgreSQL.

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

Send the key in the `X-API-Key` header:

```
X-API-Key: <your_api_key>
```

**An API key does not open the whole API.** Almost every endpoint accepts only a bearer token and rejects a request that carries just a key. A key is accepted on these routes only:

| Route | Permission the key's owner needs |
|---|---|
| `GET /api/v1/geo-hub/ogc/` and everything below it (OGC API - Features: landing page, `conformance`, `collections`, `collections/{collection_id}`, `collections/{collection_id}/items`, `collections/{collection_id}/items/{feature_id}`) | `geo_hub.read` |
| `POST /api/v1/inbound-capture/email` and `POST /api/v1/inbound-capture/{provider}/webhook` | `inbound.write` |
| `GET /api/v1/integrations/calendar/{project_id}.ics/?token=<your_api_key>` (the key goes in the `token` query parameter, not the header) | `integrations.calendar_feed`, which must also be listed in the key's own `permissions` |

A key acts as its owner, and the `permissions` list you give when you create it can only narrow that: the request is allowed when the owner's role grants the permission and the list either is empty or contains it. The calendar feed is stricter and needs the permission listed explicitly. For everything else, sign in and use a bearer token as shown below.

Webhook lead capture configured with `api_key` auth also reads an `X-Api-Key` header, but that is the secret of that one webhook, not a user API key.

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

This endpoint does not accept an API key. A route that does, such as the OGC feature collections, is called with the key like this:

```bash
curl -s "$BASE/api/v1/geo-hub/ogc/collections" \
  -H "X-API-Key: $OCE_API_KEY"
```

## Workspace branding, and the three owner settings on it

`/api/v1/branding/` holds one JSON record per deployment: the logos and company
name that appear in the app and print on exported documents, the workspace
default appearance, and three settings that decide what the product points its
users at - and, in the third case, what it asks on their behalf.

| Method | Auth | What it does |
| --- | --- | --- |
| `GET /api/v1/branding/` | none | Returns the record. Public on purpose: the login page, the portal header and the footers all render before anybody has a token. |
| `PUT /api/v1/branding/` | admin | Merges into the record only the fields named in the request body. |
| `DELETE /api/v1/branding/` | admin | Resets the record to its defaults. |

The record is a file in the server's data directory rather than a table. It
carries no tenant data, so it needs no migration and no per-tenant row, and one
deployment has exactly one brand. The merge is by fields actually sent, so a
request that changes one setting leaves the logos, the company name and the
appearance default exactly as they were.

### `support_destination` - where an in-app bug report is sent

```json
{ "support_destination": { "kind": "url", "value": "https://support.example.com/new-ticket" } }
```

Default `null`, which means the workspace has not chosen. The bug-report menu in
the header then leaves the channel out entirely rather than showing a row that
cannot send anything: a report carries the reporter's own words plus their
machine, their build and the page they were on, so where that goes is the
operator's decision, and the product ships without one.

| `kind` | What the app does with it |
| --- | --- |
| `url` | Opens `value` as the operator set it, and copies the report to the clipboard first. Whose form that page is and what its fields are called is not the product's to guess, so the payload travels with the user instead of in a query string. |
| `email` | Opens a `mailto:` for `value` carrying the report as the message body and a subject naming the screen it came from. |

The value is admin-set but served from a public endpoint and opened in a user's
browser, so it is checked before it is stored, and a value that fails is dropped
rather than kept: `url` accepts only the `https` and `http` schemes and refuses
embedded credentials, which keeps a `javascript:`, `data:`, `vbscript:` or
`file:` destination from ever reaching a user's browser. `email` is checked
loosely - no whitespace, no scheme, exactly one `@` - because refusing a real
support address fails silently and costs the operator the channel without
telling them why. A refused value comes back as `null` on the next `GET`; the
request itself still succeeds, which is how the record's other fields behave
when one of them is unusable.

```bash
curl -X PUT "$BASE/api/v1/branding/" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"support_destination": {"kind": "email", "value": "support@example.com"}}'
```

### `legal_link_visible` - whether the footers point at the Legal page

```json
{ "legal_link_visible": false }
```

Default `true`. Only an exact `false` hides the link: a missing key, a corrupt
file or a hand-edited `"yes"` all fall back to visible, because the licence
position is not something a damaged file should get to decide.

What turning it off does, and what it cannot do:

- It removes one small footer link from the login page, the register page and the
  sidebar. That is the whole effect.
- `/legal` stays reachable and `/api/source` keeps serving the licence, the
  attribution notice and the source offer. Neither is behind this setting, and
  neither can be.
- The copyright line stays on every screen.
- The obligation does not move. This software is licensed AGPL-3.0-or-later, and
  section 13 requires the corresponding source offer to stay available to users
  who interact with it over a network. Hiding a pointer is not removing an
  obligation, so an operator turning this off should have cleared the licence
  position for their deployment first - a commercial licence, or legal review of
  the AGPL obligations. `docs/legal/COMMERCIAL-LICENSE.md` is the template for
  the first of those.

### `update_check_enabled` - whether the product asks which version is newest

```json
{ "update_check_enabled": true }
```

Default `false`. Only an exact `true` starts the check: a missing key, a corrupt
file, a hand-edited `"yes"` and a `1` all leave it off. That is the mirror image
of `legal_link_visible`, and the two rules are not inconsistent - each resolves
against the direction that needs permission. Hiding a licence pointer needs
permission, so ambiguity shows the link. Asking the internet on somebody's behalf
needs permission, so ambiguity stays quiet.

What it governs, and what it does not:

- `GET /api/system/version-check` answers `check_disabled: true` without touching
  the network while this is off, so PyPI and GitHub are never asked which release
  is newest. Turning it on takes effect on the next call, with no restart: the
  policy is read per request rather than cached.
- The web UI reads the same field and does not even ask its own backend while it is
  off, which is the difference between "nothing leaves the server" and "nothing is
  sent at all". About states which way the setting is, in the same sentence
  Settings shows beside the switch.
- Two older switches still win over a workspace that has turned it on, because
  both mean "never" and neither is reachable from this endpoint:
  `OE_DISABLE_UPDATE_CHECK` in the server's environment, and
  `~/.openestimate/no-update-check`, which the desktop launcher's "Turn off update
  checks" notice writes. An administrator cannot undo a user's opt-out from here,
  and a `GET` still reports the workspace's own decision.
- It does not govern the desktop launcher's failure screen, which asks GitHub only
  when the person looking at it presses the button, nor
  `GET /api/system/converters/version-check`, which compares each *installed DDC
  converter* against GitHub for the converter banner. Neither is a self-check, and
  the About sentence names the product rather than claiming nothing is ever asked.

```bash
curl -X PUT "$BASE/api/v1/branding/" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"update_check_enabled": true}'
```

The admin card that sets the first two is in Settings, under "Support and legal",
beside the logos and the letterhead. The card that sets the third is under "Data &
Security", beside the panel that reports what else leaves the instance. Non-admins
see all three read-only: what the workspace decided is not a secret, only changing
it is.

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
- `docs/legal/COMMERCIAL-LICENSE.md` for the commercial terms an operator clears before hiding the Legal link.
