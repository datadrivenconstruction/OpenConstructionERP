# OpenConstructionERP — ENHANCEMENTS (Part 3)

**Дата:** 2026-04-18
**Предыдущие части:**
- `qa_output/archive/part1.zip` → 10 улучшений (установка)
- `qa_output/archive/part2.zip` → 16 улучшений (immutability, security, schedule)

## Статистика Part 3

| Priority | Кол-во |
|----------|--------|
| HIGH     | 4      |
| MEDIUM   | 5      |
| LOW      | 3      |
| **Всего**| **12** |

---

## ENH-027 · HIGH · Effort: M · area: i18n — country/tax seed data
**Наблюдение:** `/api/v1/i18n_foundation/countries/` и `tax-configs/by-country/*` возвращают 0 записей (BUG-032, BUG-035).
**Предложение:** запустить seed pipeline для ISO 3166-1 countries (249 штук) + tax rates для ключевых 50 юрисдикций:
```bash
openestimate seed --countries --tax-configs
```
Данные можно взять из открытых источников: Wikipedia ISO 3166-1, Eurostat VAT rates, Tax Foundation US sales tax.
**Зачем:** без этого `region` в projects — строка без значения. UI не может автоматически заполнять currency / VAT rate / work calendar при выборе страны.
**Референс:** `backend/app/modules/i18n_foundation/seed/` — если такой папки нет, создать.

---

## ENH-028 · HIGH · Effort: M · area: boq.markups — region-aware defaults
**Наблюдение:** DACH-markups (BGK/AGK/Wagnis/Gewinn/MwSt с немецкими названиями) применяются к US/UK-проектам (BUG-033).
**Предложение:** selector по `classification_standard + region`:
```python
MARKUP_PRESETS = {
    ("din276", "DACH"): [...],      # текущий
    ("masterformat", "US"): [       # новый
      {"name": "General Conditions", "category": "overhead", "percentage": 10, "apply_to": "direct_cost"},
      {"name": "Overhead", "category": "overhead", "percentage": 10, "apply_to": "direct_cost"},
      {"name": "Profit", "category": "profit", "percentage": 5, "apply_to": "cumulative"},
      # NO VAT — sales tax state-dependent
    ],
    ("nrm", "UK"): [...],
    # ...
}
```
Если preset не найден — не apply, позволить пользователю добавить вручную.
**Зачем:** финансовая корректность. US project с VAT 19% — ошибка в сметах, может стоить контракта.

---

## ENH-029 · HIGH · Effort: S · area: api — deprecation headers
**Наблюдение:** `/tendering/*` и `/procurement/tenders/*` дубликаты без deprecation (BUG-037).
**Предложение:** на legacy endpoint'е middleware добавляет:
```
Deprecation: true
Sunset: Sat, 01 Jan 2028 00:00:00 GMT
Link: </api/v1/tendering/packages/>; rel="successor-version"
```
**Зачем:** API-клиенты должны знать, что endpoint убирается. RFC 8594 (Sunset header) + IETF draft-dalal-deprecation-header.

---

## ENH-030 · HIGH · Effort: M · area: tests — CI performance budget
**Наблюдение:** CLAUDE.md декларирует performance targets (CRUD < 200ms p95, BOQ 1000 < 500ms, CWICR < 100ms). Наши тесты показали что они выполняются сейчас, но нет автоматического gate.
**Предложение:** CI job, запускающий `test_77_performance.py` с жёсткими `assert p95 < target` и fail-on-regress:
```yaml
- name: Performance budget
  run: |
    pytest qa_output/generated_tests/test_77_performance.py --timeout=120
```
**Зачем:** без этого любой PR может незаметно добавить N+1 query / блокирующий sync I/O и деградировать UX без явной ошибки.

---

## ENH-031 · MEDIUM · Effort: S · area: docs — sync CLAUDE_QA.md spec
**Наблюдение:** Spec CLAUDE_QA.md говорит markup order "overhead → profit → VAT → contingency", реальный DACH — "overhead → overhead → contingency → profit → VAT" (BUG-034).
**Предложение:** обновить CLAUDE_QA.md, чётко указав:
- "The math example `100 × 1.10 × 1.05 × 1.19 = 137.445` assumes standard preset (e.g. US/MasterFormat)."
- "DACH preset has different order (BGK/AGK/Wagnis/Gewinn/MwSt). Verify grand_total formula per selected preset."
**Зачем:** иначе новый QA-инженер будет писать тесты на несуществующий инвариант.

