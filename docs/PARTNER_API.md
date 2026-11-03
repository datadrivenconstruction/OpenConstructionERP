# Partner API: keys and webhooks

Connect OpenConstructionERP to your BI, ERP or accounting system with two things: API keys that you scope and limit, and signed webhooks that retry until they get through.

Everything below is also in the interactive API docs under the tag **Partner API**. Manage keys and endpoints in the app under **Settings, Developer**.

Languages: English, [Deutsch](PARTNER_API.de.md), [Русский](PARTNER_API.ru.md).

## API keys

Send the key in the `X-API-Key` header:

```bash
curl -H "X-API-Key: oe_xxxxxxxx" https://your-server/api/v1/...
```

A key acts as its owner, never as more. Its **scopes** can only narrow what the owner's role allows. A key with no scopes keeps the owner's full authority; give every integration the smallest set it needs. Scope names are permission names such as `boq.read`; the full list for your server is `GET /api/v1/users/me/api-keys/scopes/`.

Keys are created, rotated and revoked by a signed-in user:

| Call | Purpose |
| --- | --- |
| `GET /api/v1/users/me/api-keys/` | List your keys (the secret is never shown again) |
| `POST /api/v1/users/me/api-keys/` | Create a key. The plaintext is in this response only |
| `POST /api/v1/users/me/api-keys/{id}/rotate/` | New key with the same name, scopes and limits. The old key works for 24 more hours |
| `DELETE /api/v1/users/me/api-keys/{id}` | Revoke at once |

Create options:

| Field | Rule |
| --- | --- |
| `name` | Unique among your active keys |
| `permissions` | Scope names from the catalogue |
| `expires_at` or `expires_in_days` | In the future, at most 2 years ahead |
| `rate_limit_per_min` | 1 to 6000. Omit for the server default |
| `allowed_cidrs` | Up to 20 IPv4 or IPv6 networks, for example `203.0.113.0/24`. Omit to allow any address |

A user can hold 25 active keys. The server never logs a key; the audit log records its id and visible prefix only.

### Errors and limits

| Status | Meaning |
| --- | --- |
| 401 | Missing, unknown, revoked or expired key |
| 403 `api_key.ip_denied` | The client address is outside `allowed_cidrs` |
| 403 | The key does not carry the scope the route needs |
| 429 `api_key.rate_limited` | Over the key's per-minute limit. Wait `Retry-After` seconds |

Responses to key calls include `X-RateLimit-Limit` and `X-RateLimit-Remaining`. Behind a reverse proxy, set `TRUSTED_PROXIES` so the client address is read from `X-Forwarded-For` and not spoofed.

## Webhooks

Create an endpoint with `POST /api/v1/integrations/webhooks/`. The URL must be `https` (plain `http` only on a server running in debug mode) and must resolve to a public address; it is checked again at every send, so a name that later points to an internal address is refused. You may set a `secret` of at least 24 characters; when you omit it the server generates one and returns it as `signing_secret` once. An account can hold 20 endpoints.

Subscribe to event names from `GET /api/v1/integrations/webhooks/events/`, or to `*` for all. `POST /api/v1/integrations/webhooks/{id}/test/` sends an event named `ping`.

Each delivery is a `POST` with a JSON body and these headers:

| Header | Value |
| --- | --- |
| `X-OE-Signature` | `t=<unix seconds>,v1=<hex HMAC-SHA256>` |
| `X-OE-Event` | Event name |
| `X-OE-Delivery` | Delivery id. Stays the same across retries and redeliveries: use it to de-duplicate |
| `X-Webhook-Signature` | Legacy: HMAC of the body alone. Kept for two releases, then removed. Migrate to `X-OE-Signature` |

Body:

```json
{
  "event": "boq.position.created",
  "event_id": "…",
  "timestamp": "2026-11-03T12:00:00+00:00",
  "source_module": "oe_boq",
  "data": { "…": "…" }
}
```

### Verify the signature

The signed text is the timestamp, a dot, and the raw request body. Reject a timestamp more than 5 minutes from your clock, and compare in constant time.

Python:

```python
import hashlib, hmac, time

def verify(secret: str, header: str, body: bytes, tolerance: int = 300) -> bool:
    parts = dict(p.strip().split("=", 1) for p in header.split(","))
    t = int(parts["t"])
    if abs(time.time() - t) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])
```

Node.js:

```js
const crypto = require("node:crypto");

function verify(secret, header, rawBody, tolerance = 300) {
  const parts = Object.fromEntries(header.split(",").map((p) => p.trim().split("=")));
  const t = Number(parts.t);
  if (!Number.isFinite(t) || Math.abs(Date.now() / 1000 - t) > tolerance) return false;
  const expected = crypto.createHmac("sha256", secret).update(`${t}.`).update(rawBody).digest("hex");
  const given = Buffer.from(parts.v1 ?? "");
  const want = Buffer.from(expected);
  return given.length === want.length && crypto.timingSafeEqual(given, want);
}
```

`rawBody` must be the bytes as received, before any JSON parsing.

### Delivery and retries

Answer with any `2xx` within 10 seconds. Redirects are not followed.

| Result | What happens |
| --- | --- |
| `2xx` | Delivered |
| `408`, `429`, `5xx`, timeout, connection error | Retried after 1 minute, 5 minutes, 30 minutes, 6 hours; after the fifth failed send the delivery is `dead` |
| Any other `4xx`, `3xx`, blocked address | `dead` at once, no retry |

Status per delivery: `pending`, `retrying`, `delivered`, `dead`. A dead delivery can be sent again with `POST /api/v1/integrations/webhooks/deliveries/{id}/redeliver/` (or the Redeliver button in Settings, Developer); it starts with a fresh schedule. An endpoint is switched off after 10 dead deliveries in a row.

## Compatibility

The contract is additive. Within a major version we may add endpoints, response fields, event names, scopes and headers; we do not rename or remove them, and we do not change what they mean. Ignore fields and events you do not know. The public `/api/public/v1` surface with its own versioned schema is planned as a separate step.
