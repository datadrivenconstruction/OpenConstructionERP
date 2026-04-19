# OpenConstructionERP — BUGS (Part 5)

**Дата:** 2026-04-18
**Версия:** 1.9.0 · commit `767b38f232596cfb191f9790ce2053ab5108a7d4`
**Предыдущие части:**
- `archive/part1.zip` — 21 баг
- `archive/part2.zip` — 10 багов (2 BLOCKER + 1 SECURITY-CRIT)
- `archive/part3.zip` — 8 багов
- `archive/part4.zip` — 75 багов (3 SECURITY-CRIT + 1 BLOCKER + 12 CRITICAL)

## Методология Part 5 — 6 параллельных субагентов

| Агент | Область | Метрика |
|-------|---------|---------|
| H | RBAC exhaustive matrix (421 endpoints × 4 роли = ~1700 probes) | 5 findings |
| I | Import/Export roundtrip (Excel/CSV/GAEB) | 10+ data-loss findings |
| J | Performance stress + memory | 5 bottlenecks |
| K | Schedule/CPM deep (18 сценариев) | 2 bugs, CPM 18/18 PASS |
| L | Workflow engines (CO/Tender/Submittals/RFI/NCR/Approval) | 6 HIGH bugs |
| M | API fuzz (261 endpoints, 4510 requests) | 32 unhandled 500s |

## Статистика Part 5

| Severity        | Новых  |
|-----------------|--------|
| SECURITY-CRIT   | 0      |
| BLOCKER         | 0      |
| CRITICAL        | 8      |
| MAJOR           | 25     |
| MINOR           | 18     |
| INFO            | 4      |
| **Всего**       | **55** |

## Общая статистика (части 1–5)

| Severity        | Всего |
|-----------------|-------|
| BLOCKER         | 7     |
| SECURITY-CRIT   | 4     |
| CRITICAL        | 21    |
| MAJOR           | 53    |
| MINOR           | 63    |
| INFO            | 21    |
| **Всего**       | **169** |

---

# 🔥 CRITICAL (8 новых)

## BUG-115 · CRITICAL · module: costs · category: privilege-escalation (RBAC)
**Заголовок:** `DELETE /api/v1/costs/actions/clear-database/` — **estimator может стереть всю CWICR cost database** (55000+ items).

**Репро:**
```bash
# estimator token
curl -X DELETE -H "Authorization: Bearer $TOK_ESTIMATOR" \
  http://127.0.0.1:8080/api/v1/costs/actions/clear-database/
# → 200 / 204: database wiped
```

**Impact:** Разрушение core seed data. Любой estimator user без single-privilege check может стереть 55K cost items. Восстановление — только через `openestimate seed --cwicr` или reseed.

**Fix:** `@require_role("admin")` на этом DELETE endpoint. Или вообще убрать exposure — cost DB clear должен быть CLI operation, не HTTP.

---

## BUG-116 · CRITICAL · module: demo · category: privilege-escalation
**Заголовок:** `DELETE /api/demo/clear-all` — estimator clears all demo data.

**Impact:** Estimator удаляет все 5 demo проектов (Berlin/London/NY/Paris/Dubai).

**Fix:** RBAC на demo endpoints (admin-only).

---

## BUG-117 · CRITICAL · module: schedule · category: privilege-escalation
**Заголовок:** `DELETE /api/v1/schedule/relationships/{id}` — estimator удаляет FS/FF/SS/SF зависимости в чужих schedule'ах.

**Impact:** Ломает critical path computation в чужих проектах.

**Fix:** project-level RBAC.

---

## BUG-118 · CRITICAL · module: perf · category: availability
**Заголовок:** Concurrent writes → **93.5% error rate** (35 × 500 + 23 conn-errors + 20 cancelled tasks из 62 attempts).

**Репро (from Agent J):** 20 async clients × 5 POST positions в один BOQ:
- Only 4/62 succeeded.
- Throughput 0.1 pos/sec (vs 24 pos/sec sequential).
- Root cause: SQLite lock contention (Part 4 BUG-049 quantified).

**Impact:** Production unusable для любого use case где несколько пользователей одновременно редактируют один BOQ (real-world estimating).

**Fix:** переход на PostgreSQL обязателен перед production deploy. Либо retry middleware (ENH-054).

