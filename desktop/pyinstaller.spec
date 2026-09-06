# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the OpenConstructionERP backend sidecar.

Builds the FastAPI backend into a single executable that Tauri
launches as a sidecar process.

Usage:
    cd desktop
    pyinstaller pyinstaller.spec
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Paths
ROOT = Path(SPECPATH).parent
BACKEND = ROOT / "backend"
FRONTEND_DIST = ROOT / "frontend" / "dist"
# NOTE: do not add ``data/catalog`` to ``datas`` below. There used to be a
# DATA_CATALOG constant here, defined and never used, which read like a
# bundling step somebody had started. It is 77 MB of regional cost catalogues
# derived from public sector norm systems, and the sidecar deliberately does
# not carry it: the catalog module downloads a region on demand and caches it
# under ~/.openestimator. Putting it in the installer would ship that data
# inside a signed artifact, which is a licensing decision and not a packaging
# one. See the Data Sources section of NOTICE before changing this.

# Collect all backend module packages for hidden imports
modules_dir = BACKEND / "app" / "modules"
hidden_imports = [
    # Embedded PostgreSQL 16 + its drivers. SQLAlchemy picks the driver from
    # the URL at runtime (create_engine), so PyInstaller's static import graph
    # never sees asyncpg / psycopg2 and would otherwise omit them, leaving the
    # frozen sidecar unable to connect to its own database. pixeltable_pgserver
    # boots the cluster; its bundled PG binaries are collected by the
    # hook-pixeltable_pgserver.py hook on hookspath below.
    "asyncpg",
    "psycopg2",
    "pixeltable_pgserver",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "app.cli",
    "app.cli_static",
    "app.main",
    "app.config",
    "app.database",
    "app.core",
    "app.core.module_loader",
    "app.core.i18n",
    "app.core.i18n_router",
    "app.core.permissions",
    "app.core.validation",
    "app.core.validation.engine",
    "app.core.validation.rules",
    "app.core.vector",
    "app.core.hooks",
    "app.core.events",
    "app.core.demo_projects",
    "app.core.marketplace",
    # Heavy feature deps imported lazily / dynamically inside service methods,
    # so PyInstaller's static import graph never sees them and would omit the
    # modules from the frozen sidecar - silently breaking the feature on the
    # DESKTOP build only (the wheel works because pip installs them). PyMuPDF
    # exposes both the legacy "fitz" and the modern "pymupdf" import names and
    # the code uses both. lazrs is the LAZ/COPC decompression backend that
    # laspy imports dynamically, so it must be named explicitly or point-cloud
    # LAZ reads fail at runtime. The cv2 / fitz / pymupdf binary payloads are
    # collected by their pyinstaller-hooks-contrib hooks once the module is in
    # the graph.
    "fitz",  # PyMuPDF - PDF vector takeoff, raster render, text extract
    "pymupdf",  # PyMuPDF modern import alias
    "cv2",  # opencv-python-headless - raster room/wall detector
    "laspy",  # LAS/LAZ/COPC point-cloud reader
    "lazrs",  # laspy's LAZ/COPC decompression backend (dynamic import)
    "pypdf",  # PDF stamping / merge (pdf_stamp, property_dev exports)
]

# The CWICR vector-store client, in the lock since the [semantic-clients] extra
# landed. It is imported inside a function body (qdrant_adapter._get_client),
# which the static graph does follow, so the top-level package would arrive on
# its own. What would not arrive is what the code then reaches for: those
# submodules are themselves lazy (qdrant_client.http.models, and
# qdrant_client.local for the embedded on-disk store), named nowhere
# modulegraph can read. collect_submodules walks the whole package so the
# frozen sidecar carries the same client the wheel does. Without it the build
# keeps a client that cannot open a store, which is the behaviour the extra
# just fixed, wearing the shape of a working install.
hidden_imports += collect_submodules("qdrant_client")

# The local encoder, in the lock since the [semantic-encoder] extra landed.
# Every import of it sits inside a function body (core/vector.py get_embedder,
# costs/matcher.py), which is thinner than it looks rather than invisible: the
# static graph does follow imports inside function bodies, and a Windows build
# with this line deleted still collected 167 sentence_transformers modules off
# those two call sites. collect_submodules supplies the remaining 18.
#
# It has to be named here for a second reason that has nothing to do with
# imports. embedding_installer.start_background_download() asks
# semantic_library_available() before it fetches anything, and that answers by
# looking up a sentence_transformers spec. A frozen sidecar that carries the
# weights-downloader but not the library would find no spec, decline to start
# the download, and log a single INFO line - the desktop build advertising an
# encoder it had already decided not to fetch.
#
# torch and transformers arrive on their own as module-level imports of
# sentence_transformers, and their binary payloads are collected by the
# pyinstaller-hooks-contrib hooks once the packages are in the graph. They are
# named anyway, because what drags them in is one import statement inside
# somebody else's package and that is a thin thread to hang a gigabyte on.
hidden_imports += collect_submodules("sentence_transformers")
hidden_imports += ["torch", "transformers"]

