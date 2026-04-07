# OpenEstimator.io — Рекомендации по улучшению

> Дата: 2026-03-26
> После: полный аудит платформы (342 API теста, 46 E2E тестов, 18 страниц)

---

## КРИТИЧЕСКИЕ (нужно сделать)

### 1. PDF Export crash (connection reset)
**Проблема:** PDF export (`/api/v1/boq/boqs/{id}/export/pdf`) вызывает crash бэкенда на Windows. Connection reset при генерации больших PDF.
**Решение:** Обернуть генерацию PDF в `try/except`, использовать streaming response, проверить memory на больших BOQ (133+ positions).

### 2. Change Password endpoint возвращает 500
**Проблема:** `POST /api/v1/users/me/change-password` — 500 Internal Server Error.
**Решение:** Проверить service layer — скорее всего `hash_password` или `verify_password` вызывает ошибку при сравнении.

### 3. Schedule CPM расчёт крашится
**Проблема:** `POST /schedules/{id}/calculate-cpm` — 500 при наличии activities.
**Решение:** Добавить проверку на пустые `start_date/end_date`, обработку circular dependencies в графе.

---

## ВЫСОКИЙ ПРИОРИТЕТ (значительно улучшит UX)

### 4. Duplicate projects в Dashboard
**Проблема:** На dashboard в "Recent Projects" одни и те же проекты показываются по несколько раз (Test DACH, Test UK повторяются 5-6 раз). Это из-за множественных запусков тестов.
**Решение:** Добавить pagination/limit на dashboard, или дедупликацию по ID. Также стоит добавить bulk delete для тестовых проектов.

### 5. Onboarding tour перекрывает UI
**Проблема:** Tour dialog открывается при каждом логине и блокирует взаимодействие. Пользователь должен нажать Skip/Next.
**Решение:** Сохранять `tour_completed` в user profile или localStorage. Показывать только один раз для нового пользователя.

### 6. BOQ List дублирует BOQ при множественных тестах
**Проблема:** 21 BOQ в списке, многие дублируются ("Updated Test BOQ" × 7). Нет возможности bulk delete.
**Решение:** Добавить multi-select + bulk delete в BOQ list page. Фильтр "Show test data" → hide.

### 7. Числовой формат не адаптируется под регион
**Проблема:** Все числа показываются в формате `1,400.00` (US), даже для DACH проектов (должно быть `1.400,00`).
**Решение:** Использовать `Intl.NumberFormat` с locale из проекта. Для DACH → `de-DE`, для UK → `en-GB`.

---

## СРЕДНИЙ ПРИОРИТЕТ (UX improvements)

### 8. Empty state для новых пользователей
**Проблема:** Без demo проектов dashboard пустой — нет guidance что делать первым делом.
**Решение:** Добавить welcome card с 3 кнопками: "Install Demo Project", "Create First Project", "Import Existing BOQ".

### 9. Sidebar — группы Procurement и Tools свёрнуты по умолчанию
**Проблема:** Пользователь может не увидеть Tendering, Validation, Sustainability — они спрятаны в свёрнутых группах.
**Решение:** Если в группе есть активная страница — разворачивать автоматически. Или добавить badge с count на свёрнутую группу.

### 10. BOQ Editor — Quality Score всегда 100
**Проблема:** Если все позиции заполнены, score = 100 даже если цены нереалистичные (€85,000/m²). Score не учитывает benchmark comparison.
**Решение:** Добавить benchmark-based checks в validation: сравнение с медианой CWICR, warning если rate отклоняется > 3σ.

### 11. AI Estimate — кнопка "Generate" неактивна без текста
**Проблема:** Кнопка `Generate Estimate` disabled, но нет визуального hint почему. Пользователь может не понять.
**Решение:** Показать маленький текст "Enter project description to continue" под кнопкой.

### 12. Markup panel — нет visual feedback при toggle
**Проблема:** При toggle OFF/ON markup — grand total обновляется, но нет visual indicator что именно изменилось (сколько было → стало).
**Решение:** Показать `+5,230 EUR` или `-5,230 EUR` рядом с toggle на 3 секунды.

### 13. Export GAEB — нет preview
**Проблема:** GAEB XML скачивается без preview. Пользователь не знает что внутри.
**Решение:** Добавить "Preview GAEB" modal с tree view структуры LV.

### 14. Version History — нет diff view
**Проблема:** Snapshots показывают только name и date. Нет сравнения "что изменилось между версиями".
**Решение:** Добавить diff view: добавленные позиции (зелёный), удалённые (красный), изменённые (жёлтый).

---

## НИЗКИЙ ПРИОРИТЕТ (nice to have)