---

## BUG-119 · CRITICAL · module: perf · category: degradation
**Заголовок:** Reads degrade на **+146 843%** под concurrent write pressure.

**Репро (Agent J, mixed load 50R + 10W, 30s):**
- Baseline read p95: 15ms.
- Under write pressure: p95 = **22 357 ms**.

**Impact:** В реальных условиях (50 estimators читают + 10 делают updates) — каждый read зависает на 22 секунды. Всё UI становится non-responsive.

**Fix:** SQLite → PostgreSQL. Либо в SQLite: WAL + separate read/write engines.

---

## BUG-120 · CRITICAL · module: changeorders · category: integration-broken
**Заголовок:** **Approved Change Order не обновляет project.budget_estimate** — нет writeback в BOQ.

**Репро (from Agent L):**
```bash
# Project created with budget_estimate=100000
# CO created with line items totaling +5000
# CO submit → approve
# project.budget_estimate STILL 100000  ← should be 105000
```

`backend/app/modules/changeorders/service.py::approve_order` — только flips status + sets `approved_by/approved_at`. Нет project writeback, нет event bus publish.

**Impact:** Фундаментальное нарушение business contract. Approved CO — это финансовое обязательство, которое должно отражаться в project.budget_estimate / BOQ / EVM. Сейчас approved CO — просто информационная запись без финансовых последствий.

