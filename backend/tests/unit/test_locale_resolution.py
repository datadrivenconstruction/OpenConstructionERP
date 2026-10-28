# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Wires scripts/check_locale_resolution.py into the pytest run.

That script is a regression LOCK, not a bug report: the defect it guards is
not live today and its own docstring says so and shows the measurement. This
file makes it fire on every ordinary backend test run. ci.yml's "Run unit
tests with pytest" step runs ``pytest tests/unit`` directory-scoped, so a new
file here is collected with no workflow change.

The red proof is the reason to believe any of it. Rather than a synthetic
fixture, it loads the three catalogues that actually carried this defect as
they stood before 341d37ca7 fixed them, and requires the lock to flag all
three and to clear all three post-fix versions. Those are the exact defects it
exists to catch, so passing against them is evidence and not decoration. Both
backend lanes check out with fetch-depth 0, so the history is present in CI.

Every one of these red proofs failed at least once while being written, which
is the only reason they are trusted: the ownership filter compared against a
dotted label and silently skipped every function in a file-loaded module, the
argument filler could not reach risk.localize's table, and the bundle probe
duck-typed on an attribute the pre-fix bcf copy did not have. Each of those
made the lock report a known defect as clean.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "check_locale_resolution.py"

#: The commit that fixed all three, and the files it fixed.
_FIX_COMMIT = "341d37ca7"
_HISTORICAL = {
    "requirements": "backend/app/modules/requirements/intl.py",
    "risk": "backend/app/modules/risk/intl.py",
    "bcf": "backend/app/modules/bcf/messages/__init__.py",
}


def _load_gate():
    spec = importlib.util.spec_from_file_location("check_locale_resolution", _SCRIPT)
    assert spec and spec.loader, f"cannot load {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()
gate.prepare_environment()


