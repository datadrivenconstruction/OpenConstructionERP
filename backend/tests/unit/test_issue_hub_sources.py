# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every module that owns a defect register is either in the Issue Hub or named here.

The Unified Issue Hub merges five registers into one list so that, in the words
of its own subtitle, nothing falls between the cracks. The union it reads is
declared once, in ``frontend/src/features/issues/issueSources.ts``, as the
``IssueSource`` type. Nothing checked that union against the platform.

Measured, the platform holds defect registers in more modules than the hub
reads. A module that starts holding defects is invisible to the hub, and the
only symptom is a screen that quietly shows a subset while being named for the
whole: a user filtering the hub to "all sources" still misses whole registers,
and there is no log line or failing assertion anywhere to say so.

This gate censuses the backend for issue-like models, maps the hub's sources
onto their owning modules, and requires every censused module to be either
covered or named in ``KNOWN_ABSENT_FROM_HUB`` with the reason. It fails in
both directions: a new defect register with no hub source and no allowlist
line fails, and an allowlist line that outlives its gap fails too.

The census is name-based and says so. It finds a module whose model or table
carries one of ``_ISSUE_WORDS``; a register called ``Deficiency`` would slip
past it. The word list is the declared limit of the instrument, not a claim
that the platform holds nothing else. Widening the list is the way to widen
the gate - writing a second gate beside it is not.

The word list also produces one false positive on purpose, and it is kept
rather than tuned away: ``hse_advanced.PPEIssue`` is an issuance of protective
equipment, not a defect. Narrowing the words until it disappears would take
real registers with it, so it is allowlisted with that reason, which is also
what stops a future reader from "fixing" the gap by wiring PPE into the hub.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_BACKEND_MODULES = pathlib.Path(__file__).resolve().parents[2] / "app" / "modules"
_ISSUE_SOURCES = (
    pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src" / "features" / "issues" / "issueSources.ts"
)

# A model or table naming one of these is treated as a defect register.
_ISSUE_WORDS = (
    "ncr",
    "punch",
    "defect",
    "snag",
    "issue",
    "clash",
    "nonconform",
    "non_conform",
    "observation",
)

# Which backend module each hub source reads. The hub's own names are short
# labels ("punch"), not module names ("punchlist"), so the mapping is explicit.
_SOURCE_TO_MODULE = {
    "markup": "markups",
    "punch": "punchlist",
    "ncr": "ncr",
    "bcf": "bcf",
    "clash": "clash",
    "neighbour": "site_logistics",
}

# Modules holding a defect register the hub does not read. Each line is a work
# item, so each carries what the register is and why it is still outside.
KNOWN_ABSENT_FROM_HUB: dict[str, str] = {
    "site_sensors": (
        "ConcreteMix is a concrete mix design with its maturity calibration, not a defect. "
        "The census matches it by name only; sensor alerts are threshold readings, not a defect register."
    ),
    "delivery_model": (
        "DecisionCriterion is a weighted selection criterion for comparing delivery forms, "
        "not a defect. The census matches it by name only; the module holds no defect register."
    ),
    "engineering_brief": (
        "SpecificationIssue is a numbered issue of the requirements specification as a document, "
        "not a defect. The census matches it by name only; the module holds no defect register."
    ),
    "qms": (
        "QMSNCR and QMSPunchItem. The QMS module was built as a unified replacement for "
        "the legacy inspections, ncr and punchlist modules and its docstring says the "
        "legacy ones keep running with cross-references stored via metadata fields. "
        "There is no metadata column on either QMS model, so no such cross-reference "
        "can exist: the two NCR registers and the two punch registers are disjoint. "
        "The only live link is a read of PunchItem.rework_cost for COPQ analytics "
        "(qms/service.py:1892). Deciding whether QMS defects belong in the same list "
        "as commercial ones is a product call, not a mechanical one"
    ),
    "commissioning": (
        "CxIssue, a deficiency raised against a CxSystem, carrying severity and status. "
        "A critical issue that is still open blocks its system from being commissioned, "
        "so this is the register with the hardest downstream consequence of any listed "
        "here, and it is absent from the one screen that claims to show everything open"
    ),
    "defects_liability": (
        "DlpDefect, a defect notice raised against a warranty during the defects "
        "liability period, on a minor/major/critical scale. Post-handover work, which "
        "is the phase the hub's five sources cover least"
    ),
    "property_dev": (
        "Snag, a defect noted during or after handover, with a nullable buyer_id for "
        "snags raised by the buyer through the portal. Buyer-raised items reaching no "
        "shared list is the sharpest version of the gap"
    ),
    "safety": (
        "SafetyObservation, carrying severity, likelihood, risk_score and "
        "corrective_action. Genuinely arguable: a proactive observation is not a "
        "defect, and folding safety into a defect list may be wrong. Listed so the "
        "decision is made rather than defaulted into"
    ),
    "hse_advanced": (
        "PPEIssue is NOT a defect register. It records a single issuance of protective "
        "equipment to a worker (recipient, ppe_type, size, serial, valid_until). It "
        "matches the census only because issue is both a noun and a verb. Do not wire "
        "it into the hub"
    ),
    "clash_ai_triage": (
        "ClashTriageResult is a derived AI triage of rows that already belong to the "
        "clash module, which the hub does read. Covered by clash, not a register of "
        "its own"
    ),
}


