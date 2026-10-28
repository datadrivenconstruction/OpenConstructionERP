#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Fail if a directory under backend/app/modules has no manifest.py.

The module loader finds modules by looking for a manifest. `ModuleLoader.discover`
walks each module root and `_discover_in` keeps a directory only if it holds a
`manifest.py`; a directory without one is skipped by a bare `continue`, with no
log line, no warning and no error.

That silence is the whole reason this gate exists. Every other way a module can
be wrong is loud: a manifest that raises on import gets a `logger.exception`, a
manifest with no `ModuleManifest` in it gets a `logger.warning`, an unresolvable
`depends` entry gets a warning from `resolve_order`. Only absence is quiet, and
absence is the one case where a module that is missing looks exactly like a
module that was never written. There is no diagnostic to grep for, because
nothing is emitted.

What absence costs, when the directory is a real module:

  * it is not in the registry, so `GET /api/v1/modules` does not list it and the
    admin enable/disable UI has no row for it;
  * its `router.py` is never mounted, so every endpoint in it answers 404 in
    production while the file sits in the tree looking implemented;
  * its `models.py` is never imported, so Alembic autogenerate never sees the
    tables and a fresh database does not have them;
  * nothing can declare it in `depends`, because there is no name to depend on.

Three directories are exempt today and each is a genuine support library: pure
Python domain math, no router, no ORM. See ALLOWLIST below for the per-entry
reason. The exemption is not taken on trust - `_exempt_premise_holds` rechecks
the claim on every run, so the day one of them grows a router or declares a
table the allowlist stops covering it and this gate fails. An allowlist that
never rechecks why it exists is just a list of names.

Scope, stated so nobody reads more into a green run than it earns: this checks
that a manifest is PRESENT. It does not check that the manifest is valid. A
`manifest.py` that raises on import, or that defines no `ModuleManifest`, passes
this gate and still leaves the module unloaded - loudly, in the log, which is a
different problem with a different signal.

Run from anywhere:

    python scripts/check_module_manifests.py

An optional argument scans a different directory instead, which is what the
gate's own negative-control test uses so it never has to touch the real tree:

    python scripts/check_module_manifests.py /path/to/fixture
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULES = ROOT / "backend" / "app" / "modules"

# Directories that are deliberately not modules. Each is a pure library imported
# by modules that do carry a manifest, so its code ships and its endpoints are
# mounted - by the importing module's router, under the importing module's name.
ALLOWLIST: dict[str, str] = {
    # EN 16931 e-invoice writer (CII and UBL). Pure library, ORM-free; the
    # download endpoints live in oe_finance and render from its Invoice.
    "einvoice": "pure EN 16931 library, no router and no tables; used by oe_finance",
    # Formula-based take-off math. Pure library, ORM-free; the measurement-sheet
    # endpoints live in oe_boq and render from its BoQ items.
    "measurement": "pure take-off library, no router and no tables; used by oe_boq",
    # Unit-rate decomposition math. Pure library, ORM-free; the price-analysis
    # endpoints live in oe_boq, and the model is shared by several modules.
    "price_breakdown": "pure unit-rate library, no router and no tables; used by oe_boq and others",
}

# What disqualifies a directory from the allowlist. A support library has no
# router to mount and owns no tables; if either appears, the directory is a
# module whatever the allowlist says, and the exemption has to be re-argued.
#
# The two halves are detected differently on purpose. A router is found by
# filename because that is exactly how the loader finds it - `router.py`, no
# other name works. Tables are found by content, because filename is the wrong
# question here: two of the three allowlisted directories keep their domain
# model in `model.py`, singular, and a check that looked for `models.py` would
# have stayed green while `price_breakdown/model.py` grew a `__tablename__` and
# its tables quietly never reached Alembic - the precise failure this gate is
# for. Content also catches a table declared in a file called anything at all.
ROUTER_FILE = "router.py"
ORM_MARKERS = ("__tablename__", "DeclarativeBase", "declarative_base", "Mapped[")


