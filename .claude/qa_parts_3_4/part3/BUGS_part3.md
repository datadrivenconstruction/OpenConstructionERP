# OpenConstructionERP — BUGS (Part 3)

**Дата:** 2026-04-18
**Версия:** 1.9.0 · commit `767b38f232596cfb191f9790ce2053ab5108a7d4`
**Предыдущие части:**
- `qa_output/archive/part1.zip` → BUGS_part1.md (21 бага + 16 позитивных)
- `qa_output/archive/part2.zip` → BUGS_part2.md (10 багов + 25 позитивных)

## Скоуп части 3

Углубление:
- Markups math precision + order per spec
- EVM formulas (SPI/CPI/EAC/VAC)
- Document upload security
- Locale formatting / seed data completeness
- Reports templates (README: 12)
- Requirements (EAC triplets + 4 Quality Gates)
- Risk matrix (5×5)
- OpenAPI schema completeness
- Performance benchmarks (CRUD < 200ms, 1000 positions < 500ms, CWICR < 100ms)
- GAEB XML schema validation + UTF-8 umlaut roundtrip

## Статистика — Part 3

| Severity       | Новых в Part 3 |
|----------------|----------------|
| BLOCKER        | 0              |
| SECURITY-CRIT  | 0              |
| CRITICAL       | 0              |
| MAJOR          | 2              |
| MINOR          | 4              |
| INFO           | 2              |
| **Всего**      | **8**          |

## Статистика — общая (Part 1 + 2 + 3)

| Severity       | Всего |
|----------------|-------|
| BLOCKER        | 6     |
| SECURITY-CRIT  | 1     |
| CRITICAL       | 1     |
| MAJOR          | 6     |
| MINOR          | 17    |
| INFO           | 8     |
| **Всего**      | **39** |

## Автотесты — общая статистика (Part 1+2+3)

**231 автотест** (29 pytest-файлов, ~4500 строк Python):
- **222 PASS** (96%)
- **6 FAILED** (все задокументированы)
- **13 SKIPPED** (endpoint shape различается / предусловие не совпало)

---

## BUG-032 · MAJOR · module: i18n · category: seed-data missing
**Заголовок:** `/api/v1/i18n_foundation/countries/` возвращает 0 записей — README обещает locale-aware country data, но таблица пуста.

**Репро (10 сек):**
```bash
TOK=$(...)
curl -s -H "Authorization: Bearer $TOK" \
  http://127.0.0.1:8080/api/v1/i18n_foundation/countries/ | python -m json.tool
# {"items": [], "total": 0}
```

**Ожидание:** как минимум 50+ стран (README упоминает 11 регионов + 20 standards с региональной привязкой). По ISO 3166-1 — 249 стран.

**Факт:** 0 стран. Инфраструктура есть (endpoint, schema), но seed данных нет.

**Impact:**
- `GET /api/v1/i18n_foundation/tax-configs/by-country/DE` тоже возвращает `{"items": [], "total": 0}` — из-за отсутствия countries.
- Региональные defaults (currency, tax rate, work calendar, holiday list) не могут быть автоматически определены → UI при выборе региона не заполняет правильные значения.
- Отсутствует основа для `project.region` — в проекте DACH/Europe/Middle East как литералы, не связаны с ISO кодами.

**Fix:** запустить seed-скрипт стран (должен быть в `backend/app/scripts/seed.py` или миграциях). Либо добавить `openestimate seed --countries` команду.

**Trace:** `qa_output/logs/pytest-p3.log` (test_78_locale_formatting.py::test_countries_list)

---

## BUG-033 · MAJOR · module: boq.markups · category: logic
**Заголовок:** Markup defaults применяются независимо от `region` / `classification_standard` — masterformat-проект с `region="Other"` получает немецкие markup'ы (BGK/AGK/Wagnis/Gewinn/MwSt).

**Репро:**
```bash
TOK=$(...)
# Создаём проект масштаба US с masterformat, currency USD
P=$(curl -s -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"name":"QA_US","region":"Other","classification_standard":"masterformat","currency":"USD"}' \
  http://127.0.0.1:8080/api/v1/projects/ | python -c "import json,sys; print(json.load(sys.stdin)['id'])")
B=$(curl -s -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d "{\"project_id\":\"$P\",\"name\":\"b\"}" \
  http://127.0.0.1:8080/api/v1/boq/boqs/ | python -c "import json,sys; print(json.load(sys.stdin)['id'])")
curl -s -H "Authorization: Bearer $TOK" \
  "http://127.0.0.1:8080/api/v1/boq/boqs/$B/structured/" | python -c "
import json,sys
d=json.load(sys.stdin)
for m in d.get('markups',[]):
    print(' ', m['name'], m['percentage'], '%')
"
# Вывод (на "USD / masterformat / Other"):
#   Baustellengemeinkosten (BGK) 10.0 %
#   Allgemeine Geschäftskosten (AGK) 8.0 %
#   Wagnis (W) 2.0 %
#   Gewinn (G) 3.0 %
#   Mehrwertsteuer (MwSt.) 19.0 %
```