def _modules_with_issue_registers() -> dict[str, list[str]]:
    """Census backend modules whose models name a defect register."""
    found: dict[str, list[str]] = {}
    for models in sorted(_BACKEND_MODULES.rglob("models.py")):
        if "__pycache__" in str(models):
            continue
        source = models.read_text(encoding="utf-8", errors="ignore")
        module = models.relative_to(_BACKEND_MODULES).parts[0]
        for match in re.finditer(r"^class (\w+)\(Base\):", source, re.M):
            segment = source[match.end() : match.end() + 2500]
            table = re.search(r'__tablename__ = "([^"]+)"', segment)
            blob = f"{match.group(1)} {table.group(1) if table else ''}".lower()
            if any(word in blob for word in _ISSUE_WORDS):
                found.setdefault(module, []).append(match.group(1))
    return found


def _declared_sources() -> set[str]:
    """Read the hub's source union from the file that defines it."""
    text = _ISSUE_SOURCES.read_text(encoding="utf-8")
    match = re.search(r"export type IssueSource =([^;]+);", text)
    assert match, "IssueSource union not found - this gate is reading the wrong file"
    return set(re.findall(r"'([a-z_]+)'", match.group(1)))


def test_census_finds_a_real_population() -> None:
    """Print the denominator beside the verdict, so a broken sweep cannot pass."""
    census = _modules_with_issue_registers()
    assert len(census) > 5, f"census found only {len(census)} modules - the instrument is broken"


@pytest.mark.skipif(not _ISSUE_SOURCES.exists(), reason="frontend tree not present")
def test_source_names_map_onto_real_modules() -> None:
    """The hub's five labels must still name modules that exist."""
    assert set(_SOURCE_TO_MODULE) == _declared_sources(), (
        "the hub's IssueSource union and this mapping disagree; update _SOURCE_TO_MODULE"
    )
    missing = [m for m in _SOURCE_TO_MODULE.values() if not (_BACKEND_MODULES / m).is_dir()]
    assert not missing, f"hub sources naming modules that do not exist: {missing}"


@pytest.mark.skipif(not _ISSUE_SOURCES.exists(), reason="frontend tree not present")
def test_every_defect_register_is_read_or_named() -> None:
    """A defect register outside the hub must be a decision, not an oversight."""
    census = _modules_with_issue_registers()
    covered = set(_SOURCE_TO_MODULE.values())
    undocumented = {
        module: models
        for module, models in census.items()
        if module not in covered and module not in KNOWN_ABSENT_FROM_HUB
    }
    assert not undocumented, (
        f"these modules own a defect register the Issue Hub does not read, and are not "
        f"named in KNOWN_ABSENT_FROM_HUB: {undocumented}. Either wire the source into "
        f"issueSources.ts or add the module with the reason it stays out."
    )

    repaired = sorted(set(KNOWN_ABSENT_FROM_HUB) & covered)
    assert not repaired, (
        f"these modules are now read by the Issue Hub but are still listed as absent: "
        f"{repaired}. Delete their KNOWN_ABSENT_FROM_HUB entries."
    )

    stale = sorted(set(KNOWN_ABSENT_FROM_HUB) - set(census))
    assert not stale, (
        f"these modules no longer hold a defect register the census can see: {stale}. "
        f"Delete their entries, or widen _ISSUE_WORDS if the register was renamed."
    )


def test_allowlist_entries_all_carry_a_reason() -> None:
    """A bare module name tells a reader nothing about what is missing."""
    thin = sorted(k for k, v in KNOWN_ABSENT_FROM_HUB.items() if len(v) < 40)
    assert not thin, f"these entries need a reason, not a placeholder: {thin}"
