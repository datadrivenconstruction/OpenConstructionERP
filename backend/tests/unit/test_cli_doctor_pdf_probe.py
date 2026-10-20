# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The doctor's PDF probe must import the way the upload path imports.

The probe spawns ``sys.executable -c "import <mod>"`` so a broken native
extension takes down a child instead of the diagnostic. That is right for a
normal install and wrong for the frozen desktop build, where ``sys.executable``
is the app binary and ``-c`` reaches the app's own CLI. Without the desktop
arm every healthy desktop install would be reported as a broken PDF reader.
"""

from __future__ import annotations

import sys

import pytest

from app import cli
from app.modules.takeoff.service import _use_in_process_pdf_parser


class TestDesktopPredicateDoesNotDrift:
    """The CLI restates the parser's condition; it must stay the same condition."""

    @pytest.mark.parametrize(
        ("frozen", "desktop_env"),
        [
            (False, None),
            (False, "1"),
            (False, "true"),
            (False, "YES"),
            (False, "on"),
            (False, "0"),
            (False, "no"),
            (False, ""),
            (True, None),
            (True, "0"),
        ],
    )
    def test_cli_predicate_matches_the_parser(
        self,
        monkeypatch: pytest.MonkeyPatch,
        frozen: bool,
        desktop_env: str | None,
    ) -> None:
        monkeypatch.setattr(sys, "frozen", frozen, raising=False)
        if desktop_env is None:
            monkeypatch.delenv("OE_DESKTOP", raising=False)
        else:
            monkeypatch.setenv("OE_DESKTOP", desktop_env)

        assert cli._pdf_reader_imports_in_process() == _use_in_process_pdf_parser()


