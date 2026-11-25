# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠How an answer was arrived at, travelling beside the answer.

Wave one of the jurisdiction plan. The product resolves a great many things from
a jurisdiction - working weeks, payment clocks, notice periods, tax rates, phone
and address rules - and until now the resolved value travelled alone. A caller
handed a number could not tell a row written for its own country from a default
that happens to be shaped like one, and several surfaces went further and
stamped the requested country onto an answer produced by the generic rules.

That is the defect this module exists to make unspellable. It is not
instrumentation and not logging: a log is not something a caller can branch on,
and every one of the defects below was already being logged when it shipped.

What it is not
--------------
It is not a wrapper around the value. Wrapping was considered and rejected,
because provenance is per axis rather than per answer, and a single wrapper
keyed on jurisdiction paints an answer green while a second axis is silently
wrong. The tax engine is the worked example: it raises on an unknown
jurisdiction, which is honest, and returns the same bytes for "zero-rated" and
"I have no rate for this date", which is not. One envelope would have called it
covered. So a :class:`Provenance` is a *field beside* the value, and a function
with two axes returns two of them.

The pattern is not invented here either. :func:`app.modules.carbon.
resolve_grid_factor` has shipped it correctly for some time, returning the
country requested, the country used, and an explicit fallback flag, with a
docstring saying why: so a reviewer is never handed a country-specific-looking
number that is really a world average. This module is that pattern given a name,
so that four modules adopting it at once end up with one vocabulary instead of
four.

Why the constructor refuses some combinations
---------------------------------------------
:class:`Provenance` rejects a declaration that contradicts itself, and that is
the whole point of it being a type. ``source=DECLARED`` with ``requested`` and
``used`` differing is precisely the shipped defect where a config endpoint says
"these are Canada's phone rules" about the generic ones; ``source=FALLBACK``
with the two equal is the same lie told the other way. Both raise. A caller can
still write down something false about the world, but it can no longer write
down something the fields themselves disagree about.

Why a fallback must name what answered
--------------------------------------
``source=FALLBACK`` with an empty ``used`` is refused, and it is worth saying
why separately, because it is the one contradiction a careful adopter produces
without trying. ``fell_back(axis, code, table.get(code, ""))`` looks reasonable
and yields a fallback that names nothing as having stood in, while still
reporting :attr:`~Provenance.usable` as true. A caller is then told it may
compute with a value whose origin the record does not carry, which is the exact
condition this module exists to make unspellable. Name the stand-in, even if
only as a token such as ``"INTERNATIONAL"``; and if nothing answered at all,
that is an :attr:`Source.UNAVAILABLE`, not a fallback.

``used`` is descriptive, never a discriminant
---------------------------------------------
Branch on :attr:`Provenance.source`, or on :attr:`~Provenance.answered` for the
boolean. Never on the text of ``used``. The source is an enum defined once in
this file and cannot drift; the stand-in token is per module by design, because
what answered in one module's absence genuinely differs from what answered in
another's. Code reading ``used == "INTERNATIONAL"`` to catch every fallback is
asking the wrong field, and it will miss the fallbacks whose stand-in is
something else.

Which is also why the token is named for the thing that answered and not for
the slot it fills. ``"DEFAULT"`` tells a reader only that the non-default did
not answer, and :attr:`~Provenance.answered` already told them that. A token
naming a permissive digit pattern, a hardcoded Monday-to-Friday week or a
genuine international default carries what the value cannot: the shape of what
the caller is actually holding. The test for a candidate token is whether a
reader who has never opened the module learns something from it; if it would be
equally true of a different stand-in, it is too weak.

The token must also not claim more than the stand-in is. Calling a permissive
pattern ``"INTERNATIONAL"`` would assert an international standard behind a
regex that exists to accept anything, which is the same overclaim this module
refuses everywhere else.

Why UNAVAILABLE is not FALLBACK
-------------------------------
A fallback is an answer: the generic rule applied, and it may well be right. An
unavailable is the absence of one, and the two must never share a code path,
because the failure that motivated this distinction is a holiday calculation
raising, being swallowed into an empty set, and every day of the year becoming a
working day with nothing but a log to say so. "No holidays" and "I could not
work out the holidays" are different, and only one of them is safe to compute
dates from.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Source(StrEnum):
    """Where a resolved value came from, weakest last.

    Ordered deliberately: :func:`weakest` relies on declaration order, so a new
    member must be inserted at its true strength rather than appended.
    """

    #: The caller stated it outright on the entity being resolved.
    DECLARED = "declared"
    #: Inherited from the project the entity belongs to.
    PROJECT = "project"
    #: Inherited from the platform-wide default.
    PLATFORM = "platform"
    #: No row exists for what was asked; an international default answered.
    FALLBACK = "fallback"
    #: No answer at all. A computation failed, or a registry could not be read.
    #: Never a value a caller may compute with.
    UNAVAILABLE = "unavailable"


