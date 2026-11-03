# Partner-API: Schlüssel und Webhooks

Verbinden Sie OpenConstructionERP mit Ihrem BI-, ERP- oder Buchhaltungssystem: mit API-Schlüsseln, die Sie eingrenzen und begrenzen, und mit signierten Webhooks, die so lange wiederholt werden, bis sie ankommen.

Alles Folgende steht auch in der interaktiven API-Dokumentation unter dem Tag **Partner API**. Schlüssel und Endpunkte verwalten Sie in der App unter **Einstellungen, Entwickler**.

Sprachen: [English](PARTNER_API.md), Deutsch, [Русский](PARTNER_API.ru.md).

## API-Schlüssel

Senden Sie den Schlüssel im Header `X-API-Key`:

```bash
curl -H "X-API-Key: oe_xxxxxxxx" https://ihr-server/api/v1/...
```

Ein Schlüssel handelt als sein Besitzer, nie mit mehr Rechten. Seine **Scopes** können die Rechte der Rolle des Besitzers nur einschränken. Ein Schlüssel ohne Scopes behält die vollen Rechte des Besitzers; geben Sie jeder Integration nur die Scopes, die sie braucht. Scope-Namen sind Berechtigungsnamen wie `boq.read`; die vollständige Liste Ihres Servers liefert `GET /api/v1/users/me/api-keys/scopes/`.

Schlüssel werden von angemeldeten Benutzern erstellt, rotiert und widerrufen:

| Aufruf | Zweck |
| --- | --- |
| `GET /api/v1/users/me/api-keys/` | Ihre Schlüssel auflisten (das Geheimnis wird nie wieder angezeigt) |
| `POST /api/v1/users/me/api-keys/` | Schlüssel erstellen. Der Klartext steht nur in dieser Antwort |
| `POST /api/v1/users/me/api-keys/{id}/rotate/` | Neuer Schlüssel mit gleichem Namen, Scopes und Limits. Der alte gilt noch 24 Stunden |
| `DELETE /api/v1/users/me/api-keys/{id}` | Sofort widerrufen |

Optionen beim Erstellen:

| Feld | Regel |
| --- | --- |
| `name` | Eindeutig unter Ihren aktiven Schlüsseln |
| `permissions` | Scope-Namen aus dem Katalog |
| `expires_at` oder `expires_in_days` | In der Zukunft, höchstens 2 Jahre |
| `rate_limit_per_min` | 1 bis 6000. Ohne Angabe gilt der Server-Standard |
| `allowed_cidrs` | Bis zu 20 IPv4- oder IPv6-Netze, etwa `203.0.113.0/24`. Ohne Angabe ist jede Adresse erlaubt |

Ein Benutzer kann 25 aktive Schlüssel haben. Der Server protokolliert nie einen Schlüssel; das Audit-Log enthält nur die Id und das sichtbare Präfix.

### Fehler und Limits

| Status | Bedeutung |
| --- | --- |
| 401 | Schlüssel fehlt, unbekannt, widerrufen oder abgelaufen |
| 403 `api_key.ip_denied` | Die Client-Adresse liegt außerhalb von `allowed_cidrs` |
| 403 | Der Schlüssel trägt den für die Route nötigen Scope nicht |
| 429 `api_key.rate_limited` | Pro-Minute-Limit des Schlüssels überschritten. `Retry-After` Sekunden warten |

Antworten auf Schlüsselaufrufe enthalten `X-RateLimit-Limit` und `X-RateLimit-Remaining`. Hinter einem Reverse-Proxy setzen Sie `TRUSTED_PROXIES`, damit die Client-Adresse aus `X-Forwarded-For` gelesen und nicht gefälscht wird.

## Webhooks

Einen Endpunkt legen Sie mit `POST /api/v1/integrations/webhooks/` an. Die URL muss `https` sein (einfaches `http` nur auf einem Server im Debug-Modus) und auf eine öffentliche Adresse auflösen; sie wird bei jedem Senden erneut geprüft, ein Name, der später auf eine interne Adresse zeigt, wird abgelehnt. Sie können ein `secret` mit mindestens 24 Zeichen setzen; ohne Angabe erzeugt der Server eines und gibt es einmalig als `signing_secret` zurück. Ein Konto kann 20 Endpunkte haben.

Abonnieren Sie Ereignisnamen aus `GET /api/v1/integrations/webhooks/events/` oder `*` für alle. `POST /api/v1/integrations/webhooks/{id}/test/` sendet ein Ereignis `ping`.

Jede Zustellung ist ein `POST` mit JSON-Body und diesen Headern:

| Header | Wert |
| --- | --- |
| `X-OE-Signature` | `t=<Unix-Sekunden>,v1=<Hex-HMAC-SHA256>` |
| `X-OE-Event` | Ereignisname |
| `X-OE-Delivery` | Zustell-Id. Bleibt bei Wiederholungen und erneutem Senden gleich: damit entdoppeln Sie |
| `X-Webhook-Signature` | Alt: HMAC nur über den Body. Bleibt zwei Releases, dann entfällt er. Stellen Sie auf `X-OE-Signature` um |

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

### Signatur prüfen

Signiert wird der Zeitstempel, ein Punkt und der unveränderte Request-Body. Lehnen Sie einen Zeitstempel ab, der mehr als 5 Minuten von Ihrer Uhr abweicht, und vergleichen Sie in konstanter Zeit.

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

`rawBody` müssen die Bytes sein, wie sie ankamen, vor jedem JSON-Parsing.

### Zustellung und Wiederholungen

Antworten Sie innerhalb von 10 Sekunden mit einem beliebigen `2xx`. Weiterleitungen werden nicht verfolgt.

| Ergebnis | Folge |
| --- | --- |
| `2xx` | Zugestellt |
| `408`, `429`, `5xx`, Timeout, Verbindungsfehler | Wiederholung nach 1 Minute, 5 Minuten, 30 Minuten, 6 Stunden; nach dem fünften fehlgeschlagenen Senden ist die Zustellung `dead` |
| Jedes andere `4xx`, `3xx`, gesperrte Adresse | Sofort `dead`, keine Wiederholung |

Status je Zustellung: `pending`, `retrying`, `delivered`, `dead`. Eine tote Zustellung senden Sie mit `POST /api/v1/integrations/webhooks/deliveries/{id}/redeliver/` erneut (oder mit der Schaltfläche Erneut senden unter Einstellungen, Entwickler); sie beginnt mit einem frischen Zeitplan. Ein Endpunkt wird nach 10 toten Zustellungen in Folge abgeschaltet.

## Kompatibilität

Der Vertrag ist rein additiv. Innerhalb einer Hauptversion können Endpunkte, Antwortfelder, Ereignisnamen, Scopes und Header hinzukommen; wir benennen sie nicht um, entfernen sie nicht und ändern ihre Bedeutung nicht. Ignorieren Sie Felder und Ereignisse, die Sie nicht kennen. Die öffentliche Schnittstelle `/api/public/v1` mit eigenem versioniertem Schema ist als eigener Schritt geplant.
