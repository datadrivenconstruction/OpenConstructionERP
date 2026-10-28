# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The Chinese pack, and the one word it spelled two ways.

A Chinese cost item is read by two things that never agreed with each other.
``match_elements`` builds a section path by asking
:func:`classification_order` which standards to try and taking the first one
the item has a code under; the registry answers ``gb50500``. The two engine
rules read the same dict under ``gbt50500``, and the shipped demo bills were
keyed to match the rules. So the rules worked, and every line of both Chinese
demo projects rendered with no section path at all.

Neither half errored. A missing section path is an empty string, and an empty
string is what a line with no classification looks like, so there was nothing
to see. The tests below are mostly about that: they assert the produced value
rather than the absence of an exception, because absence of an exception was
never in question.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.core.classification_registry import (
    CLASSIFICATION_STANDARD_LABELS,
    KNOWN_CLASSIFICATION_STANDARDS,
    classification_order,
    resolve_standard,
)
from app.core.demo_packs import PACK_TEMPLATES

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "packs" / "china-gbt50500" / "src" / "openconstructionerp_china_gbt50500"
DEMO_PACKS = REPO_ROOT / "backend" / "app" / "core" / "demo_packs"
CHINESE_DEMOS = ("office-shanghai", "residential-shenzhen")


def _template(demo_id: str) -> Any:
    """The shipped demo template, looked up by id.

    ``PACK_TEMPLATES`` is a list that each pack module appends itself to on
    import, so there is no key to miss: a pack that raised on import is simply
    not in it, and the ``KeyError`` this raises is the loud version of that.
    """
    by_id = {t.demo_id: t for t in PACK_TEMPLATES}
    return by_id[demo_id]


