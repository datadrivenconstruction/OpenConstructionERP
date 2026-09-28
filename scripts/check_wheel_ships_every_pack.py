# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Ask an INSTALLED wheel which packs it lists, and whether each one can read its files.

Run with the interpreter of a clean virtualenv the built wheel was installed
into, from a directory outside the repository, so ``app`` resolves to
``site-packages`` and not to the source tree::

    cd "$RUNNER_TEMP" && "$VENV/bin/python" "$REPO/scripts/check_wheel_ships_every_pack.py" "$REPO"

The unit gates read the tree and the publish workflow reads the archive at tag
time, with a floor rather than the list. Neither one installs the wheel and asks
discovery the question a user's install asks. This does, before a tag exists:

* the packs discovery lists are exactly the packs ``backend/pyproject.toml``
  force-includes, no fewer and no withheld partner pack;
* every file a manifest names (onboarding script, logo, favicon, extra locales,
  rule-pack documents) is readable through ``read_pack_file``, which is the
  path the API serves them on.

Exits non-zero and names every failure.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path, PurePosixPath


def _shipped(repo: Path) -> set[str]:
    data = tomllib.loads((repo / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    fi = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    return {PurePosixPath(k).parts[2] for k in fi if k.startswith("../packs/")}


def main() -> int:
    repo = Path(sys.argv[1]).resolve()
    # app.database builds its engine at import and refuses a non-PostgreSQL URL.
    # Nothing here connects.
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://oe:oe@127.0.0.1:1/oe")
    os.environ.setdefault("DATABASE_SYNC_URL", "postgresql+psycopg2://oe:oe@127.0.0.1:1/oe")

    import app
    from app.core.partner_pack.discovery import _packs_dir, discover_packs, read_pack_file, reset_cache

    where = Path(app.__file__).resolve()
    if repo in where.parents:
        print(f"app resolved to the source tree ({where}); run from outside the repository")
        return 2

    reset_cache()
    tree = _packs_dir()
    if tree is None:
        print(f"the installed app ({where}) finds no pack tree at all")
        return 1

    failures: list[str] = []
    installed_dirs = {p.parents[2].name for p in tree.glob("*/src/openconstructionerp_*/manifest.py")}
    expected = _shipped(repo)
    for name in sorted(expected - installed_dirs):
        failures.append(f"{name}: force-included but not in the installed pack tree {tree}")
    for name in sorted(installed_dirs - expected):
        failures.append(f"{name}: in the installed pack tree but not force-included")

    packs = discover_packs()
    if len(packs) != len(expected):
        failures.append(f"discovery lists {len(packs)} packs, the wheel ships {len(expected)}")

    checked = 0
    for m in packs:
        wanted = [m.onboarding_script_path, m.branding.logo_path, m.branding.favicon_path]
        wanted += list(m.additional_locales.values())
        wanted += [f"rule_packs/{doc}.json" for doc in m.validation_rule_packs]
        for rel in filter(None, wanted):
            checked += 1
            if not read_pack_file(m.slug, rel):
                failures.append(f"{m.slug}: manifest names {rel}, the installed pack cannot read it")

    print(f"installed app: {where}")
    print(f"pack tree: {tree}")
    print(f"{len(packs)} packs discovered, {len(expected)} shipped, {checked} declared files read")
    for f in failures:
        print(f"FAIL {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
