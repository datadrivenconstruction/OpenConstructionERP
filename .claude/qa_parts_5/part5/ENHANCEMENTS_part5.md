# OpenConstructionERP — ENHANCEMENTS (Part 5)

**Дата:** 2026-04-18
**Предыдущие части:** 1 (10), 2 (16), 3 (12), 4 (38) — всего 76

## Статистика Part 5

| Priority | Кол-во |
|----------|--------|
| CRITICAL | 5      |
| HIGH     | 12     |
| MEDIUM   | 14     |
| LOW      | 6      |
| **Всего**| **37** |

---

## CRITICAL (5)

### ENH-077 · CRITICAL · rbac — role-guard on destructive DELETEs
Дефолт для `DELETE /api/*/actions/clear-*/` и `DELETE /api/demo/*` = admin-only. Добавить decorator `@require_role("admin")` или explicit permission check. Решает BUG-115/116/117.

Ещё лучше: cost DB clear / demo reset **не должны быть HTTP endpoints** — только CLI (`openestimate seed --reset-cost-db`). HTTP-exposed destructive ops — always footgun.

### ENH-078 · CRITICAL · perf — move to PostgreSQL for non-single-user deployments
SQLite `busy_timeout=30000` + WAL **не решает** concurrent write pattern (BUG-118: 93.5% error rate на 20 concurrent writers; BUG-119: reads +146843% degradation под write pressure).

Fast-follow:
1. Включить SQLite FK (Part 4 ENH-042) — одна строка.
2. Document "SQLite = single-user / demo mode only; PostgreSQL required for team use" в README.
3. Quickstart docker-compose уже предоставляет PostgreSQL — update docs.

### ENH-079 · CRITICAL · changeorders — approval writeback event
В `changeorders/service.py::approve_order`:
```python
async def approve_order(self, order_id, approver_id):
    co = await self.get(order_id)
    co.status = "approved"
    co.approved_by = approver_id
    co.approved_at = datetime.utcnow()
    # NEW: writeback to project
    project = await self.projects.get(co.project_id)
    project.budget_estimate = (project.budget_estimate or 0) + co.total_amount
    await self.session.commit()
    # NEW: publish event
    await event_bus.publish("changeorder.approved", {
        "co_id": co.id, "project_id": co.project_id, "delta": co.total_amount,
    })
```
Это решает BUG-120. EVM и budget dashboards subscribe на event.

### ENH-080 · CRITICAL · tendering — apply-winner endpoint
```
POST /api/v1/tendering/packages/{pkg_id}/apply-winner/
Body: {"bid_id": "..."}
Behavior:
  1. Mark bid as winner
  2. For each BOQ position в tender package → update unit_rate = bid.line_items[pos_id].rate
  3. Optional: create markup "awarded" per section для tracking
  4. Publish event tender.awarded
```
Закрывает BUG-121.

### ENH-081 · CRITICAL · fuzz hardening — Pydantic global config
```python
# backend/app/core/schemas.py — shared base
class StrictBaseModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",           # fix BUG-144-147
        str_strip_whitespace=True,
        validate_assignment=True,
    )

# Numeric float fields — disallow NaN/Inf globally
class MoneyModel(StrictBaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def reject_nan_inf(cls, v):
        if isinstance(v, float) and (v != v or v == float("inf") or v == float("-inf")):
            raise ValueError("NaN / Infinity not allowed")
        return v
```
Все финансовые schemas extend `MoneyModel`. Закрывает BUG-124-138 (15 NaN crashes).

---

## HIGH (12)

### ENH-082 · HIGH · submittals/rfi — 500 debugging + fix
BUG-122/123 — вероятно одинаковый bug class (session.refresh after async state transition). Нужна трасса 500s и fix в service layer. Same patch model как changeorders fix.

### ENH-083 · HIGH · workflows — step role enforcement
В `enterprise_workflows/service.py::advance_step`:
```python
step = workflow.steps[request.current_step]
if step["role"] and user.role != step["role"]:
    raise PermissionError(f"Step requires role={step['role']}")
if step["assigned_to"] and user.id != step["assigned_to"]:
    raise PermissionError(f"Step assigned to another user")
```
Закрывает BUG-156.