#: Sources that mean a real row was found for what the caller asked about.
_ANSWERED_ON_ITS_OWN_TERMS = frozenset({Source.DECLARED, Source.PROJECT, Source.PLATFORM})


@dataclass(frozen=True, slots=True)
class Provenance:
    """How one axis of an answer was resolved.

    Args:
        axis: What this describes, as a stable token - ``"jurisdiction"``,
            ``"effective_date"``, ``"language"``, ``"currency"``. Free text
            rather than an enum because modules own their own axes and the core
            holds only the question; a closed set here would mean editing core
            to add a dimension, which is the coupling the plugin rule forbids.
        requested: What the caller asked for, verbatim. Empty when the caller
            asked for nothing in particular.
        used: What actually answered. Equal to *requested* exactly when the
            answer was found on its own terms. Required for a fallback, which
            must name what stood in even if only as a token; see below.
        detail: Optional free text for a caller that must explain itself to a
            human, such as the window a partial answer was limited to. Never
            parsed, never a substitute for *source*.

    Raises:
        ValueError: If the fields contradict each other. See the module
            docstring; this is the reason the type exists.
    """

    axis: str
    source: Source
    requested: str = ""
    used: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.axis:
            raise ValueError("a provenance must name the axis it is about")
        if self.source in _ANSWERED_ON_ITS_OWN_TERMS:
            if self.requested and self.used and self.requested != self.used:
                raise ValueError(
                    f"{self.source.value} claims the answer was found for {self.requested!r}, "
                    f"but {self.used!r} is what answered; that is a fallback"
                )
        elif self.source is Source.FALLBACK:
            if not self.used:
                raise ValueError(
                    "a fallback must name what answered instead, even if only as a token such as "
                    "'INTERNATIONAL'; a fallback that names nothing reports itself usable while "
                    "carrying no origin, and if truly nothing answered the source is unavailable"
                )
            if self.requested and self.requested == self.used:
                raise ValueError(
                    f"a fallback cannot have used the very thing it was asked for ({self.used!r}); "
                    "if a row was found, the source is not a fallback"
                )
        elif self.source is Source.UNAVAILABLE and self.used:
            raise ValueError(f"nothing answered, so {self.used!r} cannot be what was used")

    @property
    def answered(self) -> bool:
        """True when a row was found for what was asked.

        False for both a fallback and an unavailable, which is the conservative
        reading: a caller asking this question wants to know whether it may
        present the value as specific to what it asked about.
        """
        return self.source in _ANSWERED_ON_ITS_OWN_TERMS

    @property
    def usable(self) -> bool:
        """True when there is an answer to compute with, fallback included.

        The distinction from :attr:`answered` is the working state the plan
        calls amber: an uncovered jurisdiction runs on international defaults
        and says so, rather than refusing to work.
        """
        return self.source is not Source.UNAVAILABLE


def weakest(*provenances: Provenance) -> Provenance:
    """The least trustworthy axis among *provenances*.

    An answer is only as honest as its worst axis, so a caller deciding whether
    to label something jurisdiction-specific asks this rather than checking one
    field it happens to remember. Ties go to the first argument, so a caller
    that orders its axes meaningfully gets a stable answer.

    Raises:
        ValueError: If given nothing. An empty call would otherwise have to
            invent a verdict, and inventing one is the failure this module is
            about; a resolution with no axes is a bug at the call site.
    """
    if not provenances:
        raise ValueError("weakest() needs at least one provenance; an answer with no axes cannot be judged")
    order = list(Source)
    return max(provenances, key=lambda p: order.index(p.source))


def declared(axis: str, value: str) -> Provenance:
    """A row found on its own terms. The common case, spelled shortly."""
    return Provenance(axis=axis, source=Source.DECLARED, requested=value, used=value)


def fell_back(axis: str, requested: str, used: str, detail: str = "") -> Provenance:
    """No row for *requested*; *used* answered instead."""
    return Provenance(axis=axis, source=Source.FALLBACK, requested=requested, used=used, detail=detail)


def unavailable(axis: str, requested: str, detail: str = "") -> Provenance:
    """Nothing answered. The value beside this must not be computed with."""
    return Provenance(axis=axis, source=Source.UNAVAILABLE, requested=requested, detail=detail)
