"""Guard: the desktop PyInstaller lock carries the right dependency set.

The desktop build installs dependencies from ``requirements-desktop.lock`` and
then runs ``pip install -e . --no-deps``, so anything missing from the lock is
simply absent from the frozen sidecar. A stale lock once shipped without PyMuPDF
/ OpenCV / laspy / lazrs / pypdf (PDF takeoff, raster room detection, point-cloud
reads, PDF stamping) and with pandas 3.x even though ``pyproject.toml`` caps it
below 3.0 - silently breaking those features on the desktop channel only, while
the wheel kept working. This test fails fast if the lock drifts away from the
declared base dependencies again.

The lock is compiled with one extra, ``[semantic-encoder]``, which pulls
``[semantic-clients]`` behind it. That replaced a narrower ``[semantic-clients]``
compile once the encoder download became default-on for desktop_mode. Under the
old lock the desktop build shipped a downloader with nothing that could load
what it downloaded: ``start_background_download`` asks
``semantic_library_available()`` first, that looks for a ``sentence_transformers``
spec, the frozen sidecar had none, and the advertised download quietly never
began. So the checks run in both directions - the client and the encoder that
the desktop build exists to carry must be present, and the CWICR bge-m3 stack,
which needs a separate ~700 MB model no desktop install ever fetches, must not
be.

The last test in this file compares two files rather than one. A name can be
pinned in the lock and excluded in ``desktop/pyinstaller.spec`` at the same
time, and when that happens the build installs a dependency and then throws it
away. That is not hypothetical: it is precisely what ``torch`` and ``scipy``
did, and it is invisible at build time because PyInstaller reports no error for
excluding something it was going to bundle.

It is a pure file-parsing test (no application import), so it runs anywhere the
test suite is collected.
"""

import ast
import re
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
_LOCK = _BACKEND / "requirements-desktop.lock"
_SPEC = _BACKEND.parent / "desktop" / "pyinstaller.spec"

# The command that regenerates the lock. Both flags are load-bearing. Without
# ``--extra semantic-encoder`` uv resolves the base dependencies only and
# silently drops the vector-store client and the encoder below. Without
# ``--torch-backend=cpu`` it resolves torch's default Linux wheels, which
# declare the whole nvidia CUDA stack and take the Linux install from roughly
# 190 MB of wheels to roughly 2.7 GB, for a headless server that never
# addresses a GPU.
_REGEN = (
    "uv pip compile pyproject.toml --universal --python-version 3.12 "
    "--extra semantic-encoder --torch-backend=cpu -o requirements-desktop.lock"
)

# Running it is not a minimal repair, which matters because every failure below
# prints it as the fix. The command re-resolves every pin against the index as
# it stands that day, so a regen taken to add one missing name also lands
# whatever upstream published since the file was last compiled. Recompiling
# this lock on 2026-08-17 with no dependency change at all moved 37 pins, three
# of them across a major version: opencv-python-headless 4 to 5, trimesh 4 to
# 5, reportlab 4 to 5. Read the diff before committing one.

# Package-name prefixes that only appear when torch resolved its GPU build.
# Kept as prefixes because the CUDA wheels are split across a dozen
# differently-suffixed distributions (nvidia-cublas, nvidia-cudnn-cu13,
# cuda-toolkit, triton) and a new CUDA release renames them again.
_GPU_PREFIXES = ("nvidia-", "cuda-", "triton")

# Base deps whose absence silently breaks a desktop-only feature. Each is an
# unconditional (non-optional, non-platform-gated) dependency declared in
# pyproject.toml. Every one but the last is also imported by application code,
# which is what makes it findable by anything that scans our imports. uharfbuzz
# is not, and that is precisely why it has to be named here by hand.
#
# reportlab imports uharfbuzz on our behalf, from a try/except at the top of
# reportlab.pdfbase.ttfonts, and it is the whole reason Thai and Devanagari
# print correctly rather than merely visibly. Without it reportlab reports every
# face as unshapable, pdf_fonts.font_needs_shaping answers False by design, and
# the two Noto faces the sidecar still bundles draw a Thai tone mark at
# consonant height on top of the vowel that is already there. That is a wrong
# glyph rather than a missing one, so it survives every check that only asks
# whether text rendered at all, and it reaches the user looking like text.
#
# The lock is the only place this can go missing. PyInstaller needs no help:
# 6.21.0 follows that try/except, collects the extension module unaided and
# shapes correctly, which was measured against a frozen artifact rather than
# assumed. The wheel and the Docker image both install from pyproject.toml and
# so were never exposed; the desktop channel installs from this file and then
# runs pip install -e . --no-deps, which is what makes this list load bearing.
_REQUIRED_BASE_DEPS = (
    "pymupdf",
    "opencv-python-headless",
    "laspy",
    "lazrs",
    "pypdf",
    "pandas",
    # Read inside a function only when an .xls arrives, so a lock without it
    # builds and starts fine and fails the first Excel 97-2003 bill imported.
    "xlrd",
    "uharfbuzz",
)