class TestFrozenBuildIsNotProbedWithAChild:
    """On desktop the probe must import here, never spawn the app binary."""

    def test_frozen_build_does_not_spawn_a_subprocess(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "frozen", True, raising=False)

        import subprocess

        def _explode(*args: object, **kwargs: object) -> None:
            raise AssertionError(
                "doctor spawned sys.executable on a frozen build - that launches "
                "the app binary, not an interpreter, and reports a healthy "
                "install as a broken PDF reader"
            )

        monkeypatch.setattr(subprocess, "run", _explode)

        checks = cli.check_optional_extras()
        pdf = [c for c in checks if c.name == "PDF takeoff"]
        assert pdf, "the PDF takeoff check disappeared from the doctor output"
        # `.message`, not `.detail`: Check has no `detail`, and an assert's
        # message is only evaluated when the assert fails, so the wrong
        # attribute name sat here harmlessly until the day it mattered and
        # then raised AttributeError instead of saying what went wrong.
        assert pdf[0].status == "ok", f"a readable install reported as {pdf[0].status}: {pdf[0].message}"

    def test_normal_install_still_uses_a_child(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        monkeypatch.delenv("OE_DESKTOP", raising=False)

        seen: list[list[str]] = []
        import subprocess

        real_run = subprocess.run

        def _record(cmd: object, *args: object, **kwargs: object) -> object:
            if isinstance(cmd, list):
                seen.append([str(part) for part in cmd])
            return real_run(cmd, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(subprocess, "run", _record)

        cli.check_optional_extras()

        imports = [cmd for cmd in seen if len(cmd) == 3 and cmd[1] == "-c"]
        assert imports, "the PDF probe stopped using a child interpreter"
        assert any("import pdfplumber" in cmd[2] for cmd in imports), (
            "pdfplumber is the primary reader and must be probed"
        )
        assert any("import pypdfium2" in cmd[2] for cmd in imports), (
            "pypdfium2 is the fallback reader and must be probed"
        )


class TestTheOcrExtraAnswersInBothDirections:
    """The [cv] check must report OCR present as well as OCR absent.

    It used to append a Check only when paddleocr was missing, so an install
    that HAD the extra produced no line at all. "OCR works here" and "this
    check never ran" printed identically, which is the one thing a report
    cannot do. It also decided on ``find_spec`` alone, which resolves a module
    without executing it, so a wheel set that is installed but cannot load
    counted as installed - the blind spot already closed for the vector and
    encoder checks and left open on this one.
    """

    CV = "PDF dimension OCR [cv]"

    def _cv_check(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        frontend: bool = True,
        frontend_imports: bool = True,
        engine: bool = True,
        engine_imports: bool = True,
        engine_distribution: str | None = None,
        unreadable_distribution: bool = False,
        sibling_distributions: tuple[str, ...] = (),
    ) -> list:
        """Run the extras report with the OCR wheels' state forced.

        Six dials rather than two, because the states that matter in the field
        cannot be expressed with booleans over one question. Frontend present
        and importable with no engine behind it needs three of them. The last
        two exist because `paddle` is an import name this check assumes rather
        than measures: one puts the engine under its distribution name only,
        the other damages an unrelated dist-info. Both describe environments
        where a careless answer prints an error at an install that works.
        """
        import importlib.metadata as importlib_metadata
        import importlib.util as importlib_util
        import subprocess

        # The child-process arm, so the probe is the one a normal install uses
        # and nothing is imported into the test interpreter.
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        monkeypatch.delenv("OE_DESKTOP", raising=False)

        real_find_spec = importlib_util.find_spec
        found = {"paddleocr": frontend, "paddle": engine}

        def fake_find_spec(name: str, package: str | None = None):
            if name in found:
                return object() if found[name] else None
            return real_find_spec(name, package)

        class _Result:
            def __init__(self, code: int, err: bytes = b"") -> None:
                self.returncode = code
                self.stdout = b""
                self.stderr = err

        def fake_run(cmd, **kwargs):
            source = cmd[2] if len(cmd) == 3 else ""
            # Whole statement, never a substring: "import paddleocr" contains
            # "import paddle", so a substring match made the engine dial fire on
            # the frontend's probe. The broken-engine test then went green by
            # exercising the frontend branch and never reached the branch it
            # was written for.
            if source == "import paddleocr" and not frontend_imports:
                return _Result(1, b"ImportError: DLL load failed while importing _ocr\n")
            if source == "import paddle" and not engine_imports:
                return _Result(1, b"ImportError: libpaddle.so: cannot open shared object file\n")
            return _Result(0)

        class _Dist:
            def __init__(self, name: str) -> None:
                self.metadata = {"Name": name}

        class _UnreadableDist:
            """A dist-info that raises when read, as a damaged one does."""

            @property
            def metadata(self):
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "invalid start byte")

        def fake_distributions():
            # The damaged entry goes FIRST, ahead of the engine. A scan that
            # short-circuits will otherwise pass or fail on iteration order
            # rather than on the code being right.
            entries = [_UnreadableDist()] if unreadable_distribution else []
            entries.append(_Dist("openconstructionerp"))
            if engine_distribution:
                entries.append(_Dist(engine_distribution))
            entries.extend(_Dist(name) for name in sibling_distributions)
            return iter(entries)

        monkeypatch.setattr(importlib_util, "find_spec", fake_find_spec)
        monkeypatch.setattr(importlib_metadata, "distributions", fake_distributions)
        monkeypatch.setattr(subprocess, "run", fake_run)

        return [c for c in cli.check_optional_extras() if c.name == self.CV]

    def test_a_working_install_says_so_instead_of_saying_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        found = self._cv_check(monkeypatch)
        assert len(found) == 1, "an install WITH the extra must still produce a line"
        assert found[0].status == "ok"

    def test_the_frontend_importing_is_not_enough_to_call_ocr_working(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The state the [cv] extra actually installs, measured on a real venv.

        `pip install paddleocr` brings no paddlepaddle, because upstream leaves
        the CPU/GPU/platform choice to the caller. In that state find_spec finds
        it, `import paddleocr` succeeds, `from paddleocr import PaddleOCR`
        succeeds, and OCR cannot run. A check that only imports the frontend
        calls this healthy.
        """
        found = self._cv_check(monkeypatch, engine=False)
        assert len(found) == 1
        assert found[0].status == "error", "OCR without an inference engine is not a working install"
        assert "paddlepaddle" in found[0].message, (
            f"the operator has to know WHICH piece is missing, got {found[0].message!r}"
        )

    def test_the_missing_engine_is_not_answered_with_reinstall_the_extra(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reinstalling [cv] reproduces this state exactly, so it cannot be the fix."""
        found = self._cv_check(monkeypatch, engine=False)
        remedy = found[0].hint or ""
        assert "paddlepaddle" in remedy, f"the remedy must name the engine, got {remedy!r}"
        assert "openconstructionerp[cv]" not in remedy, (
            "reinstalling the extra installs the same wheels again and lands back here"
        )

    def test_installed_but_unloadable_is_not_reported_as_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """find_spec would call this one installed; importing it does not."""
        found = self._cv_check(monkeypatch, frontend_imports=False)
        assert len(found) == 1
        assert found[0].status == "error", "a wheel set that cannot import is not a working OCR install"
        assert "will not import" in found[0].message

    def test_a_broken_engine_is_distinguished_from_an_absent_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Present-but-unloadable and absent need different fixes, so different lines."""
        broken = self._cv_check(monkeypatch, engine_imports=False)
        assert broken[0].status == "error"
        assert "will not import" in broken[0].message
        # Naming the engine, not just the fault: both this branch and the
        # unloadable-frontend one say "will not import", so asserting only the
        # phrase let this test pass on the wrong branch once already.
        assert "engine" in broken[0].message, f"the engine branch must say so, got {broken[0].message!r}"
        absent = self._cv_check(monkeypatch, engine=False)
        assert broken[0].message != absent[0].message, "two different faults must not print one sentence"

    @pytest.mark.parametrize("distribution", ["paddlepaddle", "paddlepaddle-gpu", "PaddlePaddle"])
    def test_an_engine_under_another_name_is_not_called_missing(
        self, monkeypatch: pytest.MonkeyPatch, distribution: str
    ) -> None:
        """The import name is an assumption; being wrong about it must stay cheap.

        This check reads `paddle` as the engine's import name. If that is ever
        wrong - upstream renames it, a GPU build lands under something else -
        then deciding on that name alone prints an error at an install that
        works and tells its operator to install what they already have. So the
        distribution name is asked as a second opinion and absence has to fail
        both, including the name-cased and the -gpu variants.
        """
        found = self._cv_check(monkeypatch, engine=False, engine_distribution=distribution)
        assert len(found) == 1
        assert found[0].status == "ok", (
            f"an engine installed as {distribution!r} was reported {found[0].status}: {found[0].message}"
        )

    def test_an_engine_found_only_by_distribution_is_not_imported_under_a_guessed_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not importing beats importing under a name that may not answer.

        If the engine is visible only as a distribution, then `paddle` is not
        its import name here, and probing it would fail and print "installed
        but will not import" - swapping one false error for another.
        """
        found = self._cv_check(monkeypatch, engine=False, engine_imports=False, engine_distribution="paddlepaddle")
        assert found[0].status == "ok"
        assert "will not import" not in found[0].message

    def test_the_engine_is_not_found_in_its_own_frontends_distribution_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The prefix has to stay long enough to exclude the frontend.

        Measured in a real environment rather than reasoned about: installing
        paddleocr next to the engine leaves three distributions whose names
        begin with "paddle" - paddleocr, paddlepaddle and paddlex. The lookup
        matches on "paddlepaddle", which is correct and also picks up the -gpu
        build. Shortened to "paddle" it would answer present whenever the
        frontend is present, and this check could never report the one state it
        exists for: a frontend installed with no engine behind it.

        So this is the environment where the engine really is absent and its
        neighbours really are not, and the answer must still be an error.
        """
        found = self._cv_check(
            monkeypatch,
            engine=False,
            engine_distribution=None,
            sibling_distributions=("paddleocr", "paddlex"),
        )
        assert len(found) == 1
        assert found[0].status == "error", (
            "a frontend with no engine was reported as working, so the distribution "
            f"lookup matched a neighbour rather than the engine: {found[0].message}"
        )
        assert "paddlepaddle" in found[0].message

    def test_one_damaged_dist_info_does_not_answer_for_every_other_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One bad entry must not decide the question for the whole environment.

        A single unreadable dist-info anywhere in site-packages, from a half
        written install or a bad encoding, raises mid-iteration. Guarded around
        the sweep instead of around the entry, that throws away the answer for
        every other distribution and prints the false "engine missing" this
        helper exists to prevent - and prints it by iteration order, since the
        scan stops at the first match and the damaged entry may come before the
        engine or after it. Same shape as one malformed row failing every row.
        """
        found = self._cv_check(
            monkeypatch,
            engine=False,
            engine_distribution="paddlepaddle",
            unreadable_distribution=True,
        )
        assert found[0].status == "ok", (
            f"a damaged dist-info hid an installed engine: {found[0].status} - {found[0].message}"
        )

    def test_a_plain_install_without_the_extra_is_still_only_a_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Absent stays non-fatal: a stock install is meant not to carry this."""
        found = self._cv_check(monkeypatch, frontend=False)
        assert len(found) == 1
        assert found[0].status == "warn"
        assert "geometry detection still works" in found[0].message
