# Getting Started

Three ways to run OpenConstructionERP. Pick whichever fits your setup.

## Path A: Desktop App (easiest)

Download the installer for your platform:

- **[openconstructionerp.com/download](https://openconstructionerp.com/download)**
- Or grab from the [latest GitHub release](https://github.com/datadrivenconstruction/OpenConstructionERP/releases/latest): Windows `.exe`, macOS `.dmg` (Apple Silicon), Linux `.deb` / `.AppImage`

Run the installer, launch the app. First launch takes about one minute to set up the local database. No Python, no Docker, no terminal required.

## Path B: pip install

Requires **Python 3.12+**.

```bash
pip install --upgrade openconstructionerp
openconstructionerp
```

The package ships the FastAPI backend and a pre-built React frontend in a single wheel. On first run it sets up an embedded PostgreSQL instance, loads demo data, and opens your browser at [localhost:8080](http://localhost:8080).

**Demo login:** `demo@openconstructionerp.com` / `DemoPass1234!`

## Path C: Docker

Download both Compose files and start the stack:

```bash
curl -fsSL https://raw.githubusercontent.com/datadrivenconstruction/OpenConstructionERP/main/docker-compose.quickstart.yml       -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/datadrivenconstruction/OpenConstructionERP/main/docker-compose.quickstart.image.yml -o docker-compose.override.yml
echo "POSTGRES_PASSWORD=$(openssl rand -base64 24)" >  .env
echo "JWT_SECRET=$(openssl rand -hex 32)"           >> .env
docker compose pull app
docker compose up -d
```

The app runs at [localhost:8080](http://localhost:8080).

**Demo login:** `demo@openconstructionerp.com` / `DemoPass1234!`

## Prerequisites

| Path | Requirement |
|------|-------------|
| Desktop | None |
| pip | Python 3.12+ |
| Docker | Docker with Compose v2 |
| Source development | Python 3.12+, Node.js 22+, PostgreSQL 16+ |

## What's Next

- Explore the demo project that ships with every fresh install.
- Import your own cost data (GAEB XML, Excel, CSV) via the Import module.
- Connect a CAD/BIM model through the 3D Viewer.

For building from source, running tests, or contributing, see [DEVELOPING.md](../DEVELOPING.md).