def _git_show(revision: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=_REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, (
        f"cannot read {path} at {revision} - this red proof needs real history "
        f"(both backend lanes check out with fetch-depth 0):\n{result.stderr}"
    )
    return result.stdout


def _probe_source(name: str, source: str, workdir: Path) -> dict:
    """Load a standalone copy of a catalogue and ask the lock about it."""
    target = workdir / "__init__.py" if name == "bcf" else workdir / f"{name}_intl.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    if name == "bcf":
        # The bundle reads its JSON from the directory beside the module.
        for path in (_REPO_ROOT / "backend" / "app" / "modules" / "bcf" / "messages").glob("*.json"):
            (workdir / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    module_name = f"locale_lock_probe_{workdir.name}_{name}"
    spec = importlib.util.spec_from_file_location(module_name, target)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: a dataclass declared at module level resolves
    # its own __module__ through sys.modules and raises without this.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        return gate.probe_loaded_module(module_name, module)
    finally:
        sys.modules.pop(module_name, None)


def test_lock_is_green_on_the_current_tree() -> None:
    """The lock must pass on HEAD, or nobody will run it."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        cwd=_REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, f"lock is red on the current tree:\n{result.stdout}\n{result.stderr}"
    assert "probe actually executed" in result.stdout, "the report must print the population it speaks for"


@pytest.mark.parametrize("name", sorted(_HISTORICAL))
def test_lock_flags_the_catalogue_as_it_was_before_the_fix(name: str, tmp_path: Path) -> None:
    """The strongest available red proof: the three real defects this lock is for.

    Each of these was a catalogue that answered a regional locale in English
    while holding a complete translation for its base language. If the lock
    cannot see them it cannot see the next one either.
    """
    source = _git_show(f"{_FIX_COMMIT}^", _HISTORICAL[name])
    result = _probe_source(name, source, tmp_path / "pre")

    assert result["status"] == "probed", (
        f"the pre-fix {name} catalogue could not even be probed ({result['status']}) - "
        f"a lock that cannot demonstrate a known defect proves nothing about an unknown one"
    )
    assert result["unstripped"], f"the pre-fix {name} catalogue was NOT flagged; the lock is blind to its own case"


@pytest.mark.parametrize("name", sorted(_HISTORICAL))
def test_lock_clears_the_catalogue_as_it_stands_today(name: str, tmp_path: Path) -> None:
    """The other direction: the fixed versions must come back clean.

    Without this, a lock that flagged everything would pass the test above and
    still be worthless.
    """
    source = _git_show("HEAD", _HISTORICAL[name])
    result = _probe_source(name, source, tmp_path / "post")

    assert result["status"] == "probed", f"the current {name} catalogue could not be probed ({result['status']})"
    assert not result["unstripped"], (
        f"the current {name} catalogue is flagged as answering a regional locale in English: {result['unstripped']}"
    )


def _run_lock(*extra: str) -> subprocess.CompletedProcess[str]:
    """Run the lock in its own interpreter.

    Deliberately a subprocess rather than calling ``gate.check()`` here. A full
    run imports every module under backend/app that could hold a catalogue -
    76 of them today - and this repo has already been bitten once by a registry
    that grows on import and makes a later test in the same session answer
    differently. A gate question is not worth changing what the rest of the
    suite sees.
    """
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *extra],
        cwd=_REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def test_baseline_holds_no_entry_that_has_since_been_fixed() -> None:
    """A baseline entry that no longer reproduces is ground gained, and must be noticed.

    Left unchecked, a stale allowance silently widens the lock's blind spot:
    the name stays permitted after the code under it changed shape.
    """
    result = _run_lock()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "can leave the baseline" not in result.stdout, (
        "some baseline entries now strip the region; regenerate with --write-baseline so the "
        f"lock stops permitting them:\n{result.stdout}"
    )


def test_the_leavable_entry_warning_can_actually_fire() -> None:
    """Guards the test above from going vacuous.

    ``test_baseline_holds_no_entry_that_has_since_been_fixed`` asserts a phrase
    is ABSENT from stdout. That shape passes unconditionally the moment the
    phrase stops being emitted - a rename, a refactor, a branch that stops
    being reached - and it would pass while reporting nothing. So prove the
    phrase can appear: put a lookup that demonstrably strips today into a
    baseline and require the lock to notice it is no longer needed there.
    """
    real = json.loads((_REPO_ROOT / "scripts" / "locale_resolution_baseline.json").read_text(encoding="utf-8"))
    # risk.intl.localize strips the region; 341d37ca7 is the commit that made it.
    real["known_unstripped"]["app.modules.risk.intl"] = ["localize"]

    with tempfile.TemporaryDirectory() as tmp:
        baseline_path = Path(tmp) / "baseline.json"
        baseline_path.write_text(json.dumps(real), encoding="utf-8")
        result = _run_lock("--baseline", str(baseline_path))

    assert "can leave the baseline" in result.stdout, (
        "the lock no longer reports a baseline entry that has since been fixed, so the "
        "absence-assertion guarding it is now vacuous: " + result.stdout
    )
    assert "app.modules.risk.intl.localize" in result.stdout, result.stdout
    # A warning, not a failure: ground gained must not break the build.
    assert result.returncode == 0, result.stdout


def test_lock_goes_red_when_a_new_catalogue_stops_stripping(tmp_path: Path) -> None:
    """A catalogue written today with an exact-match lookup must be caught."""
    source = """
LABELS = {
    "open": {"en": "Open", "de": "Offen", "ru": "Otkryto"},
    "closed": {"en": "Closed", "de": "Geschlossen", "ru": "Zakryto"},
}


def status_label(status: str, lang: str = "en") -> str:
    per_lang = LABELS.get(status)
    if per_lang is None:
        return status
    return per_lang.get(lang) or per_lang["en"]
"""
    result = _probe_source("newmodule", source, tmp_path / "new")
    assert result["status"] == "probed"
    assert result["unstripped"] == ["status_label"], result


def test_a_catalogue_that_strips_the_region_is_not_flagged(tmp_path: Path) -> None:
    """The same catalogue with the idiom its 30-odd siblings use must pass.

    Paired with the test above so the pair distinguishes the lock from one that
    simply flags every catalogue it can see.
    """
    source = """
LABELS = {
    "open": {"en": "Open", "de": "Offen", "ru": "Otkryto"},
    "closed": {"en": "Closed", "de": "Geschlossen", "ru": "Zakryto"},
}


def _norm_lang(lang: str) -> str:
    return str(lang).strip().lower().replace("_", "-").split("-", 1)[0]


def status_label(status: str, lang: str = "en") -> str:
    per_lang = LABELS.get(status)
    if per_lang is None:
        return status
    return per_lang.get(_norm_lang(lang)) or per_lang["en"]
"""
    result = _probe_source("newmodule_fixed", source, tmp_path / "fixed")
    assert result["status"] == "probed", result
    assert result["unstripped"] == [], result


def test_lock_goes_red_when_a_baseline_module_vanishes(tmp_path: Path) -> None:
    """A baseline naming something the probe never reached must fail, not pass.

    This is the failure the printed population exists to make visible: a run
    that quietly stops watching a module still has nothing to report about it,
    and silence there is indistinguishable from success.
    """
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text('{"known_unstripped": {"app.modules.no_such_module.intl": ["label"]}}', encoding="utf-8")

    result = _run_lock("--baseline", str(baseline_path))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "no_such_module" in result.stdout and "stopped watching" in result.stdout, result.stdout


def test_a_missing_baseline_is_a_verdict_and_not_a_traceback() -> None:
    """The script and its baseline ship in one commit; this is what happens if they do not.

    A gate whose data file is absent does not fail in a defined way unless
    somebody defines one - it fails however the loader happens to fail, and a
    traceback and a red verdict read very differently in a log. Every other
    data-backed gate under scripts/ answers an absent file with a defined
    outcome; this one did not until this test existed.

    Asserted on stderr AND on the exit code, because "it printed something" is
    not the same claim as "it failed".
    """
    result = _run_lock("--baseline", "scripts/definitely_not_here.json")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Traceback" not in result.stderr, "the loader still picks the failure mode:" + result.stderr
    assert "is missing" in result.stderr, result.stderr


def test_a_corrupt_baseline_is_a_verdict_and_not_a_traceback(tmp_path: Path) -> None:
    """Same contract for a file that exists and cannot be parsed."""
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{ this is not json", encoding="utf-8")

    result = _run_lock("--baseline", str(baseline_path))

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Traceback" not in result.stderr, result.stderr
    assert "not valid JSON" in result.stderr, result.stderr


def test_lock_refuses_an_interpreter_that_cannot_parse_the_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Running under 3.11 made the probe report a healthy file as a SyntaxError.

    It skipped that module and still printed OK, which is the exact shape of a
    gate lying about its population. The guard must raise rather than skip.
    """
    monkeypatch.setattr(gate, "MINIMUM_PYTHON", (99, 0))
    with pytest.raises(RuntimeError, match="PEP 695"):
        gate.require_supported_interpreter()
