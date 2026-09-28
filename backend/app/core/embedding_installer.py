# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Encoder-weight installer - a non-critical background download.

Semantic search needs an encoder, and the encoder is the one asset the
platform cannot ship inside the package: the weights are hundreds of
megabytes and most installations never ask a semantic question. So they are
fetched once, in the background, from the model hub, and everything keeps
working while they are absent.

Shape
-----

This is deliberately the same shape as
:mod:`app.modules.match_elements.qdrant_supervisor`, which installs the
vector-database binary on first use: one install root under the platform's
data directory, a plain :mod:`urllib` download, partial files cleaned up on
failure, and a pure status function the router can hand straight to the UI.
A second, differently shaped installer beside that one would be a thing to
learn twice.

Layout
------

::

    <data dir>/models/
        intfloat--multilingual-e5-small/
            config.json
            model.safetensors
            tokenizer.json
            modules.json
            1_Pooling/config.json
            .oe_model_complete.json     <- written LAST

The marker file is the whole integrity story, and it is why an interrupted
download can never be loaded as a corrupt model: :func:`find_installed_model`
answers ``None`` until the marker exists, and the marker is written only after
every file has landed. Downloads stream into ``<name>.part`` and are renamed
into place one by one, so a half-written ``model.safetensors`` is never a file
the loader can open either.

Non-critical, three ways
------------------------

* Startup never waits for it. :func:`start_background_download` hands the work
  to a daemon thread and returns immediately.
* Nothing here raises into a request handler. The thread swallows everything
  into :data:`_progress`; the two public entry points a router calls
  (:func:`download_status`, :func:`start_background_download`) do not raise.
* A failure leaves the installation exactly as usable as it was. Semantic
  search already answers an honest ``503`` when no encoder is available, and
  every other feature never asked for one.

Why not ``huggingface_hub.snapshot_download``
---------------------------------------------

It would do the transfer well, but it is only importable when the semantic
extra is installed, which is exactly the case where the encoder is already
reachable. Depending on it would mean the installer cannot report why it
cannot run. ``urllib`` against the hub's public resolve endpoint has no such
hole, and it keeps this module dependency-free like its sibling above.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Reported states ──────────────────────────────────────────────────────
#
# Five, because a reader who cannot tell them apart cannot act. In order of
# what the reader should do about them: install the extra, wait, retry or read
# the error, use it, or turn it on.

STATE_LIBRARY_MISSING = "library_missing"
STATE_DOWNLOADING = "downloading"
STATE_FAILED = "failed"
STATE_READY = "ready"
STATE_NOT_REQUESTED = "not_requested"

#: Written last, into the model directory, to mark the download complete.
MARKER_FILENAME = ".oe_model_complete.json"

#: Suffix appended to a file while it is still arriving.
PART_SUFFIX = ".part"

#: Environment variable that overrides the per-deployment default in BOTH
#: directions. Truthy turns the background download on where it would be off
#: (an operator who does want an encoder on a server), falsy turns it off where
#: it would be on.
ENV_DOWNLOAD = "OE_DOWNLOAD_EMBEDDING_MODEL"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}

#: Model-hub origin. ``HF_ENDPOINT`` is the hub client's own convention for
#: pointing at a mirror, so honouring it costs nothing and gives locked-down
#: networks the same escape hatch they already use - and gives the tests a
#: local origin to install from, which is the only way to exercise this code
#: without pulling real weights.
_DEFAULT_ENDPOINT = "https://huggingface.co"

#: Files that are alternative serialisations of weights we already take, or
#: runtimes this platform does not use. Taking them turns a ~470 MB download
#: into several gigabytes of wheels nothing here can load.
_SKIP_SUFFIXES = (
    ".onnx",
    ".onnx_data",
    ".h5",
    ".msgpack",
    ".pt",
    ".pth",
    ".ot",
    ".tflite",
    ".mlmodel",
    ".mlpackage",
    ".gguf",
    ".md",
)

_SKIP_PREFIXES = (
    "onnx/",
    "openvino/",
    "coreml/",
    "tf_model",
)

#: The minimum that has to be on disk before the marker may be written.
#:
#: ``config.json`` is the floor, not a loadability proof: a sentence-transformers
#: model normally also carries ``modules.json``, and this deliberately does not
#: demand it, because a plain transformer repo without one still loads (the
#: library then assembles a default Transformer plus Pooling). Requiring it would
#: refuse installs that work. So the marker's promise is the narrower, true one:
#: every file selected from the hub listing arrived, each at its stated length.
_REQUIRED_FILES = ("config.json",)