@pytest.fixture(scope="module")
def manifest() -> Any:
    """The pack's real on-disk manifest, loaded the way the loader loads it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_china_manifest", PACK / "manifest.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MANIFEST


def _classification_dicts(demo_id: str) -> list[dict[str, str]]:
    """Every classification dict in a demo template, sections and items."""
    template = _template(demo_id)
    found: list[dict[str, str]] = []
    for section in template.sections:
        found.append(section[2])
        for item in section[3]:
            found.append(item[5])
    return found


# ── The control ──────────────────────────────────────────────────────────


def test_both_chinese_demo_templates_actually_loaded() -> None:
    """``app/core/demo_packs/__init__.py`` catches the exception from a pack
    that will not import, prints a line and carries on with the rest. A pack
    that drops out that way is simply absent from ``PACK_TEMPLATES``, so a
    test that iterates the registry and asserts a property of what it finds
    would pass over a broken pack in silence. Name them."""
    for demo_id in CHINESE_DEMOS:
        assert demo_id in {t.demo_id for t in PACK_TEMPLATES}, f"{demo_id} is not in PACK_TEMPLATES, it failed to load"
    counts = {d: len(_classification_dicts(d)) for d in CHINESE_DEMOS}
    assert all(n > 50 for n in counts.values()), f"a Chinese demo lost its bill: {counts}"


# ── The defect ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("demo_id", CHINESE_DEMOS)
def test_a_chinese_demo_item_produces_a_section_path(demo_id: str) -> None:
    """The assertion the defect was invisible to.

    This is the loop from ``match_elements/service.py``, run over the codes the
    pack actually ships. Before the key was renamed it returned ``None`` for
    every line of both bills, and returned it quietly.
    """
    template = _template(demo_id)
    order = classification_order(template.classification_standard, template.region)
    for classification in _classification_dicts(demo_id):
        path = next(
            (f"{CLASSIFICATION_STANDARD_LABELS[s]} {classification[s]}" for s in order if classification.get(s)), None
        )
        assert path is not None, (
            f"{demo_id}: a cost item keyed {sorted(classification)} produced no section path. "
            f"classification_order offered {order[:3]}..., and none of them is a key on the item."
        )


@pytest.mark.parametrize("demo_id", CHINESE_DEMOS)
def test_the_demo_declares_a_standard_the_resolver_accepts(demo_id: str) -> None:
    """``resolve_standard`` drops an explicit value it does not know and falls
    through to the region. Here the region happens to rescue it, which is why
    the wrong value survived so long: the answer was right and the reason was
    not, so nothing downstream looked wrong."""
    template = _template(demo_id)
    assert template.classification_standard in KNOWN_CLASSIFICATION_STANDARDS
    resolution = resolve_standard(template.classification_standard, template.region)
    assert resolution.source == "explicit", (
        f"{demo_id} names {template.classification_standard!r} and the registry resolved it "
        f"by {resolution.source!r} instead, which means the declared value was ignored."
    )


@pytest.mark.parametrize("demo_id", CHINESE_DEMOS)
def test_no_cost_item_is_keyed_with_the_rule_set_name(demo_id: str) -> None:
    """``gbt50500`` is the engine rule set and ``gb50500`` is the
    classification standard. They are different namespaces resolved by
    different registries, and only one of them belongs on a cost item."""
    stray = [c for c in _classification_dicts(demo_id) if "gbt50500" in c]
    assert not stray, (
        f"{demo_id}: {len(stray)} cost items are keyed 'gbt50500'. That is the rule set identifier; "
        f"the section path builder looks for the classification standard, which is 'gb50500'."
    )


@pytest.mark.parametrize("demo_id", CHINESE_DEMOS)
def test_the_rule_set_declaration_was_not_renamed_along_with_the_keys(demo_id: str) -> None:
    """The other half of the same distinction, and the half a careless sweep
    would have taken with it. Renaming the rule set would break the manifest
    that declares it and every message key in four locales."""
    template = _template(demo_id)
    assert "gbt50500" in template.validation_rule_sets, (
        f"{demo_id} no longer declares the gbt50500 rule set. The engine rules are registered "
        f"under that identifier and a project that does not name it runs none of them."
    )


# ── The engine rules ─────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["gb50500", "gbt50500"])
async def test_the_code_rules_read_an_item_under_either_spelling(key: str) -> None:
    """A customer installation has been storing bills since before the rename,
    and those rows carry the old key. Dropping it would turn a bill that
    passed yesterday into one that fails today, which is a worse thing to do
    to a user than one extra dictionary lookup."""
    from app.core.validation.engine import ValidationContext
    from app.core.validation.rules import GBT50500CodeRequired, GBT50500ValidCode

    position = {
        "id": "p1",
        "ordinal": "0101.1",
        "type": "item",
        "description": "平整场地 (Site clearance and grading)",
        "unit": "m2",
        "quantity": 4200.0,
        "unit_rate": 8.50,
        "classification": {key: "010101001"},
    }
    context = ValidationContext(data={"positions": [position]}, metadata={"locale": "en"})

    required = await GBT50500CodeRequired().validate(context)
    valid = await GBT50500ValidCode().validate(context)
    assert required and required[0].passed, f"the presence rule did not see the code under {key!r}"
    assert valid and valid[0].passed, f"the format rule did not see the code under {key!r}"
    assert valid[0].details["given_code"] == "010101001"


# ── What the pack declares against what is on disk ───────────────────────


def test_every_declared_rule_pack_document_exists(manifest: Any) -> None:
    """``validation_rule_packs`` entries are document ids and each has to be
    the stem of a file in ``rule_packs/``. A declared document that is not
    there is a 404 on a screen that offers to open it."""
    stems = {p.stem for p in (PACK / "rule_packs").glob("*.json")} if (PACK / "rule_packs").is_dir() else set()
    missing = set(manifest.validation_rule_packs) - stems
    assert not missing, f"declared but not on disk: {sorted(missing)}"


def test_every_rule_pack_document_on_disk_is_declared(manifest: Any) -> None:
    """The other direction. A document nobody declares is never shown."""
    if not (PACK / "rule_packs").is_dir():
        pytest.skip("the pack ships no rule_packs directory yet")
    stems = {p.stem for p in (PACK / "rule_packs").glob("*.json")}
    undeclared = stems - set(manifest.validation_rule_packs)
    assert not undeclared, f"on disk but not declared: {sorted(undeclared)}"


def test_a_declared_onboarding_script_exists(manifest: Any) -> None:
    if manifest.onboarding_script_path is None:
        pytest.skip("the pack runs the default wizard steps")
    assert (PACK / manifest.onboarding_script_path).is_file()


def test_a_declared_logo_exists(manifest: Any) -> None:
    """The manifest currently sets this to None on purpose and says why in a
    comment: naming a file that is not there only made the endpoint 404."""
    if manifest.branding.logo_path is None:
        pytest.skip("the pack draws a monogram from its two brand colours")
    assert (PACK / manifest.branding.logo_path).is_file()


def test_every_declared_locale_overlay_exists(manifest: Any) -> None:
    for code, relative in (manifest.additional_locales or {}).items():
        assert (PACK / relative).is_file(), f"{code} overlay declared at {relative} and not on disk"


def test_the_pack_promises_an_interface_the_app_can_actually_show(manifest: Any) -> None:
    """``default_locale`` resolves against the app's own bundles, not the
    pack's. A locale the app does not ship falls back to English silently,
    which is why the Hungarian pack declares ``en`` and this one declares
    ``zh``: the difference is which file is on disk, not which is preferred.
    """
    locales = REPO_ROOT / "frontend" / "src" / "app" / "locales"
    assert (locales / f"{manifest.default_locale}.ts").is_file(), (
        f"the pack asks for a {manifest.default_locale!r} interface and the app ships no "
        f"{manifest.default_locale}.ts, so every user of this pack would silently get English."
    )


# ── The documents, once they exist ───────────────────────────────────────


def _documents() -> list[Path]:
    directory = PACK / "rule_packs"
    return sorted(directory.glob("*.json")) if directory.is_dir() else []


@pytest.mark.parametrize("path", _documents(), ids=lambda p: p.stem)
def test_a_document_states_how_far_it_has_been_reviewed(path: Path) -> None:
    """A pack document is read by somebody deciding whether to price a tender
    against it. Whether it was derived from a published base read in full or
    drawn from public sources and still waiting on a domain expert is the
    difference between the two, and the reader cannot tell by looking."""
    document = json.loads(path.read_text(encoding="utf-8"))
    status = document.get("review_status", "")
    assert isinstance(status, str) and len(status) > 30, (
        f"{path.name} does not say how far it has been reviewed. Every other country pack's "
        f"documents do, and a reader has no other way to tell."
    )


@pytest.mark.parametrize("path", _documents(), ids=lambda p: p.stem)
def test_a_document_is_identified_by_its_own_filename(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document.get("rule_pack_id") == path.stem


@pytest.mark.parametrize("path", _documents(), ids=lambda p: p.stem)
def test_a_document_names_the_standard_and_the_jurisdiction(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document.get("jurisdiction") == "CN"
    assert document.get("standard") in {"gb50500", "gbt50500"}


@pytest.mark.parametrize("path", _documents(), ids=lambda p: p.stem)
def test_a_document_carries_its_chinese_wording(path: Path) -> None:
    """The reader of these is a Chinese estimator. A document that names the
    concept only in English asks them to translate back into the term they
    already use, and the term is the part that has to be exact."""
    document = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(document, ensure_ascii=False)
    assert re.search(r"[一-鿿]", text), f"{path.name} contains no Chinese at all"
    assert document.get("name_zh"), f"{path.name} has no name_zh"


def test_the_pack_ships_documents_at_all() -> None:
    """The control on every parametrised case above: an empty ``rule_packs``
    directory makes all of them vacuous, and a file of vacuous tests reads
    exactly like a file of passing ones."""
    assert _documents(), "the China pack ships no rule_pack documents"