**Fix:**
1. В `approve_order`: update `project.budget_estimate += co.total_amount` (или создать отдельный markup/position в BOQ).
2. Publish event `changeorder.approved` — EVM / budget dashboards subscribe.
3. Chain CO test из Part 5 Agent L (CO#1 +5000, CO#2 -2000) должен показать net +3000 в project.

---

## BUG-121 · CRITICAL · module: tendering · category: integration-broken
**Заголовок:** **Tender select-winner не пишет выигравшие rates в BOQ.** Winning bid — это просто status flag, нет endpoint для подтягивания ставок в BOQ.

**Endpoints:**
- `/api/v1/tendering/packages/{id}/comparison/` — показывает сравнение
- `PATCH /api/v1/tendering/packages/{id} {"status":"awarded"}` — флаг
- `/api/v1/rfq_bidding/bids/{id}/award/` — отдельный конкурирующий модуль

**Impact:** Критичный разрыв workflow: выиграла компания с bid 95000 EUR, но BOQ остаётся с original rate. Следующий step (contract generation) не знает о снижении цены → финансовые потери.

**Fix:** endpoint `POST /tendering/packages/{id}/apply-winner/` → обновляет BOQ positions с winning unit_rate'ами; публикует event.

---

## BUG-122 · CRITICAL · module: submittals · category: logic-broken
**Заголовок:** **Все mutation endpoints Submittals возвращают 500**: PATCH, `/submit/`, `/review/`, `/approve/`.

**Создание и GET работают.**

**Репро:** из Agent L — создание OK, но любой PATCH / state transition → 500.

**Impact:** Submittals workflow полностью неработоспособен. Это основной workflow для подрядчиков, submitting shop drawings / material samples на approval.

**Fix:** вероятнее всего — `session.refresh` issue в async service (same bug class как был исправлен в changeorders). Проверить трассу 500.

---

## BUG-123 · CRITICAL · module: rfi · category: logic-broken
**Заголовок:** **Все mutation endpoints RFI возвращают 500**: PATCH, `/respond/`, `/close/`.

**Создание и GET работают**. Same pattern как Submittals.

**Impact:** RFI — critical construction workflow. Создавать можно, но невозможно ответить / закрыть → все RFI навсегда "open".

**Fix:** same as BUG-122.

---

# MAJOR (25 новых)

## BUG-124..138 · MAJOR cluster: 15 NaN-float crashes (Agent M)

Pydantic `allow_inf_nan=True` default пропускает `float("nan")` через validation → crash в Decimal arithmetic / DB insert.

**Endpoints:**
1. `/boq/boqs/from-template`
2. `/boq/boqs/search-cost-items`
3. `/boq/boqs/escalate-rate`
4. `/boq/boqs/{id}/positions`
5. `/markups`
6. `/costs/`
7. `/assemblies/{id}/apply-to-boq`
8. `/catalog/`
9. `/changeorders/{id}/items`
10. `/costmodel/5d/what-if`
11. `/markups/scales`
12. `/punchlist/items`
13. `/risk/`
14. `/variations/{id}/items`
15. `/finance/evm/5d/what-if`

**Fix:** установить `allow_inf_nan=False` глобально в Pydantic BaseModel config, либо per-field `Field(..., allow_inf_nan=False)` на всех numeric полях.

## BUG-139..143 · MAJOR: 5 int64 overflow crashes (Agent M)

`2^63` проходит Pydantic (no `le=...` constraint), отвергается Postgres/SQLite INTEGER/BIGINT → unhandled `DataError` → 500.

Endpoints:
1. `/changeorders/`
2. `/fieldreports/workforce`
3. `/markups/scales`
4. `/schedule/relationships`
5. `/teams/`

**Fix:** добавить `Field(..., le=2**31-1)` на integer fields (или соответствующий предел).

## BUG-144..147 · MAJOR: 4 extra="allow" 500s

Pydantic `Extra.allow` принимает unknown field → handler крашится когда пытается обработать:
- `/users/auth/forgot-password`
- `/assemblies/import`
- `/rfq_bidding/`
- `/teams/`

**Fix:** `model_config = ConfigDict(extra="ignore")` или `extra="forbid"`.

## BUG-148..149 · MAJOR: 2 string-content 500s

- `/rfq_bidding/` — unicode-chaos / SQL-string / empty / 10KB в `rfq_number` / `description` → 500 (должно 422).
- `/teams/` — unicode-chaos / SQL в `name` → 500.

**Fix:** `Field(..., min_length=1, max_length=255, pattern=...)`.

---

## BUG-150 · MAJOR · roundtrip · Excel/CSV flattens hierarchy on re-import
Section rows → ghost positions with `unit="pcs"`; hierarchy сломана. **Fix:** importer должен detect headers (по empty unit_rate / pattern) и восстанавливать секции.

## BUG-151 · MAJOR · roundtrip · Excel exporter subtotal-row label bug
Every subtotal row labelled с **именем последней секции** (e.g. "Subtotal: 03 Geschäftskosten..." для секции 01).

**Fix:** `exporter.py` — передавать имя текущей секции в format string.

## BUG-152 · MAJOR · roundtrip · CSV/GAEB truncate unit rates to 2 decimal places
`12345.6789 → 12345.68` — silent precision loss. Excel preserves.

**Fix:** формат `%.4f` минимум в CSV/GAEB exporters.

## BUG-153 · MAJOR · roundtrip · GAEB import endpoint отсутствует
README Phase 1 ставит "GAEB XML import/export (X83)" как core feature. Export работает, **import не реализован**. Feature gap.

## BUG-154 · MAJOR · roundtrip · tampered Excel imported без валидации
Edited `unit_rate: 12345.68 → 999999.99` в Excel, импортировал → сервер принимает. Нет server-side sanity check на imported price data.

## BUG-155 · MAJOR · workflows · no cancel/withdraw endpoint в Approval Workflow
Once submitted, невозможно withdraw / cancel. **Fix:** endpoint `POST /approval-requests/{id}/cancel/` + state machine.

## BUG-156 · MAJOR · workflows · step roles not enforced
Любой authenticated user может approve **любой** step (включая step, назначенный specific reviewer).

**Fix:** `approval_step.role` должен verify против `user.role` / explicit reviewer assignment.

## BUG-157 · MAJOR · perf · CWICR autocomplete serialize under 50-concurrent
Agent J: p95 = 1571ms (target < 500ms) на пустой cost DB. Pure ASGI/DB-session contention — не search work.

**Fix:** separate read-replica engine, или in-memory cache слой перед DB.

## BUG-158 · MAJOR · perf · 200 concurrent HTTP/1.1 queues to 54s p95
Uvicorn queues requests за serialized DB path. **Fix:** same as BUG-157.

---

# MINOR (18 новых) — сгруппированно

## BUG-159 · MINOR · RBAC · unauth feedback
`POST /api/v1/feedback` — 200 без токена. Может использоваться для спама. **Fix:** require auth или rate-limit by IP.

## BUG-160 · MINOR · schedule · duration_days=0 overridden to 1
Agent K BUG-K-01: millstones (0-duration events) невозможно создать через API. `service.py:391-393` — `compute_duration` молча override.

## BUG-161 · MINOR · schedule · last_login_at race with activity insert
SQLite lock contention между users middleware UPDATE и activity INSERT. **Fix:** throttle `last_login_at` refresh (1x per N minutes).

## BUG-162 · MINOR · workflows · no submittal attachments endpoint
README не упоминает attachments явно, но ожидается. Feature gap.

## BUG-163..175 · MINOR — roundtrip data loss
Fields silently dropped on roundtrip: `classification`, `metadata`, `source`, `confidence`, `cad_element_ids`, `wbs_id`, `cost_code_id`, `parent_id`. GAEB unit lexicon shifts (`lsum→psch`, `pcs→Stk`) — asymmetric.

## BUG-176 · MINOR · perf · /api/health не exposes memory metrics
Backend process RSS 369 MB (PID 1960, 8 threads), но `/api/health` не expose. **Fix:** добавить `memory_rss_mb` / `threads` в health response.

---

# INFO (4 новых)

- **BUG-177** Pure ASGI serialization bottleneck на autocomplete-style endpoints — not a bug per se, but limits throughput.
- **BUG-178** Admin anomalies count: **0** — admin auth layer корректна.
- **BUG-179** UTF-8 / emoji preserved in all 3 export formats (positive).
- **BUG-180** 200-activity schedule + CPM в 0.32s — performance OK for typical project size.

---

# Позитивные находки Part 5

## Agent H (RBAC)
- **0 admin anomalies** — admin авторизован на всех state-changing endpoints.
- Estimator корректно получает 403 на 62 endpoint'ах (admin-only ops).
- Manager 15 forbidden — корректное разграничение ролей.

## Agent I (Roundtrip)
- **UTF-8 / emoji preserved** в Excel/CSV/GAEB (ç, é, Ж, ä, 🏗️).
- UTF-8 BOM detection works — BOM и non-BOM CSV принимаются одинаково.

## Agent J (Performance)
- **Baseline latency OK:** /projects 11ms p50, /autocomplete 8ms, /boq 15ms.
- BOQ structured load (500 positions) = **46ms** (target 500ms).
- 500-position sequential POSTs = 24 pos/s, p95 53ms.
- Large payload: 100KB description correctly rejected 422 (limit 5KB).

## Agent K (Schedule)
- **CPM correctness 18/18 PASS** — ES/EF/total_float точны до дня.
- FS/FF/SS/SF dependencies работают.
- Circular dep → 400 (не crash).
- PERT/Risk: p50 ≤ p80 ≤ p95 monotonic.
- XER + MSP XML import работают.
- Gantt response shape complete.
- 200-activity CPM в 0.32s.

## Agent L (Workflows)
- Change Order state machine: draft→submitted→approved/rejected — correct transitions, edit-after-approve → 400.
- Enterprise Workflows: 2-step approve + reject работают, approve-on-approved → 400.
- NCR create + close end-to-end.
- **BUG-G3 (RFI list без filter) fixed** с Part 4: теперь 422 вместо silent empty.

## Agent M (Fuzz)
- Из 4510 fuzz requests → 32 unique 500s. 97.7% endpoints graceful on edge input.
- Int-overflow rejected Pydantic на большинстве endpoints (только 5 из всех POST прошли).
- Unicode chaos / SQL injection отвергаются большинством endpoints.

---

# Рекомендованный порядок исправлений

1. **Срочно (RBAC):** BUG-115/116/117 — добавить `@require_role("admin")` на destructive DELETEs.
2. **Срочно (logic-broken):** BUG-120/121 (CO/Tender writeback), BUG-122/123 (Submittal/RFI mutations 500).
3. **Перед prod (perf):** переход с SQLite на PostgreSQL (решает BUG-118/119/157/158 + Part 4 BUG-049).
4. **Hardening:** BUG-124-143 (NaN/overflow — Pydantic config), BUG-144-149 (extra field handling).
5. **Data integrity:** BUG-150-154 (roundtrip losses, tampered Excel validation, GAEB import).
6. **Workflows polish:** BUG-155/156.