#: Read/connect timeout per HTTP call. Generous, because a weights file on a
#: slow link legitimately takes minutes, and the caller is a background thread
#: nobody is waiting on.
_HTTP_TIMEOUT_S = 120.0

_CHUNK_BYTES = 1024 * 256


# ── Progress state ───────────────────────────────────────────────────────


@dataclass
class _Progress:
    """Live state of the one download this process may be running.

    Guarded by :data:`_lock`. Read through :func:`download_status`, which takes
    a copy, so a reader never observes a half-updated record.
    """

    state: str = STATE_NOT_REQUESTED
    model: str = ""
    downloaded_bytes: int = 0
    total_bytes: int = 0
    files_done: int = 0
    files_total: int = 0
    error: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    #: Set once the marker lands, so status can distinguish "this process
    #: fetched it" from "it was already on disk when we started".
    installed_path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


_lock = threading.Lock()
_progress = _Progress()
#: The single in-flight download, if any. Single-flight is enforced on this
#: rather than on a boolean so a thread that died without clearing its own
#: state cannot wedge the installer permanently.
_thread: threading.Thread | None = None


def _reset_progress_for_start(model: str) -> None:
    global _progress
    with _lock_state():
        _progress = _Progress(
            state=STATE_DOWNLOADING,
            model=model,
            started_at=time.time(),
        )


# ── Deployment questions ─────────────────────────────────────────────────


def semantic_library_available() -> bool:
    """Whether ``sentence_transformers`` could be imported in this process.

    Located rather than imported, matching ``app.core.vector._has_module``:
    importing it pulls torch, and on Windows plus Anaconda that has terminated
    the process outright on an MKL/OMP DLL conflict. A status call must never
    be able to do that. The two surfaces agree because they ask the same way.
    """
    import importlib.util

    try:
        return importlib.util.find_spec("sentence_transformers") is not None
    except Exception:  # noqa: BLE001 - a broken meta path finder is a "no"
        return False


def download_enabled() -> bool:
    """Whether this deployment should fetch the encoder in the background.

    Precedence:

    1. :data:`ENV_DOWNLOAD`, honoured in both directions, so an operator who
       does want an encoder on a server can have one and an operator who does
       not want one on a workstation can refuse it.
    2. Otherwise :func:`app.config.desktop_mode` - on for the local
       single-user workspace behind the native shell, off for a server deploy,
       which does not need it.

    A source checkout counts as a server here, because ``desktop_mode()`` is
    the platform's one answer to desktop-versus-server and inventing a second
    one for the same question is how the two drift apart. A developer who
    wants the download sets the variable.
    """
    raw = os.environ.get(ENV_DOWNLOAD, "").strip().lower()
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False

    try:
        from app.config import desktop_mode

        return desktop_mode()
    except Exception:  # noqa: BLE001 - never let a config import decide by crashing
        return False


# ── Paths ────────────────────────────────────────────────────────────────


def _endpoint() -> str:
    return (os.environ.get("HF_ENDPOINT") or _DEFAULT_ENDPOINT).rstrip("/")


def resolve_model_home() -> Path:
    """Return the install root for downloaded encoder weights.

    Follows ``app.core.storage.resolve_data_dir``, the platform's single source
    of truth for writable state, for the same reason the vector-database
    supervisor does: in a container the account's home directory is inside the
    image and does not survive recreating it, so an install placed there looks
    to the operator like it uninstalled itself.

    ``huggingface_cache_dir`` in settings wins when set. It is documented as
    the override for embedding-model downloads on hosts where the default path
    is not writable, and this is the code that downloads them.

    An install already present in the legacy ``~/.openestimator/models`` keeps
    being used, so upgrading never orphans weights already on disk.
    """
    try:
        from app.config import get_settings

        configured = (get_settings().huggingface_cache_dir or "").strip()
        if configured:
            return Path(configured).expanduser()
    except Exception:  # noqa: BLE001 - fall through to the data dir
        pass

    legacy = Path.home() / ".openestimator" / "models"
    try:
        from app.core.storage import resolve_data_dir

        resolved = resolve_data_dir() / "models"
    except (ImportError, OSError):  # pragma: no cover - defensive
        return legacy
    if resolved == legacy:
        return resolved
    # The legacy root wins only when it holds a FINISHED install and the
    # resolved one does not. Testing for the directory instead would hand the
    # whole installer to a leftover empty folder, which is how a supposedly
    # relocated install keeps writing where nobody is reading.
    if _holds_completed_install(legacy) and not _holds_completed_install(resolved):
        return legacy
    return resolved


