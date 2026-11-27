# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Value bands: who else approves a requisition once its value crosses a threshold.

A project may set, in one currency, a list of bands. Each band names the amount
it starts at and the approvers it adds. When a requisition is submitted its
value (the sum of its priced lines) decides which bands apply: every band whose
start is at or below the value. Their approvers are appended, lowest band
first, after the requisition's own designated approvers, so a site buyer signs
first, the project manager next and the director last.

Worked example: bands ``5 000 EUR -> [PM]`` and ``50 000 EUR -> [Director]``.
A requisition of 6 818.70 EUR with no approvers of its own goes to the PM only;
one of 72 000 EUR goes to the PM, then the Director; one of 4 999.99 EUR keeps
the one-step approval. Neither the requester nor the submitter approves their
own requisition, so they are left out of a band; a band that then has nobody
left is refused.

Pure: plain values in, plain values out. The service stores the result.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

#: At most this many bands per project, and approvers per band.
MAX_BANDS = 6
MAX_BAND_APPROVERS = 5


class BandError(ValueError):
    """A band list that cannot be routed on. ``code`` names the reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Band:
    """One threshold: from ``from_amount`` (inclusive) these approvers also sign."""

    from_amount: Decimal
    approvers: tuple[str, ...]


@dataclass(frozen=True)
class BandedChain:
    """The approval chain a value produced, and which band put each extra approver there."""

    chain: list[str]
    added: dict[str, str] = field(default_factory=dict)
    applied: list[str] = field(default_factory=list)
    unmet: list[str] = field(default_factory=list)


def _amount(raw: Any) -> Decimal:
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise BandError("band_amount_invalid", f"Band start {raw!r} is not a number.") from None
    if not value.is_finite():
        raise BandError("band_amount_invalid", f"Band start {raw!r} is not a number.")
    return value


def parse_bands(raw: Iterable[Mapping[str, Any]] | None) -> list[Band]:
    """Bands as stored, refusing a list that would route ambiguously.

    Starts must be positive and strictly ascending, each band names one to
    :data:`MAX_BAND_APPROVERS` approvers, and nobody appears in two bands.
    """
    bands: list[Band] = []
    seen: set[str] = set()
    for entry in raw or []:
        start = _amount(entry.get("from_amount"))
        if start <= 0:
            raise BandError("band_amount_not_positive", "Each band must start above zero.")
        approvers = tuple(str(a) for a in (entry.get("approvers") or []))
        if not approvers or len(approvers) > MAX_BAND_APPROVERS:
            raise BandError(
                "band_approvers_count",
                f"Each band needs between 1 and {MAX_BAND_APPROVERS} approvers.",
            )
        if len(set(approvers)) != len(approvers) or seen & set(approvers):
            raise BandError("band_approver_repeated", "An approver may appear in only one band, once.")
        seen.update(approvers)
        if bands and start <= bands[-1].from_amount:
            raise BandError("band_amounts_not_ascending", "Band starts must rise from one band to the next.")
        bands.append(Band(from_amount=start, approvers=approvers))
    if len(bands) > MAX_BANDS:
        raise BandError("band_count", f"At most {MAX_BANDS} bands per project.")
    return bands


def requisition_value(extended_costs: Iterable[Any]) -> Decimal:
    """The value a requisition is routed on: the sum of its line amounts, unpriced lines as zero."""
    total = Decimal("0")
    for raw in extended_costs:
        try:
            total += Decimal(str(raw if raw not in (None, "") else "0"))
        except (InvalidOperation, ValueError, TypeError):
            continue
    return total


def banded_chain(
    base: Sequence[str],
    bands: Sequence[Band],
    value: Decimal,
    *,
    excluded: Collection[str] = (),
) -> BandedChain:
    """Append the approvers of every band ``value`` reaches to ``base``.

    ``added`` maps each appended approver to the start of the band that brought
    them; ``applied`` lists the starts of the bands reached; ``unmet`` the starts
    of bands that have no approver left once ``excluded`` (the requester and the
    submitter, who never approve their own requisition) is left out.
    """
    chain = [str(a) for a in base]
    added: dict[str, str] = {}
    applied: list[str] = []
    unmet: list[str] = []
    for band in bands:
        if value < band.from_amount:
            continue
        start = format(band.from_amount, "f")
        applied.append(start)
        eligible = [a for a in band.approvers if a not in excluded]
        if not eligible:
            unmet.append(start)
            continue
        for approver in eligible:
            if approver not in chain:
                chain.append(approver)
                added[approver] = start
    return BandedChain(chain=chain, added=added, applied=applied, unmet=unmet)
