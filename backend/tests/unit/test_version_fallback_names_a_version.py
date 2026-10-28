# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The version the CLI prints has to be a version, and it has to be this tree's.

``_resolve_version`` reads the ``Settings`` field first and falls back to
``importlib.metadata`` when that raises. It was the other way round until
41bc99c00, and the order matters: metadata reports whatever distribution is
installed in the environment, so a source checkout with any earlier
``pip install openconstructionerp`` beside it printed the installed version
while ``/api/health`` on the same interpreter printed the running one.

The Settings branch reads ``Settings.model_fields["app_version"]``, and
``app_version`` is declared with ``default_factory``, so pydantic keeps
``PydanticUndefined`` in ``default`` and there is no ``default`` to read.

``PydanticUndefined`` is an object with a ``__str__``, which is what made this
survive. Nothing raised, so the ``except`` below it never ran and the value
never became "unknown". The line printed to the user was

    OpenConstructionERP vPydanticUndefined

on the one code path that only ever runs when somebody is already trying to
work out what they have installed.

What this file asserts, and the limit of it. It drives each branch by making
the other one raise, which is a stand in for the real causes rather than the
causes themselves, and it cannot prove the frozen build takes the metadata
branch. What it can do is fail the day either branch stops naming a version,
and fail the day the order goes back.

The order is checked by driving the two sources apart rather than by comparing
them. Comparing them was the earlier form of the control here, and it could
only ever pass: a CI runner installs the package from the tree it just checked
out, so both sources answer the same and a resolver reading either one agrees
with both. It went red for the first time on a developer machine whose
environment still held an older editable install, which is precisely the
situation 41bc99c00 exists for, and what it convicted there was the correct
behaviour.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import sys
import types
from typing import Any

import pytest

from app.cli import _resolve_version, cmd_version

#: A version no tree is ever at, so an answer of exactly this one can only have
#: come from the metadata lookup and never from the pyproject beside the source.
NOT_THIS_TREE = "0.0.1"


def _boom(*_args: Any, **_kwargs: Any) -> str:
    raise importlib.metadata.PackageNotFoundError("openconstructionerp")


def _settings_version() -> str:
    """What the Settings branch of the resolver would answer."""
    from app.config import Settings

    field = Settings.model_fields["app_version"]
    factory = field.default_factory
    return str(factory()) if factory is not None else str(field.default)  # type: ignore[call-arg]


def _break_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the Settings branch raise, so the metadata fallback is reached.

    Replacing the module rather than reaching into pydantic internals: the
    resolver does ``from app.config import Settings`` inside its ``try``, so a
    stand-in module without that name raises ImportError exactly where the real
    causes (a frozen build, a checkout that was never installed) raise.
    """
    monkeypatch.setitem(sys.modules, "app.config", types.ModuleType("app.config"))


def test_the_settings_branch_names_a_version_and_not_a_sentinel() -> None:
    """The branch the resolver takes first still names the version.

    No patching: the Settings branch is the one that answers, and the sentinel
    regression lived in it. Making the metadata lookup raise here would prove
    nothing, because the resolver never reaches it.
    """
    resolved = _resolve_version()

    # Named rather than merely truthy. "PydanticUndefined" is a perfectly good
    # non-empty string, so a test that only checked for emptiness would have
    # passed against the defect it exists to catch.
    assert "Undefined" not in resolved, f"the resolver returned a pydantic sentinel: {resolved!r}"
    assert resolved != "unknown", "the resolver gave up where it has a value available"
    assert resolved[0].isdigit(), f"a version starts with a digit, got {resolved!r}"


def test_the_settings_branch_agrees_with_the_field_it_reads() -> None:
    """The value is the one the model would have produced itself."""
    expected = _settings_version()

    assert expected[0].isdigit()
    assert "Undefined" not in expected
    assert _resolve_version() == expected


def test_the_running_source_wins_over_the_installed_distribution(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control on the order, driven apart rather than compared.

    An environment where the installed distribution and the running tree hold
    the same version cannot tell the two branches apart, and every CI runner is
    such an environment. So the metadata lookup is made to answer a version no
    tree is at. The resolver has to answer the tree's, and the only branch that
    can give it that is the Settings one.
    """
    monkeypatch.setattr(importlib.metadata, "version", lambda *_a, **_k: NOT_THIS_TREE)

    resolved = _resolve_version()

    assert resolved == _settings_version()
    assert resolved != NOT_THIS_TREE, "the resolver read the installed distribution instead of the running source"


def test_the_metadata_branch_answers_when_settings_cannot(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fallback is still wired, and still returns what it read.

    Asserting the exact value the metadata lookup was made to give, so this
    cannot be satisfied by the Settings branch having answered after all.
    """
    monkeypatch.setattr(importlib.metadata, "version", lambda *_a, **_k: NOT_THIS_TREE)
    _break_settings(monkeypatch)

    assert _resolve_version() == NOT_THIS_TREE


def test_the_resolver_says_unknown_only_when_neither_branch_can_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The last resort names itself rather than printing whatever it holds."""
    monkeypatch.setattr(importlib.metadata, "version", _boom)
    _break_settings(monkeypatch)

    assert _resolve_version() == "unknown"


def test_the_printed_line_uses_the_resolver(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``version`` prints what the resolver returns, under the same conditions.

    ``cmd_version`` used to carry its own copy of the lookup, which is how one
    of the two copies could be fixed while the other went on printing the
    sentinel. Asserting on the printed line rather than on the source keeps that
    from coming back without pinning how the sharing is written.

    The metadata lookup is pushed off the tree's version for the same reason as
    above: a private copy of it inside ``cmd_version`` would print that, and on
    a machine where the two sources agree the line would look correct anyway.
    """
    monkeypatch.setattr(importlib.metadata, "version", lambda *_a, **_k: NOT_THIS_TREE)

    expected = _resolve_version()
    cmd_version(argparse.Namespace())
    printed = capsys.readouterr().out

    assert f"OpenConstructionERP v{expected}" in printed
    assert NOT_THIS_TREE not in printed
    assert "Undefined" not in printed
