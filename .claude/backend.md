# CLAUDE.md — Backend (FastAPI)

Parent: [../CLAUDE.md](../CLAUDE.md)

## Контекст

FastAPI backend для OpenEstimate. Async-first, module-based architecture.
Все бизнес-модули в `app/modules/`. Core framework в `app/core/`.

## Команды

```bash
uvicorn app.main:create_app --factory --reload --port 8000
pytest
pytest --cov=app --cov-report=term
ruff check app/ tests/
ruff format app/ tests/
alembic upgrade head
alembic revision --autogenerate -m "description"
```

## Архитектурные правила

### Layered Architecture

```
Router (HTTP) → Service (Business Logic) → Repository (Data Access) → Database
                     ↕                            ↕
                  Events/Hooks              SQLAlchemy Models
                     ↕
                 Validation
```

- **Router**: только HTTP логика. НЕ бизнес-логика.
- **Service**: вся бизнес-логика. Stateless. Events, hooks, validation.
- **Repository**: data access. SQLAlchemy queries only.
- **Models**: SQLAlchemy ORM. Наследуют `app.database.Base`.
- **Schemas**: Pydantic v2 request/response.

### Database Conventions

- Table names: `oe_{module}_{entity}`
- All tables: `id` (UUID PK), `created_at`, `updated_at`, `created_by`
- JSONB для metadata
- Temporal: `valid_from`, `valid_to` для versioned records

### Validation — обязательна при любом импорте данных

```python
report = await validation_engine.validate(data=parsed, rule_sets=["gaeb", "boq_quality"])
if report.has_errors:
    return ImportResult(status="validation_failed", report=report)
```

### Performance Targets

- CRUD: < 200ms (p95)
- BOQ load 1000 positions: < 500ms
- Validation 1000 positions: < 2s
- CWICR search: < 100ms
