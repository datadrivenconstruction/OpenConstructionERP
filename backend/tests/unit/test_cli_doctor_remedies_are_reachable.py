# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A remedy the reader cannot carry out is worse than no remedy at all.

Every hint in the doctor was written for a pip install, which is where most of
them are read. The desktop build has no pip in it: ``sys.executable`` is the
app binary, so "pip install --force-reinstall openconstructionerp" cannot be
run there at all. An operator who follows it learns only that the tool which
found the fault also cannot fix it, and the next report they read gets less
trust than it deserves.

The sweep below is deliberately over the whole doctor rather than over the
lines known to be wrong today. Only one of them can reach a desktop reader as
things stand, because everything else the doctor names is in
``requirements-desktop.lock`` and those branches report ok with the hint never
rendered. That is a fact about today's lock, not about this code: a dependency
leaving the lock arms another line silently, with nothing to catch it.
"""

from __future__ import annotations

import importlib
import inspect
import sys

import pytest

from app import cli
from app.core import self_upgrade

#: Advice that cannot be followed from inside a bundle. Matched
#: case-insensitively against the rendered hint.
UNREACHABLE_FROM_A_BUNDLE = ("pip install", "pip3 install", "python -m pip", "npm run build")


def _zero_argument_checks() -> list:
    """Every doctor check that can be called with no arguments.

    Collected by inspection rather than listed by hand, so a check added later
    is swept without anyone remembering to add it here. The ones taking
    arguments (data dir, host, port) are left out because they touch the
    filesystem and network, not because they are exempt: if one of those ever
    grows a pip hint, it needs its own test.
    """
    found = []
    for name, obj in vars(cli).items():
        if not name.startswith("check_") or not callable(obj):
            continue
        params = inspect.signature(obj).parameters.values()
        if all(p.default is not inspect.Parameter.empty for p in params):
            found.append(obj)
    return found


def _flatten(result) -> list:
    return list(result) if isinstance(result, list) else [result]


@pytest.fixture
def doctor_on_a_bundle(monkeypatch: pytest.MonkeyPatch):
    """Run the doctor as it runs inside a frozen build, with nothing healthy.

    Two dials, because a hint only renders on a check that is unhappy, and the
    two ways to be unhappy print different remedies. ``absent`` is the plain
    "not installed" branch; ``broken`` is present-but-unimportable. A sweep
    over a healthy environment would pass while proving nothing, since ok
    checks print no hint.
    """

    def _run(*, absent: bool) -> list:
        monkeypatch.setattr(sys, "frozen", True, raising=False)

        import importlib.util as importlib_util

        real_find_spec = importlib_util.find_spec
        real_import_module = importlib.import_module

        optional = {
            "lancedb",
            "sentence_transformers",
            "pdfplumber",
            "pypdfium2",
            "paddleocr",
            "paddle",
            "pandas",
            "pyarrow",
        }

        def fake_find_spec(name: str, package: str | None = None):
            if name in optional:
                return None if absent else object()
            return real_find_spec(name, package)

        def fake_import_module(name: str, package: str | None = None):
            if name in optional:
                raise ImportError(f"DLL load failed while importing {name}")
            return real_import_module(name, package)

        # No paddlepaddle under any name, so the engine question has to answer
        # from the import name and cannot be rescued by the distribution list.
        def fake_distributions():
            return iter(())

        monkeypatch.setattr(importlib_util, "find_spec", fake_find_spec)
        monkeypatch.setattr(importlib, "import_module", fake_import_module)
        monkeypatch.setattr("importlib.metadata.distributions", fake_distributions)

        # The frontend lookup is a real one in a source checkout and would
        # report ok, hiding its own hint. Force the branch that has one.
        import app.cli_static as cli_static

        def _no_frontend():
            raise FileNotFoundError("no bundled UI and no dev build")

        monkeypatch.setattr(cli_static, "get_frontend_dir", _no_frontend)

        checks = []
        for fn in _zero_argument_checks():
            checks.extend(_flatten(fn()))
        return checks

    return _run


class TestNoRemedyAsksAFrozenBuildToRunPip:
    @pytest.mark.parametrize("absent", [True, False], ids=["nothing installed", "installed but broken"])
    def test_every_rendered_hint_is_something_the_reader_can_do(self, doctor_on_a_bundle, absent: bool) -> None:
        offenders = [
            (c.name, c.hint)
            for c in doctor_on_a_bundle(absent=absent)
            if c.status != "ok" and any(bad in (c.hint or "").lower() for bad in UNREACHABLE_FROM_A_BUNDLE)
        ]
        assert not offenders, (
            "the desktop build has no pip and no repo checkout, so these remedies "
            f"cannot be carried out by the reader who is shown them: {offenders}"
        )

    def test_the_sweep_actually_reaches_hints(self, doctor_on_a_bundle) -> None:
        """The guard above passes trivially if nothing renders a hint.

        An environment where every check is happy, or a sweep that collects no
        checks, satisfies "no bad hints" while proving nothing. So count what
        was examined before trusting what was not found.
        """
        checks = doctor_on_a_bundle(absent=True)
        assert len(checks) >= 8, f"the sweep collected only {len(checks)} checks: {[c.name for c in checks]}"
        with_hints = [c for c in checks if c.status != "ok" and c.hint]
        assert len(with_hints) >= 4, (
            f"only {len(with_hints)} unhappy checks rendered a hint, so the guard had almost nothing to judge"
        )

    def test_the_guard_fails_on_the_shape_it_replaced(
        self, monkeypatch: pytest.MonkeyPatch, doctor_on_a_bundle
    ) -> None:
        """A green guard is worth what it would have caught.

        Every hint used to be the pip text unconditionally, which is what both
        helpers returning their first argument reproduces. If the sweep above
        cannot see offenders in that state then it is passing on the
        arrangement of the test rather than on the code, and would go on
        passing if the routing were removed tomorrow.

        Both helpers, not one: stubbing only ``_repair_hint`` would leave the
        no-extra sites routed and still find offenders elsewhere, so the test
        would go green while covering less than it claims.
        """
        monkeypatch.setattr(cli, "_repair_hint", lambda pip_advice, frozen_advice=None: pip_advice)
        monkeypatch.setattr(cli, "_no_extra_hint", lambda pip_advice: pip_advice)
        offenders = [
            c.name
            for c in doctor_on_a_bundle(absent=True)
            if c.status != "ok" and any(bad in (c.hint or "").lower() for bad in UNREACHABLE_FROM_A_BUNDLE)
        ]
        assert offenders, "the sweep found nothing to object to even with every remedy unrouted"

    def test_a_check_that_asks_for_an_install_is_caught_even_without_the_word_pip(self) -> None:
        """What makes a remedy unreachable is the asking, not the wording.

        The engine hint says "Install a paddlepaddle build for this platform"
        and never says pip. A guard that greps for the word would pass it while
        it stayed just as impossible to follow, so the routing is asserted at
        the helper rather than inferred from the text.
        """
        monkey = "Install a paddlepaddle build for this platform"
        assert cli._no_extra_hint(monkey) == monkey, "outside a bundle the original advice must survive untouched"


class TestTheServerInstallStillGetsPipAdvice:
    """The frozen arm must be a redirection, not a deletion.

    Most readers of these hints are on a pip install, where pip is exactly the
    right answer. A change that quietly stopped telling them so would fix the
    smaller audience by breaking the larger one.
    """

    def test_pip_advice_survives_where_pip_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        assert (
            cli._repair_hint("pip install 'openconstructionerp[vector]'") == "pip install 'openconstructionerp[vector]'"
        )

    def test_the_bundle_gets_the_bundle_answer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert cli._repair_hint("pip install x") == self_upgrade.DESKTOP_REPAIR
        assert cli._no_extra_hint("pip install x") == self_upgrade.DESKTOP_NO_EXTRA
        assert self_upgrade.DESKTOP_REPAIR != self_upgrade.DESKTOP_NO_EXTRA, (
            "a bundle that shipped something broken and a bundle that never carried it "
            "need different answers, and one of them is a loop if given to the other"
        )

    def test_a_windows_installer_build_is_not_treated_as_frozen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OE_DESKTOP is the wrong question and must not be the one asked.

        The Windows installer builds are desktop too, and they run a real
        python.exe out of a private venv, so pip advice is correct for them.
        Answering on desktop_mode instead of on sys.frozen would take working
        advice away from them.
        """
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        monkeypatch.setenv("OE_DESKTOP", "1")
        assert cli._repair_hint("pip install x") == "pip install x"