---

## ENH-032 · MEDIUM · Effort: M · area: reports — templates discoverable
**Наблюдение:** README обещает "12 built-in templates", но `/api/v1/reporting/templates/` не найден (тест skipped).
**Предложение:** явный endpoint `GET /api/v1/reporting/templates/` возвращающий список:
```json
{"templates": [
  {"id": "executive_summary", "name": "Executive Summary", "format": "pdf", "version": "1.0"},
  {"id": "boq_detailed", "name": "Detailed BOQ", "format": "pdf", ...},
  ...
]}
```
**Зачем:** без discoverable list'а пользователь не знает, какие отчёты доступны. UI вынужден хардкодить константы.

---

## ENH-033 · MEDIUM · Effort: M · area: documents — upload endpoint shape
**Наблюдение:** В OpenAPI есть `/api/v1/documents/*` endpoints, но конкретно upload endpoint не нашёлся через pattern matching `upload` (тест skipped).
**Предложение:** стандартизировать upload под `POST /api/v1/documents/` с multipart/form-data, явно задокументировать в OpenAPI через `application/multipart+form-data` content-type.
**Зачем:** API-клиенты должны найти endpoint по OpenAPI без догадок.

---

## ENH-034 · MEDIUM · Effort: S · area: i18n — error on unknown country
**Наблюдение:** `/tax-configs/by-country/XX` для unknown ISO код возвращает 200 empty. Это silent success (BUG-036).
**Предложение:** аналогично ENH-019 (locale fallback): вернуть 404 + hint `{"detail": "Country code 'XX' not recognized. Valid: ISO 3166-1 alpha-2, see /api/v1/i18n_foundation/countries/"}`.
**Зачем:** UI и API клиенты смогут обработать ошибку правильно.

---

## ENH-035 · MEDIUM · Effort: S · area: markups — expose preset info
**Наблюдение:** user создаёт BOQ и видит 5 DACH markup'ов сразу — не знает **откуда они взялись**.
**Предложение:** в `POST /boqs/` response добавить:
```json
{
  "id": "...",
  "name": "...",
  "markup_preset_applied": "dach.din276",
  "markup_preset_source": "project.region + project.classification_standard",
  ...
}
```
**Зачем:** UI может показать tooltip "5 German markups applied based on DACH region. Change preset →". Без этого — магия.

---

## ENH-036 · MEDIUM · Effort: L · area: boq — markup templates / presets library
**Наблюдение:** дефолтные markup'ы зашиты в код. Невозможно добавить новый regional preset без релиза.
**Предложение:** создать модуль `markup_presets` с CRUD через API + marketplace-like discovery:
```
GET /api/v1/markup-presets/    # все доступные
POST /api/v1/boqs/{id}/apply-preset/   # применить preset к BOQ
```
Preset — yaml/json файл в data-директории, редактируется без пересборки.
**Зачем:** для 20 standards × 11 regions матрица markup'ов должна быть data, не code. Маркетплейс (как в README для модулей) — естественное развитие.

---

## ENH-037 · LOW · Effort: S · area: security — document content-type validation
**Наблюдение:** Upload с filename `malicious.exe` не 500, но и не документировано отвергается ли на magic-bytes / content-type.
**Предложение:** явный documented list разрешённых типов:
- docs: pdf, doc, docx, odt
- images: jpg, png, gif, svg
- CAD: rvt, ifc, dwg, dgn
- tables: xlsx, csv

При загрузке других — 415 Unsupported Media Type с explicit list.
**Зачем:** предотвратить хранение исполняемых файлов на сервере (даже если ничего с ними не делают).

---

## ENH-038 · LOW · Effort: S · area: gaeb — schema version header
**Наблюдение:** GAEB export возвращает XML, но без явной версии (3.2 / 3.3 / X83 / X84).
**Предложение:** response header `X-GAEB-Version: 3.3` + атрибут корня XML `<GAEB version="3.3">`.
**Зачем:** subcontractor-импортёры могут не понимать какую DTD использовать.

---

# Итого Part 3

12 enhancement'ов. Высокий приоритет:
- ENH-027: seed countries / tax configs
- ENH-028: region-aware markup defaults (фиксит BUG-033)
- ENH-029: deprecation headers
- ENH-030: CI performance budget

Средний приоритет:
- ENH-032: report templates endpoint
- ENH-035: expose applied markup preset в response
- ENH-036: markup presets library