def scanned_directories(modules_dir: pathlib.Path) -> list[pathlib.Path]:
    """Every directory the loader would consider, by the loader's own predicate.

    Mirror of the filter in `ModuleLoader._discover_in`: sorted iteration, keep
    directories, skip any name starting with an underscore. Deliberately not
    keyed on `__init__.py`, which the loader does not look at either - a
    directory with neither file is just as invisible, and a gate whose
    population differs from the loader's reports on a different set of modules
    than the one that actually loads.
    """
    return [entry for entry in sorted(modules_dir.iterdir()) if entry.is_dir() and not entry.name.startswith("_")]


def _exempt_premise_holds(module_dir: pathlib.Path) -> list[str]:
    """What this directory holds that contradicts "only a support library"."""
    found: list[str] = []
    if (module_dir / ROUTER_FILE).exists():
        found.append(ROUTER_FILE)
    for source in sorted(module_dir.glob("*.py")):
        text = source.read_text(encoding="utf-8", errors="replace")
        if any(marker in text for marker in ORM_MARKERS):
            found.append(f"ORM models in {source.name}")
            break
    return found


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    modules_dir = pathlib.Path(args[0]).resolve() if args else MODULES

    if not modules_dir.is_dir():
        print(f"modules directory not found: {modules_dir}", file=sys.stderr)
        return 1

    directories = scanned_directories(modules_dir)
    if not directories:
        print(f"no module directories found under {modules_dir}", file=sys.stderr)
        return 1

    missing: list[pathlib.Path] = []
    over_exempt: list[tuple[pathlib.Path, list[str]]] = []
    exempt = 0

    for module_dir in directories:
        if (module_dir / "manifest.py").exists():
            continue
        if module_dir.name in ALLOWLIST:
            contradicts = _exempt_premise_holds(module_dir)
            if contradicts:
                over_exempt.append((module_dir, contradicts))
            else:
                exempt += 1
            continue
        missing.append(module_dir)

    failed = False

    if missing:
        failed = True
        print(
            f"\n{len(missing)} directory(ies) under {modules_dir} have no manifest.py:",
            file=sys.stderr,
        )
        for module_dir in missing:
            evidence = _exempt_premise_holds(module_dir)
            detail = f"  has {', '.join(evidence)}" if evidence else ""
            print(f"  {module_dir.name}{detail}", file=sys.stderr)
        print(
            "\nThe loader skips a directory with no manifest.py silently - no log line and no\n"
            "error - so this does not surface anywhere at runtime. The module is absent from\n"
            "the registry and from GET /api/v1/modules, its router is never mounted and every\n"
            "endpoint in it answers 404, its models never reach Alembic autogenerate, and no\n"
            "other manifest can name it in depends.\n"
            "\n"
            "Either write the manifest, or - if the directory is a support library with no\n"
            "router and no tables - add it to ALLOWLIST in this file with a one-line reason.",
            file=sys.stderr,
        )

    if over_exempt:
        failed = True
        print(
            f"\n{len(over_exempt)} allowlisted directory(ies) are no longer support libraries:",
            file=sys.stderr,
        )
        for module_dir, contradicts in over_exempt:
            found = ", ".join(contradicts)
            print(f"  {module_dir.name}  now has {found}", file=sys.stderr)
            print(f"    exempted as: {ALLOWLIST[module_dir.name]}", file=sys.stderr)
        print(
            "\nThe exemption was granted because the directory had no router to mount and no\n"
            "tables to migrate. It has one now, and it is still invisible to the loader, so\n"
            "those routes are not served and those tables are not created. Write the manifest\n"
            "and drop the allowlist entry.",
            file=sys.stderr,
        )

    if failed:
        return 1

    carrying = len(directories) - exempt
    print(
        f"module manifests: {len(directories)} directories scanned under {modules_dir.name}, "
        f"{carrying} carr{'ies' if carrying == 1 else 'y'} a manifest, {exempt} allowlisted "
        f"support librar{'y' if exempt == 1 else 'ies'}, 0 silently invisible."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
