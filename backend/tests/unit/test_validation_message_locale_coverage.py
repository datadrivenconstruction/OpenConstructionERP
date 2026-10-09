# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Wires scripts/check_validation_message_locale_coverage.py into the pytest run.

That script is the actual gate (it can be run by hand and prints its own
report); this file is what makes it fire on every ordinary backend test run
without a CI workflow edit. That is measured, not assumed: ci.yml's "Run unit
tests with pytest" step (grep the step name, the line number will drift) runs
``pytest tests/unit`` sharded six ways, directory-scoped, so a new file in this
directory is collected with no workflow change. Most of ci-postgres.yml names
individual files instead and would NOT have picked this up. Same relationship
test_backend_locale_catalogue.py has to backend/locales - except that guard
predates this one and covers a different catalogue (app.core.i18n's 28 backend
locales), not the seven MessageBundle catalogues under backend/app. Nothing
checked those before this file: not test_validation_i18n.py (per-key coverage
inside locales that already exist, never file count), not
test_backend_locale_catalogue.py (wrong directory), not any
scripts/check_i18n_*.py (all scoped to frontend/).

A gate that cannot go red is not a gate, so this exercises every failure path
directly rather than trusting that the script's logic is correct by inspection.
The locale-loss proof is parametrised over all six module catalogues rather
than sampling one: the gate was widened from one catalogue to seven, and a
proof that bcf is ratcheted says nothing about the other five.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "check_validation_message_locale_coverage.py"
_BASELINE = _REPO_ROOT / "scripts" / "validation_i18n_locale_coverage_baseline.json"
_APP_ROOT = _REPO_ROOT / "backend" / "app"
_CORE_CATALOGUE = "backend/app/core/validation/messages"


def _load_gate():
    spec = importlib.util.spec_from_file_location("check_validation_message_locale_coverage", _SCRIPT)
    assert spec and spec.loader, f"cannot load {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()

# Computed once at import so the red proofs can be parametrised by catalogue
# name. Every catalogue except the core bundle is one this gate did not watch
# before it was widened.
_CATALOGUES = gate.discover_catalogues(_APP_ROOT)
_NEWLY_WATCHED = sorted(name for name in _CATALOGUES if name != _CORE_CATALOGUE)


def _copy_catalogue(name: str, dest: Path) -> Path:
    shutil.copytree(_CATALOGUES[name], dest)
    return dest


