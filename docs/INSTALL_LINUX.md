# Installing OpenConstructionERP on Linux (Ubuntu / Debian)

This page covers the Linux-specific gotchas that the generic `pip install openconstructionerp` instruction does not. If you are on Ubuntu 23.04 or newer (including Ubuntu 26), read this first - `pip install` directly to system Python will fail.

Tested on Ubuntu 22.04, 24.04, 26.04 and Debian 12.

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

Run on a different port:

```bash
openconstructionerp --port 9090
# or via env var
OE_PORT=9090 openconstructionerp
```

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
ExecStart=/home/oe/openconstructionerp-venv/bin/openconstructionerp
Restart=on-failure
Environment=OE_PORT=8080

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now openconstructionerp
sudo systemctl status openconstructionerp
journalctl -u openconstructionerp -f
```

Note: installs set up before the rename may still run under the legacy unit name `openestimate.service` - those keep working, this template applies to new installs.

---

## 7. BIM/CAD converters (.rvt / .ifc / .dwg / .dgn)

Native CAD/BIM files are turned into element data + 3D geometry by the DDC
`cad2data` converters. On Linux these ship as signed `.deb` packages from
`https://pkg.datadrivenconstruction.io` (amd64 only for now - arm64 is not yet
published). IFC also has a built-in text fallback parser, so `.ifc` files still
import without the binary - just with simplified placeholder geometry instead of
real meshes.

**You normally do not need this section.** The app installs the converter
automatically the first time you upload a CAD/BIM file (and you can also trigger
it from **Settings -> BIM Converters -> Install**). The download runs in the
background and the panel updates when it finishes. It tries several methods so it
works on the widest range of hosts:

- it does **not** require root - the packages are unpacked into the app's own
  data directory (`~/.openestimator/converters/`), so an unprivileged service
  account can provision the converter on its own;
- it does **not** require `dpkg`/`apt` - it unpacks the `.deb` payload with a
  built-in pure-Python reader when those tools are absent (minimal containers,
  non-Debian distros);
- it resumes interrupted downloads and retries slow or flaky links
  automatically, and self-tests the binary after install.

On a slow server link the first download (the IFC chain is ~114 MB) can take a
few minutes - that is expected; let it run.

Only if the automatic install genuinely cannot complete (no outbound network, a
blocking proxy, or an unsupported CPU architecture) install it from the terminal
as a fallback. **amd64 only** - check your arch with `uname -m` (`x86_64` =
amd64). On arm64 the binary converter is not yet published, so `.ifc` files fall
back to the built-in placeholder parser.

### Option A - signed apt source (recommended; auto-updates)

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://pkg.datadrivenconstruction.io/ddc-archive-keyring.gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/ddc-archive-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/ddc-archive-keyring.gpg] https://pkg.datadrivenconstruction.io stable main" \
  | sudo tee /etc/apt/sources.list.d/ddc.list
sudo apt update
sudo apt install -y ddc-ifcconverter     # or ddc-rvtconverter / ddc-dwgconverter / ddc-dgnconverter
```

### Option B - direct .deb download (no apt source; one converter)

Downloads the four IFC packages and lets `apt` resolve their order and system
dependencies. (Swap the names for `ddc-rvtconverter` etc. for other formats - see
the repo's `Packages` index for the current version numbers.)

```bash
cd /tmp
base=https://pkg.datadrivenconstruction.io/pool/main/d
wget $base/ddc-deps-kernel/ddc-deps-kernel_27.2_amd64.deb
wget $base/ddc-deps-ifc/ddc-deps-ifc_27.2_amd64.deb
wget $base/ddc-thirdparty/ddc-thirdparty_18.4.3.0_amd64.deb
wget $base/ddc-ifcconverter/ddc-ifcconverter_18.4.3.0_amd64.deb
sudo apt install -y ./ddc-deps-kernel_27.2_amd64.deb ./ddc-deps-ifc_27.2_amd64.deb \
                    ./ddc-thirdparty_18.4.3.0_amd64.deb ./ddc-ifcconverter_18.4.3.0_amd64.deb
```

Either option installs the binary at `/usr/bin/IfcExporter` (or
`RvtExporter` / `DwgExporter` / `DgnExporter`). The app finds it automatically -
no restart needed. Confirm, then re-upload the model or click **Re-check** on the
BIM converters panel:

```bash
ls -l /usr/bin/IfcExporter        # should exist and be > 1 KB
```

---

## Troubleshooting checklist

| Symptom | Cause | Fix |
|---------|-------|-----|
| `error: externally-managed-environment` | PEP 668 | Use venv or pipx (section 1) |
| `Could not find a version that satisfies the requirement` | Python <3.12 | Install python3.12 (section 2) |
| Long compile output, then a `gcc` error | Source build, missing headers | Install apt packages (section 3) |
| `ModuleNotFoundError` after install | Wrong venv active | Re-run `source ~/openconstructionerp-venv/bin/activate` |
| `Address already in use` | Port 8080 taken | `ss -tlnp \| grep 8080` then `--port 9090` (section 5) |
| `openconstructionerp: command not found` after pipx | Path not refreshed | `pipx ensurepath` then open a new shell |
| BIM converter install "signal timed out", stuck on placeholder geometry | A slow link aborted an older build's blocking download | Fixed in 8.8.0+: the install now runs in the background, resumes, and unpacks without root or dpkg. Retry **Settings -> BIM Converters -> Install**; only if it still fails, install from the terminal (section 7) |

If you still cannot install, run `openconstructionerp doctor` (or `python -m openconstructionerp doctor`) and open an issue with the full output: https://github.com/datadrivenconstruction/OpenConstructionERP/issues