# Auto-discover modules.
#
# The layers below are the ones the module loader reaches for by name rather
# than by import statement, so they have to be declared here. Not every module
# has every layer: 192 module packages carry 189 manifests, 188 routers, 173
# services, 171 schemas, 150 models, 110 repositories, 57 event modules, 40
# validator modules, 2 repair modules, one schema package and a single
# pipeline_nodes. Naming every layer for every module regardless produced 167
# lines of
#
#   ERROR: Hidden import 'app.modules.<name>.repository' not found
#
# on every desktop build, one per name that was never on disk. They were
# harmless - PyInstaller carries on and the bundle is complete - and that was
# the problem: a genuinely missing dependency reports itself with the same
# words, so the one line worth reading arrived as line 168 of a list nobody
# could read. The count is not a coincidence; the set of errors in the CI log
# for the 15.4.0 sidecar build is exactly the set of these names that no file
# backs.
#
# So ask the disk. A layer is declared when it exists as ``<layer>.py`` or as a
# ``<layer>/`` package, and is not mentioned at all otherwise, which leaves the
# hidden-import channel free to mean what it says. Excluding the absent names
# instead would have been wrong twice over: the ``excludes`` list below means
# "nothing in the sidecar imports this", and the list would need editing every
# time a module gained a file.
#
# The last five names are the ones the criterion had always covered and the
# tuple had never listed. ``module_loader`` imports ``events``, ``validators``
# and ``pipeline_nodes`` by name under ``contextlib.suppress``, and
# ``app/core/data_repairs.py`` walks ``app.modules`` with
# ``pkgutil.iter_modules`` and imports ``app.modules.<name>.repairs`` the same
# way. All of them reached the bundle before they were listed here, but only
# through the ``backend/app`` tree that ``datas`` ships below - measured on a
# published Windows sidecar, 27 of those files had no frozen module and were
# imported from source out of the extracted tree. That works, and it is not
# something to rest on: the ``datas`` entry describes itself as data, and the
# day somebody narrows it to what it says it is, five layers stop importing
# with no error to read.
#
# ``repairs`` is also why the criterion cannot be "a filename common enough to
# look like a layer". Two modules carry ``repairs.py`` today against 189
# manifests, so any rule keyed on how many modules have the file would rank it
# with the one-off helpers. Discovery is what makes a layer, not frequency.
#
# ``schema`` is the thinnest of the ten and it earns its place the same way.
# ``module_builder`` drops a module's table by importing
# ``app.modules.<key>.schema``, and exactly one package in the tree answers to
# that name: ``eac/schema/``, which holds the canonical EacRuleDefinition JSON
# Schema and the loader for it. Nothing imports that package with an import
# statement - the eac code reaches for ``schemas``, ``schemas_api`` and
# ``schemas_graph``, all of which are different files - so before this line it
# reached the sidecar only as source under ``datas``.
#
# The shape of the failure is what made this worth naming rather than leaving
# to luck. A discovery pass that finds nothing registers nothing, reports no
# failures and leaves the health endpoint describing a clean boot, on the one
# install route that ships no migration tree at all - which is the route the
# repairs were written to serve.
#
# backend/tests/unit/test_desktop_hidden_imports_resolve.py reads those import
# sites out of the backend source and fails if this tuple is missing one of
# them, so a layer invented next year arrives as a red test rather than as a
# silent dependency on the line below.
_MODULE_LAYERS = (
    "models",
    "schemas",
    "router",
    "service",
    "repository",
    "manifest",
    "events",
    "validators",
    "pipeline_nodes",
    "repairs",
    "schema",
)

if modules_dir.is_dir():
    for mod_dir in sorted(modules_dir.iterdir()):
        if mod_dir.is_dir() and (mod_dir / "__init__.py").exists():
            mod_name = mod_dir.name
            hidden_imports.append(f"app.modules.{mod_name}")
            for layer in _MODULE_LAYERS:
                if (mod_dir / f"{layer}.py").is_file() or (mod_dir / layer / "__init__.py").is_file():
                    hidden_imports.append(f"app.modules.{mod_name}.{layer}")

# Data files to include
datas = []

