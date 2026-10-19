# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A readiness message names its proof by title or evidence type, never by a raw id."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.quality_concept import validators
from app.modules.quality_concept.messages import is_key_present

UUID = "1f820821-aaaa-bbbb-cccc-000000000001"


async def _message(locale: str, **params: str) -> str:
    ctx = ValidationContext(
        data={"evidence": [{"code": "placed_quantity_missing", "ref": UUID, "params": params}]},
        metadata={"locale": locale},
    )
    (result,) = await validators.ProofQuantityKnown().validate(ctx)
    return result.message


@pytest.mark.asyncio
async def test_untitled_proof_is_named_by_evidence_type_and_package_in_german() -> None:
    msg = await _message("de", evidence_type="concrete_conformity_tests", package="BA-1")
    assert "Konformitätsprüfungen Beton (BA-1)" in msg
    assert UUID not in msg


@pytest.mark.asyncio
async def test_untitled_proof_falls_back_to_english_for_other_locales() -> None:
    msg = await _message("fr", evidence_type="weld_inspection", package="")
    assert "Weld inspection" in msg
    assert UUID not in msg and "{" not in msg


@pytest.mark.asyncio
async def test_unknown_evidence_type_is_humanised_not_raw() -> None:
    msg = await _message("en", evidence_type="custom_site_check", package="P2")
    assert "Custom site check (P2)" in msg


@pytest.mark.asyncio
async def test_title_wins_over_evidence_type() -> None:
    msg = await _message("de", label="Betonprüfung Decke", evidence_type="weld_inspection", package="P2")
    assert "Betonprüfung Decke" in msg and "Schweißnahtprüfung" not in msg


@pytest.mark.asyncio
async def test_without_any_name_the_ref_still_shows() -> None:
    assert UUID in await _message("en")


def test_every_shipped_evidence_type_has_a_name_in_en_and_de() -> None:
    root = Path(validators.__file__).parent
    codes = {e["code"] for e in json.loads((root / "catalogues" / "neutral.json").read_text("utf8"))["evidence_types"]}
    assert codes
    for code in codes:
        for loc in ("en", "de"):
            assert is_key_present(f"quality_concept.evidence_type.{code}", loc), (code, loc)
