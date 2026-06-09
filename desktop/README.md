# OpenConstructionERP Desktop

This folder holds the desktop build of OpenConstructionERP by DataDrivenConstruction. The desktop app is a native shell built with Tauri that bundles the full backend and an embedded PostgreSQL database into a single installer. People who install it do not need Python, pip, Docker, or any database setup. They download one file, run it, and the app takes care of the rest.

This README is for developers who build the installers. If you are a user looking to install and run the app, read `docs/desktop/INSTALL.md` instead.

## How it fits together

The native window is a Tauri v2 application (`src-tauri/`). On launch it picks a free local port, spawns the backend as a sidecar process, shows a branded splash screen while it waits for `/api/health` to come up, then navigates the webview to the running app. When the window closes, the sidecar is shut down with it.

The backend sidecar is a single self-contained executable produced by PyInstaller from `pyinstaller.spec`. It is the same FastAPI backend that runs everywhere else, frozen together with the built frontend, the data catalog, and the embedded PostgreSQL binaries. On first start the sidecar boots its own PostgreSQL cluster (via pixeltable-pgserver, no external Postgres needed) and serves the app over HTTP on the local port that Tauri assigns. All data lives locally under the user's home directory.

So a finished installer contains two things stitched together: the Tauri shell and the PyInstaller sidecar. Building it is a two-step process, sidecar first, then the Tauri bundle.

## Prerequisites

You need three toolchains on the build machine.

Rust stable with Cargo, plus the Tauri CLI (`cargo install tauri-cli` or use `cargo tauri` via the project). This compiles the native shell.

Node.js (the workflow uses Node 20) for building the React frontend. The frontend is built and shipped inside the sidecar.

Python 3.12 for building the sidecar with PyInstaller. Install the backend in editable mode first so all runtime dependencies are present: from `backend/`, run `pip install -e ".[dev]"`.

On Linux you also need the WebKitGTK and tray dependencies before the Tauri build: `libwebkit2gtk-4.1-dev`, `libappindicator3-dev`, and `librsvg2-dev`.

## Step 1: build the backend sidecar

Run the helper script from the repository root. It builds the frontend, runs PyInstaller against `pyinstaller.spec`, and copies the resulting binary into `src-tauri/binaries/` with the exact name Tauri expects.

```bash
./desktop/build-sidecar.sh
```

The script detects your platform's Rust target triple automatically. You can also pass one explicitly:

```bash
./desktop/build-sidecar.sh x86_64-pc-windows-msvc
```

The supported target triples are `x86_64-pc-windows-msvc` (Windows), `x86_64-apple-darwin` and `aarch64-apple-darwin` (macOS Intel and Apple Silicon), and `x86_64-unknown-linux-gnu` (Linux).

Tauri requires the sidecar to be named with the target triple appended, for example `openestimate-server-x86_64-pc-windows-msvc.exe` on Windows or `openestimate-server-aarch64-apple-darwin` on Apple Silicon. The script handles that naming and the `.exe` extension on Windows, and drops the file in `desktop/src-tauri/binaries/`. That path matches the `externalBin` entry in `tauri.conf.json`.

A few notes on what the spec does, so the output is correct. It freezes `backend/app/cli.py` as the entry point into a single self-contained build, with all backend modules auto-discovered as hidden imports. It explicitly keeps `asyncpg`, `psycopg2`, and `pixeltable_pgserver` because SQLAlchemy chooses its driver from the database URL at runtime, so PyInstaller's static analysis would otherwise miss them and the frozen sidecar could not reach its own database. A local hook under `desktop/hooks/` collects the embedded PostgreSQL binaries (postgres, initdb, pg_ctl, and the runtime libraries) so the cluster can actually start. The build ships `pyproject.toml` next to the bundled app so the sidecar reports the real product version rather than whatever happens to be pip-installed on the build machine. Heavy unused stacks like Torch, TensorFlow, SciPy, Matplotlib, and the Qt bindings are excluded to keep the binary lean, while numpy, pandas, openpyxl, and pyarrow stay in because the cost-database import path needs them.

## Step 2: build the Tauri installer

With the sidecar in place, build the platform installer from this folder:

```bash
cd desktop
cargo tauri build
```

Tauri reads `src-tauri/tauri.conf.json`, packages the shell together with the sidecar, and produces the native installer for the platform you are on. Outputs land under `src-tauri/target/release/bundle/`. The exact subfolder depends on the platform: NSIS `.exe` on Windows, `.dmg` on macOS, and both `.deb` and `.AppImage` on Linux.

The Windows installer is configured as a per-machine NSIS install and fetches WebView2 automatically if it is missing. The macOS bundle targets macOS 10.15 and up. The Linux `.deb` declares a dependency on `libwebkit2gtk-4.1-0`.

## Releases via CI

You do not normally build all three platforms by hand. The workflow at `.github/workflows/desktop-release.yml` runs on any pushed version tag (`v*`). It builds the sidecar on Windows, macOS arm64, and Ubuntu in parallel, then builds the matching Tauri bundle on each runner and attaches the installers to the GitHub Release for that tag. Tag a version, let CI run, and the `.exe`, `.dmg`, `.AppImage`, and `.deb` files appear on the release.

## Signing the Windows installers

The Windows `.exe` and `.msi` are signed with an Authenticode certificate after they are built. The certificate is a GlobalSign certificate held in an Azure Key Vault HSM, and the private key never leaves the vault. The release workflow signs each Windows installer by calling out to the vault with AzureSignTool, then re-uploads the signed files over the unsigned ones, so the binaries on the published release are the signed binaries.

For signing to run, set these five repository secrets in GitHub Actions:

AZURE_KV_URL is the Key Vault URL, for example https://myvault.vault.azure.net. AZURE_KV_CERT_NAME is the certificate name inside the vault. AZURE_KV_CLIENT_ID is the service principal application (client) id. AZURE_KV_CLIENT_SECRET is the Key Vault client secret for that service principal, and it must be a freshly rotated secret. AZURE_KV_TENANT_ID is the Entra (Azure AD) tenant id.

If these secrets are not set, on forks, on pull requests, or before you add them, the signing step skips cleanly and the build still succeeds with unsigned installers. The macOS and Linux installers are not signed by this step.

## Layout

```
desktop/
  build-sidecar.sh        Builds the frontend and the PyInstaller sidecar, names it for Tauri
  pyinstaller.spec        PyInstaller spec for the self-contained backend sidecar
  hooks/                  PyInstaller hook that collects the embedded PostgreSQL binaries
  src-tauri/
    tauri.conf.json       Tauri config: product name, bundle targets, NSIS, sidecar binary
    src/main.rs           Native shell: spawns the sidecar, splash, health wait, navigate
    binaries/             Where the named sidecar binary is placed before the Tauri build
    icons/                App and installer icons
```

Questions: info@datadrivenconstruction.io. Licensed under AGPL-3.0.
