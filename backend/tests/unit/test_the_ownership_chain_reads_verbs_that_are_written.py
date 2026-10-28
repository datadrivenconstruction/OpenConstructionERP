# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The ownership chain reads two activity-log verbs. Something must write them.

Two services reconstruct who held a change record and when, and both do it by
selecting activity rows whose ``action`` is one of two verbs. Each declares
those verbs as its own private constant, and each says in a comment that they
are kept in sync with the write side. ``core/audit_log.py`` makes the same
claim from the other end: "it must match on both the write and the read side."
Three claims, no mechanism.

The failure is silent and it is in a feature whose whole point is evidence. If
a writer stops emitting one of these verbs - renamed in a refactor, or a new
change family that never learned to write it - the select simply matches fewer
rows. No exception, no empty-result branch, no log line. The chain comes back
shorter, the provability score comes back lower, and both look like a record
that was genuinely never handed off. A claim that cannot be disproved by its
own history is exactly what a claims-evidence module must not produce.

Two things are checked, because the claim has two halves. The hand-off verb has
a real source of truth in core and the readers merely copy it, so that half is
an equality. The status verb has no constant anywhere - it is a bare literal at
roughly forty write sites - so that half is checked per module, against the
three services whose records the chain actually resolves.

The limit is written down rather than left to be discovered: a verb renamed at
every write site in one module fails here, and a verb renamed at one of that
module's several write sites does not. The per-module granularity is chosen
because that is the granularity at which the damage appears - one change
family quietly losing its status segments while the others keep theirs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core import audit_log
from app.modules.change_intelligence import service as change_intelligence_service
from app.modules.claims_evidence import provability_service

#: The two modules that read the chain back, and the private constants each
#: uses. Both are listed because they are siblings making the same claim: a
#: gate that checked one would be blind to the other drifting, and two
#: features that reconstruct the same chain must not disagree about what they
#: are reconstructing it from.
READERS = {
    "change_intelligence.service": change_intelligence_service,
    "claims_evidence.provability_service": provability_service,
}

#: The services whose records the chain resolves. Every one of them has to
#: write both verbs, because the chain is only as complete as the family it is
#: asked about.
WRITERS = (
    "app/modules/changeorders/service.py",
    "app/modules/variations/service.py",
    "app/modules/moc/service.py",
)

_ACTION_LITERAL = re.compile(r"""action=["'](?P<verb>[a-z_]+)["']""")
_HANDOFF_CALL = re.compile(r"\blog_ownership_handoff\s*\(")


def _source(relative: str) -> str:
    return (Path(audit_log.__file__).parents[2] / relative).read_text(encoding="utf-8")


def _verbs_written_in(relative: str) -> set[str]:
    """Every ``action="..."`` literal in one service's source."""
    return {m.group("verb") for m in _ACTION_LITERAL.finditer(_source(relative))}


def test_both_readers_copy_the_handoff_verb_from_core_rather_than_from_memory() -> None:
    """The half of the claim that has a source of truth to check against.

    ``ACTION_OWNERSHIP_HANDOFF`` in core is what ``log_ownership_handoff``
    writes, so a reader whose private copy has drifted reads nothing at all
    for that verb - not fewer rows, none - and every chain it builds loses its
    hand-off segments while keeping its status ones.
    """
    for name, module in READERS.items():
        copied = module._ACTION_OWNERSHIP_HANDOFF
        assert copied == audit_log.ACTION_OWNERSHIP_HANDOFF, (
            f"{name} reads back {copied!r} while log_ownership_handoff writes "
            f"{audit_log.ACTION_OWNERSHIP_HANDOFF!r}. Nothing matches, so every ownership "
            "chain that module builds silently loses its hand-off segments."
        )


def test_the_two_readers_agree_with_each_other_about_both_verbs() -> None:
    """Siblings reconstructing the same chain must reconstruct it from the same rows.

    If these two ever disagree, the ownership view and the provability score
    are built from different populations, and the disagreement shows up as two
    features quietly telling a user different histories of the same record.
    """
    names = ("_ACTION_OWNERSHIP_HANDOFF", "_ACTION_STATUS_CHANGED")
    for constant in names:
        values = {name: getattr(module, constant) for name, module in READERS.items()}
        assert len(set(values.values())) == 1, (
            f"the two readers disagree about {constant}: {values}. They select from the same "
            "table for the same records, so one of them is reading rows the other cannot see."
        )


@pytest.mark.parametrize("relative", WRITERS)
def test_every_change_family_writes_the_status_verb_the_chain_reads(relative: str) -> None:
    """Each service the chain resolves must emit the status verb it looks for.

    Checked against the source rather than against a constant because there is
    no constant: ``status_changed`` is a bare literal at every write site in
    the platform. That is the finding as much as the check is - the verb the
    chain depends on is spelled out by hand roughly forty times and typed
    nowhere.
    """
    wanted = change_intelligence_service._ACTION_STATUS_CHANGED
    written = _verbs_written_in(relative)

    assert written, (
        f"no action= literal found in {relative} at all. Either the audit call was "
        "restructured or the file moved; this check is now reading nothing, which is the "
        "vacuous pass it exists to prevent."
    )
    assert wanted in written, (
        f"{relative} writes {sorted(written)} and the ownership chain selects on {wanted!r}. "
        f"Records of that family keep their hand-off segments and silently lose their status "
        f"ones, which reads as a change that nobody ever moved."
    )


@pytest.mark.parametrize("relative", WRITERS)
def test_every_change_family_records_a_handoff_at_all(relative: str) -> None:
    """A family that never calls the writer has an empty chain by construction.

    This is the case the synthesis in ``build_ownership_chain_for`` papers
    over: with no hand-off rows it invents a single open segment from the
    record itself, so a family that stopped recording hand-offs still returns
    a plausible-looking chain of exactly one holder.
    """
    assert _HANDOFF_CALL.search(_source(relative)), (
        f"{relative} never calls log_ownership_handoff, so records of that family have no "
        "hand-off rows. The chain will synthesize a single open segment from the record "
        "itself, which looks like a change assigned once and never passed on."
    )
