# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure derivation engine for the basis-of-estimate.

Turns the finished estimate contents (a flat list of BOQ position dicts) into a
structured, editable basis-of-estimate: the inclusions, exclusions and
assumptions that qualify what an estimate does and does not cover.

The engine is deliberately stdlib-only - no ORM, no app imports - so it loads on
a bare interpreter and can be unit tested without a database or the FastAPI
dependency graph. The service layer feeds it plain dicts and persists whatever
it returns.

Two derivations happen here:

* :func:`derive_trades` reads which work sections (trades) are present, absent or
  flagged in the estimate. A trade is keyed on the DIN 276 main cost group
  (an open classification standard already used across the platform); a position
  with no classification is matched on its description keywords as a fallback so
  a BOQ imported without cost codes still yields useful coverage.
* :func:`draft_basis` turns that coverage into the three qualification lists. A
  present trade becomes an inclusion, an expected-but-absent trade becomes an
  exclusion, and each quality flag (unpriced lines, missing quantities,
  provisional sums, work marked "by others") becomes an assumption. A fixed set
  of standard estimate qualifications is always drafted so the document reads
  like one an estimator would hand a client.

Every drafted line carries a deterministic id so a regenerate is stable and the
UI can key, reorder and toggle items without server round-trips.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# ── Trade taxonomy (DIN 276 main cost groups) ───────────────────────────────
#
# The main groups of DIN 276:2018-12, used here as an open, language-neutral
# work-section taxonomy. ``core`` marks the groups a normal building estimate is
# expected to carry (building construction + technical systems, matching the
# platform's DIN276 completeness rule); their absence is a meaningful exclusion
# rather than simply "not applicable". ``keywords`` drive the description
# fallback for positions that arrive without a cost code - kept conservative so
# a stray word does not misfile a line.


@dataclass(frozen=True)
class Trade:
    """One work section in the basis-of-estimate taxonomy."""

    code: str
    label: str
    core: bool
    keywords: tuple[str, ...]


TRADE_TAXONOMY: tuple[Trade, ...] = (
    Trade(
        "100",
        "Site and land",
        core=False,
        keywords=("site acquisition", "land purchase", "plot", "grundstück"),
    ),
    Trade(
        "200",
        "Site preparation and servicing",
        core=False,
        keywords=(
            "site clearance",
            "demolition",
            "earthwork",
            "excavation",
            "servicing",
            "utilities connection",
            "enabling works",
        ),
    ),
    Trade(
        "300",
        "Building construction works",
        core=True,
        keywords=(
            "concrete",
            "reinforcement",
            "rebar",
            "formwork",
            "masonry",
            "brickwork",
            "blockwork",
            "structure",
            "structural",
            "wall",
            "slab",
            "roof",
            "foundation",
            "beton",
            "screed",
            "plaster",
            "facade",
            "cladding",
        ),
    ),
    Trade(
        "400",
        "Building services and technical systems",
        core=True,
        keywords=(
            "hvac",
            "heating",
            "ventilation",
            "cooling",
            "plumbing",
            "sanitary",
            "electrical",
            "wiring",
            "lighting",
            "mechanical",
            "fire alarm",
            "sprinkler",
            "lift",
            "elevator",
            "ductwork",
            "pipework",
        ),
    ),
    Trade(
        "500",
        "External and landscaping works",
        core=False,
        keywords=(
            "external works",
            "landscap",
            "paving",
            "fencing",
            "planting",
            "car park",
            "drainage",
            "kerb",
        ),
    ),
    Trade(
        "600",
        "Furniture, fixtures and equipment",
        core=False,
        keywords=(
            "furniture",
            "furnishing",
            "fitting",
            "equipment",
            "appliance",
            "signage",
            "loose furniture",
        ),
    ),
    Trade(
        "700",
        "Ancillary and professional costs",
        core=False,
        keywords=(
            "professional fee",
            "design fee",
            "consultant",
            "supervision",
            "permit",
            "insurance",
            "survey fee",
        ),
    ),
    Trade(
        "800",
        "Financing costs",
        core=False,
        keywords=("financing", "interest", "loan", "finance charge"),
    ),
)

_TRADE_BY_CODE: dict[str, Trade] = {t.code: t for t in TRADE_TAXONOMY}

# Description markers for quality flags. Substring-matched on a folded
# (lower-cased) description, so partial and cased forms all hit.
_PROVISIONAL_MARKERS: tuple[str, ...] = (
    "provisional",
    "prov sum",
    "provisional sum",
    "pc sum",
    "p.c. sum",
    "prime cost",
    "allowance",
    "to be confirmed",
    "tbc",
)
_BY_OTHERS_MARKERS: tuple[str, ...] = (
    "by others",
    "by client",
    "by separate contract",
    "not included",
    "excluded",
    "n.i.c",
    "not in contract",
)

_CENTS = Decimal("0.01")


def to_decimal(value: object) -> Decimal:
    """Parse a money/quantity value into a Decimal, degrading to zero.

    Accepts the Decimal-as-string the wire carries, a real number, ``None`` or
    junk. Never raises: an unparseable or non-finite value collapses to ``0`` so
    a single bad row can never break a rollup.
    """
    if value is None or value == "":
        return Decimal("0")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")
    if not parsed.is_finite():
        return Decimal("0")
    return parsed


def fmt_decimal(value: Decimal) -> str:
    """Render a Decimal money value as a plain 2dp string (never scientific)."""
    return str(value.quantize(_CENTS, rounding=ROUND_HALF_UP))


