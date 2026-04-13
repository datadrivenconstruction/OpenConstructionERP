# OpenConstructionERP

**The #1 open-source platform for construction cost estimation**

Professional BOQ, 4D scheduling, 5D cost model, AI-powered estimation, CAD/BIM takeoff — all in one platform.

## Quick Start

```bash
pip install openconstructionerp
openestimate init-db
openestimate serve
```

Opens at **http://localhost:8080** with SQLite — zero configuration needed.

Demo login: `demo@openestimator.io` / `DemoPass1234!`

If anything goes wrong, run `openestimate doctor` for diagnostics.

## Features

- **BOQ Editor** — Hierarchical Bill of Quantities with AG Grid, markups, validation, export (PDF/Excel/CSV/GAEB)
- **55,000+ Cost Items** — CWICR database across 11 regions with resource breakdown
- **7,000+ Resource Catalog** — Materials, labor, equipment with prices
- **AI Estimation** — Generate BOQ from text, photo, PDF, Excel, or CAD/BIM (7 LLM providers)
- **4D Schedule** — Gantt chart with CPM, dependencies, auto-generate from BOQ
- **5D Cost Model** — Earned Value Management, S-curve, budget tracking
- **20 Regional Standards** — DIN 276, NRM, MasterFormat, GAEB, and 16 more
- **21 Languages** — Full i18n with RTL support
- **42 Validation Rules** — Automatic compliance checking

## CLI Commands

```bash
openestimate serve   [--host HOST] [--port PORT] [--data-dir DIR] [--open] [--quiet]
openestimate init-db [--data-dir DIR]    # Create local SQLite DB + data dirs
openestimate doctor  [--port PORT]       # Run installation health checks
openestimate seed    [--demo]            # Load demo project data
openestimate version                     # Show version info
```

The `openconstructionerp` command is also available as a longer alias for both binaries.

## Links

- [Documentation](https://openconstructionerp.com/docs)
- [GitHub](https://github.com/datadrivenconstruction/OpenConstructionERP)
- [Telegram Community](https://t.me/datadrivenconstruction)

## License

AGPL-3.0 — [Data Driven Construction](https://datadrivenconstruction.io)
