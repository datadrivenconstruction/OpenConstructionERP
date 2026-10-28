# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the event-reconciliation API.

There is no money in this module. ``confidence`` is a ratio in ``[0, 1]`` and
is carried on the wire as a plain ``float`` (the field is not money-named, so it
does not trip the money-as-string convention the cost modules follow).
"""

from __future__ import annotations

from pydantic import BaseModel


class ThreadRecordOut(BaseModel):
    """One record in an assembled event thread, projected to a uniform shape.

    The fields mirror the engine's ``CandidateRecord`` so the timeline a caller
    renders is exactly what was scored: ``record_type`` / ``record_id`` identify
    the source row, ``occurred_at`` is its ISO-8601 timestamp (or null when the
    row is undated), and ``refs`` are the tracked codes (``CO-14`` etc.) the
    record carries. ``is_seed`` marks the record the thread was assembled around.
    """

    record_type: str
    record_id: str
    subject: str
    party: str | None
    occurred_at: str | None
    refs: list[str]
    is_seed: bool


class ThreadLinkOut(BaseModel):
    """One scored, explainable correlation inside an event thread.

    Endpoints are the engine's canonical ``(type, id)`` pairs. ``confidence`` is
    the blended score in ``[0, 1]`` and ``reasons`` names every signal that fired
    (``shared_reference`` / ``subject_match`` / ``party_and_date_proximity`` /
    ``embedding_similarity``). ``status`` is the persisted review state -
    ``suggested`` for a link the engine proposed that no one has ruled on yet,
    else ``confirmed`` / ``rejected``. ``link_id`` is the persisted row's id when
    a decision exists, else null (a pure engine suggestion has no row yet).
    """

    link_id: str | None
    left_type: str
    left_id: str
    right_type: str
    right_id: str
    relation: str
    confidence: float
    reasons: list[str]
    status: str


class EventThreadOut(BaseModel):
    """The reconciled cross-channel thread assembled around one seed event.

    ``records`` is the deterministically ordered timeline (by ``occurred_at``,
    then by record identity) of every record connected to the seed through links
    at or above the engine threshold, excluding any link a reviewer has rejected.
    ``links`` are the scored correlations among those records, strongest first.
    ``confirmed_count`` / ``rejected_count`` summarise the persisted decisions
    reflected in the thread.
    """

    project_id: str
    event_key: str
    seed_type: str | None
    seed_id: str | None
    records: list[ThreadRecordOut]
    links: list[ThreadLinkOut]
    confirmed_count: int
    rejected_count: int


class RecordLinkDecisionIn(BaseModel):
    """Request to persist a confirm / reject decision on a correlation.

    Identifies the link by its canonical endpoints (the same ``(type, id)``
    pairs the thread view returns) and the ``relation``; the endpoints are
    re-canonicalised server-side so either argument order resolves to the one
    undirected link. ``status`` must be ``confirmed`` or ``rejected``.
    ``confidence`` is optional context (the engine score at decision time);
    when omitted the persisted row keeps 0 unless a prior row already had one.
    """

    left_type: str = ""
    left_id: str = ""
    right_type: str = ""
    right_id: str = ""
    relation: str = "same_event"
    status: str = "confirmed"
    confidence: float | None = None


class RecordLinkOut(BaseModel):
    """A persisted record-link decision, confidence as a plain float ratio.

    ``left_subject`` / ``right_subject`` say what the two endpoints are, so the
    decision log reads as a list of decisions rather than a list of ids. They
    are resolved here because a decision outlives the thread it was taken in:
    the page showing the log is rarely the page holding those two records, so
    the client has nothing to look the subject up in. A subject is ``None``
    when the source record has since been deleted, and the endpoint id is on
    the wire either way.
    """

    id: str
    project_id: str
    left_type: str
    left_id: str
    left_subject: str | None = None
    right_type: str
    right_id: str
    right_subject: str | None = None
    relation: str
    confidence: float
    status: str
    created_by: str | None