def normalize_din276_main_group(raw: object) -> str:
    """Return the DIN 276 main cost group (``N00``) of a classification code.

    Folds the dotted CAD forms (``"330.10"`` -> ``"330"``) and reduces any valid
    3+ digit numeric KG code to its top-level hundred (``"331"`` -> ``"300"``).
    Returns ``""`` when the input is not a usable numeric KG code.
    """
    code = str(raw or "").strip()
    if not code:
        return ""
    head = code.split(".", 1)[0].strip()
    if len(head) >= 3 and head[:3].isdigit():
        first = head[0]
        if first != "0":
            return f"{first}00"
    return ""


def _fold(text: object) -> str:
    """Lower-case a description for case-insensitive keyword matching."""
    return str(text or "").strip().lower()


def _match_trade_by_keyword(description: str) -> Trade | None:
    """Assign a trade from description keywords, or ``None`` when none match."""
    folded = _fold(description)
    if not folded:
        return None
    for trade in TRADE_TAXONOMY:
        if any(kw in folded for kw in trade.keywords):
            return trade
    return None


# ── Coverage model ──────────────────────────────────────────────────────────


@dataclass
class TradePresence:
    """A trade that appears in the estimate, with its rollup."""

    code: str
    label: str
    core: bool
    position_count: int = 0
    total: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class TradeCoverage:
    """The present / absent / flagged picture derived from the estimate."""

    present: list[TradePresence] = field(default_factory=list)
    absent_core: list[Trade] = field(default_factory=list)
    total_positions: int = 0
    classified_positions: int = 0
    unclassified_positions: int = 0
    zero_rate_positions: int = 0
    missing_quantity_positions: int = 0
    provisional_positions: int = 0
    by_others_positions: int = 0


def derive_trades(positions: list[dict]) -> TradeCoverage:
    """Derive trade coverage and quality flags from BOQ position dicts.

    Args:
        positions: Flat list of position dicts. Each may carry
            ``classification`` (``{"din276": "330"}``), ``description``,
            ``quantity``, ``unit_rate`` and ``total``. All keys are optional and
            defended - a sparse dict is handled, not assumed.

    Returns:
        A :class:`TradeCoverage` with present trades (ordered by descending
        rolled-up total), the expected trades that are absent, and the counts
        that seed the assumptions.
    """
    presence: dict[str, TradePresence] = {}
    coverage = TradeCoverage()

    for pos in positions:
        classification = pos.get("classification") or {}
        din_raw = classification.get("din276", "") if isinstance(classification, dict) else ""
        description = pos.get("description", "")
        main_group = normalize_din276_main_group(din_raw)

        trade: Trade | None
        if main_group and main_group in _TRADE_BY_CODE:
            trade = _TRADE_BY_CODE[main_group]
            coverage.classified_positions += 1
        else:
            trade = _match_trade_by_keyword(description)
            if trade is None:
                coverage.unclassified_positions += 1

        coverage.total_positions += 1

        rate = to_decimal(pos.get("unit_rate"))
        qty = to_decimal(pos.get("quantity"))
        if rate <= 0:
            coverage.zero_rate_positions += 1
        if qty <= 0:
            coverage.missing_quantity_positions += 1

        folded = _fold(description)
        if any(marker in folded for marker in _PROVISIONAL_MARKERS):
            coverage.provisional_positions += 1
        if any(marker in folded for marker in _BY_OTHERS_MARKERS):
            coverage.by_others_positions += 1

        if trade is not None:
            entry = presence.get(trade.code)
            if entry is None:
                entry = TradePresence(code=trade.code, label=trade.label, core=trade.core)
                presence[trade.code] = entry
            entry.position_count += 1
            entry.total += to_decimal(pos.get("total"))

    # Present trades, richest first (a tie falls back to the taxonomy order).
    order = {t.code: i for i, t in enumerate(TRADE_TAXONOMY)}
    coverage.present = sorted(
        presence.values(),
        key=lambda p: (-p.total, order.get(p.code, 99)),
    )

    present_codes = set(presence)
    coverage.absent_core = [t for t in TRADE_TAXONOMY if t.core and t.code not in present_codes]
    return coverage


# ── Line provenance (where the priced lines came from) ──────────────────────
#
# ``Position.source`` records how a line entered the bill. Its vocabulary is
# fifteen values wide (see the pattern on ``boq.schemas.PositionBase.source``),
# which is too fine to read at a glance and too coarse to ignore: an estimate
# whose quantities were taken off a model is a different animal from one typed
# by hand, and that difference is the first thing a reviewer asks about. The
# fifteen values are therefore folded into four families a cost engineer already
# thinks in. An unknown value folds to ``manual`` - the conservative reading,
# since nothing about it evidences a measurement.

SOURCE_FAMILIES: dict[str, str] = {
    # Quantities taken off a drawing or a model.
    "cad_import": "measured",
    "cad_import_ai": "measured",
    "ai_takeoff": "measured",
    "takeoff": "measured",
    # Lines that arrived inside somebody else's bill or spreadsheet.
    "gaeb_import": "imported",
    "excel_import": "imported",
    "bc3_import": "imported",
    "smart_import": "imported",
    "smart_import_ai": "imported",
    # Lines generated from a reference cost database, assembly or price match.
    "cost_database": "catalogue",
    "assembly": "catalogue",
    "cwicr": "catalogue",
    "ai_match": "catalogue",
    "enriched": "catalogue",
    # Typed by an estimator.
    "manual": "manual",
}

# Display order, strongest evidence first.
FAMILY_ORDER: tuple[str, ...] = ("measured", "imported", "catalogue", "manual")

