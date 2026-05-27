# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Qdrant vector-DB supervisor — no Docker, no daemon.

Mirrors the existing converter-installer pattern from
:mod:`app.modules.takeoff.router` and :mod:`app.modules.boq.cad_import`:
we keep one binary under ``~/.openestimator/qdrant/`` and spawn it as a
plain subprocess whenever a feature that needs it (currently only
``/match-elements``) discovers the URL is unreachable.

Why no Docker?
--------------

Every other heavy dependency in OpenConstructionERP degrades gracefully
to a local-only path: PostgreSQL → SQLite, Redis → in-memory cache,
MinIO → local filesystem. Qdrant used to require a docker-compose
profile (``--profile ai up -d qdrant``) which made it the only thing
keeping Docker on the critical path. Qdrant ships a single self-contained
binary on every platform — using that directly removes the last Docker
dependency for a one-machine install.

Layout
------

::

    ~/.openestimator/qdrant/
        qdrant.exe          (Windows) or qdrant (Linux/macOS)
        config/
            config.yaml     (storage + service defaults)
        storage/            (Qdrant's collections live here)
        snapshots/          (incoming snapshot files)

The binary is fetched from GitHub Releases on demand by
:func:`install_qdrant_native`. The asset name pattern is
``qdrant-{triple}.{archive}`` — see :data:`_PLATFORM_ASSET` for the
mapping.

Lifecycle
---------

* :func:`find_qdrant_binary` — fast path-stat lookup, no network.
* :func:`probe_qdrant` — 1.5 s ``GET /readyz`` health probe.
* :func:`spawn_qdrant` — ``subprocess.Popen`` detached from the parent
  process so the server keeps running across uvicorn reloads.
* :func:`install_qdrant_native` — downloads + extracts the latest
  release for the current platform.

We do NOT track child PIDs across requests — re-spawning when the port
is already bound is harmless (Qdrant refuses to start and exits, the
existing instance keeps serving). For the same reason we do not try to
kill an existing instance on uninstall; the operator does that via Task
Manager / ``pkill qdrant``.
"""

from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────


QDRANT_HOME: Path = Path.home() / ".openestimator" / "qdrant"
QDRANT_STORAGE_DIR: Path = QDRANT_HOME / "storage"
QDRANT_SNAPSHOTS_DIR: Path = QDRANT_HOME / "snapshots"
QDRANT_CONFIG_DIR: Path = QDRANT_HOME / "config"

# GitHub Releases API for the official Qdrant repository. We pin to a
# specific tag rather than `/releases/latest` because Qdrant 1.17+
# introduced WAL clock replication (`newest_clocks.json`) which trips
# Windows Defender on fsync during snapshot restore — every install
# of a CWICR catalogue on native Windows fails with `os error 5`. The
# pinned tag is the newest version that:
#   1. Reads DDC's current BGE-M3 v3 snapshot format (post-RocksDB
#      removal, so 1.13–1.15 are out).
#   2. Does not write `newest_clocks.json`, so Defender never blocks
#      the fsync — the install just works with no exclusion needed.
# Verified empirically on 2026-05-13: 1.13.6 fails (RocksDB legacy),
# 1.16.3 succeeds end-to-end (HTTP 200, 55719 points loaded), 1.17.x
# and 1.18.0 fail with the Defender lock. Bump this with care: re-test
# on Windows before changing.
_QDRANT_REPO = "qdrant/qdrant"
_QDRANT_PINNED_TAG = "v1.16.3"
_PINNED_RELEASE_URL = f"https://api.github.com/repos/{_QDRANT_REPO}/releases/tags/{_QDRANT_PINNED_TAG}"

# Map (system, machine) → release asset filename pattern. Qdrant
# publishes static binaries for the three desktop triples we care
# about — Windows MSVC, Linux musl, macOS universal. The ``{tag}``
# placeholder is filled from the resolved release name (e.g. ``v1.12.5``).
_PLATFORM_ASSET: dict[tuple[str, str], str] = {
    ("windows", "amd64"): "qdrant-x86_64-pc-windows-msvc.zip",
    ("windows", "x86_64"): "qdrant-x86_64-pc-windows-msvc.zip",
    ("linux", "x86_64"): "qdrant-x86_64-unknown-linux-musl.tar.gz",
    ("linux", "amd64"): "qdrant-x86_64-unknown-linux-musl.tar.gz",
    ("linux", "aarch64"): "qdrant-aarch64-unknown-linux-musl.tar.gz",
    ("linux", "arm64"): "qdrant-aarch64-unknown-linux-musl.tar.gz",
    ("darwin", "x86_64"): "qdrant-x86_64-apple-darwin.tar.gz",
    ("darwin", "arm64"): "qdrant-aarch64-apple-darwin.tar.gz",
    ("darwin", "aarch64"): "qdrant-aarch64-apple-darwin.tar.gz",
}


def _binary_name() -> str:
    return "qdrant.exe" if sys.platform.startswith("win") else "qdrant"


def _expected_binary_path() -> Path:
    return QDRANT_HOME / _binary_name()


# ── Public helpers ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class QdrantHealth:
    reachable: bool
    url: str | None
    installed: bool
    binary_path: str | None
    storage_dir: str
    spawn_attempted: bool
    message: str
    install_hint: str
    download_url: str | None


def find_qdrant_binary() -> Path | None:
    """‌⁠‍Return the on-disk path to ``qdrant[.exe]`` or ``None`` if missing."""

    candidate = _expected_binary_path()
    if candidate.is_file() and candidate.stat().st_size > 1_000_000:
        return candidate

    # Fall back to PATH for users who installed Qdrant via Homebrew /
    # `cargo install qdrant` / apt. ``shutil.which`` handles ``.exe``
    # resolution on Windows transparently.
    on_path = shutil.which("qdrant")
    if on_path:
        return Path(on_path)
    return None


def probe_qdrant(url: str, *, timeout_s: float = 1.5) -> bool:
    """‌⁠‍Return ``True`` if Qdrant answers ``GET /readyz`` quickly.

    ``readyz`` is the official liveness endpoint — it returns 200 with
    the string ``all shards are ready`` once the storage layer has
    finished mounting collections. We accept any 2xx response so the
    probe stays compatible with older Qdrant builds that only expose
    ``/`` and not ``/readyz`` yet.
    """

    if not url:
        return False
    target = url.rstrip("/") + "/readyz"
    try:
        req = urllib.request.Request(target, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        pass
    # Some older builds return 4xx on /readyz before collections mount;
    # fall back to the root endpoint which always responds.
    try:
        req = urllib.request.Request(url.rstrip("/") + "/", method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False


def _write_default_config() -> Path:
    """Ensure ``config/config.yaml`` exists. Returns the file path.

    Qdrant works fine without a config (defaults to ``./storage`` /
    ``./snapshots`` relative to the binary's CWD) but we want absolute
    paths under ``QDRANT_HOME`` so a different CWD on respawn doesn't
    create a second storage tree. Minimal YAML — Qdrant fills in the
    rest of the schema from its compiled-in defaults.
    """

    QDRANT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    QDRANT_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    QDRANT_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    config_path = QDRANT_CONFIG_DIR / "config.yaml"
    if config_path.exists():
        return config_path

    # YAML is whitespace-sensitive but trivial enough to hand-write;
    # avoiding a PyYAML import keeps the supervisor dependency-free.
    config_path.write_text(
        "storage:\n"
        f"  storage_path: {json.dumps(str(QDRANT_STORAGE_DIR))}\n"
        f"  snapshots_path: {json.dumps(str(QDRANT_SNAPSHOTS_DIR))}\n"
        "service:\n"
        "  host: 127.0.0.1\n"
        "  http_port: 6333\n"
        "  grpc_port: 6334\n",
        encoding="utf-8",
    )
    return config_path


def spawn_qdrant(binary_path: Path) -> int | None:
    """Start ``qdrant`` detached from the parent process. Returns pid.

    The child process is launched with:

    * working directory == ``QDRANT_HOME`` so any relative paths in
      Qdrant's compiled-in defaults land under our control.
    * ``--config-path`` pointing at the on-disk YAML so storage and
      ports survive across spawns.
    * ``stdin`` / ``stdout`` / ``stderr`` detached from the parent (file
      handles redirected to ``qdrant.log`` for post-mortem triage) so a
      uvicorn reload doesn't drag the server down.
    * platform-specific detachment flags — on Windows we set
      ``CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS``; on POSIX we
      ``setsid`` via ``start_new_session=True``.

    Returns ``None`` if the spawn fails (rare — usually means the binary
    is missing executable bits on POSIX).
    """

    if not binary_path.is_file():
        logger.warning("spawn_qdrant: binary missing at %s", binary_path)
        return None

    config_path = _write_default_config()
    log_path = QDRANT_HOME / "qdrant.log"

    # POSIX needs the binary executable; the unzip step we use for
    # tar.gz preserves permissions but ``shutil.unpack_archive`` on a
    # zip dropped to a NFS share can drop the executable bit. Add it
    # back idempotently — it's a no-op when already set.
    if not sys.platform.startswith("win"):
        try:
            mode = binary_path.stat().st_mode
            binary_path.chmod(mode | 0o111)
        except OSError as exc:
            logger.debug("spawn_qdrant: chmod failed (continuing): %s", exc)

    cmd = [str(binary_path), "--config-path", str(config_path)]

    creation_flags = 0
    kwargs: dict = {
        "cwd": str(QDRANT_HOME),
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }

    try:
        log_fh = log_path.open("ab", buffering=0)
    except OSError as exc:
        logger.warning("spawn_qdrant: could not open log file: %s", exc)
        log_fh = subprocess.DEVNULL  # type: ignore[assignment]

    kwargs["stdout"] = log_fh
    kwargs["stderr"] = subprocess.STDOUT

    if sys.platform.startswith("win"):
        # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
        creation_flags = 0x00000200 | 0x00000008
        kwargs["creationflags"] = creation_flags
    else:
        kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603 — trusted binary path
    except (OSError, ValueError) as exc:
        logger.error("spawn_qdrant: Popen failed: %s", exc)
        return None

    logger.info("Spawned qdrant pid=%s from %s", proc.pid, binary_path)
    return proc.pid


def _resolve_release_asset() -> tuple[str, str]:
    """Return ``(asset_name, asset_download_url)`` for the current platform.

    Hits the pinned-tag Releases API (see ``_QDRANT_PINNED_TAG`` for
    why we don't use ``/latest``) and walks the asset list. Raises
    ``RuntimeError`` if the platform is unsupported (e.g. 32-bit
    Windows, FreeBSD) or GitHub is unreachable — the install endpoint
    surfaces this as a clear 503 to the UI. We fall back to the
    well-known ``releases/download/<tag>/<asset>`` URL pattern if the
    Releases API itself is rate-limited; the asset URL is stable per
    tag so this is safe.
    """

    system = platform.system().lower()
    machine = platform.machine().lower()
    asset_key = _PLATFORM_ASSET.get((system, machine))
    if asset_key is None:
        raise RuntimeError(
            f"No Qdrant binary published for {system}/{machine}. "
            "Supported: Windows x86_64, Linux x86_64/aarch64, macOS x86_64/arm64."
        )

    req = urllib.request.Request(
        _PINNED_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "OpenConstructionERP-qdrant-installer",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        # Rate-limited or transient GitHub error — fall back to the
        # well-known download URL for the pinned tag. The asset URL
        # pattern is stable, so this stays correct as long as Qdrant
        # doesn't rename the asset (we'd notice in CI on the first
        # download).
        if exc.code in (403, 404, 429):
            fallback = f"https://github.com/{_QDRANT_REPO}/releases/download/{_QDRANT_PINNED_TAG}/{asset_key}"
            logger.warning(
                "GitHub API rate-limited (%s) — falling back to direct URL %s",
                exc.code,
                fallback,
            )
            return asset_key, fallback
        raise RuntimeError(f"GitHub Releases API returned {exc.code}: {exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Could not reach GitHub Releases API: {exc}") from exc

    assets = payload.get("assets") or []
    for asset in assets:
        name = asset.get("name") or ""
        if name == asset_key:
            url = asset.get("browser_download_url")
            if url:
                return name, url

    available = ", ".join(a.get("name", "?") for a in assets)
    raise RuntimeError(
        f"Qdrant {_QDRANT_PINNED_TAG} release does not include asset {asset_key!r}. Available assets: {available}"
    )


def install_qdrant_native(*, force: bool = False) -> Path:
    """Download + extract the latest Qdrant release. Returns binary path.

    Idempotent: when ``find_qdrant_binary()`` already returns a path and
    ``force`` is False, this is a no-op and the existing path is
    returned. Use ``force=True`` to overwrite (the operator's "upgrade
    Qdrant" path).

    Raises ``RuntimeError`` with a user-readable message on any failure
    so the caller can pass it straight to ``HTTPException(detail=...)``.
    The partial download is cleaned up on failure — we don't want a
    stale .zip lingering after a network hiccup.
    """

    existing = find_qdrant_binary()
    if existing and not force:
        logger.info("install_qdrant_native: already installed at %s", existing)
        return existing

    QDRANT_HOME.mkdir(parents=True, exist_ok=True)
    asset_name, download_url = _resolve_release_asset()

    archive_path = QDRANT_HOME / asset_name
    try:
        urllib.request.urlretrieve(download_url, str(archive_path))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        archive_path.unlink(missing_ok=True)
        raise RuntimeError(f"Download from {download_url} failed: {exc}") from exc

    target = _expected_binary_path()
    target_dir = target.parent
    try:
        if asset_name.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as zf:
                # Qdrant's zip contains a single top-level qdrant.exe;
                # extract it directly so we don't create an extra nest.
                for member in zf.namelist():
                    base = Path(member).name
                    if base.lower() == "qdrant.exe":
                        with zf.open(member) as src, target.open("wb") as dst:
                            shutil.copyfileobj(src, dst)
                        break
                else:
                    raise RuntimeError(
                        f"Archive {asset_name} did not contain qdrant.exe — release layout may have changed."
                    )
        elif asset_name.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive_path, "r:gz") as tf:
                for member in tf.getmembers():
                    base = Path(member.name).name
                    if base == "qdrant" and member.isfile():
                        src = tf.extractfile(member)
                        if src is None:
                            continue
                        with target.open("wb") as dst:
                            shutil.copyfileobj(src, dst)
                        target.chmod(0o755)
                        break
                else:
                    raise RuntimeError(f"Archive {asset_name} did not contain a qdrant binary.")
        else:
            raise RuntimeError(f"Unsupported archive type: {asset_name}")
    except (zipfile.BadZipFile, tarfile.TarError) as exc:
        raise RuntimeError(f"Could not extract {asset_name}: {exc}") from exc
    finally:
        archive_path.unlink(missing_ok=True)

    if not target.is_file() or target.stat().st_size < 1_000_000:
        raise RuntimeError(f"Extraction left no valid binary at {target} — treat this as install failure.")

    _ = target_dir  # explicit
    logger.info("Installed Qdrant at %s (asset=%s)", target, asset_name)
    return target


def ensure_qdrant_running(url: str | None, *, spawn_if_installed: bool = True) -> QdrantHealth:
    """One-shot health probe + optional auto-spawn. Pure function — no router deps.

    Behaviour:

    * If ``url`` is None or empty → ``reachable=False``,
      ``installed=False``, message points at the install action.
    * If Qdrant answers on ``url`` → return reachable.
    * Else, if the binary is installed and ``spawn_if_installed`` is
      True → spawn it, wait up to 8 s for the port to come up, return
      the new state.
    * Else → return ``installed=False`` with a clear ``install_hint``.

    The 8 s wait is a budget, not a sleep — we poll every 400 ms so a
    fast-booting Qdrant (<1 s on SSD) returns almost immediately. The
    upper bound is short enough that a UI ``"Refresh status"`` button
    feels snappy.
    """

    binary = find_qdrant_binary()
    installed = binary is not None
    spawn_attempted = False

    if url and probe_qdrant(url):
        return QdrantHealth(
            reachable=True,
            url=url,
            installed=installed,
            binary_path=str(binary) if binary else None,
            storage_dir=str(QDRANT_STORAGE_DIR),
            spawn_attempted=False,
            message="Vector database is up and answering on the configured URL.",
            install_hint="",
            download_url=None,
        )

    # Unreachable — try to auto-spawn if we have the binary on disk.
    if url and binary and spawn_if_installed:
        spawn_attempted = True
        spawn_qdrant(binary)
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if probe_qdrant(url, timeout_s=0.8):
                return QdrantHealth(
                    reachable=True,
                    url=url,
                    installed=True,
                    binary_path=str(binary),
                    storage_dir=str(QDRANT_STORAGE_DIR),
                    spawn_attempted=True,
                    message="Vector database started from local binary.",
                    install_hint="",
                    download_url=None,
                )
            time.sleep(0.4)

    # Still down. Build a hint that does NOT mention Docker — the
    # native binary is the only recommended path here.
    if not installed:
        try:
            asset_name, asset_url = _resolve_release_asset()
            download_url: str | None = asset_url
            install_hint = (
                'Vector database is not installed. Click "Install Qdrant" to '
                f"download {asset_name} from the official GitHub Releases "
                "(no Docker required). The install completes in about 30 seconds."
            )
        except RuntimeError as exc:
            download_url = None
            install_hint = (
                f"Vector database is not installed and the auto-installer "
                f"could not reach the GitHub Releases API: {exc}. "
                "Download the binary manually from "
                "https://github.com/qdrant/qdrant/releases/latest and place it "
                f"at {_expected_binary_path()}."
            )
        return QdrantHealth(
            reachable=False,
            url=url,
            installed=False,
            binary_path=None,
            storage_dir=str(QDRANT_STORAGE_DIR),
            spawn_attempted=spawn_attempted,
            message="Vector database is not running.",
            install_hint=install_hint,
            download_url=download_url,
        )

    # Installed but spawn didn't bring it up in time. Common cause:
    # port 6333 in use by an older Qdrant the user already started.
    return QdrantHealth(
        reachable=False,
        url=url,
        installed=True,
        binary_path=str(binary) if binary else None,
        storage_dir=str(QDRANT_STORAGE_DIR),
        spawn_attempted=spawn_attempted,
        message=(
            "Vector database binary is installed but did not respond on "
            f"{url}. Another process may be holding the port, or the binary "
            "is still booting — wait 10 seconds and click Refresh."
        ),
        install_hint=(f"Binary found at {binary}. Check ~/.openestimator/qdrant/qdrant.log for startup errors."),
        download_url=None,
    )


__all__ = [
    "QDRANT_HOME",
    "QDRANT_STORAGE_DIR",
    "QdrantHealth",
    "ensure_qdrant_running",
    "find_qdrant_binary",
    "install_qdrant_native",
    "probe_qdrant",
    "spawn_qdrant",
]
