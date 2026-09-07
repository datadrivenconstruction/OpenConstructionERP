# OpenConstructionERP

Open-source construction cost estimation: BOQ, cost matching, CAD/BIM takeoff.

> ### After `pip install`, type one command: **`openconstructionerp`**
>
> That's the only thing you need to remember. It prints a welcome,
> asks you to **press `o` + Enter** to open the app in your browser, then
> starts the server at **http://127.0.0.1:8080** (and shows a login).

---

## Install

```bash
pip install openconstructionerp
```

Python 3.12+ required. No Docker, no separate PostgreSQL, no Redis. An embedded PostgreSQL database is bundled and starts on its own.

## First run

```bash
openconstructionerp
```

This single command:

1. Starts an embedded PostgreSQL database in your home data folder (no Docker, nothing to install)
2. Seeds demo data (projects, BOQs, cost catalogues)
3. Starts the API and UI at **http://127.0.0.1:8080**
4. Prints demo login credentials

No config files. No environment variables. It just works.

> **If `openconstructionerp` is not found** right after install, pip most likely
> put the launcher in a Scripts folder that is not on your PATH (this is common
> on Windows). Run it through Python instead. This works from any folder and is
> the exact same app:
>
> ```bash
> python -m openconstructionerp
> ```

## Subsequent runs

```bash
openconstructionerp
```

Same command every time. Your data persists between runs.

## Other commands

```bash
openconstructionerp init-db    # create the local database
openconstructionerp serve      # start the server
openconstructionerp doctor     # health check if anything looks wrong
openconstructionerp welcome    # re-print the welcome screen
```

## CLI reference

```bash
openconstructionerp serve   [--host HOST] [--port PORT] [--data-dir DIR] [--open] [--quiet]
openconstructionerp init-db [--data-dir DIR]    # Create the local database + data dirs
openconstructionerp doctor  [--port PORT]       # Run installation health checks
openconstructionerp seed    [--demo]            # Load demo project data
openconstructionerp version                     # Show version
```

## What you get

- **BOQ editor**: hierarchical bill of quantities with assemblies, formulas, multi-currency
- **Cost database**: import your own rates (Excel/CSV) or use the bundled example templates
- **Cost matching**: vector search matches line items to historical cost data
- **CAD/BIM takeoff**: quantities from DWG/DXF and IFC/RVT (via DDC, no IfcOpenShell)
- **4D / 5D**: cost-loaded schedule, earned value (SPI/CPI), cash-flow, what-if scenarios
- **Validation**: DIN 276, GAEB, NRM, MasterFormat rule packs flag issues at import
- **Reporting**: PDF/Excel exports, dashboards, BCF issue exchange

## Configuration (optional)

Everything works with zero config. To customise, pass flags or set environment variables:

```bash
openconstructionerp serve --port 9000 --data-dir /var/lib/oce

# Or via environment:
DATABASE_URL=postgresql+asyncpg://user:pass@host/db   # Use an external PostgreSQL instead of the embedded one
OE_DATA_DIR=/var/lib/oce                              # Change the data location
```

The port has no environment variable. It is chosen only by `serve --port`, so a
service definition or a launcher script has to put it on the command line.

## Development

The backend is a Python 3.12+ FastAPI application (Pydantic v2, async SQLAlchemy). PostgreSQL is the only supported database. For local development an embedded PostgreSQL (pixeltable-pgserver) runs in-process, so there is no Docker and no separate database server to install for a basic run. SQLite is not supported and was removed in v6.6.0. Leave `DATABASE_URL` unset to use the embedded server, or set it to point at an external PostgreSQL.

### Set up

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### Run the dev server

The simplest way is the CLI, which starts the embedded database, seeds demo data, and serves the API together with the built UI:

```bash
openconstructionerp serve --port 8080
```

To run just the API with autoreload against the app factory:

```bash
uvicorn app.main:create_app --factory --reload --port 8000
```

Interactive API docs are then at http://localhost:8000/api/docs and the raw OpenAPI schema at http://localhost:8000/api/openapi.json. See `docs/api/README.md` for the full HTTP API guide.

### Tests

```bash
cd backend
pytest                    # whole suite
pytest tests/unit         # unit tests only
pytest -k boq             # a subset by keyword
```

Tests run with pytest and pytest-asyncio (`asyncio_mode = auto`). The suite runs serially against one PostgreSQL database that the test harness provisions when the tests load.

### Formatting and linting

Code style is enforced with ruff (line length 120, target `py312`). Format and lint before committing:

```bash
ruff format .
ruff check .
```

The lint rule set is `E, F, W, I, N, UP, B, A, C4, PT, RET, SIM`. The exact configuration lives in `backend/pyproject.toml`.

## Links

- Docs: https://openconstructionerp.com
- Issues: https://github.com/DataDrivenConstruction/OpenConstructionERP/issues
- Source: https://github.com/DataDrivenConstruction/OpenConstructionERP

## License

AGPL-3.0-or-later. Commercial licensing available, contact info@datadrivenconstruction.io