### ENH-084 · HIGH · workflows — cancel/withdraw endpoint
```
POST /api/v1/workflows/requests/{id}/cancel/ (owner only)
→ state "cancelled", audit entry
```

### ENH-085 · HIGH · boq — Int boundary validation
Audit всех integer fields → добавить `le=2^31-1` или `le=max_safe`. Закрывает BUG-139-143.

### ENH-086 · HIGH · boq — String field validation
`Field(..., min_length=1, max_length=N, pattern=SAFE_PATTERN)` для `rfq_number`, `team.name` etc. Закрывает BUG-148-149.

### ENH-087 · HIGH · boq — import hierarchy preservation
Excel/CSV importer должен distinguish section header rows vs positions:
- Detect heuristic: row с empty `unit`/`quantity`/`unit_rate`, description-only → section
- Или явный "marker column" `is_section` в экспорте (hidden column)
- Либо preserve ordinal prefix structure (01 → section, 01.001 → position)

Закрывает BUG-150.

### ENH-088 · HIGH · boq — CSV/GAEB decimal precision
Export format strings `%.4f` минимум. Либо параметр `?precision=N`. Закрывает BUG-152.

### ENH-089 · HIGH · boq — GAEB XML import
Phase 1 promised feature (README: "Basic reporting (PDF summary)", "GAEB XML import/export"). Export есть, import не реализован. Закрывает BUG-153.

Implementation:
```python
@router.post("/boqs/import/gaeb/")
async def import_gaeb(file: UploadFile, project_id: UUID):
    content = await file.read()
    parsed = parse_gaeb_x83(content)  # lxml, same library as export
    boq = await create_boq_from_gaeb(parsed, project_id)
    return boq
```

### ENH-090 · HIGH · boq — import sanity checks
При импорте Excel/CSV:
- unit_rate change > 10x vs benchmark → warning (не block)
- quantity или unit_rate == 0 → info
- impossible units (ozkg?) → reject

Закрывает BUG-154.

### ENH-091 · HIGH · perf — retry middleware
```python
@middleware("http")
async def sqlite_retry_middleware(request, call_next):
    for attempt in range(3):
        try:
            return await call_next(request)
        except OperationalError as e:
            if "database is locked" in str(e) and attempt < 2:
                await asyncio.sleep(0.1 * (2 ** attempt))
                continue
            raise
```
Смягчает BUG-118/119 на SQLite (не полный fix, но снижает 500 rate).

### ENH-092 · HIGH · schedule — millestones (duration=0)
`compute_duration` должна уважать explicit `duration_days=0`:
```python
if "duration_days" in data and data["duration_days"] is not None:
    return data["duration_days"]  # respect explicit input including 0
return (end - start).days + 1
```
Закрывает BUG-160.

### ENH-093 · HIGH · perf — separate read engine
`app/database.py`:
```python
write_engine = create_async_engine(DATABASE_URL, ...)
read_engine = create_async_engine(DATABASE_URL, 
    pool_size=10, max_overflow=20,
    connect_args={"timeout": 5})
```
Read queries via `read_engine`, writes via `write_engine`. На PostgreSQL — можно read-replica.

---

## MEDIUM (14)

### ENH-094 · MEDIUM · fuzz — property-based testing в CI
Add `hypothesis` как dev dep; CI job `pytest --hypothesis-profile=ci` на 50 endpoints с 30min budget. Предотвращает регрессии BUG-124-149.

### ENH-095 · MEDIUM · workflows — idempotency на approve
Second approve на already-approved = 200 no-op (не 400). Idempotency-Key header.

### ENH-096 · MEDIUM · boq — export structured metadata sheet
Excel — добавить hidden sheet "_metadata" с JSON project/boq metadata. На import — распаковать обратно.

### ENH-097 · MEDIUM · boq — export GAEB metadata placement
Не помещать positions в "Ungrouped" fabricated section `ID="00"`. Mapping: `section.code → <ParentID>`.

### ENH-098 · MEDIUM · boq — GAEB unit lexicon symmetric
Maintain explicit mapping `internal → gaeb` и `gaeb → internal`. Test symmetric roundtrip.

