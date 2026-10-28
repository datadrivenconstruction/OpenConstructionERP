# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Running a migration must not silence the application's loggers.

``alembic/env.py`` configures logging from ``alembic.ini`` on every migration
run. ``logging.config.fileConfig`` defaults ``disable_existing_loggers`` to
True, and alembic.ini names only ``root``, ``sqlalchemy`` and ``alembic``, so
the default sets ``disabled = True`` on every other logger that already exists.
A disabled logger drops records inside ``Logger.handle`` before any handler is
reached, it stays disabled for the life of the process, and nothing in
``caplog.at_level`` or ``setLevel`` undoes it.

That does not matter for ``alembic upgrade`` at a shell prompt, where the
process exits straight afterwards. It matters a great deal for a test session,
which runs a migration and then keeps going for another thirty thousand tests.
On the 2026-09-22 nightly the Windows job ran the migration round-trip at test
1530 and then failed 83 later tests across 43 unrelated files, every one of them
asserting on captured log output and every one of them reporting that no record
arrived. macOS was spared only because those migration tests died in setup on an
unrelated bug, so alembic never ran there at all - which is worth remembering,
because fixing that bug hands macOS the same failure unless this one is fixed
too.

Two assertions, and the second is the one that gives the first its meaning. The
keyword being present is a spelling check; the keyword being what keeps the
loggers alive is the property. If a future Python makes ``False`` the default,
the second test goes red and says so rather than leaving a guard that passes for
a reason nobody checked.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_ENV_PY = _BACKEND / "alembic" / "env.py"
_ALEMBIC_INI = _BACKEND / "alembic.ini"

# Run in a child process on purpose. ``fileConfig`` reconfigures the root
# logger and closes the handlers it removes, including the ones pytest is
# holding, so a test that called it here would damage the session it runs in -
# which is the very thing being tested against.
_PROBE = """
import json, logging, sys
from logging.config import fileConfig

ini, keep = sys.argv[1], sys.argv[2] == "keep"
subject = logging.getLogger("app.core.cache")
if keep:
    fileConfig(ini, disable_existing_loggers=False)
else:
    fileConfig(ini)
print(json.dumps({"disabled": subject.disabled}))
"""


def _fileconfig_call() -> ast.Call:
    """The ``fileConfig(...)`` call ``env.py`` makes, as an AST node."""
    tree = ast.parse(_ENV_PY.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "fileConfig"
    ]
    assert len(calls) == 1, f"expected exactly one fileConfig call in {_ENV_PY}, found {len(calls)}"
    return calls[0]


def _run_probe(mode: str) -> bool:
    """Return whether ``app.core.cache`` ends up disabled in a fresh process."""
    done = subprocess.run(
        [sys.executable, "-c", _PROBE, str(_ALEMBIC_INI), mode],
        capture_output=True,
        text=True,
        cwd=str(_BACKEND),
        timeout=60,
    )
    assert done.returncode == 0, f"probe failed: {done.stderr}"
    return json.loads(done.stdout.strip())["disabled"]


def test_env_py_asks_fileconfig_to_leave_existing_loggers_alone() -> None:
    """The call must name the keyword; the default is the wrong way round."""
    call = _fileconfig_call()
    keywords = {kw.arg: kw.value for kw in call.keywords}
    assert "disable_existing_loggers" in keywords, (
        "alembic/env.py calls fileConfig without disable_existing_loggers, which defaults to True "
        "and disables every app logger for the rest of the process"
    )
    value = keywords["disable_existing_loggers"]
    assert isinstance(value, ast.Constant) and value.value is False, (
        f"disable_existing_loggers must be the literal False, got {ast.dump(value)}"
    )


@pytest.mark.parametrize(
    ("mode", "expected_disabled"),
    [("keep", False), ("default", True)],
    ids=["with_the_keyword_the_logger_survives", "without_it_the_logger_is_disabled"],
)
def test_the_keyword_is_what_keeps_the_logger_alive(mode: str, expected_disabled: bool) -> None:
    """Both directions, so the guard cannot pass for the wrong reason.

    The second case is not testing our code, it is pinning the behaviour our
    code is defending against. If it ever goes green with ``expected_disabled``
    True no longer holding, the default changed underneath us and the keyword
    has stopped being load-bearing, which is worth a red line rather than a
    silent one.
    """
    assert _run_probe(mode) is expected_disabled
