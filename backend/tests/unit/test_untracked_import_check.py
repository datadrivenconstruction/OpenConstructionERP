"""The gate that refuses a commit importing a module git does not carry.

``scripts/check_untracked_imports.py`` exists because of a defect that is
invisible where it is written. A committed file imports a module that only
exists as an untracked file in the working tree; every import works and every
test passes on the author's disk, and the backend fails to start on the first
machine that reads the commit instead of the disk. Two instances of it sat in
the tree on the day the script was written.

A gate is only worth its silence if its noise has been seen, so every case here
comes in the pair that matters: one tree the check must refuse, and beside it
the nearest tree it must accept. The false-accept half is what proves the check
still works; the false-reject half is what keeps it switched on, because a gate
that fires on a shared tree with many authors is a gate somebody deletes.

The shapes that must NOT be refused are not invented. Each is in backend/ now:

    * ``import alembic.config`` - a third-party package whose name is also a
      directory under backend/. That directory has no ``__init__.py``, so it is
      a namespace portion and loses to the installed distribution. A first cut
      of the script treated every directory as a project root and reported 51
      findings, all of them this line, burying the 3 real ones.
    * ``if TYPE_CHECKING:`` imports, which never execute.
    * ``try: import x / except Exception: pass`` around an import of
      ``app.core.models_registry``, a module that does not exist and is not
      meant to - backend/app/scripts/migrate_sqlite_to_postgres.py.
    * ``from package import Symbol``, where the symbol is a class rather than a
      submodule. This is most of the from-imports in the tree.

And the shape that must NOT be accepted merely because it is wrapped: an
``except ImportError:`` whose body only re-raises is not a fallback. The module
is still required, so the import still has to be in the commit.

Cases:
    * an untracked module behind a plain import is caught
    * the same import passes once the module is tracked
    * a module absent from the tree entirely is caught
    * a gitignored module is caught, and said to be ignored rather than missing
    * an untracked ``__init__.py`` on the path is caught
    * ``from package import untracked_submodule`` is caught
    * ``from package import Symbol`` is not caught
    * a third-party name matching a namespace directory is not caught
    * a namespace directory inside the project is not caught either
    * TYPE_CHECKING imports are not caught
    * an optional import with a real fallback is not caught
    * an ``except ImportError`` that only re-raises is still caught
    * a broad ``except Exception`` around real work does not silence the import
    * relative imports resolve to the right package before being judged
    * the script's own --self-test refuses a bad tree, and fails when it cannot

Deliberately not here: an assertion that the live tree is clean right now.
``Repo hygiene`` runs the script against the real files on every push, so a
copy of that assertion would be a second check of one thing, and it would be a
slow one - the full scan reads every tracked Python file under backend/. Worse,
in a working tree it would go red for whoever ran it whenever any of the many
authors sharing this tree had an untracked module half-written, which is the
normal state of that tree and not a defect in anybody's commit. What is left
here is what a run against the tree cannot cover: the shapes the check has to
judge, including the ones that do not exist in the tree and would not until the
day they broke it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_untracked_imports.py"

# A minimal tracked tree: one package, one submodule, one importer.
TRACKED = {
    "backend/app/__init__.py",
    "backend/app/core/__init__.py",
    "backend/app/core/config.py",
    "backend/app/modules/__init__.py",
    "backend/app/modules/takeoff/__init__.py",
    "backend/app/modules/takeoff/router.py",
    "backend/app/main.py",
}


def _load_script():
    """Import the script by path. scripts/ is not a package.

    Both the spec and its loader are Optional in the stdlib signature, and an
    unguarded dereference turns a failed resolution into an AttributeError on a
    line that says nothing about the cause.

    The module has to be in ``sys.modules`` before it executes. ``@dataclass``
    resolves its annotations through ``sys.modules[cls.__module__]``, so a
    module loaded from a spec and never registered raises AttributeError on
    None inside dataclasses.py, on a line that names neither this file nor the
    script.
    """
    spec = importlib.util.spec_from_file_location("check_untracked_imports", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not build an import spec for {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return _load_script()


def _index(script, *, tracked=None, untracked=(), ignored=()):
    """Build a ModuleIndex over a tree that does not exist on disk."""
    tracked_set = set(TRACKED if tracked is None else tracked)
    on_disk = tracked_set | set(untracked) | set(ignored)
    return script.ModuleIndex(tracked=tracked_set, on_disk=on_disk, untracked=set(untracked))


def _check(script, source: str, index, path: str = "backend/app/main.py"):
    return script.check_file(path, source, index)


def _modules(findings) -> list[str]:
    return sorted(finding.module for finding in findings)


def test_script_exists():
    """A rename or a move would make every other test here silently vacuous."""
    assert SCRIPT_PATH.is_file(), SCRIPT_PATH


# --------------------------------------------------------------------------
# The half that must be refused.
# --------------------------------------------------------------------------


def test_an_untracked_module_behind_a_plain_import_is_caught(script):
    """The live shape: backend/app/main.py importing app.core.host_disclosure."""
    index = _index(script, untracked=["backend/app/core/host_disclosure.py"])
    findings = _check(script, "from app.core.host_disclosure import describe\n", index)
    assert _modules(findings) == ["app.core.host_disclosure"]
    assert findings[0].reason == "untracked"
    assert findings[0].defining_file == "backend/app/core/host_disclosure.py"


def test_the_same_import_passes_once_the_module_is_tracked(script):
    """The other direction of the same case: the check has to be able to clear.

    Without this, a check that returned a finding for every import would pass
    the test above and be useless.
    """
    index = _index(script, tracked=TRACKED | {"backend/app/core/host_disclosure.py"})
    assert _check(script, "from app.core.host_disclosure import describe\n", index) == []


def test_a_module_absent_from_the_tree_entirely_is_caught(script):
    """What the working-tree defect looks like once it reaches a checkout.

    A checkout has no untracked files at all, so the same broken import shows up
    as a name nothing defines. One rule has to cover both worlds or the gate
    only works on the machine where the mistake was made.
    """
    index = _index(script)
    findings = _check(script, "from app.core.nothing_defines_this import thing\n", index)
    assert _modules(findings) == ["app.core.nothing_defines_this"]
    assert findings[0].reason == "no such module"


def test_a_gitignored_module_is_caught_and_named_as_ignored(script):
    """An ignored file can never be committed, so `git add` is the wrong advice.

    `git ls-files --others --exclude-standard` cannot see this case at all,
    which is why the check compares against the tracked set and the disk rather
    than against the untracked list.
    """
    index = _index(script, ignored=["backend/app/core/scratch_probe.py"])
    findings = _check(script, "import app.core.scratch_probe\n", index)
    assert _modules(findings) == ["app.core.scratch_probe"]
    assert findings[0].reason == "ignored by .gitignore"


def test_an_untracked_package_init_on_the_path_is_caught(script):
    """The submodule can be tracked and the import still fail in a checkout."""
    index = _index(
        script,
        tracked=TRACKED | {"backend/app/modules/postcalc/norm.py"},
        untracked=["backend/app/modules/postcalc/__init__.py"],
    )
    findings = _check(script, "from app.modules.postcalc.norm import rate\n", index)
    assert "app.modules.postcalc" in _modules(findings)


def test_a_from_import_of_an_untracked_submodule_is_caught(script):
    """`from package import submodule` is an import of the submodule."""
    index = _index(script, untracked=["backend/app/modules/takeoff/probe.py"])
    findings = _check(script, "from app.modules.takeoff import router, probe\n", index)
    assert _modules(findings) == ["app.modules.takeoff.probe"]


def test_an_except_importerror_that_only_reraises_is_still_caught(script):
    """Re-raising is not a fallback. The module is still required."""
    source = (
        "try:\n"
        "    from app.core.host_disclosure import describe\n"
        "except ImportError as exc:\n"
        '    raise RuntimeError("install the extras") from exc\n'
    )
    index = _index(script, untracked=["backend/app/core/host_disclosure.py"])
    assert _modules(_check(script, source, index)) == ["app.core.host_disclosure"]


def test_a_broad_except_around_real_work_does_not_silence_the_import(script):
    """backend/app/main.py guards startup in `except Exception` throughout.

    Treating every such block as an optional-import guard took 111 of the 232
    intra-project imports in four files out of the check's reach. A bare
    `except Exception` only makes an import optional when the try body is
    nothing but imports, which is the shape of an optional dependency and not
    the shape of a guarded startup block.
    """
    source = (
        "def boot(app):\n"
        "    try:\n"
        "        from app.core.host_disclosure import describe\n"
        "        app.state.disclosure = describe()\n"
        "        app.state.ready = True\n"
        "    except Exception:\n"
        "        app.state.ready = False\n"
    )
    index = _index(script, untracked=["backend/app/core/host_disclosure.py"])
    assert _modules(_check(script, source, index)) == ["app.core.host_disclosure"]


def test_a_relative_import_of_an_untracked_sibling_is_caught(script):
    """`from . import x` has to be resolved before it can be judged."""
    index = _index(script, untracked=["backend/app/modules/takeoff/probe.py"])
    findings = _check(
        script,
        "from . import probe\n",
        index,
        path="backend/app/modules/takeoff/router.py",
    )
    assert _modules(findings) == ["app.modules.takeoff.probe"]


# --------------------------------------------------------------------------
# The half that must NOT be refused. Every source below is in backend/ today.
# --------------------------------------------------------------------------


def test_a_third_party_name_matching_a_namespace_directory_is_not_caught(script):
    """`import alembic.config` reaches site-packages, not backend/alembic/.

    backend/alembic/ has no __init__.py, so it is a namespace portion and loses
    to the installed regular package. Reading it as a project root produced 51
    findings, all false, against 3 real ones.
    """
    index = _index(script, tracked=TRACKED | {"backend/alembic/env.py"})
    source = "import alembic.config\nfrom alembic import op\nfrom alembic.runtime.migration import MigrationContext\n"
    assert _check(script, source, index) == []
    assert index.roots == {"app"}


def test_a_namespace_directory_inside_the_project_is_not_caught(script):
    """backend/app/ carries fifteen directories with no __init__.py.

    Fonts, licences, seed data, message catalogues. A namespace package imports
    at runtime and has no file to track, so there is nothing to refuse; reading
    one as a missing module would invent a finding out of a directory that is
    working correctly.
    """
    index = _index(script, tracked=TRACKED | {"backend/app/core/fonts/NOTICE.txt"})
    assert _check(script, "import app.core.fonts\n", index) == []


def test_standard_library_and_third_party_imports_are_not_caught(script):
    index = _index(script)
    source = "import json\nimport os.path\nfrom fastapi import FastAPI\nfrom sqlalchemy.orm import Session\n"
    assert _check(script, source, index) == []


def test_type_checking_imports_are_not_caught(script):
    """They never execute, so they cannot stop the backend from starting."""
    source = (
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from app.core.host_disclosure import Disclosure\n"
    )
    index = _index(script, untracked=["backend/app/core/host_disclosure.py"])
    assert _check(script, source, index) == []


def test_an_optional_import_with_a_real_fallback_is_not_caught(script):
    """The live shape from backend/app/scripts/migrate_sqlite_to_postgres.py.

    That file wraps `import app.core.models_registry`, a module that does not
    exist, in `except Exception: pass` on purpose. Nothing about it is broken
    and a gate that reports it would be switched off within the day.
    """
    source = "try:\n    import app.core.models_registry  # noqa: F401\nexcept Exception:  # noqa: BLE001\n    pass\n"
    index = _index(script)
    assert _check(script, source, index) == []


def test_an_import_error_fallback_naming_the_error_is_not_caught(script):
    source = "try:\n    from app.core.host_disclosure import describe\nexcept ImportError:\n    describe = None\n"
    index = _index(script, untracked=["backend/app/core/host_disclosure.py"])
    assert _check(script, source, index) == []


def test_a_from_import_of_a_symbol_is_not_caught(script):
    """Most from-imports in the tree name a class, not a submodule.

    Reading `Settings` as a module would put a finding on nearly every file in
    backend/, which is the failure mode that gets a gate deleted rather than
    fixed.
    """
    index = _index(script)
    source = "from app.core.config import Settings, get_settings, DEFAULT_LOCALE\n"
    assert _check(script, source, index) == []


def test_a_multiline_parenthesised_import_is_read_whole(script):
    """The form grep gets wrong and the reason this reads the AST.

    Both names are on their own lines inside parentheses, and one of them is a
    real submodule that is untracked.
    """
    source = "from app.modules.takeoff import (\n    router,\n    probe,\n)\n"
    index = _index(script, untracked=["backend/app/modules/takeoff/probe.py"])
    assert _modules(_check(script, source, index)) == ["app.modules.takeoff.probe"]


def test_a_wildcard_import_of_a_tracked_package_is_not_caught(script):
    index = _index(script)
    assert _check(script, "from app.core.config import *\n", index) == []


# --------------------------------------------------------------------------
# The script as a program, and the tree it is pointed at.
# --------------------------------------------------------------------------


def test_the_scripts_own_self_test_passes(script):
    """--self-test is the check proving it still refuses, on its own fixture."""
    assert script.self_test() == 0


def test_the_self_test_fails_when_the_check_stops_refusing(script, monkeypatch):
    """The self-test has to be able to fail, or it certifies nothing.

    With `locate` reporting everything as tracked, the check finds nothing, and
    the self-test must notice that rather than print OK.
    """
    monkeypatch.setattr(
        script.ModuleIndex,
        "locate",
        lambda self, module: ("module", "backend/app/__init__.py"),
    )
    assert script.self_test() == 2


def test_the_roots_are_read_from_the_tree_rather_than_hardcoded(script):
    """A new top-level package under backend/ has to be covered on arrival."""
    index = _index(script, tracked=TRACKED | {"backend/plugins/__init__.py"})
    assert index.roots == {"app", "plugins"}


def test_a_file_that_cannot_be_parsed_is_reported_rather_than_skipped(script):
    """Silence from an unreadable file is indistinguishable from a clean one."""
    findings = _check(script, "def broken(:\n", _index(script))
    assert len(findings) == 1
    assert "cannot be parsed" in findings[0].reason