### ENH-099 · MEDIUM · rbac — feedback endpoint rate-limit
`/api/v1/feedback` — либо require auth, либо strict IP-based rate limit (1/hour).

### ENH-100 · MEDIUM · perf — health exposes memory/cpu
```python
@router.get("/api/health")
async def health():
    import psutil
    p = psutil.Process()
    return {
        "status": "healthy", "version": "...",
        "memory_rss_mb": round(p.memory_info().rss / 1024 / 1024, 1),
        "threads": p.num_threads(),
        "open_fds": p.num_fds() if hasattr(p, 'num_fds') else None,
        "uptime_seconds": (datetime.utcnow() - _START_TIME).total_seconds(),
    }
```
Для production monitoring.

### ENH-101 · MEDIUM · perf — throttle last_login_at refresh
Обновлять не чаще чем раз в 5-10 минут per user. Закрывает BUG-161.

### ENH-102 · MEDIUM · rbac — automated matrix CI
Test из `test_p5_agent_h_rbac.py` — в CI как smoke. Автоматически ловит privilege-escalation регрессии.

### ENH-103 · MEDIUM · docs — document RBAC matrix
Per endpoint table: which role can do what. Auto-generate из `@require_role` / `@require_permission` декораторов.

### ENH-104 · MEDIUM · audit — every successful DELETE publishes event
`entity.deleted` event → audit subscribers. Text включает `{actor, resource_type, resource_id, timestamp}`. Сейчас audit cascade на delete может не всегда работать (см. BUG-052 Part 4).

### ENH-105 · MEDIUM · boq — bulk paste endpoint optimization
Sequential POSTs = 24 pos/s. Bulk endpoint `/boqs/{id}/positions/bulk/` уже существует — use it из UI paste path. Target 200+ pos/s.

### ENH-106 · MEDIUM · schedule — expose slack / total_float в gantt
Response уже содержит, но key inconsistency (`total_float` vs `total_slack`). Document canonical name.

### ENH-107 · MEDIUM · tender — deprecation headers на /procurement/tenders/
Одна из двух duplicate APIs (Part 3 BUG-037 + Part 4 Agent L confirmed) — пометить deprecated:
```
Deprecation: @1767225600  # unix epoch sunset date
Link: </api/v1/tendering/packages/>; rel="successor-version"
```

---

## LOW (6)

### ENH-108 · LOW · docs — RFI required filter documented
`GET /api/v1/rfi/` требует `?project_id=`. Document в OpenAPI `required: true`.

### ENH-109 · LOW · changelog — auto-tag every release
Pre-commit hook:
```bash
# .git/hooks/post-tag: if version line in CHANGELOG.md changes and new version isn't tagged, fail
```

### ENH-110 · LOW · logs — structured JSON logs in production
Сейчас `structlog` installed но частично использован. Полный переход на JSON structured логи упрощает production troubleshooting.

### ENH-111 · LOW · takeoff — duration_min/most_likely/max validation
Monte Carlo input: pessimistic ≥ most_likely ≥ optimistic ≥ 0. Если нарушено — 422.

### ENH-112 · LOW · fuzz — pytest-randomly для seed exploration
Fuzz seed вариация — разные random inputs каждый CI run (фиксированный seed записать для reproducibility).

### ENH-113 · LOW · observability — SQLite lock-contention metric
Metric `db_lock_contentions_total` counter → alert при > N/min. Видимость BUG-118/119 в production.

---

# Итого Part 5

**5 CRITICAL** приоритетов:
1. Role-guard destructive DELETEs (trivial fix, большой security win).
2. PostgreSQL migration path (архитектурный).
3. CO/Tender writeback events (business contract).
4. Submittal/RFI 500 mutations (critical workflow).
5. Pydantic strict validation (NaN/extra/int bounds — global hardening).

**Самое неожиданное из Part 5:** Change Order approval — **полностью decoupled** от проекта. Approve CO на +5M EUR — project.budget_estimate не меняется. Это delays нахождение проблемы until tender phase или production billing.

**Самое ценное из Part 5:** CPM computation точен до дня (Agent K 18/18). Это core construction-domain feature — она работает. Большинство остальных багов — infrastructure/RBAC/data-integrity, не domain logic.
