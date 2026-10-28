# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Resource-category normalisation: machinery must stay distinct from equipment.

Regression for the methodology engine. The post-Soviet СМР/SMR cascade splits
construction machinery (which rides inside the SMR works base) from installed
equipment (which carries only some markups) - see
``app.modules.methodology.templates._CASCADE_BASE_MAPPING`` (Uzbekistan /
railway). The BOQ cost breakdown used to fold ``machinery`` into ``equipment``,
which silently zeroed the machinery base and over-stated equipment whenever a
methodology computed from a ``boq_id``. These tests pin the split so that
regression cannot return.
"""

from decimal import Decimal

import pytest

from app.modules.boq.service import BOQService
from app.modules.methodology.bases import resolve_bases
from app.modules.methodology.templates import _CASCADE_BASE_MAPPING, _SMR_COMPOSITE

_norm = BOQService._normalize_resource_category
_classify = BOQService._classify_position_category


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # machinery + its synonyms now get their OWN category
        ("machinery", "machinery"),
        ("Machinery", "machinery"),
        ("  MACHINERY  ", "machinery"),
        ("machine", "machinery"),
        ("maschine", "machinery"),  # German
        ("mechanism", "machinery"),
        ("mechanisms", "machinery"),  # ru "механизмы"
        # installed equipment stays equipment - NOT machinery
        ("equipment", "equipment"),
        ("plant", "equipment"),
        ("geraet", "equipment"),
        # the other canonical categories are unchanged
        ("labor", "labor"),
        ("labour", "labor"),
        ("material", "material"),
        ("materials", "material"),
        ("subcontractor", "subcontractor"),
        ("nachunternehmer", "subcontractor"),
        ("anything-else", "other"),
    ],
)
def test_normalize_resource_category(raw: str, expected: str) -> None:
    assert _norm(raw) == expected


def test_machinery_distinct_from_equipment() -> None:
    """The whole point: the two must never collapse into one bucket."""
    assert _norm("machinery") != _norm("equipment")


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        # Construction plant / mechanisms that perform the work -> machinery.
        # These are the positions that previously leaked into ``equipment`` on
        # the description-heuristic fallback (no resource metadata) path.
        ("Kran 50t Vorhaltung", "machinery"),
        ("Mobile crane hire per day", "machinery"),
        ("Bagger 25t Einsatz", "machinery"),
        ("Excavator operation", "machinery"),
        ("Radlader / wheel loader", "machinery"),
        ("Vibration roller compaction", "machinery"),
        ("Planierraupe", "machinery"),
        # Installed / hired equipment stays equipment - NOT machinery.
        ("Geruest stellen", "equipment"),
        ("Scaffold rental", "equipment"),
        ("Site container hire", "equipment"),
        ("Equipment hire", "equipment"),
        # The other heuristic buckets are unchanged by the split.
        ("Beton C25/30 liefern", "material"),
        ("Bewehrung verlegen", "labor"),
        ("Sonstige Leistungen", "other"),
    ],
)
def test_classify_position_category_splits_machinery(description: str, expected: str) -> None:
    """The description-keyword fallback must emit ``machinery`` for plant, so it
    stays consistent with ``_normalize_resource_category`` and the cost-breakdown
    categories. Plant keywords are checked before the broader equipment list."""
    assert _classify(description) == expected


def test_classify_machinery_distinct_from_equipment() -> None:
    """A crane is machinery; a scaffold is equipment - never the same bucket."""
    assert _classify("Turmdrehkran") == "machinery"
    assert _classify("Geruest") == "equipment"
    assert _classify("Turmdrehkran") != _classify("Geruest")


def test_cascade_base_mapping_sees_machinery_total() -> None:
    """End-to-end intent: a breakdown that now emits a ``machinery`` total feeds
    a non-zero machinery base, an un-inflated equipment base, and a full SMR
    composite under the UZ/railway cascade mapping. Previously machinery was 0
    and equipment absorbed it."""
    # Totals as the fixed breakdown now reports them (machinery separate).
    totals = {
        "labor": Decimal("100"),
        "machinery": Decimal("40"),
        "material": Decimal("200"),
        "equipment": Decimal("75"),
    }
    bases = resolve_bases(_CASCADE_BASE_MAPPING, totals)
    assert bases["machinery"] == Decimal("40")  # not zero
    assert bases["equipment"] == Decimal("75")  # not inflated by machinery
    assert bases["materials"] == Decimal("200")  # token "materials" <- type "material"

    # A composite sums resolved BASE TOKENS (not raw resource types): the cascade
    # engine computes SMR = labor + machinery + materials over ``bases``.
    smr = sum((bases[tok] for tok in _SMR_COMPOSITE["SMR"]), Decimal(0))
    assert smr == Decimal("340")
