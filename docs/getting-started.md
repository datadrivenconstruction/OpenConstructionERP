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

> **Running on a VPS or remote server?** The default binds to localhost only.
> To make the app reachable over the network, start it with:
>
> ```bash
> openconstructionerp serve --host 0.0.0.0
> ```
>
> For a production setup with systemd, see [INSTALL_LINUX.md](INSTALL_LINUX.md).

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

## Watch

- [Install and set up your first project](https://www.youtube.com/watch?v=WjDK-uk9b1w) (4:41)
- [Full product walkthrough](https://www.youtube.com/watch?v=X06cIaroAeI) (12:00)
- [Build an estimate step by step](https://www.youtube.com/watch?v=zGgfX19b3gc) (4:48)
- More by topic in the [Video guides](../README.md#video-guides) section of the README, or on the [OpenConstruction Academy channel](https://www.youtube.com/channel/UCQ3IWLMLnBFwNeG5VBxXQ5Q/videos).

## What's Next

- Explore the demo project that ships with every fresh install.
- Import your own cost data (GAEB XML, Excel, CSV) via the Import module.
- Connect a CAD/BIM model through the 3D Viewer.

For building from source, running tests, or contributing, see [DEVELOPING.md](../DEVELOPING.md).
