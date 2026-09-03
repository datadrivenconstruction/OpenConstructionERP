# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The vocabulary of the RFQ register.

The models, the schemas and the pure comparison all have to agree on what an
adjustment kind or a quote status is. Keeping the words here rather than in
``models`` means the pure layers can read them without importing the ORM, and
there is one place a new value is added instead of three that drift.
"""

from __future__ import annotations

#: ``RFQ.evaluation_method`` values. ``lowest_price`` ranks on the normalised
#: amount alone; ``best_value`` blends it with the technical score using
#: ``RFQ.technical_weight``.
EVALUATION_METHODS: frozenset[str] = frozenset({"lowest_price", "best_value"})

#: ``RFQBid.status`` values. Awarding is tracked separately on ``is_awarded``,
#: because standing (may this quote be ranked at all?) and outcome (did it win?)
#: are different questions: a quote can be late and still win, once the buyer
#: has admitted it in writing.
BID_STATUS_RECEIVED = "received"
BID_STATUS_LATE = "late"
BID_STATUS_WITHDRAWN = "withdrawn"
BID_STATUS_DISQUALIFIED = "disqualified"
BID_STATUSES: frozenset[str] = frozenset(
    {
        BID_STATUS_RECEIVED,
        BID_STATUS_LATE,
        BID_STATUS_WITHDRAWN,
        BID_STATUS_DISQUALIFIED,
    }
)

#: ``RFQBidAdjustment.kind`` values. Free text would make one supplier's freight
#: and another's delivery two different things and defeat the point of
#: normalising at all.
ADJUSTMENT_KINDS: frozenset[str] = frozenset(
    {
        "freight",
        "taxes",
        "duties",
        "installation",
        "commissioning",
        "warranty",
        "site_services",
        "discount",
        "provisional_sum",
        "other",
    }
)

#: ``RFQBidAdjustment.source`` values: the supplier stated it, or the buyer
#: added an allowance to make the quote comparable with the others.
ADJUSTMENT_SOURCES: frozenset[str] = frozenset({"bidder", "buyer"})


# ── The quote gate ───────────────────────────────────────────────────────────
#
# Tiered minimum price-count before a package may be awarded, keyed off the
# package value:  ≤ over → 1 quote is enough · > over → ``min`` · > over3 →
# ``min3``. The defaults are the tiers a real contractor ran on:
# $3k → two prices, $7.5k → three. Overridable per install via env vars, and
# an UNREADABLE override TIGHTENS to three-for-everything rather than
# silently switching the gate off - a gate that fails open is not a gate.
import logging as _logging
import math as _math
import os as _os

_gate_logger = _logging.getLogger(__name__)

_QUOTE_GATE_DEFAULTS: dict[str, float | int] = {
    "over": 3000.0,  # above this, ``min`` prices are required
    "min": 2,
    "over3": 7500.0,  # above this, ``min3`` prices are required
    "min3": 3,
}
_QUOTE_GATE_TIGHTENED: dict[str, float | int] = {"over": 0.01, "min": 3, "over3": 0.01, "min3": 3}


def quote_gate_rule() -> dict[str, float | int]:
    """The tier table in force: env-overridable, tightening on bad config."""
    raw = {
        "over": _os.environ.get("OE_RFQ_MIN_QUOTES_OVER"),
        "min": _os.environ.get("OE_RFQ_MIN_QUOTES"),
        "over3": _os.environ.get("OE_RFQ_THREE_QUOTES_OVER"),
        "min3": _os.environ.get("OE_RFQ_THREE_QUOTES_MIN"),
    }
    if not any(v is not None for v in raw.values()):
        return dict(_QUOTE_GATE_DEFAULTS)
    try:
        rule = dict(_QUOTE_GATE_DEFAULTS)
        for key, val in raw.items():
            if val is not None:
                rule[key] = int(val) if key.startswith("min") else float(val)
        # `float()` happily accepts "inf" and "nan", and both switch the
        # gate OFF rather than tightening it: no package value is ever
        # greater than inf, and every comparison against nan is False. A
        # minimum of 0 is the same hole spelled differently. These are the
        # exact strings someone reaches for to "disable the gate for now".
        for key in ("over", "over3"):
            if not _math.isfinite(rule[key]) or rule[key] <= 0:
                raise ValueError(f"{key} must be a positive, finite amount")
        if rule["min"] < 1 or rule["min3"] < 1:
            raise ValueError("a minimum of less than one quote is not a gate")
        if rule["over3"] < rule["over"] or rule["min3"] < rule["min"]:
            raise ValueError("the upper tier must not be looser than the lower one")
        return rule
    except (TypeError, ValueError):
        _gate_logger.error("Quote-gate env override unreadable - tightening to three quotes for everything")
        return dict(_QUOTE_GATE_TIGHTENED)


#: The award-reason vocabulary the UI offers. Free text is also accepted -
#: the rule is that SOME written reason exists, not that it comes from a list.
AWARD_REASONS: tuple[str, ...] = (
    "Best price",
    "Best lead time",
    "Best price and lead time",
    "Only supplier who quoted",
    "Technical compliance",
    "Preferred supplier / rates agreement",
    "Previous experience on this site",
    "Client directed",
    "Availability - others could not meet the program",
)