# Frontend dist
if FRONTEND_DIST.is_dir():
    datas.append((str(FRONTEND_DIST), "app/_frontend_dist"))

# Translation files, validation rules, etc. from backend.
#
# This ships the app package directory as it stands on the machine doing the
# building, so anything sitting in backend/app at that moment is baked into the
# artefact. A local build was measured carrying app/_frontend_dist_prev, 700
# files and 14.9 MB of gitignored leftover, which no release has ever contained
# because CI checks out clean. That is also why it has never been visible.
# Build from a clean tree before weighing an artefact or quoting what it holds.
datas.append((str(BACKEND / "app"), "app"))

# The backend UI locale catalogue. app/core/i18n.py resolves it as
# ``Path(__file__).parent.parent.parent / "locales"``, a directory that sits
# NEXT TO the app package rather than inside it, so shipping backend/app just
# above does not carry it: in a frozen bundle that path is
# ``sys._MEIPASS/locales``, and no desktop build had ever contained it.
#
# It survived that long because a missing catalogue used to be a warning that
# refilled the directory from an embedded copy, so the sidecar started and
# served a partial catalogue instead of failing. The copy knew 20 of the
# languages and a much smaller key set, which is why refilling was replaced by
# a hard error, and the error is right: recovering the wrong catalogue is
# worse than not recovering. What it also did was convert this omission from a
# quietly degraded desktop build into one that exits during startup, with the
# launcher able to report only that the backend did not start in time.
#
# The wheel force-includes the same folder at the same top-level path for the
# same reason (backend/pyproject.toml), and the two have to stay in step;
# backend/tests/unit/test_desktop_spec_ships_wheel_data.py checks that they do.
#
# Deliberately unconditional, unlike the frontend dist above. That one is
# absent on a tree nobody has built yet, this one is tracked in git, so a
# missing directory here means the build is wrong and PyInstaller should stop
# rather than produce another bundle that cannot start.
datas.append((str(BACKEND / "locales"), "locales"))

# The match service tuning data. Same shape as the catalogue above:
# app/core/match_service/data_paths.py looks for a ``data/match`` directory
# beside the app package, which in a frozen bundle is
# ``sys._MEIPASS/data/match``, so shipping backend/app does not carry it.
# Four files, about 12 KB, holding encoder score bands, per language fuzzy
# cutoffs and two region overlays.
#
# This one never broke a build and never will, which is the reason it went
# unnoticed: every reader falls back to hardcoded constants when the
# directory is absent, so no desktop bundle has ever failed over it and none
# has ever used the shipped tuning either. The wheel force-includes the same
# directory at the same destination (backend/pyproject.toml) and
# backend/tests/unit/test_desktop_spec_ships_wheel_data.py checks the pair.
#
# Not to be confused with the NOTE at the top of this file: that one is
# about ``data/catalog``, which stays out of the installer on a licensing
# basis NOTICE records as pending. These four files were authored in this
# repository and carry the project's own copyright header.
#
# Unconditional, like the catalogue and the packs: tracked in git, so an
# absent directory means the build is wrong and PyInstaller should say so.
datas.append((str(ROOT / "data" / "match"), "data/match"))

# The community packs. Same shape as the catalogue above and missing for the
# same reason: app/core/partner_pack/discovery.py looks for a ``packs``
# directory sitting NEXT TO the app package, which in a frozen bundle is
# ``sys._MEIPASS/packs``, so shipping backend/app does not carry them and no
# desktop build had ever contained one. The wheel force-includes the same
# fifteen paths at the same destinations (backend/pyproject.toml), and
# backend/tests/unit/test_desktop_spec_ships_wheel_data.py checks the two
# lists against each other.
#
# The list is written out here rather than derived from the wheel map on
# purpose. Reading the map would make that comparison agree with itself, and
# the point of the gate is that two independently maintained lists have to be
# brought into line by hand when a pack is added.
#
# Which packs, and why not all nineteen, is a licensing decision recorded next
# to the wheel map: the deprecated pack and the three carrying a third party's
# name are held back from community artefacts.
_COMMUNITY_PACKS = (
    "aus",
    "brazil-sinapi",
    "china-gbt50500",
    "hungary-hu",
    "russia-gesn",
    "india-cpwd",
    "mexico-mx",
    "modular-prefab",
    "nzs",
    "renewables-epc",
    "retail-grocery-dach",
    "saudi-vision2030",
    "south-africa",
    "uk-jct",
    "us-california",
    "us-costdata",
    "us-texas",
)
for _pack_slug in _COMMUNITY_PACKS:
    # Unconditional, like the catalogue: these are tracked in git, so an
    # absent one means the build is wrong and PyInstaller should say so rather
    # than produce another bundle that lists no packs.
    datas.append((str(ROOT / "packs" / _pack_slug / "src"), f"packs/{_pack_slug}/src"))

