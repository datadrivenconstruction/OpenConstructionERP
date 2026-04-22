# OpenConstructionERP

**The #1 open-source platform for construction cost estimation**

Professional BOQ, 4D scheduling, 5D cost model, AI-powered estimation, CAD/BIM takeoff — all in one platform.

---

> ### ▶ After `pip install`, type one command: **`openestimate`**
>
> That's the only thing you need to remember. It prints a welcome,
> asks **press `o` + Enter** to open the app in your browser, then
> starts the server at **http://127.0.0.1:8080**.

---

## Quick Start

```bash
pip install openconstructionerp
openestimate                 # welcome screen + o-to-open-browser + server
```

That's the whole first run. The bare `openestimate` command:

1. Prints a welcome with links to docs, issues, and the community chat.
2. Creates a local SQLite database and data folder under `~/.openestimate/`.
3. Starts the server at **http://127.0.0.1:8080** and opens your browser.

Demo login: `demo@openestimator.io` / `DemoPass1234!`

Prefer explicit steps? Run them yourself:

```bash
openestimate init-db         # create the local database
openestimate serve           # start the server
openestimate doctor          # health check if anything looks wrong
openestimate welcome         # re-print the welcome screen + support links
```

### Where to ask questions

- **Community chat (Telegram):** https://t.me/datadrivenconstruction
- **Bug reports / feature requests:** https://github.com/datadrivenconstruction/OpenConstructionERP/issues
- **Docs:** https://openconstructionerp.com/docs

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
