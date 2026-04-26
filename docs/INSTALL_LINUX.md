# Installing OpenConstructionERP on Linux (Ubuntu / Debian)

This page covers the Linux-specific gotchas that the generic `pip install openconstructionerp` instruction does not. If you are on Ubuntu 23.04 or newer (including Ubuntu 26), read this first — `pip install` directly to system Python will fail.

Tested on Ubuntu 22.04, 24.04, 26.04 and Debian 12.

---

## TL;DR

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv build-essential libpq-dev libjpeg-dev zlib1g-dev libgeos-dev
python3.12 -m venv ~/openestimate-venv
source ~/openestimate-venv/bin/activate
pip install --upgrade openconstructionerp
openestimate --version
openestimate
```

Open http://localhost:8080. Done.

---

## 1. The PEP 668 trap (Ubuntu 23.04+)

Modern Ubuntu and Debian mark the system Python as "externally-managed" and refuse `pip install`:

```
error: externally-managed-environment
× This environment is externally managed
```

This is intentional and protects your OS. There are two correct fixes — pick one.

### Fix A: virtual environment (recommended)

```bash
python3.12 -m venv ~/openestimate-venv
source ~/openestimate-venv/bin/activate
pip install --upgrade openconstructionerp
```

The venv is isolated from the system. Reactivate it in any new shell with `source ~/openestimate-venv/bin/activate`.

### Fix B: pipx (CLI-only, no venv ceremony)

```bash
sudo apt install -y pipx
pipx ensurepath
pipx install openconstructionerp
```

pipx creates a private venv per-tool and exposes the `openestimate` command on your `PATH`. Restart the shell after `ensurepath`.

Do **not** use `pip install --break-system-packages` — it can corrupt your system Python.

---

## 2. Python 3.12 vs 3.13 on Ubuntu 26

OpenConstructionERP requires Python 3.12 or newer (`requires-python = ">=3.12"`). Ubuntu 26 ships with `python3.13` as the default `python3`, which works, but some heavy wheels (pyarrow, opencv-python-headless) may lag a release behind on 3.13. If `pip install` complains about missing wheels on 3.13, fall back to 3.12 explicitly:

```bash
sudo apt install -y python3.12 python3.12-venv
python3.12 -m venv ~/openestimate-venv
source ~/openestimate-venv/bin/activate
python --version   # Python 3.12.x
pip install --upgrade openconstructionerp
```

On Ubuntu 22.04 / Debian 12 where 3.12 is not in the default repos, use the deadsnakes PPA:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.12 python3.12-venv
```

---

## 3. System packages for source-build fallback

OpenConstructionERP depends on pandas, pyarrow, opencv-python-headless, Pillow, asyncpg, psycopg2-binary, cryptography. All of these publish manylinux wheels, so a fresh `pip install` on a supported architecture downloads pre-built binaries — no compiler needed.

If pip falls back to building from source (uncommon CPU architecture, very new Python, locked-down corporate mirror), install the development headers first:

```bash
sudo apt install -y \
  build-essential \
  libpq-dev \
  libjpeg-dev \
  zlib1g-dev \
  libgeos-dev \
  python3.12-dev
```

---

## 4. Verify the install

```bash
openestimate --version
openestimate doctor    # per-check OK / WARN / ERROR report
openestimate           # starts the server on port 8080
```

Then open http://localhost:8080. The first boot creates a SQLite database and seeds the three demo accounts (see the main README).

---

## 5. "Address already in use" on port 8080 or 8000

Find what is holding the port and either stop it or pick another port:

```bash
ss -tlnp | grep -E ':(8080|8000)\b'
# or, if ss is not installed:
sudo lsof -iTCP:8080 -sTCP:LISTEN
```

Run on a different port:

```bash
openestimate --port 9090
# or via env var
OE_PORT=9090 openestimate
```

---

## 6. Running as a systemd service (optional)

For a long-running deployment, drop a unit file at `/etc/systemd/system/openestimate.service`:

```ini
[Unit]
Description=OpenConstructionERP
After=network.target

[Service]
Type=simple
User=oe
WorkingDirectory=/home/oe
ExecStart=/home/oe/openestimate-venv/bin/openestimate
Restart=on-failure
Environment=OE_PORT=8080

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now openestimate
sudo systemctl status openestimate
journalctl -u openestimate -f
```

---

## Troubleshooting checklist

| Symptom | Cause | Fix |
|---------|-------|-----|
| `error: externally-managed-environment` | PEP 668 | Use venv or pipx (section 1) |
| `Could not find a version that satisfies the requirement` | Python <3.12 | Install python3.12 (section 2) |
| Long compile output, then a `gcc` error | Source build, missing headers | Install apt packages (section 3) |
| `ModuleNotFoundError` after install | Wrong venv active | Re-run `source ~/openestimate-venv/bin/activate` |
| `Address already in use` | Port 8080 taken | `ss -tlnp \| grep 8080` then `--port 9090` (section 5) |
| `openestimate: command not found` after pipx | Path not refreshed | `pipx ensurepath` then open a new shell |

If you still cannot install, run `openestimate doctor` (or `python -m openconstructionerp doctor`) and open an issue with the full output: https://github.com/datadrivenconstruction/OpenConstructionERP/issues
