# Architecture Overview

## System Diagram

```
                          +------------------+
                          |   React Frontend |
                          |   (TypeScript)   |
                          +--------+---------+
                                   |
                              HTTP / WS
                                   |
                          +--------+---------+
                          | FastAPI Backend   |
                          | (Python 3.12+)   |
                          +--------+---------+
                                   |
              +--------------------+--------------------+
              |                    |                    |
     +--------+-------+  +--------+-------+  +---------+------+
     | PostgreSQL 16+  |  | Redis          |  | MinIO (S3)     |
     | (primary store) |  | (cache, tasks) |  | (file storage) |
     +--------+--------+  +----------------+  +----------------+
              |
     +--------+--------+
     | Qdrant (optional)|
     | (vector search)  |
     +-----------------+
```

## Backend

The backend is a FastAPI application with **191 modules** under `backend/app/modules/`. Each module is a self-contained plugin with a `manifest.py` that declares metadata, dependencies, and validation rules. Modules are discovered and loaded automatically at startup.

A module typically contains:

| File | Purpose |
|------|---------|
| `manifest.py` | Module metadata and config |
| `models.py` | SQLAlchemy ORM models |
| `schemas.py` | Pydantic v2 request/response schemas |
| `repository.py` | Database queries |
| `service.py` | Business logic |
| `router.py` | FastAPI route handlers |

## Frontend

The frontend is a React 18 + TypeScript single-page application.

- **~180 feature directories** under `frontend/src/features/` (pages, panels, dialogs)
- **17 plugin modules** under `frontend/src/modules/` (self-registering extensions)
- **45 locale files** under `frontend/src/app/locales/`, 44 languages offered in the UI
- State management via Zustand, server state via React Query, tables via AG Grid, 3D via Three.js

## Stack

| Layer | Technology |
|-------|-----------|
| API framework | FastAPI, Pydantic v2 |
| Background tasks | Celery + Redis |
| Frontend | React 18, TypeScript, AG Grid, Three.js, PDF.js, Yjs |
| Database | PostgreSQL 16+ (pg_duckdb, pgvector, PostGIS) |
| CAD conversion | DDC cad2data pipeline |
| CV/OCR | PaddleOCR 3.0 + YOLOv11 |
| Vector search | Qdrant (prod) / pgvector (simple deploy) |
| File storage | MinIO (S3-compatible) / local filesystem (dev) |
| Real-time collaboration | Yjs + y-websocket |

## Key Design Decisions

- **Modules as plugins.** Drop a module into the modules directory and restart. No central registry to edit.
- **Validation is first-class.** Every module declares validation rules. Validation is mandatory in all workflows, not optional.
- **CAD via conversion.** No IfcOpenShell dependency. All BIM/CAD formats are converted to a canonical internal format through the DDC cad2data pipeline. Modules read and write canonical data only.
- **i18n everywhere.** Zero hardcoded user-facing strings. All text goes through the translation system.
- **AI-augmented, human-confirmed.** AI features produce suggestions with confidence scores. A human always reviews and approves before anything is applied.
- **Single-database simplicity.** PostgreSQL is the only required infrastructure dependency.

## Data Flow: CAD to Cost

```
Any CAD/BIM format
       |
  DDC cad2data (conversion)
       |
  Canonical format (internal)
       |
  +----+----+----+----+
  |    |    |    |    |
 BOQ  Cost  3D   QTO  Validation
      DB   View
```

All modules operate on the canonical format. Source formats (IFC, DWG, GAEB XML, Excel) are import/export boundaries, not internal representations.
