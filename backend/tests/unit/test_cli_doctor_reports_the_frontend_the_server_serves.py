# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The frontend check must answer from the server's lookup, not its own copy of it.

The check used to repeat the expression ``cli_static.get_frontend_dir()`` uses,
on the reasoning that two copies of one expression cannot disagree. In the
frozen desktop build they disagree, because the expression is identical and the
anchor is not: ``cli`` is the PyInstaller entry script and runs as ``__main__``
with ``__file__`` at the root of the unpacked bundle, while ``cli_static`` is a
module inside the ``app`` package with ``__file__`` one level down, which is
where the UI is unpacked. The copy looked one directory too high and reported
"no frontend" on a sidecar that was serving the UI.

That is not reproducible in a source checkout, where both anchors land in the
same place, so these tests pin the property that makes the bug impossible rather
than the symptom: the check reports whatever the lookup reports, including when
the lookup names somewhere the check would never have looked by itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.cli import check_frontend_bundled, run_preflight


class TestTheCheckAnswersFromTheLookup:
    def test_a_found_ui_is_reported_ok_and_named(self, monkeypatch: pytest.MonkeyPatch) -> None:
        found = Path("/somewhere/app/_frontend_dist")
        monkeypatch.setattr("app.cli_static.get_frontend_dir", lambda: found)

        check = check_frontend_bundled()

        assert check.status == "ok"
        # Naming the directory is what lets an operator tell the bundled UI from
        # a dev build without guessing which branch answered.
        assert str(found) in check.message

    def test_a_missing_ui_stays_a_warning_with_the_way_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def missing():
            raise FileNotFoundError("Frontend dist not found.")

        monkeypatch.setattr("app.cli_static.get_frontend_dir", missing)

        check = check_frontend_bundled()

        # Warn rather than error: an API-only server is a supported install, not
        # a broken one.
        assert check.status == "warn"
        assert "API only" in check.message
        assert check.hint


class TestTheCheckDoesNotSecondGuessTheLookup:
    def test_it_trusts_a_directory_it_would_never_have_found_itself(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The regression this exists for.

        Status alone does not carry it. The old implementation also answered ok
        on a developer machine, because its second branch finds the repo's own
        frontend/dist and that exists in a checkout: the test would have passed
        against the code it was written to catch, for a reason having nothing to
        do with the fix. Measured, not supposed - it did exactly that.

        Naming the directory is what discriminates. The path below is reachable
        from nowhere this module would look, so a check still computing its own
        answer cannot put it in the message no matter which branch it takes.
        """
        elsewhere = Path("/nowhere/near/this/module")
        monkeypatch.setattr("app.cli_static.get_frontend_dir", lambda: elsewhere)

        check = check_frontend_bundled()

        assert check.status == "ok"
        assert str(elsewhere) in check.message

    def test_it_does_not_swallow_a_failure_that_is_not_absence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A broken lookup must not be reported as a tidy "no frontend".

        FileNotFoundError is the lookup's way of saying it looked and found
        nothing. Anything else means the lookup itself is wrong, and calling
        that a missing UI would send the operator after the wrong problem.
        """

        def broken():
            raise RuntimeError("the lookup itself is broken")

        monkeypatch.setattr("app.cli_static.get_frontend_dir", broken)

        check = check_frontend_bundled()

        assert check.status == "error"
        assert "could not run" in check.message
        assert "RuntimeError" in check.message


class TestOneCheckCannotTakeDownTheReport:
    def test_an_unimportable_web_stack_costs_one_line_not_the_whole_run(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The reason this check may not import anything heavy above its guard.

        cli_static imports fastapi and starlette at module level, while this
        module's own imports are stdlib only on purpose: that is what lets the
        CLI diagnose an install whose dependencies did not resolve. run_preflight
        builds its list as a plain literal with no per-check guard, so an
        ImportError escaping this one check does not degrade a line, it aborts
        the report before anything prints.

        Asserting on the returned Check alone would not catch that, since a
        version that takes the whole run down never gets far enough to be asked.
        So this calls run_preflight and requires the other checks to still be
        there, which is the property that actually matters to someone whose
        install is broken.
        """
        monkeypatch.setitem(sys.modules, "app.cli_static", None)

        checks = run_preflight("127.0.0.1", 8931, tmp_path, verbose=False)

        names = [c.name for c in checks]
        assert "Python version" in names
        assert "Data directory" in names
        frontend = [c for c in checks if c.name == "Frontend bundle"]
        assert len(frontend) == 1
        assert frontend[0].status == "error"