def _holds_completed_install(root: Path) -> bool:
    """Whether ``root`` contains at least one model whose marker was written."""
    try:
        return any(child.is_dir() and (child / MARKER_FILENAME).is_file() for child in root.iterdir())
    except OSError:
        return False


def _slug(repo_id: str) -> str:
    """Filesystem-safe directory name for a hub repo id.

    ``intfloat/multilingual-e5-small`` -> ``intfloat--multilingual-e5-small``.
    Anything outside the hub's own id alphabet is dropped rather than escaped,
    because a repo id is caller-influenced in principle and a path separator
    smuggled through here would write outside the install root.
    """
    safe = []
    for ch in repo_id.replace("/", "--"):
        safe.append(ch if (ch.isalnum() or ch in "-_.") else "_")
    out = "".join(safe).strip(". ")
    return out or "model"


def active_repo_id() -> str:
    """The encoder this installation would load, per settings."""
    try:
        from app.config import get_settings

        name = (get_settings().embedding_model_name or "").strip()
        if name:
            return name
    except Exception:  # noqa: BLE001
        pass
    from app.core.vector import EMBEDDING_MODEL

    return EMBEDDING_MODEL


def local_model_dir(repo_id: str | None = None) -> Path:
    """Where ``repo_id``'s weights live once installed. Does not create it."""
    return resolve_model_home() / _slug(repo_id or active_repo_id())


def find_installed_model(repo_id: str | None = None) -> Path | None:
    """Return the model directory only if the download completed.

    The marker is written last, so this is ``None`` for a directory that holds
    a partial download, and the loader is never handed one.
    """
    target = local_model_dir(repo_id)
    try:
        if (target / MARKER_FILENAME).is_file():
            return target
    except OSError:  # pragma: no cover - defensive
        return None
    return None


# ── Hub file listing ─────────────────────────────────────────────────────


def _resolve_file_list(repo_id: str) -> list[str]:
    """Return the repo-relative filenames worth downloading for ``repo_id``.

    Isolated from the transfer so the hub's response shape lives in one place:
    a field rename upstream is one edit here and one test double, rather than a
    scatter of dictionary reads through the download loop.
    """
    url = f"{_endpoint()}/api/models/{urllib.parse.quote(repo_id, safe='/')}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "OpenConstructionERP-model-installer",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed http(s) origin
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Model hub returned {exc.code} for {repo_id}: {exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"Could not reach the model hub for {repo_id}: {exc}") from exc

    siblings = payload.get("siblings") or []
    names = [str(s.get("rfilename") or "") for s in siblings if isinstance(s, dict)]
    names = [n for n in names if n]
    if not names:
        raise RuntimeError(f"Model hub listed no files for {repo_id}.")
    return _select_files(names)


def _select_files(names: list[str]) -> list[str]:
    """Filter a repo file list down to what the encoder actually loads.

    Weights are published several times over - safetensors, a pickled
    ``pytorch_model.bin``, ONNX, OpenVINO, CoreML. Taking all of them is the
    difference between one download and several. Safetensors wins when present;
    ``pytorch_model.bin`` is taken only when it does not, so a repo published
    the old way still installs.
    """
    kept: list[str] = []
    has_safetensors = any(n.endswith(".safetensors") for n in names)

    for name in names:
        if any(name.startswith(p) for p in _SKIP_PREFIXES):
            continue
        # Anything under a dot-name is repository metadata, never a loader
        # input: .gitattributes, .cache/, and on the model this platform
        # actually ships, 21 files of .eval_results/*.yaml benchmark scores.
        # They are small, so the cost is not bytes - it is that they are most
        # of the file count, which would send the progress bar to 70% in a
        # second and then park it there for the whole of the real weights.
        if any(segment.startswith(".") for segment in name.split("/")):
            continue
        if "/" in name and name.split("/")[0] in {"onnx", "openvino", "coreml"}:
            continue
        lowered = name.lower()
        if lowered.endswith(".bin"):
            # The pickled weights are a fallback, not a companion.
            if has_safetensors or not lowered.endswith("pytorch_model.bin"):
                continue
            kept.append(name)
            continue
        if any(lowered.endswith(s) for s in _SKIP_SUFFIXES):
            continue
        kept.append(name)
    return kept