# Vector-store clients from the [semantic-clients] extra. qdrant-client opens
# the CWICR match store, and it is imported inside a function body, so a lock
# without it produces a sidecar that answers an empty 200 from /match-elements
# instead of failing loudly. lancedb is the generic store that
# VECTOR_BACKEND=lancedb selects, and that default already ships, so leaving the
# backend out did not save the megabytes: it moved the failure from the build to
# the user's first query.
#
# lancedb sat in this comment as deliberately absent, on a measurement of 157 MB
# that stopped being true. Version 0.37.1 and the three distributions it adds to
# this lock (deprecation, lance-namespace, lance-namespace-urllib3-client) weigh
# 62 MB on Linux, 68 MB on Windows and 56 MB on macOS, well under half the old
# figure. The decision and both numbers are recorded next to the extra in
# pyproject.toml; this file only enforces the outcome. Re-measure before citing
# either figure again.
_REQUIRED_CLIENT_DEPS = ("qdrant-client", "lancedb")

# The local encoder, and the two libraries it cannot load weights without.
# sentence-transformers is what core/vector.py and costs/matcher.py import;
# torch is its runtime; scipy arrives through scikit-learn and is listed here
# because it was one of the two names the PyInstaller spec used to exclude, so
# a regression that dropped it would look like a resolver hiccup rather than the
# feature removal it is.
_REQUIRED_ENCODER_DEPS = (
    "sentence-transformers",
    "torch",
    "transformers",
    "scipy",
)

# The CWICR bge-m3 half of [semantic], which the desktop build deliberately does
# not carry. FlagEmbedding encodes the 30 cwicr_<lang> collections and needs a
# ~700 MB model that no desktop install downloads; polars reads an
# operator-supplied rate parquet that nothing ships. Both would be weight with
# no reachable code path. Anything that drags one of these into the lock has
# resolved [semantic] or [all] where it meant [semantic-encoder].
_FORBIDDEN_CWICR_DEPS = (
    "flagembedding",
    "polars",
)


def _lock_versions() -> dict[str, str]:
    """Map normalised distribution name -> pinned version from the lock."""
    versions: dict[str, str] = {}
    for line in _LOCK.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9._-]+)==([^\s;]+)", line)
        if match:
            versions[match.group(1).lower()] = match.group(2)
    return versions


def _spec_excludes() -> list[str]:
    """The ``excludes=[...]`` argument of the spec's ``Analysis(...)`` call.

    Parsed rather than pattern-matched. A regex over the spec text would also
    match the word inside the long comment above the list, which is where these
    names are discussed at length.
    """
    tree = ast.parse(_SPEC.read_text(encoding="utf-8"), filename=str(_SPEC))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "Analysis"):
            continue
        for keyword in node.keywords:
            if keyword.arg == "excludes" and isinstance(keyword.value, ast.List):
                return [elt.value for elt in keyword.value.elts if isinstance(elt, ast.Constant)]
    return []


def test_required_base_deps_present_in_desktop_lock() -> None:
    versions = _lock_versions()
    missing = [dep for dep in _REQUIRED_BASE_DEPS if dep.lower() not in versions]
    assert not missing, (
        f"requirements-desktop.lock is missing base deps the frozen sidecar needs: {missing}. Regenerate with: {_REGEN}"
    )


def test_vector_clients_present_in_desktop_lock() -> None:
    versions = _lock_versions()
    missing = [dep for dep in _REQUIRED_CLIENT_DEPS if dep.lower() not in versions]
    assert not missing, (
        f"requirements-desktop.lock is missing [semantic-clients] vector-store clients: {missing}. "
        "A lock compiled without the extra looks healthy but ships a sidecar whose /match-elements "
        "returns nothing and whose configured lancedb backend has no store to open. "
        f"Regenerate with: {_REGEN}"
    )


def test_local_encoder_present_in_desktop_lock() -> None:
    versions = _lock_versions()
    missing = [dep for dep in _REQUIRED_ENCODER_DEPS if dep.lower() not in versions]
    assert not missing, (
        f"requirements-desktop.lock is missing the local encoder stack: {missing}. Without it the "
        "frozen sidecar downloads embedding weights it has nothing to load, or - worse - "
        "semantic_library_available() answers False and the default-on download never starts at "
        f"all, so the desktop build behaves as if the feature were switched off. Regenerate with: {_REGEN}"
    )


def test_cwicr_embedder_absent_from_desktop_lock() -> None:
    versions = _lock_versions()
    present = [dep for dep in _FORBIDDEN_CWICR_DEPS if dep.lower() in versions]
    assert not present, (
        f"requirements-desktop.lock resolved the CWICR bge-m3 stack: {present}. The desktop build "
        "carries [semantic-encoder], not [semantic]: FlagEmbedding needs a ~700 MB model no desktop "
        "install downloads and polars reads a parquet nothing ships, so both are weight with no "
        f"reachable code path. Regenerate with: {_REGEN}"
    )


