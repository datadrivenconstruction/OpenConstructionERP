# QA Output — Part 5 (archived)

**Заморожено:** 2026-04-18 ~22:00

## Что внутри

| Файл | Описание |
|------|----------|
| `BUGS_part5.md` | 55 новых багов (8 CRITICAL + 25 MAJOR + 18 MINOR + 4 INFO) |
| `ENHANCEMENTS_part5.md` | 37 предложений (5 CRITICAL, 12 HIGH, 14 MEDIUM, 6 LOW) |
| `agent_reports/` | 6 full subagent reports + artifacts + JSON matrices |

## Методология Part 5 — 6 параллельных субагентов

| Агент | Область | Итог |
|-------|---------|------|
| H | RBAC exhaustive matrix | 421 endpoints × 4 роли, 5 findings |
| I | Import/Export roundtrip | 10+ data-loss findings, 0/3 формата lossless |
| J | Performance stress | 93.5% error rate на concurrent writes |
| K | Schedule/CPM deep | 18/18 CPM PASS (точны до дня), 2 medium bugs |
| L | Workflows deep | 19/20, 6 HIGH bugs |
| M | API fuzz | 32 unhandled 500s на 261 endpoints |

Σ — **~460 tests**, новые 55 багов.

## Ключевые находки Part 5

🔥 **8 CRITICAL:**
- BUG-115 estimator DELETE cost database (RBAC privilege escalation)
- BUG-116 estimator DELETE demo
- BUG-117 estimator DELETE schedule relationships
- BUG-118 93.5% error rate на concurrent writes (SQLite)
- BUG-119 read latency +146843% под write pressure
- BUG-120 CO approval НЕ обновляет project.budget_estimate (business contract violation)
- BUG-121 Tender select-winner нет writeback в BOQ
- BUG-122/123 Submittals/RFI ВСЕ mutation endpoints → 500

**Главный insight:** CPM-математика идеальна (Agent K 18/18). Большинство проблем — infrastructure / RBAC / business-logic writeback, не domain logic.

## Что в сумме (части 1–5)

- **Автотестов:** ~860+ (30+ pytest-файлов)
- **Багов:** 169 (7 BLOCKER + 4 SECURITY-CRIT + 21 CRITICAL + 53 MAJOR + 63 MINOR + 21 INFO)
- **Улучшений:** 113

## Следующая часть?

Part 6 — можно копать ещё:
- Requirements / Quality Gates полный аудит
- Collaboration (Yjs multi-user editing, presence, locks)
- Document versioning + CDE
- Reports templates × 12 — каждый протестировать
- Takeoff AI photo-estimate flow (нужны ключи)
- Full UI screenshot × 21 язык (требует fix auth bug BUG-047 Part 4)
- Data consistency invariants — после N random ops, проверить invariants
- Plugin / module lifecycle (install / uninstall / reload)
