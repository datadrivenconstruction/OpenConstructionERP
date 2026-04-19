# QA Output — Part 3 (archived)

**Заморожено:** 2026-04-18 ~17:00

## Что внутри

| Файл | Описание |
|------|----------|
| `BUGS_part3.md` | 8 новых багов (2 MAJOR + 4 MINOR + 2 INFO) + 16 позитивных находок |
| `ENHANCEMENTS_part3.md` | 12 новых предложений (4 HIGH, 5 MEDIUM, 3 LOW) |

## Ключевые находки Part 3

- **BUG-032 (MAJOR)** — countries endpoint пустой (seed data missing)
- **BUG-033 (MAJOR)** — DACH markups применяются к US/UK проектам (German VAT в US смете)
- **BUG-034 (MINOR)** — markup order: spec vs actual
- **BUG-035 (MINOR)** — tax-configs пустые
- **BUG-036 (MINOR)** — unknown country ISO → 200 empty (должно 404)
- **BUG-037 (MINOR)** — duplicated tendering/procurement endpoints без deprecation

## Performance targets (CLAUDE.md) — все ✅

| Endpoint | Target | p95 измерено |
|----------|--------|--------------|
| /api/health | — | 14ms |
| /projects | < 200ms | 39ms |
| /costs/autocomplete | < 100ms | 75ms |
| /boq/{id}/structured (200 pos) | < 500ms | 190ms |

## Охват Part 3

- Markup math + order per spec
- EVM formulas, division-by-zero handling
- Document upload security (path traversal, null byte, executable rejection)
- Locale formatting + currency conversion
- Reports templates (README claim 12)
- Requirements EAC triplets
- Risk matrix 5×5
- OpenAPI completeness
- Performance benchmarks (4 targets, all pass)
- GAEB XML schema + UTF-8 umlaut roundtrip

## Автотесты добавлено в Part 3

40 новых (test_70–test_79). Итого — 231 автотест.

## Следующая часть

Part 4 — maximum depth, параллельное исследование через субагентов (UI, DB schema, deep security, AI providers, BIM/CAD, validation rules × negative cases, git history audit).