def test_torch_is_pinned_to_its_cpu_build() -> None:
    """The desktop sidecar is a headless HTTP server and never addresses a GPU.

    Two assertions because they fail in different ways. A lock recompiled
    without ``--torch-backend=cpu`` still works, still passes every other test
    in this file, and simply makes the Linux installer about 2.5 GB heavier -
    which nobody notices until a release. The CUDA distributions are the
    visible symptom; the local version on the torch pin is the cause.

    macOS is exempt and has to be: there are no CUDA wheels for it, so the
    pytorch index publishes no ``+cpu`` variant and the plain PyPI wheel is
    already CPU-only.
    """
    versions = _lock_versions()
    assert versions, f"parsed no pins from {_LOCK}; the lock format changed and this guard went blind"

    gpu = sorted(name for name in versions if name.startswith(_GPU_PREFIXES))
    assert not gpu, (
        f"requirements-desktop.lock resolved torch's GPU build; it pulled {len(gpu)} CUDA "
        f"distributions: {gpu[:5]}{' ...' if len(gpu) > 5 else ''}. That is roughly 2.5 GB of "
        f"wheels the headless sidecar cannot use. Regenerate with: {_REGEN}"
    )

    torch_pins = [line for line in _LOCK.read_text(encoding="utf-8").splitlines() if re.match(r"^torch==", line)]
    assert torch_pins, "torch missing from requirements-desktop.lock"
    non_darwin = [line for line in torch_pins if "darwin" not in line or "!=" in line]
    assert non_darwin and all("+cpu" in line for line in non_darwin), (
        f"torch is pinned as {torch_pins} but the Windows and Linux pins must carry the +cpu "
        f"local version. Regenerate with: {_REGEN}"
    )


def test_pandas_pinned_below_3_in_desktop_lock() -> None:
    versions = _lock_versions()
    pandas_version = versions.get("pandas")
    assert pandas_version is not None, "pandas missing from requirements-desktop.lock"
    major = int(pandas_version.split(".")[0])
    assert major < 3, (
        f"requirements-desktop.lock pins pandas {pandas_version}; pyproject.toml "
        "caps it <3 (pandas 3.0 changed string-column type inference). Regenerate "
        "the lock so it respects the cap."
    )


def test_no_locked_dependency_is_excluded_by_the_spec() -> None:
    """Installing a dependency and then telling PyInstaller to drop it.

    The two files are edited for different reasons months apart, and nothing
    else compares them. When ``[semantic-encoder]`` was added to the lock, torch
    and scipy were still in the spec's excludes, so the build would have
    downloaded 190 MB of encoder on Windows and then frozen a sidecar without
    it. PyInstaller says nothing about excluding a package it was going to
    bundle.

    That state was built and measured rather than argued about. A Windows
    sidecar frozen from this spec with torch and scipy put back in excludes
    still carries sentence_transformers, 167 modules of it, because PyInstaller
    reads the imports inside function bodies too. It carries no torch and no
    scipy at all, so the first import that runs for real fails, pulling torch,
    scipy and sklearn at module level.

    That build also claimed the feature it could not deliver. Until 58c2c9f7c
    ``doctor`` answered "Semantic search [semantic]: sentence-transformers
    installed" from a find_spec lookup, and a lookup is satisfied by what sits
    in the archive whether or not it can load. That check imports for real now
    and says so when the import fails, which removes the false claim but not
    the cost: it is a report from a build that has already been made, and on
    the desktop channel, shipped. This test reaches the same conclusion from
    two files at commit time.

    The comparison is by distribution name, which is the same as the import name
    for every name currently in either list. It would not catch a distribution
    whose import name differs from its package name (opencv-python-headless
    imports as cv2), so this is a floor rather than a proof.
    """
    versions = _lock_versions()
    excludes = _spec_excludes()

    # A scanner that compared nothing would pass. Both sides have to be real
    # before the intersection below means anything.
    assert versions, f"parsed no pins from {_LOCK}; the lock format changed and this guard went blind"
    assert excludes, (
        f"parsed no excludes from {_SPEC}; the Analysis(excludes=[...]) call moved and this guard went blind"
    )

    clash = sorted({name for name in excludes if name.lower() in versions})
    print(f"compared {len(versions)} locked distributions against {len(excludes)} spec excludes: {len(clash)} clash")
    assert not clash, (
        f"desktop/pyinstaller.spec excludes {clash}, which requirements-desktop.lock installs. "
        "The desktop build would download these and then freeze a sidecar without them. Either "
        "drop the name from the spec's excludes list or drop the dependency that pulls it into "
        "the lock, but do not do both."
    )
