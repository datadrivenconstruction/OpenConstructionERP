# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Permits lifecycles (table driven), shipped catalogues and their wiring into module 1."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.core.fsm import FSMError
from app.modules.permits.catalogue import (
    CATALOGUE_DIR,
    PERMIT_TYPE_KIND,
    PermitTypeCatalogue,
    default_catalogue_id,
    merged,
    shipped_catalogues,
    validate_permit_type_catalogue,
)
from app.modules.permits.fsm import APPLICATION_FSM, CONDITION_FSM, PERMIT_FSM

APPLICATION_TABLE = [
    ("planned", "preparing", True),
    ("preparing", "submitted", True),
    ("preparing", "internal_review", True),
    ("internal_review", "submitted", True),
    ("submitted", "validated", True),
    ("validated", "under_review", True),
    ("under_review", "info_requested", True),
    ("info_requested", "under_review", True),
    ("under_review", "decided", True),
    ("planned", "submitted", False),
    ("planned", "decided", False),
    ("decided", "under_review", False),
    ("withdrawn", "preparing", False),
    ("decided", "withdrawn", False),
]
CONDITION_TABLE = [
    ("open", "evidence_submitted", True),
    ("evidence_submitted", "discharged", True),
    ("open", "discharge_applied", True),
    ("discharge_applied", "discharged", True),
    ("discharge_applied", "open", True),
    ("open", "in_compliance", True),
    ("in_compliance", "breach", True),
    ("breach", "in_compliance", True),
    ("discharged", "superseded", True),
    ("breach", "discharged", False),
    ("waived", "open", False),
    ("superseded", "open", False),
    ("discharged", "open", False),
]
PERMIT_TABLE = [
    ("in_force", "suspended", True),
    ("suspended", "in_force", True),
    ("in_force", "lapsed", True),
    ("lapsed", "in_force", True),
    ("in_force", "superseded", True),
    ("revoked", "in_force", False),
    ("superseded", "in_force", False),
]


@pytest.mark.parametrize(
    ("fsm", "src", "dst", "ok"),
    [(APPLICATION_FSM, *r) for r in APPLICATION_TABLE]
    + [(CONDITION_FSM, *r) for r in CONDITION_TABLE]
    + [(PERMIT_FSM, *r) for r in PERMIT_TABLE],
)
def test_lifecycles(fsm, src: str, dst: str, ok: bool) -> None:
    if ok:
        fsm.validate(src, dst)
    else:
        with pytest.raises(FSMError):
            fsm.validate(src, dst)


# ── catalogues ─────────────────────────────────────────────────────────────


def test_every_shipped_file_validates_and_resolves_its_parent() -> None:
    files = sorted(CATALOGUE_DIR.glob("*.json"))
    cats = shipped_catalogues()
    assert len(files) == len(cats) >= 6
    for cid in ("neutral", "de", "de_nw", "de_bw", "uk_england", "uk_wales", "us_ibc"):
        assert cid in cats
    for c in cats.values():
        m = merged(c, cats.__getitem__)
        assert m.permit_types, c.id


def test_every_statutory_figure_has_url_and_review_status() -> None:
    for c in shipped_catalogues().values():
        for t in c.permit_types:
            if t.clock.period is not None:
                assert t.clock.source_url and t.clock.review_status is not None, (c.id, t.code)
            if t.validity is not None:
                assert t.validity.source_url and t.validity.review_status is not None, (c.id, t.code)


def test_verified_figures_are_only_the_ones_read_on_the_primary_source() -> None:
    cats = shipped_catalogues()
    assert str(cats["de"].type_map()["bimschg_genehmigung"].clock.review_status) == "verified"
    assert str(cats["uk_england"].type_map()["full_planning_permission"].validity.review_status) == "verified"
    # Land building law and the MBO fallback are not verified yet.
    assert str(cats["de_nw"].type_map()["baugenehmigung"].validity.review_status) == "unconfirmed"
    assert str(cats["de"].type_map()["baugenehmigung"].validity.review_status) == "unconfirmed"
    # US ships no invented periods (lead decision g).
    for t in merged(cats["us_ibc"], cats.__getitem__).permit_types:
        assert t.clock.period is None and t.validity is None