# The sources that mean a model proposed the line or its price. Kept separate
# from the family fold: an AI-assisted takeoff is still a measurement, it just
# carries a confidence a human should have looked at.
AI_SOURCES: frozenset[str] = frozenset({"ai_takeoff", "cad_import_ai", "smart_import_ai", "ai_match"})

# Below this, an AI-proposed line is reported as needing review. Matches the
# threshold the copilot uses to decide a proposal cannot be applied unattended.
LOW_CONFIDENCE_THRESHOLD: Decimal = Decimal("0.7")

# Word-shaped confidence values persisted by older seeds and importers. The BOQ
# grid coerces the same three words (``boq.service._CONFIDENCE_LABELS``); the map
# is repeated rather than imported because this engine is stdlib-only by
# contract and must load without the app graph.
_CONFIDENCE_WORDS: dict[str, Decimal] = {
    "high": Decimal("0.9"),
    "medium": Decimal("0.6"),
    "med": Decimal("0.6"),
    "low": Decimal("0.3"),
}


def source_family(raw: object) -> str:
    """Fold a ``Position.source`` value into its basis-of-estimate family.

    Args:
        raw: The stored source string, or anything else.

    Returns:
        One of ``measured`` / ``imported`` / ``catalogue`` / ``manual``. An
        unrecognised or empty value folds to ``manual``.
    """
    return SOURCE_FAMILIES.get(str(raw or "").strip().lower(), "manual")


def parse_confidence(raw: object) -> Decimal | None:
    """Parse a stored confidence into a 0-1 Decimal, or ``None`` when absent.

    Accepts the numeric 0-1 contract and the ``high`` / ``medium`` / ``low``
    words legacy rows carry. Anything else - including an out-of-range number -
    yields ``None`` rather than a fabricated score, so an unreadable value is
    reported as "no confidence recorded" instead of quietly counting as good.
    """
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None
    if text in _CONFIDENCE_WORDS:
        return _CONFIDENCE_WORDS[text]
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not parsed.is_finite() or parsed < 0 or parsed > 1:
        return None
    return parsed


