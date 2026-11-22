# Construction AI OS

<sub>A modified, independently maintained distribution of
<a href="https://github.com/datadrivenconstruction/OpenConstructionERP">OpenConstructionERP</a>
by Artem Boiko / DataDrivenConstruction (AGPL-3.0-or-later). Attribution and what changed: <a href="NOTICE">NOTICE</a>.</sub>

A self-hosted workspace for construction cost estimating and project delivery.
Estimating, cost data, CAD and BIM takeoff, scheduling, tendering, documents and
site records run in one installation - on your own machine or on your own server -
and its modules are enabled per project.

[Source code](https://github.com/abdelnabym519-cpu/Construction-AI-OS) · [Documentation](docs/) · [Development](DEVELOPING.md) · [Report an issue](https://github.com/abdelnabym519-cpu/Construction-AI-OS/issues)

## What it covers

| Area | In it |
| --- | --- |
| Estimating | Hierarchical BOQ editor with inline editing, resources and assemblies, markups, validation against DIN 276 / NRM / MasterFormat, export to Excel, CSV, PDF and GAEB XML (X83) |
| Cost data | Cost bases and a resource catalogue, semantic search across cost items, regional price adjustment, import from Excel or CSV or over the API |
| Takeoff | RVT, IFC and DWG through the DDC converters; measurement on PDFs and images; quantities applied to BOQ positions with the source parameter shown beside the unit |
| Delivery | 4D/5D scheduling, tendering, change orders, documents with versions, punch lists, daily diary with HSE tracking, clash detection |
| AI | Estimate drafts from text, a photograph or a PDF, and a cost advisor that answers against your own cost database. A draft is not an estimate; see the AI disclaimer below |
| Platform | One module per domain under `backend/app/modules`, enabled per project; a portal for people outside the installation; an HTTP API |

Every module is listed in [MODULES.md](MODULES.md).

## Install

Installation and startup problems are covered in the troubleshooting guide:
[English](docs/INSTALL_TROUBLESHOOTING.md), [Deutsch](docs/INSTALL_TROUBLESHOOTING.de.md),
[Русский](docs/INSTALL_TROUBLESHOOTING.ru.md). Every route below except the
desktop app needs Python 3.12 or newer; check with `python --version`.

### Desktop app

Download the installer for your system from the
[latest release](https://github.com/abdelnabym519-cpu/Construction-AI-OS/releases/latest):
Windows `.exe`, macOS `.dmg` (Apple Silicon), or Linux `.deb` / `.AppImage`.
Nothing else to install - the database runs locally inside the app.

**Your operating system warns you before it runs the installer, and that is
expected.** The desktop builds are unsigned because this project has no code
signing certificate. On Windows, SmartScreen says "Windows protected your PC";
choose More info, then Run anyway. If Windows 11 Smart App Control blocks the app
instead there is no Run anyway button, and
[docs/desktop/WINDOWS_BLOCKED.md](docs/desktop/WINDOWS_BLOCKED.md) sets out the
options. On macOS, Gatekeeper says the developer cannot be verified; open the app
from the Finder context menu and choose Open, or clear it with
`xattr -dr com.apple.quarantine`. Linux packages are unaffected. If you would
rather verify a download than trust the warning, every release carries
`SHA256SUMS` together with a Sigstore signature and certificate, so you can check
the bytes you received against what the build produced.

There is no Intel macOS build. On an Intel Mac, use pip or Docker.

The first launch takes about a minute while it sets up the local database; every
launch after that is fast.

### pip

```bash
pip install --upgrade openconstructionerp
openconstructionerp
```

One wheel, carrying the backend and the pre-built frontend. The first run sets up
a local embedded PostgreSQL database - no Docker and no separate server - asks
whether to load demo data, and opens your browser at http://localhost:8080. Every
later run is the same command.

If the command is not found after install, run it through Python instead, which
works on every operating system and never depends on PATH:

```bash
python -m openconstructionerp
```

`openconstructionerp doctor` prints a per-check OK/WARN/ERROR report about the
install it is run against. For PATH setup, including the Ubuntu and Debian
PEP 668 workarounds, see [docs/getting-started.md](docs/getting-started.md).

### One-line installer

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/abdelnabym519-cpu/Construction-AI-OS/main/scripts/install.sh | bash

# Windows (PowerShell)
irm https://raw.githubusercontent.com/abdelnabym519-cpu/Construction-AI-OS/main/scripts/install.ps1 | iex
```

Chooses Docker if it is installed, otherwise uv, otherwise a dedicated virtual
environment; installs there; puts the command on your PATH; and finishes with the
URL and how to sign in. Open a new terminal afterwards. Runs at
http://localhost:8080.

### Docker

From the published image:

```bash
curl -fsSL https://raw.githubusercontent.com/abdelnabym519-cpu/Construction-AI-OS/main/docker-compose.quickstart.yml       -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/abdelnabym519-cpu/Construction-AI-OS/main/docker-compose.quickstart.image.yml -o docker-compose.override.yml
echo "POSTGRES_PASSWORD=$(openssl rand -base64 24)" >  .env
echo "JWT_SECRET=$(openssl rand -hex 32)"           >> .env
docker compose pull app && docker compose up -d
```

Or build from source, which is also the better choice on Apple Silicon:

```bash
git clone https://github.com/abdelnabym519-cpu/Construction-AI-OS.git
cd Construction-AI-OS
echo "POSTGRES_PASSWORD=$(openssl rand -base64 24)" >  .env
echo "JWT_SECRET=$(openssl rand -hex 32)"           >> .env
make quickstart
```

Open http://localhost:8080. On Windows PowerShell the same steps need a different
redirect - a plain `>` there writes a `.env` that Compose cannot read - and
[docs/getting-started.md](docs/getting-started.md#path-c-docker) has them.

### From source

```bash
git clone https://github.com/abdelnabym519-cpu/Construction-AI-OS.git
cd Construction-AI-OS

pip install -e ./backend[server]
cd frontend && npm install && cd ..

# Linux / macOS
make dev

# Windows, two terminals
# Terminal 1: cd backend && uvicorn app.main:create_app --factory --reload --port 8000
# Terminal 2: cd frontend && npm run dev
```

Opens http://localhost:5173. Needs Python 3.12+ and Node.js 22 or newer.

### On a server

By default the app listens on `127.0.0.1`, so only the machine it runs on can
reach it. To make it reachable over a network:

```bash
openconstructionerp serve --host 0.0.0.0 --port 8080
```

Put a reverse proxy and TLS in front of it. For systemd and proxy configuration,
see [docs/INSTALL_LINUX.md](docs/INSTALL_LINUX.md).

### Demo data

Demo data is opt-in. It loads only when you answer Yes to the first-run prompt, or
set `SEED_DEMO=true`, or start with `serve --demo`. `serve --no-demo` starts
without it and persists that choice in `<data-dir>/demo_seed_choice.json`, so later
starts stay clean too.

When it loads it creates three accounts - admin, estimator and manager - and offers
a password-free demo sign-in. That sign-in is a separate switch an administrator
can turn off from the Settings screen without a restart; it is persisted in
`<data-dir>/demo_login_enabled.json`, it is on until somebody turns it off, and it
is available only while demo data is seeded. Each account's password comes from
`DEMO_USER_PASSWORD`, `DEMO_ESTIMATOR_PASSWORD` or `DEMO_MANAGER_PASSWORD` when you
set them, and is otherwise generated per installation and written to
`~/.openestimator/.demo_credentials.json` with mode 600. The startup log names that
file and never prints a password.

For a deployment anyone can reach, set those three variables to strong unique
secrets before the first start, or start with `serve --no-demo`. Do not reuse a
password from an example, a screenshot or an earlier version of this file.

## Interface languages

The interface is available in 44 languages, and choosing one switches the whole
surface rather than the screen you are on. Right-to-left layouts are supported for
the languages that need them.

The counts in this file are measured, not maintained by hand.
`scripts/check_public_language_counts.py` reads every language count in this
document and in [DEVELOPING.md](DEVELOPING.md), works out which question each one
is asking, and checks it against the tree: 45 locale files in
`frontend/src/app/locales/`, 44 entries in the `SUPPORTED_LANGUAGES` list in
`frontend/src/app/i18n.ts`, and 38 distinct languages once a regional variant is
folded into its base. The guard also fails when a count is reworded out of reach
of its own check, so a number here cannot go stale quietly.

## Stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, AG Grid - 44 languages |
| Database | PostgreSQL 16+; an embedded PostgreSQL starts automatically for local runs, so there is nothing to configure |
| Vector search | LanceDB (embedded) or Qdrant |
| CAD/BIM | [DDC Converters](https://github.com/datadrivenconstruction) for RVT, IFC and DWG |
| i18n | i18next - 44 languages, full RTL support |
| AI | Any LLM reachable over a REST API; bring your own key |

## Documentation

| Page | What it is |
| --- | --- |
| [docs/](docs/) | Everything that ships with the code |
| [docs/getting-started.md](docs/getting-started.md) | First run, PATH, platform notes |
| [docs/INSTALL_LINUX.md](docs/INSTALL_LINUX.md) | Server install with systemd and a reverse proxy |
| [docs/architecture/README.md](docs/architecture/README.md) | Where the architecture notes start |
| [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md) | System overview, stack and module structure |
| [docs/api/README.md](docs/api/README.md) | The HTTP surface |
| [DEVELOPING.md](DEVELOPING.md) | Building, testing and the guard lanes |
| [MODULES.md](MODULES.md) | The module list |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How contributions work in this repository |
| [CONTRIBUTORS.md](CONTRIBUTORS.md) | The people credited for the platform this distribution builds on |

## Security

Report vulnerabilities privately via
[GitHub Security Advisories](https://github.com/abdelnabym519-cpu/Construction-AI-OS/security/advisories/new)
on this repository. See [SECURITY.md](SECURITY.md) for the full
coordinated-disclosure policy and supported versions.

## AI disclaimer

AI suggestions produced by this software are preliminary estimates. A
qualified construction-estimation professional must verify all
quantities, classifications, and costs before any contractual or
tender-submission use. See [NOTICE](NOTICE) and [TERMS.md](docs/legal/TERMS.md) §4.

## Trademarks

All product names, logos, and trademarks referenced in this repository
are property of their respective owners. Any comparative references to
commercial categories or products are made for fair comparative purposes
based on publicly available information. Construction AI OS is an
independent modified distribution of the original OpenConstructionERP
project and is not affiliated with, endorsed by, or sponsored by any
third-party trademark owners. Full attributions in [NOTICE](NOTICE).

## License

**AGPL-3.0** - see [LICENSE](LICENSE). Third-party attributions in
[NOTICE](NOTICE).

You can freely use, modify, and distribute this software. If you modify
and deploy it as a service, AGPL §13 requires you to make the
corresponding source code available under the same license.

The upstream project offers **commercial licensing** for the original
OpenConstructionERP; see [COMMERCIAL-LICENSE.md](docs/legal/COMMERCIAL-LICENSE.md)
and the note at its top - it does not automatically extend to this
modified distribution. Deploying THIS distribution closed-source needs
permission from the copyright holders of the code you deploy: see the
NOTICE preamble.

No dependency we ship is under the AGPL, so the commercial license
covers everything a closed-source deployment runs. Releases up to and
including 18.7.0 shipped PyMuPDF, which is AGPL; PDF reading now goes
through pypdfium2 (Apache-2.0 / BSD-3-Clause). Section 4a of that file
has the details.

## Privacy and terms

- [PRIVACY.md](docs/legal/PRIVACY.md) - GDPR / UK DPA / CCPA / LGPD baseline
- [TERMS.md](docs/legal/TERMS.md) - terms of use for the hosted instance
- [COOKIES.md](docs/legal/COOKIES.md) - browser storage inventory
- [SECURITY.md](SECURITY.md) - responsible disclosure