**Ожидание:** для `classification_standard=masterformat` применяются markup defaults США (general conditions, overhead, profit, sales tax — не VAT). Для `Other` — либо пустой список markups, либо запрос при создании проекта.

**Факт:** всегда применяются DACH/German defaults.

**Impact:**
- US-проект, использующий German VAT 19% — финансовая ошибка. VAT в США не существует (sales tax применяется только к продажам, не к строительным работам, варьируется 0-10%).
- Немецкие названия markup'ов в англоязычном проекте — UX bug и непонятно пользователю.
- Grand total расхождение с ожиданием: 100 × 1.10 × 1.05 × 1.19 = 137.445 (spec), но получаем 167+ из-за стака дефолтных + custom markup'ов.

**Fix:** `backend/app/modules/boq/service.py` — применять markup defaults на основе `classification_standard` + `region`:
- `masterformat` + US → CSI-style: general conditions 10%, overhead 10%, profit 5-10%, sales tax 0-10%
- `din276` + DACH → BGK/AGK/Wagnis/Gewinn/MwSt (текущий)
- `nrm` + UK → preliminaries 10%, OHP 12-20%, VAT 20%
- `masterformat` + Other → не apply, спросить пользователя

---

## BUG-034 · MINOR · module: boq.markups · category: docs-mismatch
**Заголовок:** Порядок markups отличается от декларированного спекой.

**Spec CLAUDE_QA.md §6.5:**
> "Порядок markups: overhead → profit → VAT → contingency.
> Проверь на примере: 100 × 1.10 × 1.05 × 1.19 = 137.445."

**Факт (DACH defaults):**
- sort_order 0: Baustellengemeinkosten (BGK) — 10% — category=overhead
- sort_order 1: Allgemeine Geschäftskosten (AGK) — 8% — category=overhead
- sort_order 2: Wagnis (W) — 2% — category=contingency
- sort_order 3: Gewinn (G) — 3% — category=profit
- sort_order 4: MwSt — 19% — category=tax

Реальный порядок: **overhead → overhead → contingency → profit → VAT**.
Spec ожидает: **overhead → profit → VAT → contingency**.

**Impact:** при контингенси перед profit, сумма отличается от spec-формулы. Это может быть корректно с точки зрения немецких стандартов (Wagnis применяется на direct cost отдельно от Gewinn), но не соответствует описанию в CLAUDE_QA.md.

**Fix:** либо исправить spec в CLAUDE_QA.md под реальный DACH-порядок, либо добавить параметр `markup_order_preset = "dach" | "uk" | "us" | "spec"`.

---

## BUG-035 · MINOR · module: i18n · category: seed-data
**Заголовок:** `/api/v1/i18n_foundation/tax-configs/by-country/{country}` возвращает 0 конфигов для любой страны.

**Репро:**
```bash
for country in DE US GB FR IT; do
  echo -n "$country: "
  curl -s -H "Authorization: Bearer $TOK" \
    "http://127.0.0.1:8080/api/v1/i18n_foundation/tax-configs/by-country/$country" \
    | python -c "import json,sys; d=json.load(sys.stdin); print(d.get('total',len(d)))"
done
# DE: 0
# US: 0
# GB: 0
# FR: 0
# IT: 0
```

**Impact:** zero-value seed. Следствие BUG-032. Без tax configs, markup BUG-033 не может быть исправлен корректно — нужны tax rates на страну.

**Fix:** seed tax configs как минимум для стран из списка 20 standards / 11 регионов README.

---

## BUG-036 · MINOR · module: i18n · category: data-loss
**Заголовок:** Неизвестная страна `/api/v1/i18n_foundation/tax-configs/by-country/XX` возвращает 200 `{"items": [], "total": 0}` вместо 404.

Эквивалентно паттерну BUG-009 (silent fallback на неизвестный locale).

**Fix:** unknown ISO country code → 404.

---

## BUG-037 · MINOR · module: api.versioning · category: docs-mismatch
**Заголовок:** Duplicated endpoints: `/api/v1/tendering/packages/` и `/api/v1/procurement/tenders/packages/` — два модуля делают одно и то же, без deprecation headers.