def _file_url(repo_id: str, rfilename: str) -> str:
    quoted = urllib.parse.quote(rfilename, safe="/")
    return f"{_endpoint()}/{urllib.parse.quote(repo_id, safe='/')}/resolve/main/{quoted}"


# ── Transfer ─────────────────────────────────────────────────────────────


def _within(root: Path, candidate: Path) -> bool:
    """Whether ``candidate`` stays inside ``root`` once resolved."""
    try:
        candidate.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def _download_one(url: str, dest: Path, *, on_bytes: Any = None) -> None:
    """Fetch ``url`` into ``dest``, resuming a previous partial attempt.

    The bytes land in ``dest.part``. When that file already holds some of the
    response we ask for the remainder with a ``Range`` header and append; a
    server that ignores the header answers ``200`` instead of ``206`` and we
    start the file over rather than corrupting it by appending a second copy of
    the head. Only once the transfer completes is the part renamed onto
    ``dest``, so a file the loader can open is always a file that finished.

    "Completes" has to mean the declared length arrived, not that reading
    stopped. A connection dropped mid-file ends the read loop without raising -
    the socket simply reports end of stream - so an unverified transfer renames
    a truncated file into place and the marker written afterwards certifies it.
    Measured, not reasoned: against a source that cut the weights off after a
    third, this function reported success and the install completed green. So
    the response's ``Content-Length`` is compared against what landed, and a
    short read is a failure like any other.
    """
    part = dest.with_name(dest.name + PART_SUFFIX)
    dest.parent.mkdir(parents=True, exist_ok=True)

    have = part.stat().st_size if part.is_file() else 0
    headers = {"User-Agent": "OpenConstructionERP-model-installer"}
    if have:
        headers["Range"] = f"bytes={have}-"

    expected: int | None = None
    received = 0
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:  # noqa: S310 - fixed http(s) origin
            resuming = resp.status == 206
            mode = "ab" if resuming else "wb"
            if not resuming and have:
                have = 0
            raw_length = resp.headers.get("Content-Length")
            if raw_length is not None:
                try:
                    expected = int(raw_length)
                except ValueError:
                    expected = None
            with part.open(mode) as fh:
                while True:
                    chunk = resp.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    fh.write(chunk)
                    received += len(chunk)
                    if on_bytes is not None:
                        on_bytes(len(chunk))
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and have:
            # The part file already holds the whole object; the server is
            # telling us there is nothing past the end. Treat it as complete.
            part.replace(dest)
            return
        part.unlink(missing_ok=True)
        raise RuntimeError(f"Download of {url} failed: HTTP {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Leave the part file: it is the resume point for the next attempt, and
        # it is not loadable by anything because of the suffix.
        raise RuntimeError(f"Download of {url} failed: {exc}") from exc

    if expected is not None and received != expected:
        raise RuntimeError(
            f"Download of {url} stopped after {received} of {expected} bytes. "
            "Leaving it unfinished rather than treating a truncated file as the model."
        )

    part.replace(dest)


def install_embedding_model(*, repo_id: str | None = None, force: bool = False) -> Path:
    """Download the encoder weights. Returns the directory they landed in.

    Idempotent: an install whose marker is already on disk returns immediately
    unless ``force`` is set. Safe to call twice concurrently - the second
    caller finds the lock held and returns the in-flight directory rather than
    starting a second transfer.

    Raises ``RuntimeError`` with a message fit to hand to a user on every
    failure path, including the one where the semantic extra is not installed
    and there is therefore nothing that could load the result.
    """
    repo = repo_id or active_repo_id()

    if not semantic_library_available():
        # The library this asks for is sentence-transformers, which the desktop
        # lock resolves through [semantic-encoder]. A bundle that reaches here
        # is therefore damaged rather than lean, so the frozen wording is the
        # repair one; DESKTOP_NO_EXTRA would claim the build never carried it.
        from app.core.self_upgrade import repair_hint  # noqa: PLC0415

        raise RuntimeError(
            "The semantic search library is not part of this installation, so "
            "downloading encoder weights would fetch something nothing here "
            "can load. " + repair_hint("Install the extra first: pip install openconstructionerp[semantic].")
        )

    existing = find_installed_model(repo)
    if existing is not None and not force:
        logger.info("install_embedding_model: already installed at %s", existing)
        return existing

    # Single flight. A blocking acquire would serialise two callers into two
    # sequential downloads of the same weights; the second caller wants the
    # first one's result, not its own turn.
    if not _lock.acquire(blocking=False):
        logger.info("install_embedding_model: a download is already running")
        return local_model_dir(repo)

    try:
        _reset_progress_for_start(repo)
        target = local_model_dir(repo)
        _emit_stage("start", f"Downloading semantic search model {repo}")

        if force:
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        # A marker left from an older install must not survive a re-download:
        # while files are being replaced the directory is a partial again.
        (target / MARKER_FILENAME).unlink(missing_ok=True)

        files = _resolve_file_list(repo)
        with _lock_state() as prog:
            prog.files_total = len(files)

        for index, rfilename in enumerate(files, start=1):
            dest = target / rfilename
            if not _within(target, dest):
                raise RuntimeError(f"Model hub listed a path outside the install directory: {rfilename!r}")
            _download_one(_file_url(repo, rfilename), dest, on_bytes=_count_bytes)
            with _lock_state() as prog:
                prog.files_done = index
            _emit_stage("progress", f"{index}/{len(files)} files")

        missing = [name for name in _REQUIRED_FILES if not (target / name).is_file()]
        if missing:
            raise RuntimeError(
                f"The download left {target} without {', '.join(missing)}, so it is not a "
                "loadable model. Treating this as a failed install."
            )

        # Marker last. Everything above this line can be interrupted and the
        # directory stays invisible to find_installed_model().
        (target / MARKER_FILENAME).write_text(
            json.dumps(
                {
                    "model": repo,
                    "files": len(files),
                    "completed_at": time.time(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 - every failure is reported, none escapes as-is
        with _lock_state() as prog:
            prog.state = STATE_FAILED
            prog.error = str(exc)
            prog.finished_at = time.time()
        _cleanup_partials(local_model_dir(repo))
        # Deliberately NOT a "fail" marker. The desktop launcher latches the
        # first STAGE fail it sees as the cause of a failed boot and reports it
        # to the user as why the application did not start. An optional extra
        # that could not download is not that, and claiming it is would be the
        # loudest possible way to break "nothing else is affected". The step is
        # closed instead, the reason travels in the detail, and the real error
        # goes to the log and to the status endpoint, which is where anyone who
        # wants to act on it is looking.
        _emit_stage("done", "Semantic search model not downloaded - optional, everything else works")
        logger.warning("Encoder weights download failed for %s: %s", repo, exc)
        raise RuntimeError(str(exc)) from exc
    else:
        with _lock_state() as prog:
            prog.state = STATE_READY
            prog.finished_at = time.time()
            prog.installed_path = str(target)
        _emit_stage("done", f"Semantic search model ready ({repo})")
        logger.info("Encoder weights installed at %s", target)
        # The loader latches its failure for the process lifetime by design, so
        # without this the weights that just landed would not be used until the
        # next restart and the download would have bought nothing.
        _reset_embedder_quietly()
        return target
    finally:
        _lock.release()


def is_downloading() -> bool:
    """Whether a transfer holds the install lock right now.

    The lock is taken for the whole of :func:`install_embedding_model` and
    released in its ``finally``, so this covers the window before the progress
    record has been stamped as well - which a state read alone would miss.
    """
    return _lock.locked()


def _cleanup_partials(target: Path) -> None:
    """Remove every ``.part`` file under a failed install.

    Resume is a nicety; a partial left behind after the install gave up is a
    surprise, and the next attempt re-lists the repo anyway. The marker is
    already absent on this path, so nothing here is loadable either way - this
    is about not leaving hundreds of megabytes of rubble on the user's disk.
    """
    try:
        for path in target.rglob("*" + PART_SUFFIX):
            path.unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover - defensive
        logger.debug("Could not clean partial downloads under %s: %s", target, exc)


def _reset_embedder_quietly() -> None:
    try:
        from app.core.vector import reset_embedder

        reset_embedder()
    except Exception:  # noqa: BLE001 - a cold loader is not worth failing an install over
        logger.debug("Could not reset the cached embedder after install", exc_info=True)


class _lock_state:  # noqa: N801 - a context manager, named for how it reads at the call site
    """Hold the progress record steady for one mutation."""

    _guard = threading.Lock()

    def __enter__(self) -> _Progress:
        self._guard.acquire()
        return _progress

    def __exit__(self, *_exc: object) -> None:
        self._guard.release()


def _count_bytes(n: int) -> None:
    with _lock_state() as prog:
        prog.downloaded_bytes += n


def _emit_stage(status: str, detail: str) -> None:
    """Report progress to the desktop splash screen.

    The launcher parses ``STAGE:<id>:<status>[:<detail>]`` off the sidecar's
    stdout into a visible checklist, so emitting the marker from here is all it
    takes for the download to appear as a boot step. Best effort by
    construction - ``emit_stage`` never raises.
    """
    try:
        from app.core.embedded_pg import emit_stage

        emit_stage("model", status, detail)
    except Exception:  # noqa: BLE001 - progress reporting can never break a download
        logger.debug("Could not emit a stage marker for the model download", exc_info=True)


# ── Background start ─────────────────────────────────────────────────────


def start_background_download(*, repo_id: str | None = None, requested: bool = False) -> bool:
    """Start the download in a daemon thread if this deployment wants one.

    Returns whether a thread was started, which is what the startup path logs
    and what a test asserts on: a server deploy must answer ``False`` without
    touching the network.

    ``requested=True`` is a person asking for it - the wizard's tick, or the
    install endpoint. That skips the per-deployment default, because the
    default only ever answers "should this happen unasked", and a click is not
    unasked. An operator who set the variable to a falsy value still wins: that
    is a policy about the machine, and a UI toggle does not overrule it.

    Never raises and never blocks. Answers ``False`` when the download is
    disabled, when the semantic library is missing, when the weights are
    already installed, or when a download is already running.
    """
    global _thread

    try:
        if requested:
            if os.environ.get(ENV_DOWNLOAD, "").strip().lower() in _FALSY:
                logger.info("Encoder download was requested but %s is set to off - not starting.", ENV_DOWNLOAD)
                return False
        elif not download_enabled():
            return False
        if not semantic_library_available():
            logger.info(
                "Encoder download is on for this deployment but %s is not installed, "
                "so there is nothing that could load the weights - skipping.",
                "sentence_transformers",
            )
            return False
        repo = repo_id or active_repo_id()
        if find_installed_model(repo) is not None:
            return False
        if is_downloading():
            # The install lock, not this module's thread handle, is what "a
            # download is running" means. Keying single flight on the handle
            # alone reported a fresh start for a transfer already in flight,
            # because a transfer begun through install_embedding_model directly
            # never sets the handle. Nothing downloaded twice - the lock caught
            # it one level down - but the answer this function gave was wrong,
            # and it is the answer the install endpoint hands to the UI.
            return False
        if _thread is not None and _thread.is_alive():
            return False

        def _run() -> None:
            try:
                install_embedding_model(repo_id=repo)
            except Exception:  # noqa: BLE001 - the thread is the last line; nothing above it catches
                logger.info("Background encoder download did not complete", exc_info=True)

        _thread = threading.Thread(
            target=_run,
            name="oe-embedding-model-download",
            daemon=True,
        )
        _thread.start()
        return True
    except Exception:  # noqa: BLE001 - starting a download can never break startup
        logger.debug("Could not start the background encoder download", exc_info=True)
        return False


# ── Status ───────────────────────────────────────────────────────────────


def download_status(*, repo_id: str | None = None) -> dict[str, Any]:
    """Compose the encoder's loadability with the download's state.

    ``embedder_status()`` answers "can this process encode right now", which is
    four states. A reader also needs to know whether weights are arriving, and
    that is a fifth. The precedence below is fixed here, once, so the two
    surfaces cannot drift:

    ``library_missing`` > ``downloading`` > ``failed`` > ``ready`` >
    ``not_requested``

    The deliberate call in it: weights on disk report ``ready`` even when
    nothing has loaded them yet. ``embedder_status()`` says ``not_loaded``
    there, which is the honest answer to its own question, but a caller asking
    "will semantic search answer" would read it as a no, and reporting a
    working install as unavailable is the same dishonesty the ``503`` work just
    removed from the search path.
    """
    repo = repo_id or active_repo_id()

    try:
        from app.core.vector import embedder_status

        embedder = embedder_status()
    except Exception:  # noqa: BLE001 - status must never be the thing that breaks
        embedder = {"available": False, "state": "not_loaded", "model": repo, "dimension": 0}

    with _lock_state() as prog:
        snapshot = asdict(prog)

    installed = find_installed_model(repo)
    enabled = download_enabled()
    library = semantic_library_available()

    if not library:
        state = STATE_LIBRARY_MISSING
    elif snapshot["state"] == STATE_DOWNLOADING:
        state = STATE_DOWNLOADING
    elif installed is None and snapshot["state"] == STATE_FAILED:
        state = STATE_FAILED
    elif installed is not None or embedder.get("state") == "ready":
        state = STATE_READY
    else:
        # Wanted or not, nothing is on disk, nothing is in flight and nothing
        # has failed. The ``enabled`` flag beside this says whether it is on
        # its way; the state itself is the same either way.
        state = STATE_NOT_REQUESTED

    # File count, not bytes. The hub's listing does not carry sizes without a
    # second call, and a bar driven by files is honest as long as the caller
    # says "files" - which is why ``files_done`` / ``files_total`` travel
    # beside it rather than being folded away into a percentage.
    percent = 0
    if snapshot["files_total"]:
        percent = int(round(100 * snapshot["files_done"] / snapshot["files_total"]))
    if state == STATE_READY:
        percent = 100

    return {
        "state": state,
        "enabled": enabled,
        "model": repo,
        "installed": installed is not None,
        "install_path": str(installed) if installed is not None else "",
        "percent": percent,
        "files_done": snapshot["files_done"],
        "files_total": snapshot["files_total"],
        "downloaded_bytes": snapshot["downloaded_bytes"],
        "error": snapshot["error"],
        "library_installed": library,
        "env_var": ENV_DOWNLOAD,
        "locked": download_locked_off(),
        "embedder": embedder,
        "message": _message_for(state, repo, enabled, download_locked_off()),
    }


def download_locked_off() -> bool:
    """Whether an operator has switched the download off for this deployment.

    Distinct from "off by default". A server defaults to off and still honours
    a deliberate click in the wizard, because someone who ticks the box has
    asked for the thing. An explicit falsy ``OE_DOWNLOAD_EMBEDDING_MODEL``
    overrules even that, which is what a production unit wants.

    The UI needs to tell the two apart, or it draws a toggle the operator has
    already disabled: the user ticks it, presses Continue, and nothing happens
    with nothing said. A control that cannot act must not look like one.
    """
    return os.environ.get(ENV_DOWNLOAD, "").strip().lower() in _FALSY


def _message_for(state: str, repo: str, enabled: bool, locked: bool = False) -> str:
    """One human sentence per state, said here so every caller says the same."""
    if state == STATE_LIBRARY_MISSING:
        # Same reasoning as install_embedding_model above: sentence-transformers
        # is in the desktop lock, so a bundle missing it is damaged, not lean.
        from app.core.self_upgrade import repair_hint  # noqa: PLC0415

        return "Semantic search is not part of this installation. Everything else works without it. " + repair_hint(
            "Install the extra to enable it: pip install openconstructionerp[semantic]."
        )
    if state == STATE_DOWNLOADING:
        return f"Downloading the semantic search model ({repo}) in the background. You can keep working."
    if state == STATE_FAILED:
        return "The semantic search model could not be downloaded. Everything else keeps working; you can retry."
    if state == STATE_READY:
        return "The semantic search model is installed."
    if enabled:
        return f"The semantic search model ({repo}) has not been downloaded yet."
    if locked:
        return (
            "The semantic search model is switched off for this deployment by "
            f"{ENV_DOWNLOAD}. Everything else works; an administrator can remove "
            "that setting to allow it."
        )
    return f"The semantic search model is not downloaded on this deployment. Set {ENV_DOWNLOAD}=1 to fetch it."


def reset_state_for_tests() -> None:
    """Drop the module's progress record and thread handle.

    Test-only: the state is a process singleton by design, and a test that
    exercises a failure would otherwise leak that failure into the next one.
    """
    global _progress, _thread
    with _lock_state():
        _progress = _Progress()
    _thread = None


__all__ = [
    "ENV_DOWNLOAD",
    "MARKER_FILENAME",
    "STATE_DOWNLOADING",
    "STATE_FAILED",
    "STATE_LIBRARY_MISSING",
    "STATE_NOT_REQUESTED",
    "STATE_READY",
    "active_repo_id",
    "download_enabled",
    "download_locked_off",
    "download_status",
    "find_installed_model",
    "install_embedding_model",
    "local_model_dir",
    "resolve_model_home",
    "semantic_library_available",
    "start_background_download",
]
