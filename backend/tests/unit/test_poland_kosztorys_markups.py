"""A Polish detailed estimate puts each narzut on its own component base.

In the kalkulacja szczegolowa Kz (koszty zakupu) is taken on materials, Kp
(koszty posrednie) on labour and equipment, and Z (zysk) on labour, equipment
and Kp, then VAT on the lot. The bill stack and the flat methodology both used
to put the overhead on the whole direct cost, materials included, and the
methodology literal carried a second set of figures (12 and 8) that the bill
did not use.

The distinguishing case is a change in materials: under the Polish method it
moves Kz and VAT and leaves Kp and Z where they were. Under the old direct-cost
base it moved Kp too.

Also pinned here: Poland classifies its lines against KNR, the key the
``poland`` rule set reads.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.classification_registry import (
    CLASSIFICATION_STANDARD_LABELS,
    KNOWN_CLASSIFICATION_STANDARDS,
    classification_order,
    resolve_standard,
)
from app.modules.boq.markup_templates import (
    DEFAULT_MARKUP_TEMPLATES,
    PL_KOSZTORYS_NARZUTY,
    PL_KOSZTORYS_REVIEW_STATUS,
)
from app.modules.methodology.cascade import compute_cascade
from app.modules.methodology.templates import (
    TEMPLATES,
    build_cascade_spec_from_template,
    get_template,
)

_SLUG = "poland_kosztorys"


def _amounts(bases: dict[str, Decimal]) -> dict[str, Decimal]:
    result = compute_cascade(build_cascade_spec_from_template(_SLUG), bases)
    return {line.key: line.amount for line in result.steps}


def _position(*, r: str, m: str, s: str) -> dict[str, Decimal]:
    return {"R": Decimal(r), "M": Decimal(m), "S": Decimal(s), "podwykonawstwo": Decimal("0")}


def test_each_narzut_sits_on_its_own_component_base() -> None:
    """R = 100, M = 200, S = 50: Kz 6 % of M, Kp 65 % of R + S, Z 11 % of R + S + Kp."""
    amounts = _amounts(_position(r="100", m="200", s="50"))
    assert amounts["kz"] == Decimal("12.00")  # 0.06 * 200
    assert amounts["kp"] == Decimal("97.50")  # 0.65 * (100 + 50)
    assert amounts["z"] == Decimal("27.23")  # 0.11 * (100 + 50 + 97.50) = 27.225
    # VAT 23 % on R + M + S + Kz + Kp + Z = 486.73
    assert amounts["vat"] == Decimal("111.95")


def test_materials_move_kz_and_not_kp() -> None:
    """The case the old direct-cost base got wrong: Kp must not see materials."""
    low = _amounts(_position(r="100", m="200", s="50"))
    high = _amounts(_position(r="100", m="800", s="50"))
    assert high["kp"] == low["kp"]
    assert high["z"] == low["z"]
    assert high["kz"] == Decimal("48.00")
    assert high["kz"] != low["kz"]


def test_labour_moves_kp_and_z() -> None:
    """The mirror case: more labour raises Kp and with it Z, and leaves Kz alone."""
    low = _amounts(_position(r="100", m="200", s="50"))
    high = _amounts(_position(r="200", m="200", s="50"))
    assert high["kp"] == Decimal("162.50")  # 0.65 * 250
    assert high["z"] > low["z"]
    assert high["kz"] == low["kz"]


def test_subcontracted_work_carries_vat_and_no_narzut() -> None:
    amounts = _amounts({"R": Decimal("0"), "M": Decimal("0"), "S": Decimal("0"), "podwykonawstwo": Decimal("1000")})
    assert amounts["kz"] == amounts["kp"] == amounts["z"] == Decimal("0.00")
    assert amounts["vat"] == Decimal("230.00")


def test_the_template_reads_its_rates_from_the_one_block() -> None:
    """No rate is written in the methodology; it is the PL narzuty block and the PL bill VAT."""
    steps = {step["key"]: step for step in get_template(_SLUG)["cascade_steps"]}
    for narzut in PL_KOSZTORYS_NARZUTY:
        step = steps[str(narzut["key"])]
        assert Decimal(step["rate"]) == Decimal(str(narzut["percentage"]))
        assert step["base"] == list(narzut["base"])  # type: ignore[call-overload]
        assert step["label"] == narzut["name"]
    bill_vat = next(ln for ln in DEFAULT_MARKUP_TEMPLATES["PL"] if ln["category"] == "tax")
    assert Decimal(steps["vat"]["rate"]) == Decimal(str(bill_vat["percentage"]))


def test_the_unconfirmed_rates_say_so() -> None:
    """The Sekocenbud averages were not read from a source and travel with that flag."""
    template = get_template(_SLUG)
    assert PL_KOSZTORYS_REVIEW_STATUS == "needs_expert_review"
    assert template["review_status"] == PL_KOSZTORYS_REVIEW_STATUS
    assert "Kz" in template["description"]


def test_the_flat_poland_template_has_no_figures_of_its_own() -> None:
    """The contradiction that was reported: methodology 12 / 8 against the bill's 18 / 8.

    The shipped ``poland`` template is the bill stack, line for line, so a
    Polish project priced on the bill and on the flat methodology comes to the
    same money.
    """
    template = get_template("poland")
    assert template["derived_from_region"] == "PL"
    bill = DEFAULT_MARKUP_TEMPLATES["PL"]
    assert [step["label"] for step in template["cascade_steps"]] == [ln["name"] for ln in bill]
    assert [Decimal(step["rate"]) for step in template["cascade_steps"]] == [
        Decimal(str(ln["percentage"])) for ln in bill
    ]


def test_there_is_one_polish_detailed_template() -> None:
    polish = [tpl["slug"] for tpl in TEMPLATES if tpl.get("country_code") == "PL"]
    assert sorted(polish) == ["poland", "poland_kosztorys"]


# ── Classification ──────────────────────────────────────────────────────────


def test_poland_classifies_against_knr() -> None:
    resolved = resolve_standard(None, "PL")
    assert resolved.standard == "knr"
    assert resolved.matched
    assert resolve_standard(None, "PL_WARSAW").standard == "knr"
    assert "knr" in KNOWN_CLASSIFICATION_STANDARDS
    assert CLASSIFICATION_STANDARD_LABELS["knr"] == "KNR"


def test_a_line_without_a_knr_code_still_has_din276_next() -> None:
    """A catalogue item coded only by DIN 276 keeps a section path on a Polish project."""
    order = classification_order(None, "PL")
    assert order[0] == "knr"
    assert order[1] == "din276"


def test_other_central_european_countries_did_not_move() -> None:
    for country in ("CZ", "SK", "DE"):
        assert resolve_standard(None, country).standard == "din276"
