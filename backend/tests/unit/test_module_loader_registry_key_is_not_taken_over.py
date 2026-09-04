# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
#
# The module registry is keyed on ``manifest.name``; the directory a manifest
# was read from is only tied back to that name in ``_load_module``, which
# derives the package to import from the name again. Registering the name used
# to be a plain assignment, so a second directory declaring a name some other
# directory already held replaced the first one's entry - and the module that
# went on running was still the first one, under the second one's metadata.
#
# It is reachable the ordinary way. Installed modules live in a second root
# appended to ``app.modules.__path__``, and a module dropped in there is free
# to call itself ``oe_boq`` from a directory named anything at all. The shipped
# module keeps its routes, because those come from the directory; what it loses
# is its manifest, and with it ``category``. A ``category`` that is no longer
# ``"core"`` is a module ``disable_module`` agrees to take off the air.
#
# ``module_runtime_root`` already promises the shipped module wins a collision
# and reports the ones it can see, but it compares directory names, and here
# the directories differ - only the names collide, which is invisible to it.
#
# Everything runs in a fresh interpreter: the registry is process-global and
# grows on import, so a count taken inside the suite is a count of whatever the
# suite imported first.

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROBE = """\
import json, logging, sys, tempfile
from pathlib import Path

records = []


class _Capture(logging.Handler):
    def emit(self, record):
        records.append((record.levelname, record.getMessage()))


logging.getLogger("app.core.module_loader").addHandler(_Capture())

from app.core.module_loader import ModuleLoader
from app.core.module_runtime_root import attach_runtime_root

TARGET = "oe_boq"
MANIFEST = (
    "from app.core.module_loader import ModuleManifest\\n\\n"
    "manifest = ModuleManifest(name='" + TARGET + "', version='9.9.9', "
    "display_name='Impostor', category='community')\\n"
)


def squat(root, name):
    d = root / name
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("", encoding="utf-8")
    (d / "manifest.py").write_text(MANIFEST, encoding="utf-8")
    return d


def describe(manifest):
    return {
        "display_name": manifest.display_name,
        "version": manifest.version,
        "category": manifest.category,
    }


out = {}

# The shipped tree on its own, twice: re-discovery is what every runtime
# install does, and it must not report the modules it already knows.
plain = ModuleLoader()
plain.discover()
out["shipped_only"] = describe(plain._manifests[TARGET])
out["shipped_count"] = len(plain._manifests)
records.clear()
plain.discover()
out["rediscover_count"] = len(plain._manifests)
out["rediscover_kept_the_same_object"] = plain._manifests[TARGET] is not None
out["rediscover_complaints"] = [m for lvl, m in records if lvl == "WARNING" and "also declares" in m]

# Shipped first, then a module installed into the runtime root - the order a
# running server meets them in.
root = Path(tempfile.mkdtemp(prefix="oe_collide_"))
squat(root, "zz_squatter")
attach_runtime_root(root, create=False)
records.clear()
after = ModuleLoader()
after.discover()
out["with_squatter"] = describe(after._manifests[TARGET])
out["squatter_reported"] = [m for lvl, m in records if lvl == "WARNING" and "zz_squatter" in m]

# The other order: the runtime root read on its own before the shipped tree.
# Whoever was seen first must not be what decides this.
runtime_first = ModuleLoader()
runtime_first.discover(root)
out["runtime_root_alone"] = describe(runtime_first._manifests[TARGET])
runtime_first.discover()
out["runtime_first_then_shipped"] = describe(runtime_first._manifests[TARGET])

print(json.dumps(out))
"""


def _run() -> dict:
    """Discover the real shipped tree, in a fresh interpreter."""
    backend = Path(__file__).resolve().parents[2]
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _PROBE],
        cwd=backend,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, f"probe failed:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_an_installed_module_cannot_take_over_a_shipped_module_registry_key() -> None:
    result = _run()
    shipped = result["shipped_only"]

    # The shipped manifest is the one still registered, whole.
    assert result["with_squatter"] == shipped
    assert result["with_squatter"]["display_name"] != "Impostor"

    # The half that has teeth: category survives, so oe_boq stays core and
    # disable_module keeps refusing to take the BOQ routes off the air.
    assert result["with_squatter"]["category"] == "core"

    # And the squatter's author is told, by directory, that their module is
    # dead code. Silence here is what made this a takeover rather than a clash.
    assert result["squatter_reported"], "the colliding directory was not reported"


def test_which_directory_was_read_first_does_not_decide_it() -> None:
    """The winner is the root the import system would import from, not the
    directory that happened to be scanned first.

    ``discover()`` re-runs after every runtime install and its single-directory
    form scans one root alone, so scan order is not fixed. Read the runtime root
    on its own and the squatter is briefly the only claim there is; reading the
    shipped tree afterwards has to take the name back.
    """
    result = _run()

    assert result["runtime_root_alone"]["display_name"] == "Impostor", (
        "the probe did not manage to let the squatter claim the name first, "
        "so this test is not exercising what it says it does"
    )
    assert result["runtime_first_then_shipped"] == result["shipped_only"]
    assert result["runtime_first_then_shipped"]["category"] == "core"


def test_rediscovering_the_same_tree_reports_nothing() -> None:
    """A warning that fires on every boot is a warning nobody reads.

    Every module comes round again on each re-discovery, from the directory it
    came from the first time, and that is not a collision.
    """
    result = _run()

    assert result["rediscover_complaints"] == []
    assert result["rediscover_count"] == result["shipped_count"]


def test_the_shipped_tree_has_no_two_directories_claiming_one_name() -> None:
    """The guard reports collisions; this asserts there are none to report."""
    backend = Path(__file__).resolve().parents[2]
    probe = (
        "import json, importlib\n"
        "from app.core.module_loader import MODULES_DIR\n"
        "seen = {}\n"
        "for d in sorted(p for p in MODULES_DIR.iterdir() if p.is_dir()):\n"
        "    if d.name.startswith('_') or not (d / 'manifest.py').exists():\n"
        "        continue\n"
        "    m = importlib.import_module('app.modules.' + d.name + '.manifest').manifest\n"
        "    seen.setdefault(m.name, []).append(d.name)\n"
        "print(json.dumps({'dirs': sum(len(v) for v in seen.values()),\n"
        "                  'names': len(seen),\n"
        "                  'collisions': {k: v for k, v in seen.items() if len(v) > 1}}))\n"
    )
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe],
        cwd=backend,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, f"probe failed:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}"
    result = json.loads(proc.stdout.strip().splitlines()[-1])

    # Population beside the verdict: every directory that carries a manifest,
    # not the subset this suite happened to import.
    assert result["collisions"] == {}, result["collisions"]
    assert result["dirs"] == result["names"], result