@dataclass
class ProvenanceBucket:
    """One ``Position.source`` value, with its line count and value."""

    source: str
    family: str
    position_count: int = 0
    total: Decimal = field(default_factory=lambda: Decimal("0"))
    share_pct: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class FamilyShare:
    """One provenance family, rolled up across its sources."""

    family: str
    position_count: int = 0
    total: Decimal = field(default_factory=lambda: Decimal("0"))
    share_pct: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class ProvenanceSummary:
    """Where the estimate's lines came from, by count and by value.

    ``share_basis`` names what the percentages are a share OF. Normally that is
    value; a bill that carries no money at all would make every value share
    zero, which reads as "nothing is measured" rather than "there is nothing to
    measure", so the shares fall back to line counts and say so. A reader is
    never left to guess which of the two they are looking at.
    """

    buckets: list[ProvenanceBucket] = field(default_factory=list)
    families: list[FamilyShare] = field(default_factory=list)
    total_positions: int = 0
    priced_total: Decimal = field(default_factory=lambda: Decimal("0"))
    share_basis: str = "value"  # "value" | "count"
    ai_position_count: int = 0
    ai_total: Decimal = field(default_factory=lambda: Decimal("0"))
    scored_position_count: int = 0
    low_confidence_count: int = 0
    low_confidence_total: Decimal = field(default_factory=lambda: Decimal("0"))
    model_linked_positions: int = 0
    stale_links: int = 0
    broken_links: int = 0

    def family_share(self, family: str) -> Decimal:
        """Return the share of one family, or zero when it contributes nothing."""
        for entry in self.families:
            if entry.family == family:
                return entry.share_pct
        return Decimal("0")

    def family_positions(self, family: str) -> int:
        """Return the line count of one family, or zero when it has none."""
        for entry in self.families:
            if entry.family == family:
                return entry.position_count
        return 0


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    """Percentage of ``part`` in ``whole``, to one decimal; zero whole yields zero."""
    if whole == 0:
        return Decimal("0")
    return (part / whole * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def derive_provenance(
    rows: list[dict],
    *,
    link_counts: dict | None = None,
) -> ProvenanceSummary:
    """Summarise where the estimate's lines came from.

    Args:
        rows: One dict per ``(source, confidence)`` group, each carrying
            ``source``, ``confidence``, ``position_count`` and ``total``. The
            service produces these with a SQL ``GROUP BY`` over *every* position
            of the estimate - deliberately not over the capped scan the trade
            coverage reads, because a share computed off the first 20 000 lines
            of a longer bill would be a false statement about the whole.
        link_counts: Optional ``{"active": n, "stale": n, "broken": n}`` from the
            BOQ model-quantity links, so the summary can say how many quantities
            a model still drives and how many of those bindings have drifted.

    Returns:
        A :class:`ProvenanceSummary`. An empty input yields an empty summary
        whose shares are zero and whose ``share_basis`` stays ``value``.
    """
    buckets: dict[str, ProvenanceBucket] = {}
    summary = ProvenanceSummary()

    for row in rows:
        raw_source = str(row.get("source") or "").strip().lower() or "manual"
        family = source_family(raw_source)
        count = int(row.get("position_count") or 0)
        if count <= 0:
            continue
        total = to_decimal(row.get("total"))

        bucket = buckets.get(raw_source)
        if bucket is None:
            bucket = ProvenanceBucket(source=raw_source, family=family)
            buckets[raw_source] = bucket
        bucket.position_count += count
        bucket.total += total

        summary.total_positions += count
        summary.priced_total += total

        if raw_source in AI_SOURCES:
            summary.ai_position_count += count
            summary.ai_total += total

        score = parse_confidence(row.get("confidence"))
        if score is not None:
            summary.scored_position_count += count
            if score < LOW_CONFIDENCE_THRESHOLD:
                summary.low_confidence_count += count
                summary.low_confidence_total += total

    # A bill with no money in it cannot be shared out by value without every
    # family reading zero, so fall back to line counts and record which it is.
    # An estimate with no lines at all is left on "value": there is nothing to
    # share out either way, and naming a fallback nobody took would be noise.
    by_value = summary.priced_total > 0 or summary.total_positions == 0
    summary.share_basis = "value" if by_value else "count"
    whole = summary.priced_total if by_value else Decimal(summary.total_positions)

    for bucket in buckets.values():
        part = bucket.total if by_value else Decimal(bucket.position_count)
        bucket.share_pct = _pct(part, whole)

    family_rollup: dict[str, FamilyShare] = {}
    for bucket in buckets.values():
        entry = family_rollup.setdefault(bucket.family, FamilyShare(family=bucket.family))
        entry.position_count += bucket.position_count
        entry.total += bucket.total
    for entry in family_rollup.values():
        part = entry.total if by_value else Decimal(entry.position_count)
        entry.share_pct = _pct(part, whole)

    family_order = {name: i for i, name in enumerate(FAMILY_ORDER)}
    summary.families = sorted(family_rollup.values(), key=lambda f: family_order.get(f.family, 99))
    summary.buckets = sorted(
        buckets.values(),
        key=lambda b: (family_order.get(b.family, 99), -b.total, b.source),
    )

    counts = link_counts or {}
    summary.stale_links = int(counts.get("stale") or 0)
    summary.broken_links = int(counts.get("broken") or 0)
    summary.model_linked_positions = int(counts.get("active") or 0) + summary.stale_links + summary.broken_links
    return summary


# ── Markups actually applied ────────────────────────────────────────────────
#
# The standard qualification set drafts "value added tax is excluded" and "price
# escalation is excluded" because that is true of most estimates. It is not true
# of an estimate whose bill carries a tax or an escalation markup, and a basis
# of estimate that contradicts the bill it describes is worse than none. The
# markup picture below lets the drafter state what was really applied and drop
# the boilerplate that the bill disproves.


@dataclass
class MarkupFact:
    """One active markup line of the bill."""

    name: str
    category: str
    markup_type: str
    percentage: Decimal = field(default_factory=lambda: Decimal("0"))
    fixed_amount: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class MarkupPicture:
    """The active markups, plus the three the qualifications care about."""

    lines: list[MarkupFact] = field(default_factory=list)
    has_tax: bool = False
    has_contingency: bool = False
    has_escalation: bool = False


def summarise_markups(markups: list[dict]) -> MarkupPicture:
    """Read the bill's active markup lines into a :class:`MarkupPicture`.

    Args:
        markups: Markup dicts carrying ``name``, ``category``, ``markup_type``,
            ``percentage`` and ``fixed_amount``. All keys are defended.

    Returns:
        The picture. ``category`` drives the tax and contingency flags (the
        vocabulary the markup templates write); escalation is a ``markup_type``
        rather than a category, so it is read from there.
    """
    picture = MarkupPicture()
    for markup in markups:
        category = str(markup.get("category") or "").strip().lower()
        markup_type = str(markup.get("markup_type") or "").strip().lower()
        picture.lines.append(
            MarkupFact(
                name=str(markup.get("name") or "").strip(),
                category=category,
                markup_type=markup_type,
                percentage=to_decimal(markup.get("percentage")),
                fixed_amount=to_decimal(markup.get("fixed_amount")),
            )
        )
        if category == "tax":
            picture.has_tax = True
        if category == "contingency":
            picture.has_contingency = True
        if markup_type == "escalation":
            picture.has_escalation = True
    return picture


# ── Estimate class (AACE 18R-97) ────────────────────────────────────────────
#
# The class table and the rule that reads a bill's completeness live in the BOQ
# module (``boq.service._AACE_CLASSES`` / ``_determine_aace_class``), which is
# where the platform already exposes them at
# ``GET /boqs/{id}/classification/``. They are deliberately NOT copied here: one
# standard, one table. What this engine adds is the part that table cannot see -
# a completeness rule counts filled-in cells, and a bill of hand-typed
# quantities can be 100% filled in and still not be a definitive estimate.


@dataclass
class ClassReason:
    """One piece of evidence behind a class suggestion.

    ``code`` is an enum key the UI translates; ``value`` carries the number that
    goes in the sentence. Nothing here is English, so the reasoning survives
    translation instead of being frozen into the language it was drafted in.
    """

    code: str
    value: str = ""

    def to_dict(self) -> dict:
        """Serialise to the JSON shape stored on the model / returned to the UI."""
        return {"code": self.code, "value": self.value}


@dataclass
class ClassSuggestion:
    """A suggested AACE class, the completeness class it started from, and why.

    A suggestion is never applied on its own: the stored ``estimate_class`` stays
    empty until an estimator confirms or overrides it. This dataclass is the
    proposal, not the decision.
    """

    suggested_class: int
    base_class: int
    reasons: list[ClassReason] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise to the JSON shape stored on the model / returned to the UI."""
        return {
            "suggested_class": self.suggested_class,
            "base_class": self.base_class,
            "reasons": [r.to_dict() for r in self.reasons],
        }


# How well measured the quantities have to be before a class may claim to be
# that firm. Read as "to be suggested at class N or better, at least P% of the
# estimate's value must come from a takeoff". Ordered strictest first.
_MEASUREMENT_CEILINGS: tuple[tuple[Decimal, int], ...] = (
    (Decimal("50"), 1),
    (Decimal("25"), 2),
)
# What is left when no ceiling is met: a budget-grade estimate at best.
_UNMEASURED_CEILING_CLASS: int = 3


def suggest_estimate_class(
    base_class: int,
    provenance: ProvenanceSummary,
    coverage: TradeCoverage | None = None,
) -> ClassSuggestion:
    """Suggest an AACE class from the completeness class and the provenance.

    Args:
        base_class: The class the BOQ module's completeness rule returned (1-5,
            lower is more defined).
        provenance: Where the lines came from.
        coverage: Optional trade coverage, read only for the evidence lines.

    Returns:
        A :class:`ClassSuggestion`. The suggestion never claims to be firmer
        than the measurement evidence supports: a bill that is fully priced but
        whose quantities were typed rather than taken off cannot be suggested
        below class 3. It never runs the other way - poor measurement can only
        widen a class, never tighten one.
    """
    # ``or 5`` would be wrong here: 0 is falsy, and a caller who hands over a
    # nonsense 0 would silently get the LEAST defined class rather than a clamp.
    # Only a missing value defaults, and it defaults to the conservative end.
    raw_class = 5 if base_class is None else int(base_class)
    base = max(1, min(5, raw_class))
    measured = provenance.family_share("measured")

    ceiling = _UNMEASURED_CEILING_CLASS
    for threshold, allowed in _MEASUREMENT_CEILINGS:
        if measured >= threshold:
            ceiling = allowed
            break

    suggested = max(base, ceiling)
    reasons: list[ClassReason] = [
        ClassReason("completeness_class", str(base)),
        ClassReason("measured_share", fmt_pct(measured)),
    ]
    manual = provenance.family_share("manual")
    if manual > 0:
        reasons.append(ClassReason("manual_share", fmt_pct(manual)))
    if suggested > base:
        reasons.append(ClassReason("capped_by_measurement", str(base)))
    if provenance.low_confidence_count:
        reasons.append(ClassReason("low_confidence_lines", str(provenance.low_confidence_count)))
    if provenance.stale_links:
        reasons.append(ClassReason("stale_model_links", str(provenance.stale_links)))
    if provenance.share_basis == "count":
        reasons.append(ClassReason("share_by_count", str(provenance.total_positions)))
    if coverage is not None and coverage.zero_rate_positions:
        reasons.append(ClassReason("unpriced_lines", str(coverage.zero_rate_positions)))
    return ClassSuggestion(suggested_class=suggested, base_class=base, reasons=reasons)


def fmt_pct(value: Decimal) -> str:
    """Render a percentage as a plain one-decimal string (never scientific)."""
    return str(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def parse_accuracy_pct(raw: object) -> Decimal:
    """Parse a signed accuracy percentage such as ``"-20%"`` or ``"+30"``.

    Returns ``0`` for anything unreadable, so a malformed bound collapses the
    range to the point estimate instead of inventing one.
    """
    text = str(raw or "").strip().replace("%", "").replace("+", "")
    if not text:
        return Decimal("0")
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")
    return parsed if parsed.is_finite() else Decimal("0")


def accuracy_range(total: Decimal, low_pct: Decimal, high_pct: Decimal) -> tuple[Decimal, Decimal]:
    """Apply a signed accuracy band to a point estimate.

    Args:
        total: The point estimate.
        low_pct: Signed lower bound percentage (e.g. ``Decimal("-20")``).
        high_pct: Signed upper bound percentage (e.g. ``Decimal("30")``).

    Returns:
        ``(low_amount, high_amount)``, always ordered low-then-high even when the
        two percentages arrive the wrong way round.
    """
    hundred = Decimal("100")
    first = total * (hundred + low_pct) / hundred
    second = total * (hundred + high_pct) / hundred
    low, high = (first, second) if first <= second else (second, first)
    return low.quantize(_CENTS, rounding=ROUND_HALF_UP), high.quantize(_CENTS, rounding=ROUND_HALF_UP)


# ── Drafted basis-of-estimate ───────────────────────────────────────────────


@dataclass
class Qualification:
    """One editable line of the basis-of-estimate."""

    id: str
    category: str  # "inclusion" | "exclusion" | "assumption"
    text: str
    trade_code: str | None = None
    trade_label: str | None = None
    basis: str = ""  # why the line was drafted: "present" | "absent" | "flag" | "standard"
    source: str = "auto"  # "auto" (drafted) | "manual" (user-added)
    enabled: bool = True

    def to_dict(self) -> dict:
        """Serialise to the JSON shape stored on the model / returned to the UI."""
        return {
            "id": self.id,
            "category": self.category,
            "text": self.text,
            "trade_code": self.trade_code,
            "trade_label": self.trade_label,
            "basis": self.basis,
            "source": self.source,
            "enabled": self.enabled,
        }


@dataclass
class BasisDraft:
    """The three drafted qualification lists."""

    inclusions: list[Qualification] = field(default_factory=list)
    exclusions: list[Qualification] = field(default_factory=list)
    assumptions: list[Qualification] = field(default_factory=list)


# Standard estimate qualifications, drafted on every basis so the document reads
# like a real one. Described by function only - never a brand or product.
_STANDARD_EXCLUSIONS: tuple[tuple[str, str], ...] = (
    ("vat", "Value added tax and any other sales taxes, unless separately stated."),
    ("permits", "Statutory permits, authority fees and connection charges."),
    ("land-finance", "Land acquisition, legal costs and financing charges."),
    ("escalation", "Price escalation and inflation beyond the stated base date."),
    ("by-others", "Any work described as by others or provided under a separate contract."),
    (
        "ground",
        "Abnormal ground conditions, contamination, dewatering and rock excavation, unless stated.",
    ),
    ("loose-ffe", "Loose furniture, fittings and operational equipment, unless itemised."),
    ("prof-fees", "Professional, design and supervision fees, unless itemised."),
)

_STANDARD_ASSUMPTIONS: tuple[tuple[str, str], ...] = (
    (
        "quantities",
        "Quantities are measured from the information available at the time of estimate "
        "and are subject to confirmation at detailed design.",
    ),
    (
        "workmanship",
        "Normal working hours, standard access and unrestricted site conditions are assumed.",
    ),
    (
        "market",
        "Rates reflect competitive market conditions at the stated base date.",
    ),
)


# ── Sibling estimating-module assumptions ───────────────────────────────────
#
# The basis is deepened with what the sibling estimating modules assumed, so a
# reviewer sees them without opening each tool: the allowances / contingency
# register, the preliminaries (general-conditions) roll-up, and the date the
# priced rates are current to. The service reads each source and hands this
# engine plain values; every block degrades gracefully, contributing no line
# when the project has no data for it.

# Human labels for the allowance types the register carries (an open
# vocabulary; an unknown value folds to spaced words rather than raising).
_ALLOWANCE_TYPE_LABELS: dict[str, str] = {
    "provisional_sum": "provisional sum",
    "pc_sum": "prime cost sum",
    "contingency": "contingency",
}


def _allowance_type_label(raw: object) -> str:
    """Return a human label for an allowance type code.

    Args:
        raw: The stored type code (``provisional_sum`` / ``pc_sum`` /
            ``contingency``) or any other value.

    Returns:
        The mapped label, or the code with underscores spaced out when unknown;
        an empty value yields ``"allowance"``.
    """
    key = str(raw or "").strip().lower()
    if key in _ALLOWANCE_TYPE_LABELS:
        return _ALLOWANCE_TYPE_LABELS[key]
    return key.replace("_", " ") or "allowance"


def _money_phrase(amount: Decimal, currency: object = "") -> str:
    """Render a money amount as ``"1234.56 EUR"`` (the currency code optional)."""
    text = fmt_decimal(amount)
    code = str(currency or "").strip()
    return f"{text} {code}" if code else text


def _draft_allowance_assumptions(
    allowances: list[dict],
    *,
    markup_contingency: bool = False,
) -> list[Qualification]:
    """Draft one assumption per allowance plus a contingency-inclusion note.

    Each allowance the estimate carries - a provisional sum, a prime-cost sum or
    a contingency - becomes a line naming it, its held amount and its type, so a
    reviewer sees what has been allowed for ahead of firm measurement. A closing
    note states whether a contingency is included in the estimate total, and (for
    a single currency) how much.

    Args:
        allowances: Allowance dicts, each optionally carrying ``id``, ``label``,
            ``allowance_type``, ``held_amount`` and ``currency``. All keys are
            defended - a sparse dict is handled, not assumed.
        markup_contingency: Whether the bill applies a contingency MARKUP. A
            register with no contingency in it does not mean the estimate holds
            none - the money may sit in the markup stack instead - so the "not
            included" note is only written when neither source carries one.

    Returns:
        The drafted assumption lines, in input order, with the contingency note
        last. An empty input yields an empty list (no note is invented).
    """
    if not allowances:
        return []

    lines: list[Qualification] = []
    contingency_total = Decimal("0")
    contingency_currencies: set[str] = set()
    has_contingency = False

    for index, allowance in enumerate(allowances):
        raw_type = str(allowance.get("allowance_type") or "").strip().lower()
        type_label = _allowance_type_label(raw_type)
        label = str(allowance.get("label") or "").strip()
        name = label or type_label.capitalize()
        amount = to_decimal(allowance.get("held_amount"))
        currency = str(allowance.get("currency") or "").strip()
        ident = str(allowance.get("id") or index)
        phrase = _money_phrase(amount, currency)
        lines.append(
            Qualification(
                id=f"asm-allowance-{ident}",
                category="assumption",
                text=f"Allowance included: {name} - {phrase} ({type_label}).",
                basis="allowance",
            )
        )
        if raw_type == "contingency":
            has_contingency = True
            contingency_total += amount
            contingency_currencies.add(currency)

    if not has_contingency and markup_contingency:
        # The markup line already drafted its own inclusion; say nothing that
        # would read as a denial of it.
        return lines
    if not has_contingency:
        note = "Contingency is not included in the estimate total."
    elif len(contingency_currencies) == 1:
        phrase = _money_phrase(contingency_total, next(iter(contingency_currencies)))
        note = f"Contingency of {phrase} is included in the estimate total."
    else:
        note = "Contingency is included in the estimate total."
    lines.append(
        Qualification(
            id="asm-contingency",
            category="assumption",
            text=note,
            basis="allowance",
        )
    )
    return lines


def _draft_preliminaries_assumption(preliminaries: dict) -> Qualification | None:
    """Draft the preliminaries summary assumption, or ``None`` when there is none.

    Args:
        preliminaries: The pre-computed roll-up the service builds from
            ``preliminaries.prelim_math`` - ``grand_total``,
            ``time_related_total``, ``item_count`` and an optional ``currency``.

    Returns:
        A single assumption line naming the preliminaries total, the item count
        and the time-related portion, or ``None`` when no items were priced.
    """
    try:
        item_count = int(preliminaries.get("item_count") or 0)
    except (TypeError, ValueError):
        item_count = 0
    if item_count <= 0:
        return None

    currency = preliminaries.get("currency", "")
    total_phrase = _money_phrase(to_decimal(preliminaries.get("grand_total")), currency)
    time_phrase = _money_phrase(to_decimal(preliminaries.get("time_related_total")), currency)
    item_word = "item" if item_count == 1 else "items"
    return Qualification(
        id="asm-preliminaries",
        category="assumption",
        text=(f"Preliminaries assumed: {total_phrase} ({item_count} {item_word}, {time_phrase} time-related)."),
        basis="preliminaries",
    )


def _draft_pricing_base_date_assumption(pricing_base_date: str | None) -> Qualification | None:
    """Draft the pricing-base-date assumption, or ``None`` when no date is known.

    Args:
        pricing_base_date: The date the priced rates are current to, as a string
            (the service derives it from the freshest cost-item price date, or the
            estimate's stated base date).

    Returns:
        A single assumption line stating the price currency date and that
        escalation beyond it is excluded, or ``None`` when no date is available.
    """
    date_text = str(pricing_base_date or "").strip()
    if not date_text:
        return None
    return Qualification(
        id="asm-pricing-date",
        category="assumption",
        text=(f"Prices are current as of {date_text}; escalation beyond this date is excluded unless stated."),
        basis="pricing-date",
    )


# How each provenance family reads in the drafted prose. The UI labels the same
# families from its own translated strings; these are only for the exported
# document, which follows the estimate's English qualification text.
_FAMILY_PHRASES: dict[str, str] = {
    "measured": "measured from a drawing or model",
    "imported": "imported from a supplied bill or spreadsheet",
    "catalogue": "generated from a cost database or assembly",
    "manual": "entered by hand",
}


def _draft_provenance_assumptions(provenance: ProvenanceSummary) -> list[Qualification]:
    """Draft the "where the numbers came from" assumptions.

    Args:
        provenance: The derived :class:`ProvenanceSummary`.

    Returns:
        Up to three lines: the family split, the AI lines still awaiting review,
        and the model bindings that have drifted. A summary over no lines drafts
        nothing.
    """
    if provenance.total_positions <= 0:
        return []

    lines: list[Qualification] = []
    noun = "value" if provenance.share_basis == "value" else "line items"
    parts = [
        f"{fmt_pct(entry.share_pct)}% {_FAMILY_PHRASES.get(entry.family, entry.family)}"
        for entry in provenance.families
        if entry.share_pct > 0
    ]
    if parts:
        lines.append(
            Qualification(
                id="asm-provenance",
                category="assumption",
                text=f"Of the estimate's {noun}: {', '.join(parts)}.",
                basis="provenance",
            )
        )

    if provenance.low_confidence_count:
        count = provenance.low_confidence_count
        item_word = "line carries" if count == 1 else "lines carry"
        lines.append(
            Qualification(
                id="asm-low-confidence",
                category="assumption",
                text=(
                    f"{count} machine-proposed {item_word} a confidence below "
                    f"{LOW_CONFIDENCE_THRESHOLD} and is qualified pending an estimator's review."
                ),
                basis="provenance",
            )
        )

    if provenance.stale_links or provenance.broken_links:
        drifted = provenance.stale_links + provenance.broken_links
        item_word = "quantity is" if drifted == 1 else "quantities are"
        lines.append(
            Qualification(
                id="asm-stale-links",
                category="assumption",
                text=(
                    f"{drifted} model-driven {item_word} out of step with the current model "
                    "and were priced from the last applied take-off."
                ),
                basis="provenance",
            )
        )
    return lines


def _markup_phrase(fact: MarkupFact) -> str:
    """Render one markup line as ``"Overhead 8%"`` / ``"Bond 12500.00"``."""
    name = fact.name or fact.category or "Markup"
    if fact.markup_type == "fixed":
        return f"{name} {fmt_decimal(fact.fixed_amount)}"
    return f"{name} {fmt_decimal(fact.percentage)}%"


def _draft_markup_qualifications(picture: MarkupPicture) -> list[Qualification]:
    """Draft the lines that state what the bill's markups actually did.

    Args:
        picture: The derived :class:`MarkupPicture`.

    Returns:
        One assumption naming every active markup, plus an inclusion for each of
        tax and escalation when the bill applies them - those two replace
        standard exclusions that would otherwise contradict the bill.
    """
    if not picture.lines:
        return []

    lines: list[Qualification] = [
        Qualification(
            id="asm-markups",
            category="assumption",
            text=f"Markups applied to the direct cost: {', '.join(_markup_phrase(f) for f in picture.lines)}.",
            basis="markup",
        )
    ]
    if picture.has_tax:
        lines.append(
            Qualification(
                id="inc-tax",
                category="inclusion",
                text="Value added tax is included, as priced by the bill's tax markup.",
                basis="markup",
            )
        )
    if picture.has_escalation:
        lines.append(
            Qualification(
                id="inc-escalation",
                category="inclusion",
                text="Price escalation is included, as priced by the bill's escalation markup.",
                basis="markup",
            )
        )
    if picture.has_contingency:
        lines.append(
            Qualification(
                id="inc-contingency-markup",
                category="inclusion",
                text="A contingency is included in the estimate total, as priced by the bill's contingency markup.",
                basis="markup",
            )
        )
    return lines


def draft_basis(
    coverage: TradeCoverage,
    *,
    currency: str = "",
    base_date: str | None = None,
    allowances: list[dict] | None = None,
    preliminaries: dict | None = None,
    pricing_base_date: str | None = None,
    provenance: ProvenanceSummary | None = None,
    markups: MarkupPicture | None = None,
) -> BasisDraft:
    """Draft the inclusions, exclusions and assumptions from trade coverage.

    Args:
        coverage: The derived :class:`TradeCoverage`.
        currency: Optional ISO currency code, woven into a money assumption.
        base_date: Optional base date string, woven into an escalation assumption.
        allowances: Optional allowance dicts from the allowances / contingency
            register; each drafts an assumption and the set drafts a contingency
            note (see :func:`_draft_allowance_assumptions`).
        preliminaries: Optional pre-computed preliminaries roll-up; drafts one
            summary assumption (see :func:`_draft_preliminaries_assumption`).
        pricing_base_date: Optional date the priced rates are current to; drafts
            a price-currency assumption (see
            :func:`_draft_pricing_base_date_assumption`).
        provenance: Optional line-provenance summary; drafts the "where the
            numbers came from" assumptions (see
            :func:`_draft_provenance_assumptions`).
        markups: Optional picture of the bill's active markups. A bill that
            prices tax or escalation SUPPRESSES the matching standard exclusion
            and states the inclusion instead, so the document never denies what
            the bill charges for.

    Returns:
        A :class:`BasisDraft` of deterministic, editable qualification lines.
    """
    draft = BasisDraft()
    picture = markups or MarkupPicture()
    # A standard exclusion the bill itself disproves is dropped rather than
    # drafted and left for the estimator to notice.
    suppressed: set[str] = set()
    if picture.has_tax:
        suppressed.add("vat")
    if picture.has_escalation:
        suppressed.add("escalation")

    # Inclusions - one per present trade, richest first.
    for trade in coverage.present:
        count = trade.position_count
        item_word = "item" if count == 1 else "items"
        draft.inclusions.append(
            Qualification(
                id=f"inc-trade-{trade.code}",
                category="inclusion",
                text=f"{trade.label} is included ({count} {item_word}).",
                trade_code=trade.code,
                trade_label=trade.label,
                basis="present",
            )
        )

    # Exclusions - expected trades that are absent, then the standard set.
    for trade in coverage.absent_core:
        draft.exclusions.append(
            Qualification(
                id=f"exc-trade-{trade.code}",
                category="exclusion",
                text=f"{trade.label} is not included in this estimate.",
                trade_code=trade.code,
                trade_label=trade.label,
                basis="absent",
            )
        )
    for key, text in _STANDARD_EXCLUSIONS:
        if key in suppressed:
            continue
        draft.exclusions.append(
            Qualification(
                id=f"exc-{key}",
                category="exclusion",
                text=text,
                basis="standard",
            )
        )

    # Assumptions - one per raised quality flag, then the standard set.
    if coverage.zero_rate_positions:
        count = coverage.zero_rate_positions
        item_word = "item carries" if count == 1 else "items carry"
        draft.assumptions.append(
            Qualification(
                id="asm-unpriced",
                category="assumption",
                text=(
                    f"{count} {item_word} no unit rate and is treated as a provisional "
                    "allowance to be priced before award."
                ),
                basis="flag",
            )
        )
    if coverage.missing_quantity_positions:
        count = coverage.missing_quantity_positions
        item_word = "item has" if count == 1 else "items have"
        draft.assumptions.append(
            Qualification(
                id="asm-missing-qty",
                category="assumption",
                text=(f"{count} {item_word} no measured quantity and is assumed to be confirmed at detailed design."),
                basis="flag",
            )
        )
    if coverage.provisional_positions:
        draft.assumptions.append(
            Qualification(
                id="asm-provisional",
                category="assumption",
                text=(
                    "Provisional sums and allowances are included as noted and are to be adjusted against actual cost."
                ),
                basis="flag",
            )
        )
    if coverage.unclassified_positions:
        count = coverage.unclassified_positions
        item_word = "item is" if count == 1 else "items are"
        draft.assumptions.append(
            Qualification(
                id="asm-unclassified",
                category="assumption",
                text=(
                    f"{count} {item_word} not mapped to a cost group; trade coverage above "
                    "is assessed from item descriptions."
                ),
                basis="flag",
            )
        )

    # Where the numbers came from, before the sibling-module lines: it is the
    # first thing a second estimator asks and belongs above the detail.
    if provenance is not None:
        draft.assumptions.extend(_draft_provenance_assumptions(provenance))

    # What the bill's markups did. The inclusions it drafts are appended to the
    # inclusion list; the assumption stays with the other assumptions.
    for line in _draft_markup_qualifications(picture):
        if line.category == "inclusion":
            draft.inclusions.append(line)
        else:
            draft.assumptions.append(line)

    # Sibling estimating-module assumptions - allowances / contingency, the
    # preliminaries roll-up and the pricing base date. Each degrades gracefully:
    # an absent source contributes no line.
    draft.assumptions.extend(_draft_allowance_assumptions(allowances or [], markup_contingency=picture.has_contingency))
    prelim_line = _draft_preliminaries_assumption(preliminaries or {})
    if prelim_line is not None:
        draft.assumptions.append(prelim_line)
    pricing_line = _draft_pricing_base_date_assumption(pricing_base_date)
    if pricing_line is not None:
        draft.assumptions.append(pricing_line)

    if base_date:
        draft.assumptions.append(
            Qualification(
                id="asm-base-date",
                category="assumption",
                text=f"Rates are based on a base date of {base_date}.",
                basis="standard",
            )
        )
    if currency.strip():
        draft.assumptions.append(
            Qualification(
                id="asm-currency",
                category="assumption",
                text=f"All amounts are expressed in {currency.strip()}.",
                basis="standard",
            )
        )
    for key, text in _STANDARD_ASSUMPTIONS:
        draft.assumptions.append(
            Qualification(
                id=f"asm-{key}",
                category="assumption",
                text=text,
                basis="standard",
            )
        )

    return draft