# Ship pyproject.toml next to the bundled app package. _detect_version()
# reads the version from the source tree first and only falls back to the
# installed-wheel metadata if it cannot find a pyproject. In a frozen build
# there is no source tree, so without this the sidecar would report whatever
# openconstructionerp version happens to be pip-installed on the build
# machine instead of the real product version. Landing it at the bundle root
# (one level above app/) is exactly where _read_pyproject_version walks to.
#
# Stronger than that, and the reason not to tidy this away as redundant: this
# spec calls copy_metadata nowhere, so a frozen bundle carries dist-info only
# for whatever an upstream hook pulls in on its own. importlib.metadata is a
# source-install instrument and answers no for openconstructionerp here, which
# means the fallback this line feeds is the only branch that can answer at all.
# It also covers a second reader by accident: sarif_exporter walks
# parents[3] / "pyproject.toml", which is backend/pyproject.toml in the source
# tree and the bundle root here, because app/ sits at the root. That coincidence
# breaks the day app/ moves one level down, so move the two together.
_pyproject = BACKEND / "pyproject.toml"
if _pyproject.is_file():
    datas.append((str(_pyproject), "."))

a = Analysis(
    [str(BACKEND / "app" / "cli.py")],
    pathex=[str(BACKEND)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    # Local hooks dir holds hook-pixeltable_pgserver.py, which collects the
    # ~40 MB pginstall/ tree (postgres, initdb, pg_ctl + runtime libs) the
    # embedded cluster needs. Without it the sidecar starts then dies with
    # "postgres executable not found".
    hookspath=[str(Path(SPECPATH) / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    # numpy / pandas / openpyxl / pyarrow are base runtime deps (cost-DB
    # Excel/CSV/Parquet import), so they must NOT be excluded. What is left here
    # is dropped because nothing in the sidecar imports it, and that is the only
    # thing this list is allowed to mean.
    #
    # torch and scipy used to sit here, and the comment above them called the
    # whole list genuinely unused. That was true when it was written and stopped
    # being true when the encoder download went default-on for desktop_mode: the
    # feature ships an embedding model, the model is loaded through
    # sentence_transformers, and sentence_transformers imports torch at module
    # level and pulls scipy through scikit-learn. Excluding them did not slim a
    # build that used them, it removed a feature the same release advertises,
    # and it removed it only on the desktop channel, where nobody installing a
    # wheel would ever see it. Both names are now in requirements-desktop.lock
    # and both are gone from this list.
    #
    # It costs what a machine-learning runtime costs, and the number depends on
    # a decision made in the lock rather than here. torch's Linux wheels on PyPI
    # declare the whole nvidia CUDA stack, so a lock compiled without
    # --torch-backend=cpu adds about 2.7 GB there against about 190 MB on
    # Windows. The lock pins the CPU build, which brings Linux back in line and
    # costs the other two platforms nothing, because their PyPI wheels were
    # CPU-only to begin with. It is worth more than a download counter: the EXE
    # below is a onefile build that unpacks its entire payload to a temporary
    # directory on every launch, so this weight is paid at every start.
    #
    # The Qt bindings stay excluded because the sidecar is a headless HTTP
    # server with no GUI; they are never imported at runtime. That exclusion
    # also avoids PyInstaller's hard abort when a build machine happens to have
    # more than one Qt binding installed (it refuses to bundle both PyQt and
    # PySide), which would otherwise break the build on developer machines that
    # carry a full scientific Python stack.
    #
    # Nothing here may also appear in requirements-desktop.lock. A name in both
    # files is the exact shape of the bug above: a dependency deliberately
    # installed and then deliberately thrown away. That pairing is checked by
    # backend/tests/unit/test_desktop_lock_deps.py.
    excludes=[
        "tkinter",
        "matplotlib",
        "tensorflow",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

# Ad-hoc sign every Mach-O collected into the archive, not only the executable
# wrapped around it. macOS only; PyInstaller ignores the option elsewhere, and
# naming it unconditionally would be a lie about what the build does on Windows.
#
# An ad-hoc signature carries no Team ID, so two ad-hoc binaries can never
# mismatch. The binaries collected into the archive are a different matter: the
# Python framework installed by the build machine is signed by whoever built
# that Python, and PyInstaller packs it verbatim. At launch the onefile
# bootloader extracts the archive to a temporary directory and dlopens the
# framework from there, and dyld compares the two signatures:
#
#   code signature in '.../_MEIxxxxxx/Python.framework/Versions/3.12/Python'
#   not valid for use in process: mapping process and mapped file
#   (non-platform) have different Team IDs
#
# The process is ad-hoc with no Team ID, the framework has a real one, and the
# load is refused. The app reaches "Starting the application server" and stops
# there, on a machine that is otherwise fine. Reported against 14.4.0 on macOS
# 26, Apple Silicon, by a user who had already cleared Gatekeeper by hand.
#
# The fix is to make the payload's identity match the process's rather than to
# grant the process permission to ignore the mismatch. That needs no
# entitlement and no hardened runtime, so Entitlements.plist stays out of this
# and the ad-hoc rule in docs/desktop/MACOS_NOTARIZATION.md still holds: on the
# ad-hoc path, sign with "-" and no timestamp.
#
# This is also a prerequisite for notarization rather than a stopgap. The notary
# service sees a onefile sidecar as one Mach-O and never inspects the archive
# appended to it, so a notarized build made without this would sign the wrapper,
# pass review and still fail to start, with the mismatch now against a real Team
# ID instead of none.
codesign_identity = "-" if sys.platform == "darwin" else None

# Unpack into a directory this application owns, rather than into the system
# temporary folder.
#
# `_MEI` is PyInstaller's prefix for every program built with it, not a name of
# ours, so by default our extractions sit in %TEMP% among other vendors'. That
# is not only untidy. The launcher clears abandoned extractions at start
# (sweep_orphaned_extractions in src-tauri/src/main.rs), and in the system
# folder it would be deciding whether somebody else's abandoned directory is
# safe to remove, which is a different question from whether the directory is
# ours. Naming a root we created turns that judgement back into a fact.
#
# Under the local application data folder rather than in a folder of ours
# inside %TEMP%, because Windows cleans %TEMP% on its own: Disk Cleanup and
# Storage Sense remove temporary files that have not been touched for some
# days, and Storage Sense runs by itself when the drive is nearly full. Only
# the executables and libraries of a live extraction are held open; its data
# files are not, so such a run finds them removable while a postmaster is still
# serving out of the directory, and the postmaster then fails on the next file
# it goes to read. Nothing cleans the application data folder except the
# launcher's own sweep, which asks first. The price is that a user who moved
# %TEMP% to another drive now gets the unpacking on the system drive.
#
# Windows only, and not for lack of trying elsewhere. The bootloader expands
# environment variables in this string on Windows and documents that it does
# NOT do so on POSIX, where `~` and `$HOME` are taken literally. Every path we
# could name there would therefore be the same path for every user on the
# machine, in a world-writable directory, which is a name somebody else can
# create first. The system folder's own per-user handling is better than that,
# so POSIX keeps it, and the launcher's sweep does not run there at all.
#
# Measured rather than assumed, with PyInstaller 6.21.0, the version the release
# workflow pins: a one-file probe built with
# `--runtime-tmpdir %LOCALAPPDATA%\OCE_probe462\deep\nested` printed a
# `sys._MEIPASS` of `C:\Users\<name>\AppData\Local\OCE_probe462\deep\nested\_MEI314762`,
# having expanded the variable and created the whole missing parent chain
# itself, and removed the `_MEI` directory again on a clean exit, leaving the
# empty chain behind.
#
# The launcher has to resolve the same directory to sweep it and to measure the
# free space on it, so it carries this string as EXTRACTION_ROOT_SPEC_LITERAL
# and a test in main.rs reads this file and fails if the two stop matching.
_WINDOWS_RUNTIME_TMPDIR = r"%LOCALAPPDATA%\OpenConstructionERP\extract"

# Build a SINGLE self-contained executable (onefile), not a onedir folder.
# Tauri ships the sidecar as an externalBin, which must be one standalone file;
# a onedir build (exe + a separate _internal/ folder) cannot be used that way,
# because Tauri copies only the named binary and the sidecar would then fail to
# find its bundled Python runtime and PostgreSQL binaries. Folding a.binaries /
# a.datas / a.zipfiles into EXE produces the single file.
#
# UPX is deliberately off. Compressing the embedded PostgreSQL executables and
# their DLLs risks corrupting them, and UPX-packed binaries frequently trip
# antivirus heuristics, which is the last thing a downloadable installer needs.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="openconstructionerp-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=(_WINDOWS_RUNTIME_TMPDIR if sys.platform == "win32" else None),
    console=True,  # Keep console for server logging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=codesign_identity,
    entitlements_file=None,
)