def test_a_period_without_source_is_refused() -> None:
    raw = json.loads((CATALOGUE_DIR / "neutral.json").read_text(encoding="utf-8"))
    raw["permit_types"][0]["clock"] = {"period": 8, "unit": "weeks"}
    errors = validate_permit_type_catalogue(PermitTypeCatalogue.model_validate(raw), "tenant")
    assert any(e.startswith("statutory_figure_without_source") for e in errors)
    raw["permit_types"][0]["triggered_by_route"] = ["no_such_route"]
    errors = validate_permit_type_catalogue(PermitTypeCatalogue.model_validate(raw), "tenant")
    assert any(e.startswith("unknown_route") for e in errors)


def test_shipped_labels_are_i18n_keys() -> None:
    for c in shipped_catalogues().values():
        assert c.name_key.startswith("permits.")
        for t in c.permit_types:
            assert t.name_key.startswith("permits.type.")


def test_route_codes_are_project_route_options() -> None:
    from app.modules.project_route.schemas import ROUTE_OPTIONS

    for c in shipped_catalogues().values():
        for t in c.permit_types:
            assert set(t.triggered_by_route) <= set(ROUTE_OPTIONS), (c.id, t.code)


def test_kind_is_registered_with_module_one() -> None:
    from app.modules.permits.catalogue import register_kind
    from app.modules.project_governance.catalogue_kinds import catalogue_kinds, get_catalogue_kind

    register_kind()
    assert PERMIT_TYPE_KIND in catalogue_kinds()
    assert {c.id for c in get_catalogue_kind(PERMIT_TYPE_KIND).shipped()} == set(shipped_catalogues())


def test_default_catalogue_per_jurisdiction() -> None:
    assert default_catalogue_id("DE", "DE-NW") == "de_nw"
    assert default_catalogue_id("DE", None) == "de"
    assert default_catalogue_id("GB", "GB-WLS") == "uk_wales"
    assert default_catalogue_id("FR", None) == "neutral"
    assert default_catalogue_id(None, None) == "neutral"


def test_land_overlay_replaces_the_federal_type_by_code() -> None:
    cats = shipped_catalogues()
    nw = {t.code: t for t in merged(cats["de_nw"], cats.__getitem__).permit_types}
    assert nw["baugenehmigung"].validity.source_url.startswith("https://lexmea.de/")
    assert "bimschg_genehmigung" in nw


def test_no_phase_or_area_code_of_a_governance_model_is_written_into_the_module() -> None:
    """Review finding 1: hosting comes from catalogue tags, so no shipped model's codes appear in the code."""

    import app.modules.permits as pkg

    root = Path(pkg.__file__).resolve().parents[1] / "project_governance" / "catalogues"
    codes: set[str] = set()
    documents: set[str] = set()
    for path in root.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        codes |= {a["code"] for a in data.get("areas", []) if len(a["code"]) > 1}
        documents |= {d["code"] for d in data.get("document_types", [])}
        codes |= {p["code"] for p in data.get("phases", []) if re.search(r"\d", p["code"])}
    assert codes and documents
    # Area and phase codes are ordinary words in some models, so they are searched only where
    # the governance model is read; a document type code is distinctive everywhere.
    for name, wanted in (
        ("hosting.py", codes | documents),
        ("evidence.py", codes | documents),
        ("service.py", documents),
        ("router.py", documents),
        ("seed.py", documents),
        ("public.py", documents),
    ):
        src = (Path(pkg.__file__).parent / name).read_text(encoding="utf-8")
        found = sorted(c for c in wanted if re.search(rf'"{re.escape(c)}"', src))
        assert found == [], (name, found)