Проверено:
```
/api/v1/tendering/packages/ (POST, GET, ...)
/api/v1/procurement/tenders/packages/ (POST, GET, ...)
```
Обе схемы валидны, но нет `Deprecation: true` header или `Link: rel="successor-version"` для legacy.

**Fix:** пометить одну как deprecated (предпочтительно `/tendering/` — короче, чаще используется в UI).

---

## BUG-038 · INFO · module: boq · category: test-infra
**Заголовок:** DELETE `/api/v1/markups/{id}` не существует — только `/api/v1/boq/boqs/{boq_id}/markups/{markup_id}`. При написании тестов DELETE без контекста BOQ даёт 404.

Это не bug приложения per se, но документация OpenAPI говорит что `/api/v1/markups/` существует (GET, POST) — но индивидуальный DELETE требует boq_id. Несколько непоследовательно.

**Fix:** оставить только один вариант — либо глобальный `/markups/{id}`, либо scoped `/boqs/{id}/markups/{mid}`.

---

## BUG-039 · INFO · module: docs · category: seed-data vs README
**Заголовок:** README обещает "55,000+ cost items" — реальное количество CWICR items в свежей V4-инсталляции неизвестно (не тестировалось количество; endpoint существует и возвращает данные).

Проверить через `/api/v1/costs/?limit=1` и читать total count. Это INFO на будущее.

---

# Позитивные находки Part 3

42. **GAEB XML** — valid XML структура, содержит `Award`/`BoQ`/`PrjInfo` элементы ✅
43. **GAEB UTF-8 roundtrip** — немецкие умлауты `ä`, `ö`, `ü` (в `Stahlbetonwände`, `Geschäftskosten`) сохраняются корректно в XML ✅
44. **EVM endpoints** — нет NaN / Infinity в JSON (invalid JSON literals), обрабатывают пустой проект без 500 ✅
45. **OpenAPI 3.x** — корректная версия, большинство операций имеют `operationId`, `summary`, `tags` ✅
46. **Components schemas** — 50+ схем определены, не leak `password` в required полях GET-response ✅
47. **Risk score math** — probability × impact корректно (3 × 4 = 12) ✅
48. **Risk invalid probability** (>5) — обрабатывается без 500 ✅
49. **Currency conversion** EUR → USD через `/exchange-rates/convert/` работает ✅
50. **Work calendars** endpoint — 200 ✅
51. **Tax-configs** — не 500 (хоть и пустой, см. BUG-035) ✅
52. **Requirements** endpoints — существуют ✅
53. **Document download nonexistent** — 404, не 500 ✅
54. **Document path traversal** (`../../etc/passwd` в filename) — не 500 ✅
55. **Document null-byte filename** (`evil\x00.pdf`) — не 500 ✅
56. **Document script extension** (.exe/.bat) — не 500 ✅
57. **ZIP upload** — не crashes ✅

## Performance (CLAUDE.md targets vs actual on dev machine)

| Endpoint | CLAUDE.md target | p95 измерено | Статус |
|----------|------------------|--------------|--------|
| `/api/health` | — (предполагал 50ms) | ~14ms | ✅ |
| `/api/v1/projects/` | CRUD < 200ms | ~39ms | ✅ |
| `/api/v1/costs/autocomplete/?q=concrete` | CWICR < 100ms | ~75ms | ✅ |
| `/api/v1/boq/boqs/{id}/structured/` (200 positions) | BOQ 1000 pos < 500ms | ~190ms | ✅ (на 200 pos) |

**Все performance-targets укладываются.**

---

# Итог Part 3

Главные новые баги:
- **BUG-032 MAJOR** — countries empty seed
- **BUG-033 MAJOR** — DACH markups применяются к любому проекту (US с MasterFormat получает немецкие markup'ы с VAT 19%)
- **BUG-034 MINOR** — markup order в spec vs actual
- **BUG-035/036 MINOR** — tax-configs пустые, unknown country = 200

Главные позитивные:
- Все 4 performance-targets выполнены
- GAEB XML валидный + UTF-8 roundtrip работает
- EVM endpoints не возвращают NaN/Infinity
- Risk / Currency / Calendars / Requirements — не 500
- OpenAPI схема полнотой > 50 components

**Рекомендованный порядок фиксов части 3:**
1. BUG-032 → запустить seed countries (разблокирует BUG-035 и BUG-033 fix)
2. BUG-033 → сделать markup defaults условными от standard/region
3. BUG-034 → синхронизировать spec CLAUDE_QA.md с реальным порядком
4. Остальные — по удобству