def test_gate_is_green_on_the_current_tree() -> None:
    """The gate must pass on HEAD, or nobody will run it (mirrors the commit-subject guard test)."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        cwd=_REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, f"gate is red on the current tree:\n{result.stdout}\n{result.stderr}"


def test_the_gate_watches_more_than_the_core_bundle() -> None:
    """Guards the widening itself.

    If discovery ever collapses back to one directory the ratchet still passes
    green on every tree, because the one catalogue it kept watching is the one
    least likely to lose a locale. The failure this pins is not a wrong answer,
    it is a shrunken question.
    """
    assert len(_CATALOGUES) >= 7, f"discovery found only {sorted(_CATALOGUES)}"
    assert _CORE_CATALOGUE in _CATALOGUES
    assert len(_NEWLY_WATCHED) >= 6


def test_discovery_finds_the_catalogue_that_is_not_a_package() -> None:
    """Pins the trap that decided how discovery is written, not just today's answer.

    modules/rebar_schedule/messages has no __init__.py - its bundle is built one
    directory up in validators.py - so any search that looks for catalogue
    PACKAGES silently returns six instead of seven. This asserts both halves:
    that the discovery in use finds it, and that the package-shaped search
    really does miss it. Without the second half this test would still pass
    after someone "simplified" discovery into the broken form.
    """
    rebar = "backend/app/modules/rebar_schedule/messages"
    assert rebar in _CATALOGUES, f"discovery lost the non-package catalogue; found {sorted(_CATALOGUES)}"
    assert not (_CATALOGUES[rebar] / "__init__.py").exists(), (
        "rebar_schedule/messages has become a package - this test's premise is gone and the "
        "package-glob trap it guards no longer reproduces, so rewrite it rather than deleting it"
    )

    package_shaped = {gate.catalogue_name(p.parent) for p in _APP_ROOT.rglob("messages/__init__.py")}
    assert rebar not in package_shaped, "the package-shaped search now finds it, so this trap needs re-measuring"
    assert package_shaped < set(_CATALOGUES), "the package-shaped search is meant to be a strict subset"


def test_discovery_agrees_with_every_message_bundle_construction_site() -> None:
    """Directory names are weak evidence; what the code actually builds is strong evidence.

    Every MessageBundle construction site must point at a discovered catalogue
    and every discovered catalogue must have a site that reads it. A site with
    no catalogue means the gate is blind to a bundle; a catalogue with no site
    means it is gating data nothing loads.
    """
    claimed = gate.bundle_construction_dirs(_APP_ROOT)
    assert set(claimed) == set(_CATALOGUES), (
        f"built but not discovered: {sorted(set(claimed) - set(_CATALOGUES))}; "
        f"discovered but never built: {sorted(set(_CATALOGUES) - set(claimed))}"
    )


def test_discovery_excludes_per_locale_directories_no_bundle_reads() -> None:
    """The over-collecting rule that was rejected, pinned so it cannot come back.

    Both directories below hold per-locale JSON and would be swept in by a
    search for en.json anywhere under backend/app, but no MessageBundle reads
    either, so ratcheting them would gate a population this gate had
    misidentified.
    """
    for stranger in (
        "backend/app/modules/costs/translations",
        "backend/app/modules/property_dev/data/document_locales",
    ):
        assert (_REPO_ROOT / stranger).is_dir(), f"{stranger} moved - re-measure before editing this test"
        assert stranger not in _CATALOGUES, f"{stranger} is not a MessageBundle catalogue but discovery took it"


def test_baseline_covers_every_catalogue_on_disk() -> None:
    """A catalogue missing from the baseline passes with a reminder - forever, if nobody reads it."""
    baseline = gate.load_baseline(_BASELINE)
    unrecorded = sorted(set(_CATALOGUES) - set(baseline))
    assert not unrecorded, f"{unrecorded} answer locales that nothing is ratcheting; run --write-baseline"


@pytest.mark.parametrize("name", sorted(_CATALOGUES))
def test_baseline_matches_what_each_catalogue_actually_answers(name: str) -> None:
    """A stale baseline (recording more than a catalogue answers) would mask a real regression."""
    baseline = gate.load_baseline(_BASELINE)
    answered = gate.read_bundle_locales(_CATALOGUES[name])
    assert baseline.get(name, set()) <= answered, (
        f"baseline claims {sorted(baseline[name] - answered)} which {name} no longer answers - "
        f"the gate would report this tree as passing while it has already regressed"
    )


@pytest.mark.parametrize("name", sorted(_CATALOGUES))
def test_each_catalogue_answers_a_strict_subset_of_supported_locales(name: str) -> None:
    """Sanity check on the measurement itself, not just the ratchet outcome.

    Every locale a catalogue answers must be one app.core.i18n.SUPPORTED_LOCALES
    names. That list is what AcceptLanguageMiddleware clamps a request to, and
    it is the only value that reaches a bundle: the core engine's callers read
    it through get_locale(), and the module rules read
    ValidationContext.metadata["locale"], which is populated from the same
    place. A bundle locale outside that set is unreachable in production
    however complete its translations are.
    """
    supported = set(gate.read_supported_locales(gate.I18N_MODULE))
    answered = gate.read_bundle_locales(_CATALOGUES[name])
    assert answered <= supported, (
        f"{name} answers {sorted(answered - supported)}, which app.core.i18n.SUPPORTED_LOCALES does not "
        f"list - no request can ever resolve to that code, so no caller can request it"
    )
    assert "en" in answered, f"{name} has no en.json, and English is the bundle's unconditional last resort"


def test_frontend_measurement_is_internally_consistent() -> None:
    """The printed frontend numbers must relate the way the docstring claims."""
    files = {p.stem for p in (_REPO_ROOT / "frontend" / "src" / "app" / "locales").glob("*.ts")}
    offered = gate.read_frontend_languages(gate.FRONTEND_I18N_TS)
    offered_set = set(offered)

    assert len(offered) == len(offered_set), "a duplicate code in SUPPORTED_LANGUAGES would hide behind a set"
    # Every reachable code must correspond to a real .ts file - an entry with
    # no file behind it would mean the language picker offers something that
    # silently serves raw keys.
    missing_files = sorted(offered_set - files)
    assert not missing_files, f"SUPPORTED_LANGUAGES lists {missing_files} with no locales/*.ts file"

    base_languages = {gate.base_language(code) for code in offered}
    # Collapsing regional variants can only ever reduce the count, never grow it.
    assert len(base_languages) <= len(offered)


@pytest.mark.parametrize("name", _NEWLY_WATCHED)
def test_gate_goes_red_when_a_newly_watched_catalogue_loses_a_locale(name: str, tmp_path: Path) -> None:
    """Delete one locale file from each catalogue the widening added - the ratchet must fail, by name.

    Every one of these six could have lost a locale in silence before this gate
    was widened, so each is proved individually rather than by sampling one.
    """
    scratch = _copy_catalogue(name, tmp_path / "messages")
    baseline = gate.load_baseline(_BASELINE)
    victim = sorted(baseline[name] - {"en"})[0]
    (scratch / f"{victim}.json").unlink()

    catalogues = {**_CATALOGUES, name: scratch}
    exit_code, lines = gate.check(catalogues=catalogues, cross_check=False)

    assert exit_code == 1, f"removing {name}/{victim}.json did not turn the gate red:\n" + "\n".join(lines)
    # The locale is matched as the rendered list it appears in rather than as a
    # bare substring: a two-letter code is short enough to occur by accident in
    # a catalogue path, which would let this assertion pass on a message that
    # never actually named the lost locale.
    assert any("REGRESSION" in line and name in line and f"['{victim}']" in line for line in lines), (
        f"the failure does not say which catalogue lost {victim}:\n" + "\n".join(lines)
    )


@pytest.mark.parametrize("name", _NEWLY_WATCHED)
def test_gate_goes_red_when_a_newly_watched_catalogue_locale_is_emptied(name: str, tmp_path: Path) -> None:
    """Emptying a file must count the same as deleting it - a size-zero catalogue answers nothing."""
    scratch = _copy_catalogue(name, tmp_path / "messages")
    baseline = gate.load_baseline(_BASELINE)
    victim = sorted(baseline[name] - {"en"})[0]
    (scratch / f"{victim}.json").write_text("{}", encoding="utf-8")

    exit_code, lines = gate.check(catalogues={**_CATALOGUES, name: scratch}, cross_check=False)
    assert exit_code == 1, f"emptying {name}/{victim}.json did not turn the gate red:\n" + "\n".join(lines)
    assert any("REGRESSION" in line and name in line and f"['{victim}']" in line for line in lines)


def test_gate_goes_red_when_a_whole_catalogue_disappears() -> None:
    """A failure mode the single-catalogue version had no equivalent of.

    Deleting a module's messages directory outright removes it from discovery,
    so a per-catalogue ratchet that only compared locale sets would find
    nothing to compare and pass. Losing an entire catalogue is the largest
    possible loss of ground and has to be the loudest.
    """
    victim = _NEWLY_WATCHED[0]
    catalogues = {name: path for name, path in _CATALOGUES.items() if name != victim}

    exit_code, lines = gate.check(catalogues=catalogues, cross_check=False)
    assert exit_code == 1, f"losing the whole {victim} catalogue did not turn the gate red:\n" + "\n".join(lines)
    assert any("no longer on disk" in line and victim in line for line in lines)


def test_gate_goes_red_when_a_bundle_is_built_for_an_undiscovered_directory(tmp_path: Path) -> None:
    """The instrument going blind must fail, not pass quietly.

    Built as a self-contained miniature tree with its own baseline so the only
    thing that can turn it red is the discovery mismatch: one catalogue that
    discovery does find, and one MessageBundle built for a directory that does
    not exist. That second site is how an eighth catalogue in an unanticipated
    shape would arrive, and the whole point is that it must not arrive silently.
    """
    app_root = tmp_path / "app"
    alpha = app_root / "modules" / "alpha" / "messages"
    alpha.mkdir(parents=True)
    (alpha / "en.json").write_text(json.dumps({"common": {"ok": "OK"}}), encoding="utf-8")
    (alpha / "__init__.py").write_text("_bundle = MessageBundle(messages_dir=_MESSAGES_DIR)\n", encoding="utf-8")

    beta = app_root / "modules" / "beta"
    beta.mkdir(parents=True)
    (beta / "validators.py").write_text('MESSAGES = MessageBundle(Path(__file__).parent / "messages")\n', "utf-8")

    catalogues = gate.discover_catalogues(app_root)
    assert set(catalogues) == {gate.catalogue_name(alpha)}, "the miniature tree is not shaped as this test assumes"

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({"catalogues": {gate.catalogue_name(alpha): ["en"]}}), encoding="utf-8")

    exit_code, lines = gate.check(catalogues=catalogues, app_root=app_root, baseline_path=baseline_path)
    assert exit_code == 1, "a MessageBundle built for an undiscovered directory did not turn the gate red"
    assert any("DISCOVERY" in line and "beta" in line for line in lines), "\n".join(lines)


def test_gate_stays_green_when_a_catalogue_gains_a_locale(tmp_path: Path) -> None:
    """Growing an answered set must pass (a hard 28-of-28 requirement would block today's tree)."""
    name = _NEWLY_WATCHED[0]
    scratch = _copy_catalogue(name, tmp_path / "messages")
    # Pick a locale the catalogue does not answer yet, so the set really grows.
    gained = next(code for code in ("fr", "pl", "nl", "sv") if not (scratch / f"{code}.json").exists())
    (scratch / f"{gained}.json").write_text(json.dumps({"common": {"ok": "OK"}}), encoding="utf-8")

    exit_code, lines = gate.check(catalogues={**_CATALOGUES, name: scratch}, cross_check=False)
    assert exit_code == 0, "\n".join(lines)
    assert any(gained in line and name in line and "regenerate the baseline" in line for line in lines)


def test_gate_refuses_a_baseline_it_cannot_read(tmp_path: Path) -> None:
    """The pre-widening baseline format must fail loudly, not read as "nothing recorded".

    The old file was a flat answered_locales list with no catalogue names in it.
    Parsed leniently, that yields an empty per-catalogue mapping, which makes
    every comparison vacuous and the ratchet green on any tree at all - the
    worst failure a gate can have, because it looks exactly like success.
    """
    stale = tmp_path / "baseline.json"
    stale.write_text(json.dumps({"answered_locales": ["de", "en", "es", "ru"]}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="old single-catalogue format"):
        gate.load_baseline(stale)
