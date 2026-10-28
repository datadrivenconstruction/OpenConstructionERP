# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Characterisation tests for the unit the GAEB importer invents.

``gaeb_xml.py`` normalises a missing ``<QU>`` into a guessed unit::

    unit = _normalize_unit(unit_raw) or ("lsum" if (qty_dec is None and it_dec is not None) else "pcs")

An X84 item cannot carry ``QU`` (the unit lives on the paired X83), so on that
phase the guess always fires. Nothing downstream can tell a guessed unit from a
stated one - the only trace is ``metadata["gaeb_unit_original"]``, which the
importer alone writes.

These tests pin TODAY'S behaviour, including the constraints that make the
guess load-bearing rather than cosmetic. They are deliberately not aspirational:
each one asserts what the code does now, so that a later change to the guess has
to state which of these facts it is changing and why.
"""

from __future__ import annotations

import uuid
from collections import Counter
from pathlib import Path

import pytest

from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gaeb"
_X83 = _FIXTURES / "oce_conformance_x83.x83"
_X84 = _FIXTURES / "oce_conformance_x84.x84"

_DESC = (
    b"<Description><CompleteText><DetailTxt><Text><p><span>Putz</span>"
    b"</p></Text></DetailTxt></CompleteText></Description>"
)


def _synthetic(dp: bytes, item_body: bytes) -> bytes:
    """Build a minimal single-item GAEB document for the given DP phase."""
    head = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA' + dp + b'/3.3">'
        b"<GAEBInfo><Version>3.3</Version></GAEBInfo><Award><DP>" + dp + b"</DP>"
        b"<AwardInfo><Cur>EUR</Cur></AwardInfo>"
        b'<BoQ ID="idBoQ"><BoQInfo><Name>LV</Name></BoQInfo><BoQBody><Itemlist>'
    )
    tail = b"</Itemlist></BoQBody></BoQ></Award></GAEB>"
    return head + b'<Item ID="idI1" RNoPart="0010">' + item_body + b"</Item>" + tail


async def _items(payload: bytes) -> list:
    result = await GAEBXMLImporter.parse(payload)
    return [p for p in result.positions if not p.is_section]


# ── Which branch the shipped fixtures take ────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(not _X84.exists(), reason="X84 conformance fixture not present")
async def test_x84_fixture_invents_a_unit_for_every_position() -> None:
    """Every item of the X84 conformance fixture takes the lump-sum branch.

    The file states no ``QU`` on any item, so ``gaeb_unit_original`` is empty
    for all 27 and the stored ``lsum`` is entirely the importer's guess.
    """
    items = await _items(_X84.read_bytes())
    assert len(items) == 27
    assert dict(Counter(p.unit for p in items)) == {"lsum": 27}
    assert all(p.metadata["gaeb_unit_original"] == "" for p in items)


@pytest.mark.asyncio
@pytest.mark.skipif(not _X83.exists(), reason="X83 conformance fixture not present")
async def test_x83_fixture_never_reaches_the_fallback() -> None:
    """The X83 conformance fixture states a ``QU`` on every item.

    Its units are therefore facts from the file, not guesses - which is why no
    X83 fixture exercises either branch of the fallback.
    """
    items = await _items(_X83.read_bytes())
    assert len(items) == 27
    assert all(p.metadata["gaeb_unit_original"] != "" for p in items)


# ── Both branches of the fallback, including the one no fixture covers ────


@pytest.mark.asyncio
async def test_lump_sum_branch_no_quantity_with_a_total() -> None:
    """No ``Qty`` plus an ``IT`` yields ``lsum`` - the shape a real X84 has."""
    items = await _items(_synthetic(b"84", b"<UP>12.50</UP><IT>125.00</IT>" + _DESC))
    assert [p.unit for p in items] == ["lsum"]
    assert items[0].metadata["gaeb_unit_original"] == ""


@pytest.mark.asyncio
async def test_pieces_branch_fires_whenever_a_quantity_is_present() -> None:
    """A stated ``Qty`` with no ``QU`` yields ``pcs`` on the priced phase.

    This is the branch no shipped fixture reaches. It is not X84-specific: the
    fallback is not gated on the exchange phase at all.
    """
    items = await _items(_synthetic(b"84", b"<Qty>10.000</Qty><UP>12.50</UP><IT>125.00</IT>" + _DESC))
    assert [p.unit for p in items] == ["pcs"]
    assert items[0].metadata["gaeb_unit_original"] == ""
    assert items[0].quantity == 10.0


@pytest.mark.asyncio
async def test_pieces_branch_is_reachable_on_an_unpriced_phase_too() -> None:
    """An X83 item that omits ``QU`` also gets the invented ``pcs``."""
    items = await _items(_synthetic(b"83", b"<Qty>10.000</Qty>" + _DESC))
    assert [p.unit for p in items] == ["pcs"]
    assert items[0].metadata["gaeb_unit_original"] == ""


@pytest.mark.asyncio
async def test_a_stated_unit_is_never_overwritten() -> None:
    """The fallback only fires when the file states nothing - the invariant."""
    items = await _items(_synthetic(b"83", b"<Qty>10.000</Qty><QU>m2</QU>" + _DESC))
    assert [p.unit for p in items] == ["m2"]
    assert items[0].metadata["gaeb_unit_original"] == "m2"


@pytest.mark.asyncio
async def test_gaeb_unit_original_is_the_only_trace_of_the_guess() -> None:
    """A guessed and a stated ``lsum`` differ in exactly one field.

    ``psch`` normalises to ``lsum``, so a file that states it and a file that
    states nothing produce the same stored unit. Only ``gaeb_unit_original``
    separates them, which is what makes every other reader unable to tell.
    """
    stated = (await _items(_synthetic(b"83", b"<Qty>1.000</Qty><QU>psch</QU>" + _DESC)))[0]
    guessed = (await _items(_synthetic(b"84", b"<UP>12.50</UP><IT>125.00</IT>" + _DESC)))[0]
    assert stated.unit == guessed.unit == "lsum"
    assert stated.metadata["gaeb_unit_original"] == "psch"
    assert guessed.metadata["gaeb_unit_original"] == ""


# ── Why the guess cannot simply be dropped ────────────────────────────────


@pytest.mark.parametrize("absent", ["", None])
def test_the_position_schema_refuses_an_absent_unit(absent: str | None) -> None:
    """``PositionCreate`` rejects both empty and missing units.

    The importer's rows reach the database through this schema, so leaving the
    unit genuinely absent at the normalisation point cannot be a one-line
    change: the row would never persist.
    """
    from pydantic import ValidationError

    from app.modules.boq.schemas import PositionCreate

    with pytest.raises(ValidationError):
        PositionCreate(
            boq_id=uuid.uuid4(),
            ordinal="0010",
            description="Putz",
            unit=absent,
            quantity=1.0,
        )


def test_normalise_unit_rejects_the_empty_string() -> None:
    """The shared normaliser is the layer that refuses it."""
    from app.modules.boq.units import normalise_unit

    assert normalise_unit("") is None
    assert normalise_unit(None) is None
    assert normalise_unit("lsum") == "lsum"


def test_an_empty_unit_is_the_platform_sentinel_for_a_section() -> None:
    """An empty unit already means "section header" to the backend.

    ``_is_section`` reads an empty unit plus a zero quantity and rate as a
    section. A declined X84 position has exactly that shape, so an absent unit
    would silently reclassify it. The frontend twin
    (``features/boq/api.ts`` ``isSection``) applies the same rule WITHOUT the
    zero-quantity condition, which is pinned in ``BOQEditorPage.test.tsx``.
    """
    from app.modules.boq.service import _is_section

    class _Row:
        def __init__(self, unit: str, quantity: float, unit_rate: float) -> None:
            self.unit = unit
            self.quantity = quantity
            self.unit_rate = unit_rate

    # An absent unit on an unpriced line reads as a section header today.
    assert _is_section(_Row("", 0.0, 0.0)) is True
    # The invented units do not, which is what the guess is currently buying.
    assert _is_section(_Row("lsum", 0.0, 0.0)) is False
    assert _is_section(_Row("pcs", 0.0, 0.0)) is False
    # A priced line is never a section whatever its unit says.
    assert _is_section(_Row("", 10.0, 5.0)) is False
