# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic response schemas for the claims evidence-pack API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EvidenceEntryOut(BaseModel):
    """One source record in the evidence pack."""

    model_config = ConfigDict(from_attributes=True)

    ref_id: str
    source_module: str
    kind: str
    title: str
    occurred_at: str | None
    actor_id: str | None
    summary: str


class EvidenceSectionOut(BaseModel):
    """A named, ordered group of evidence entries."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    entries: list[EvidenceEntryOut]


class EvidencePackOut(BaseModel):
    """The assembled, deterministic evidence pack."""

    model_config = ConfigDict(from_attributes=True)

    subject_ref: str
    basis: str
    entry_count: int
    date_from: str | None
    date_to: str | None
    sections: list[EvidenceSectionOut]
    content_digest: str


# --------------------------------------------------------------------------- #
# Provability score (#6): how strong is the contemporaneous record behind one
# change / claim, graded from the evidence signals already on the project, with
# a transparent per-signal breakdown so the UI can show exactly what to cure.
# --------------------------------------------------------------------------- #


class ProvabilitySubScoreOut(BaseModel):
    """One weighted signal's contribution to the provability score.

    Mirrors :class:`app.modules.claims_evidence.provability.SubScore`. ``earned``
    is the whole points this signal earned out of ``weight``; ``fraction`` is the
    ``earned / weight`` ratio in ``[0, 1]`` it was derived from. ``present`` is a
    UI convenience flag: ``True`` once the signal is fully satisfied (fraction
    ``1.0``), so a gauge can render a green / amber row without re-deriving it.
    """

    model_config = ConfigDict(from_attributes=True)

    signal: str
    weight: int
    earned: int
    fraction: float
    present: bool


class ProvabilityWeaknessOut(BaseModel):
    """A single named gap that held the provability score below maximum.

    Mirrors :class:`app.modules.claims_evidence.provability.Weakness`. ``token``
    is a stable identifier safe to switch on or localize; ``message`` is the
    human-readable cure; ``signal`` is the weighted signal it belongs to;
    ``points_lost`` is how many points this signal's shortfall cost.
    """

    model_config = ConfigDict(from_attributes=True)

    token: str
    message: str
    signal: str
    points_lost: int


class ProvabilityScoreOut(BaseModel):
    """The graded provability of one change / claim subject.

    ``score`` is an integer 0-100; ``band`` is ``weak`` / ``moderate`` /
    ``strong`` per the engine's documented thresholds; ``sub_scores`` are the
    per-signal contributions (present vs missing) and ``weaknesses`` the ordered
    cure list. ``subject_kind`` / ``subject_id`` / ``subject_ref`` echo the
    resolved change record, and ``entry_count`` / ``date_from`` / ``date_to``
    surface the dated-record span the score was built from.
    """

    model_config = ConfigDict(from_attributes=True)

    subject_kind: str
    subject_id: str
    subject_ref: str
    score: int
    band: str
    sub_scores: list[ProvabilitySubScoreOut]
    weaknesses: list[ProvabilityWeaknessOut]
    entry_count: int
    date_from: str | None
    date_to: str | None