### 15. Keyboard shortcuts
- `Ctrl+S` — save snapshot
- `Ctrl+N` — add position
- `Ctrl+Shift+N` — add section
- `Ctrl+E` — export dialog
- `Ctrl+V` в grid → paste from Excel (автоматически)
- `F5` — recalculate rates

### 16. Drag-and-drop в BOQ
**Текущее:** Drag handle есть в grid, но reorder работает только через API.
**Улучшение:** Drag section → перемещает все дочерние позиции. Visual indicator drop zone.

### 17. Cost Database — batch import UI
**Текущее:** Import через файл работает, но нет progress bar и error summary.
**Улучшение:** Stepper: Upload → Preview → Map columns → Import → Summary (N imported, M skipped, K errors).

### 18. Mobile responsive
**Текущее:** Sidebar ломается на < 768px. BOQ grid не скроллится.
**Улучшение:** Collapsible sidebar, horizontal scroll для grid, sticky header.

### 19. Dark mode polish
**Текущее:** Dark mode работает, но некоторые компоненты (login page, onboarding cards) имеют hardcoded white backgrounds.
**Улучшение:** Аудит всех компонентов на `dark:` classes.

### 20. Real-time collaboration indicators
**Текущее:** Yjs imported но не wired.
**Улучшение:** Показать avatar пользователя рядом с позицией которую он сейчас редактирует.

---

## АРХИТЕКТУРНЫЕ

### 21. PostgreSQL migration
**Текущее:** SQLite для dev — работает, но не поддерживает concurrent writes.
**Решение:** Создать Alembic migration для PostgreSQL. Docker Compose уже настроен — нужно только `alembic upgrade head`.

### 22. Redis caching
**Текущее:** Redis в docker-compose, но не используется.
**Улучшение:** Кэшировать cost database search results (TTL=5min), BOQ grand totals, validation results.

### 23. File upload to MinIO
**Текущее:** MinIO в docker-compose, не используется. Файлы хранятся в-memory.
**Улучшение:** Сохранять uploaded PDFs, photos, CAD files в MinIO. Возвращать presigned URLs.

### 24. WebSocket для real-time updates
**Текущее:** Polling для обновлений.
**Улучшение:** WebSocket endpoint для: BOQ position updates, validation progress, AI job status.

### 25. Rate limiting
**Текущее:** Нет rate limiting — AI endpoints можно спамить.
**Решение:** Redis-based rate limiter: 10 AI requests/min per user, 100 API requests/min.

---

## i18n ДОПОЛНЕНИЯ

### 26. Отсутствующие переводы (17 языков)
**Текущее:** EN/DE/RU полностью покрыты. FR частично. 17 остальных языков — только базовые ключи.
**Решение:** Приоритет: FR, ES, ZH, AR, TR (топ-5 по рынку). Использовать AI translation → human review.

### 27. RTL поддержка (арабский)
**Текущее:** `ar` locale есть, `dir="rtl"` определён, но UI не инвертирован.
**Решение:** Добавить `[dir="rtl"]` CSS, flex-direction reverse, margin/padding mirror.

---

## КОНКУРЕНТНЫЕ ПРЕИМУЩЕСТВА (сохранять и развивать)

1. **AI Text → BOQ** — уникальная фича, нет у конкурентов
2. **AI Photo → BOQ** — уникальная фича
3. **20 языков** — конкуренты имеют 2-3
4. **Open source + self-hosted** — единственный в категории
5. **CWICR 55K cost items бесплатно** — конкуренты берут $5K+/year за базы
6. **Validation engine 15 rules** — уникальная функция в open-source сегменте
7. **Module marketplace architecture** — extensibility
8. **Multi-standard** (DIN 276 + NRM + MasterFormat) — большинство конкурентов поддерживают только 1

---

## ПРИОРИТИЗАЦИЯ

| # | Задача | Effort | Impact | Priority |
|---|--------|--------|--------|----------|
| 1 | PDF Export fix | S | HIGH | P0 |
| 2 | Change Password fix | XS | MED | P0 |
| 3 | CPM fix | S | MED | P1 |
| 4 | Dashboard dedup | S | HIGH | P1 |
| 5 | Tour persistence | XS | HIGH | P1 |
| 7 | Number format locale | M | HIGH | P1 |
| 8 | Empty state | S | MED | P2 |
| 10 | Benchmark validation | M | HIGH | P2 |
| 14 | Version diff | L | MED | P2 |
| 21 | PostgreSQL migration | M | HIGH | P2 |
| 26 | i18n 5 languages | L | HIGH | P3 |
| 27 | RTL Arabic | M | MED | P3 |
