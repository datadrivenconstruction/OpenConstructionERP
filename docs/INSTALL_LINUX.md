# Installing OpenConstructionERP on Linux (Ubuntu / Debian)

This page covers the Linux-specific gotchas that the generic `pip install openconstructionerp` instruction does not. If you are on Ubuntu 23.04 or newer (including Ubuntu 26), read this first - `pip install` directly to system Python will fail.

Tested on Ubuntu 22.04, 24.04, 26.04 and Debian 12.

A message during install or start that this page does not cover? See [Installation help](INSTALL_TROUBLESHOOTING.md) (also [online](https://openconstructionerp.com/install-help)).

---

## TL;DR

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv build-essential libpq-dev libjpeg-dev zlib1g-dev libgeos-dev
python3.12 -m venv ~/openconstructionerp-venv
source ~/openconstructionerp-venv/bin/activate
pip install --upgrade openconstructionerp
openconstructionerp --version
openconstructionerp
```

Open http://localhost:8080. Done. The legacy `openestimate` command still works as an alias of `openconstructionerp`.

That start binds to `127.0.0.1`, so the page opens on the server itself and nowhere else. To reach it from another machine, start it as `openconstructionerp serve --host 0.0.0.0 --port 8080` and open the firewall for that port.

---

## What the machine needs

Give it **3 GB of memory on a dedicated server**. That is a floor rather than
a recommendation, and the difference matters: below it the machine runs
perfectly well until the first country cost pack import, and then stops, in
the way described a few paragraphs down.

Here is the arithmetic, measured rather than estimated. The application with
every module loaded sits at roughly 800 MB before it serves a request.
PostgreSQL beside it wants another 200 to 400 MB. The operating system takes
its own share. That is most of one and a half gigabytes at idle, and idle is
not where the trouble is.

The peak is not the application, it is the one off import of a country cost
pack. A pack expands from a compressed file into hundreds of thousands of
database rows, and that import was measured at roughly 1.2 GB on top of
everything else from 17.7.0 onward, against roughly 4 GB before it. On 17.6.0
and earlier the load cannot finish on a small machine at all, so if a pack is
what you came for, check `openconstructionerp --version` first.

Add the idle figure to the import peak and two gigabytes does not fit. Three
does, with enough margin that the kernel is never choosing between your
database and your application. Dedicated is part of the figure: on a shared or
burstable instance the memory is only nominally yours, and the moment that
matters is the one moment you cannot retry cheaply.

Most cloud images ship with no swap file, Hetzner among them, which leaves no
cushion whatsoever. The moment the kernel runs short it picks the largest
process and sends it SIGKILL. Python cannot catch SIGKILL, so there is no
traceback, no error in the log and nothing in the browser except a connection
that stopped answering. The import runs inside the API process, so the whole
server goes with it rather than one failed request.

Two gigabytes of swap is usually enough and costs nothing but disk:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -m                      # Swap: should now show about 2048
```

To find out whether this is what happened to a server that has already died,
ask the kernel rather than the application log:

```bash
dmesg | grep -i "killed process"
journalctl -k --since "2 hours ago" | grep -i "out of memory"
```

If an import was interrupted, start it again. Work items are keyed by code and
region and an existing one is left untouched, so a second run cannot duplicate
what the first one already wrote.

---

## 1. The PEP 668 trap (Ubuntu 23.04+)

Modern Ubuntu and Debian mark the system Python as "externally-managed" and refuse `pip install`:

```
error: externally-managed-environment
× This environment is externally managed
```

This is intentional and protects your OS. There are two correct fixes - pick one.

### Fix A: virtual environment (recommended)

```bash
python3.12 -m venv ~/openconstructionerp-venv
source ~/openconstructionerp-venv/bin/activate
pip install --upgrade openconstructionerp
```

The venv is isolated from the system. Reactivate it in any new shell with `source ~/openconstructionerp-venv/bin/activate`.

### Fix B: pipx (CLI-only, no venv ceremony)

```bash
sudo apt install -y pipx
pipx ensurepath
pipx install openconstructionerp
```

pipx creates a private venv per-tool and exposes the `openconstructionerp` command on your `PATH`. Restart the shell after `ensurepath`.

Do **not** use `pip install --break-system-packages` - it can corrupt your system Python.

---

## 2. Python 3.12 vs 3.13 on Ubuntu 26

OpenConstructionERP requires Python 3.12 or newer (`requires-python = ">=3.12"`). Ubuntu 26 ships with `python3.13` as the default `python3`, which works, but some heavy wheels (pyarrow, opencv-python-headless) may lag a release behind on 3.13. If `pip install` complains about missing wheels on 3.13, fall back to 3.12 explicitly:

```bash
sudo apt install -y python3.12 python3.12-venv
python3.12 -m venv ~/openconstructionerp-venv
source ~/openconstructionerp-venv/bin/activate
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

OpenConstructionERP depends on pandas, pyarrow, opencv-python-headless, Pillow, asyncpg, psycopg2-binary, cryptography. All of these publish manylinux wheels, so a fresh `pip install` on a supported architecture downloads pre-built binaries - no compiler needed.

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
openconstructionerp --version
openconstructionerp doctor    # per-check OK / WARN / ERROR report
openconstructionerp           # starts the server on port 8080
```

Then open http://localhost:8080. The first boot creates the embedded PostgreSQL database and seeds the three demo accounts (see the main README).

---

## 4b. `openconstructionerp: command not found`

If the `openconstructionerp` command (or its legacy alias `openestimate`) is not found, the package installed fine. pip just put the launcher in a per-user scripts folder that is not on your PATH (typically `~/.local/bin`). You do not need to fix PATH at all. Run it through Python instead, which always works from any folder:

```bash
python -m openconstructionerp
```

Every subcommand works the same way: `python -m openconstructionerp serve`, `python -m openconstructionerp doctor`, etc.

If you would rather have the short command, add the scripts folder to your PATH. Append one line to your shell profile (`~/.bashrc` for bash, `~/.zshrc` for zsh):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
openconstructionerp
```

Inside a virtualenv the launcher lives in `<venv>/bin`, which is already on PATH while the venv is active, so this only applies to a `pip install --user` setup.

---

## 5. "Address already in use" on port 8080 or 8000

Find what is holding the port and either stop it or pick another port:

```bash
ss -tlnp | grep -E ':(8080|8000)\b'
# or, if ss is not installed:
sudo lsof -iTCP:8080 -sTCP:LISTEN
```

Run on a different port. `--port` belongs to the `serve` subcommand, so name it:

```bash
openconstructionerp serve --port 9090
```

The bare `openconstructionerp` command takes no flags of its own, and there is no environment variable for the port. `OE_PORT` does appear elsewhere, which is what makes it misleading here: the one-line installer scripts (`scripts/install.sh`, `scripts/install.ps1`) read it to build exactly the `serve --port` line above, and `docker-compose.quickstart.yml` reads it as the host side of its port mapping. On a pip install the application itself never looks at it.

---

## 6. Running as a systemd service (optional)

For a long-running deployment, drop a unit file at `/etc/systemd/system/openconstructionerp.service`:

```ini
[Unit]
Description=OpenConstructionERP
After=network.target

[Service]
Type=simple
User=oe
WorkingDirectory=/home/oe
ExecStart=/home/oe/openconstructionerp-venv/bin/openconstructionerp serve --host 0.0.0.0 --port 8080
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

The host and the port go on the command line, because nothing in the application reads them from the environment. `--host 0.0.0.0` is what makes the service reachable from another machine; the default is `127.0.0.1`, which is what you want instead when a reverse proxy on the same host is the only client.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now openconstructionerp
sudo systemctl status openconstructionerp
journalctl -u openconstructionerp -f
```

Note: installs set up before the rename may still run under the legacy unit name `openestimate.service` - those keep working, this template applies to new installs.

---

## 7. BIM/CAD converters (.rvt / .ifc / .dwg)

Native CAD/BIM files are turned into element data (and, for RVT, 3D geometry) by
DDC Converters 2.0 (`datadrivenconstruction/cad2data-Revit-IFC-DWG`, release 2026.10).
They run on **Windows 10/11 x64**; Linux and macOS builds are coming soon, so on
Linux the app cannot install or run a converter yet.

What still works on Linux without a converter:

- **DXF** drawings are read natively, with no binary.
- **IFC** files import with simplified placeholder geometry instead of real
  meshes.
- DWG, RVT and RFA files need the converter. Convert them to DXF or IFC on a
  Windows machine (or in your CAD application) and upload that instead, or run
  OpenConstructionERP on Windows.

Linux builds of the converters are coming soon; this section will describe them when they are released.

---

## Troubleshooting checklist

| Symptom | Cause | Fix |
|---------|-------|-----|
| `error: externally-managed-environment` | PEP 668 | Use venv or pipx (section 1) |
| `Could not find a version that satisfies the requirement` | Python <3.12 | Install python3.12 (section 2) |
| Long compile output, then a `gcc` error | Source build, missing headers | Install apt packages (section 3) |
| `ModuleNotFoundError` after install | Wrong venv active | Re-run `source ~/openconstructionerp-venv/bin/activate` |
| `Address already in use` | Port 8080 taken | `ss -tlnp \| grep 8080`, then `openconstructionerp serve --port 9090` (section 5) |
| `openconstructionerp: command not found` after pipx | Path not refreshed | `pipx ensurepath` then open a new shell |
| The server stops answering while a country cost pack loads, nothing in the log | The kernel out of memory killer, not the application | Add swap and run 17.7.0 or newer (see "What the machine needs"), confirm with `dmesg \| grep -i "killed process"` |
| Opens with `curl` on the server, unreachable from any other machine | The default bind is `127.0.0.1` | Start it as `openconstructionerp serve --host 0.0.0.0 --port 8080` (section 6) |
| An RVT/DWG upload says the converter is not available | DDC Converters 2.0 run on Windows 10/11 x64 (Linux and macOS coming soon) | Upload DXF or IFC instead, or run on Windows (section 7) |

If you still cannot install, run `openconstructionerp doctor` (or `python -m openconstructionerp doctor`) and open an issue with the full output: https://github.com/datadrivenconstruction/OpenConstructionERP/issues
