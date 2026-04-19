# QA Output — Part 4 (archived)

**Заморожено:** 2026-04-18 ~20:00

## Что внутри

| Файл | Описание |
|------|----------|
| `BUGS_part4.md` | 75 новых багов (3 SECURITY-CRIT + 1 BLOCKER + 12 CRITICAL + 22 MAJOR + 28 MINOR + 9 INFO) |
| `ENHANCEMENTS_part4.md` | 38 предложений (6 CRITICAL, 10 HIGH, 14 MEDIUM, 8 LOW) |
| `agent_reports/` | 7 full subagent reports |

## Методология Part 4

**7 параллельных субагентов** через Agent tool — каждый на своей области:

| Агент | Область | Итог |
|-------|---------|------|
| A | Frontend Playwright deep UI | 28 tests, 26 passed, 2 failed, 9 findings |
| B | DB schema / SQLAlchemy (47 files, 108 models) | 44 defects (7 CRITICAL) |
| C | Deep security (SSRF/XXE/IDOR/JWT) | 17 tests, 3 SECURITY-CRITICAL findings |
| D | AI module architecture | 24 tests pass, 16 arch defects |
| E | BIM/CAD/Takeoff | 19 tests, no process crash, 8 defects |
| F | 42 validation rules × 2 cases | 84 tests, 79 passed, 5 xfail (latent) |
| G | CHANGELOG + git history | 5 bugs, regression finding |

Σ: **172 tests, 154 passed, 5 failed, 13 skip** + 75 багов найдено.

## Ключевые находки Part 4

🔥 **3 SECURITY-CRITICAL:**
- BUG-040 SSRF webhook URL accepts AWS metadata
- BUG-041 SSRF/LFI via file:// scheme
- BUG-042 JWT forgery via default dev secret + self-asserted role=admin

🔥 **BLOCKER:**
- BUG-043 Login endpoint hangs indefinitely for demo-admin

🔥 **12 CRITICAL:**
- BUG-044 change-password с new=current ломает аккаунт (regression)
- BUG-045 SQLite PRAGMA foreign_keys = OFF (все ondelete декоративные)
- BUG-046 22+ missing ForeignKey на project_id колонках
- BUG-047 SPA рендерит landing page на unauthenticated (no redirect)
- BUG-048 React error #31 на 422 login response
- BUG-049 SQLite lock contention → 500s
- BUG-050-055 type-lies, cascade bugs, regression

## Что в сумме (части 1–4)

- **Автотестов:** 403 (20+ pytest-файлов, ~8000 строк Python)
- **Багов:** 114 (7 BLOCKER + 4 SECURITY-CRIT + 13 CRITICAL + 28 MAJOR + 45 MINOR + 17 INFO)
- **Улучшений:** 76 (16 HIGH/CRITICAL + 21 MEDIUM + 15 LOW + остальные)

## Следующая часть

Part 5 — ещё deeper, можем копать:
- Complete RBAC matrix (все endpoints × все роли)
- Performance stress (1000 parallel requests)
- Full UI click-through with fixed auth (после BUG-043/047 fix)
- Import/export roundtrip (Excel → import → Excel — lossless?)
- Locale coverage by UI screenshot diff в 21 language
- API backwards compat (1.7 client × 1.9 server)
