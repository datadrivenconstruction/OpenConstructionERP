# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ``italy`` rule set: an Italian bill read against its prezzario regionale.

The Italy pack declares eleven ``prezzario.*`` rule ids in
``packs/italy-it/.../rule_packs/prezzario_regionale.json``. Five of them are
implemented here, the five a bill can be checked for without a copy of the
regional list it was priced from:

* ``prezzario.voce_code_format_valid`` - a cited voce reads as one. The lists
  that follow the ministry coding print the region, the two digit edition year
  and the item path (``TOS25_01.A03.001.001``, ``VEN26-01.02.01.00``,
  ``LOM261.1C.00.010.0010``); a nuovo prezzo is cited as ``NP``. Older lists
  (Lazio, Umbria) and the chambers of commerce print the item path alone, and
  a line that says which list it is from (``metadata["prezzario"]["region"]``,
  written by the price-list import) is accepted with whatever code that list
  prints: official data never raises this warning by itself. A line imported
  from an XPWE file is accepted the same way, since it cites an item of the
  price list the file carries. What it flags is a code typed by hand that
  names no list.
* ``prezzario.voce_reference_present`` - every leaf line cites a voce or a
  nuovo prezzo.
* ``prezzario.costi_sicurezza_separated`` - the safety costs that are not
  subject to the tender discount stand on a line of their own (D.Lgs. 36/2023
  art. 41 and allegato I.7, D.Lgs. 81/2008 art. 100).
* ``prezzario.incidenza_manodopera_documented`` - every line from a prezzario
  carries its labour share, which the tender has to state separately
  (D.Lgs. 36/2023 art. 41 commi 13-14).
* ``prezzario.overheads_not_applied_twice`` - a bill priced from a prezzario
  does not add general expenses and profit on top. A regional rate already
  carries both (spese generali 13-17 per cent, utile d'impresa 10 per cent),
  so the markups would count them a second time.

The voce is read from ``classification["voci"]``, the key the classification
registry gives Italy and the cost-item import fills; the price-list import also
leaves its region, edition and shares under ``metadata["prezzario"]``. A line
that carries neither is not an Italian line, and the document level rule stays
silent on a bill with no Italian line at all, the way the Hungarian rules treat
a foreign bill in a Hungarian workspace.

The rules live in their own module, like ``project_completeness``, because the
built-in rule file is edited from several directions at once; the registration
in ``register_builtin_rules`` is the only line the two share.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
)
from app.core.validation.messages import translate
from app.core.validation.rules import (
    _get_leaf_positions,
    _get_locale,
    _get_positions,
    _ok,
    _position_metadata,
)

ITALY_RULE_SET = "italy"

# The classification key an Italian voce is filed under. One name with the
# classification registry's standard for IT, so the import, the registry and
# these rules cannot drift apart.
VOCE_CLASSIFICATION_KEY = "voci"

# Where the price-list import leaves what it knows about a line's source.
PREZZARIO_METADATA_KEY = "prezzario"

# The region prefixes of the ministry coding, one per region plus the two
# autonomous provinces (Trento, Bolzano).
REGION_PREFIXES: tuple[str, ...] = (
    "ABR",
    "BAS",
    "CAL",
    "CAM",
    "EMR",
    "FVG",
    "LAZ",
    "LIG",
    "LOM",
    "MAR",
    "MOL",
    "PIE",
    "PUG",
    "SAR",
    "SIC",
    "TOS",
    "UMB",
    "VDA",
    "VEN",
    "TRE",
    "BOL",
)

# Region, edition year, an optional edition digit (Lombardia prints ``LOM261``
# for the first 2026 edition), a separator, then the item path. The year is two
# digits in most lists; Puglia prints four and a slash (``PUG2026/01.E01``).
VOCE_CODE_RE = re.compile(
    r"^(?P<region>" + "|".join(REGION_PREFIXES) + r")(?P<year>20\d{2}|\d{2})(?P<edition>\d)?"
    r"[_./\-](?P<path>[A-Za-z0-9][A-Za-z0-9._\-]*)$"
)

# A nuovo prezzo: a rate the prezzario does not carry, priced by analysis and
# numbered ``NP.01``, ``NP 1``, ``N.P.12`` and so on.
NUOVO_PREZZO_RE = re.compile(r"^N\.?\s?P\.?[\s._\-]*\d+[A-Za-z0-9._\-]*$", re.IGNORECASE)

# An item path as the lists without a region prefix print it: segments of
# letters and digits joined by dots, dashes or spaces ("A1.01.3.a.1",
# "1.1.20.1", "2.1.11.CAM").
_UNPREFIXED_PATH_RE = re.compile(r"^[A-Za-z0-9]+(?:[.\- ][A-Za-z0-9]+)*\.?$")

# A section or line that holds the safety costs. Italian bills name them
# "oneri della sicurezza" or "costi della sicurezza"; the platform's own IT
# markup template names its line "Oneri della sicurezza non soggetti a ribasso".
_SAFETY_TEXT_RE = re.compile(r"\b(?:oneri|costi)\b[^\n]{0,40}\bsicurezza\b", re.IGNORECASE)

# A markup that adds general expenses or profit, by its name in Italian or
# English. The category alone does not say it: "overhead" is the default
# category of every markup line.
_OVERHEAD_PROFIT_RE = re.compile(
    r"spese\s+generali|\butil[ei]\b|general\s+(?:expenses|overheads?)|\boverheads?\b|\bprofit\b",
    re.IGNORECASE,
)

# The share of a bill's lines that must come from a price list before its
# general expenses and profit markups count as applied twice. Below it the
# bill is mostly priced by the estimator's own analysis, where those markups
# belong.
LIST_PRICED_SHARE: Decimal = Decimal("0.5")

# Resource types the BOQ editor files labour under.
_LABOUR_TYPES: frozenset[str] = frozenset({"labor", "labour"})

# Where an XPWE bill line keeps the shares its price-list item states, as
# fractions (``{"labour": "0.3544"}``), and the classification a safety item
# is filed under.
COST_SHARES_KEY = "cost_shares"
SAFETY_COST_TYPE = "sicurezza"


def voce_code(pos: dict[str, Any]) -> str:
    """The voce a position cites, whitespace trimmed, or ``""``."""
    classification = pos.get("classification") or {}
    if not isinstance(classification, dict):
        return ""
    return str(classification.get(VOCE_CLASSIFICATION_KEY) or "").strip()


def prezzario_block(pos: dict[str, Any]) -> dict[str, Any]:
    """What the price-list import recorded about the line, or an empty dict."""
    block = _position_metadata(pos).get(PREZZARIO_METADATA_KEY)
    return block if isinstance(block, dict) else {}


def is_italian_line(pos: dict[str, Any]) -> bool:
    """Whether the line cites a voce or came from an imported Italian list."""
    return bool(voce_code(pos) or prezzario_block(pos))


def looks_like_item_path(value: str) -> bool:
    """Whether ``value`` reads as a list's own item path ("A1.01.3.a.1", "1.1.20.1").

    A path has a digit in it; a word or a phrase in the code column does not
    cite anything.
    """
    compact = value.strip()
    return any(ch.isdigit() for ch in compact) and bool(_UNPREFIXED_PATH_RE.match(compact))


def cites_the_files_own_price_list(pos: dict[str, Any]) -> bool:
    """Whether the line came from an XPWE file and cites an item of its elenco prezzi.

    An XPWE computo carries the price list it is priced from, and every line
    points at one of its items (``xpwe_ep_id``). The code is then the list's
    own, copied by the program that wrote the file, not typed by hand, even
    when the list prints no region prefix and the file does not say which
    region it is.
    """
    return pos.get("source") == "xpwe_import" or "xpwe_ep_id" in _position_metadata(pos)


def voce_code_is_well_formed(code: str, block: dict[str, Any] | None = None) -> bool:
    """Whether ``code`` reads as a voce of a prezzario or as a nuovo prezzo.

    Any other code passes only when ``block`` names the region the line was
    imported from: the list's own numbering, stated as such, is the official
    code whatever its shape, while the same code typed by hand says nothing
    about which of twenty one lists it belongs to.
    """
    compact = code.strip()
    if not compact:
        return False
    if VOCE_CODE_RE.match(compact) or NUOVO_PREZZO_RE.match(compact):
        return True
    return bool(str((block or {}).get("region") or "").strip())


def _has_labour_share(pos: dict[str, Any]) -> bool:
    """Whether the line states its labour share in any of the shapes it can take."""
    block = prezzario_block(pos)
    for key in ("labour_share_pct", "labour_amount"):
        if block.get(key) not in (None, ""):
            return True
    meta = _position_metadata(pos)
    shares = meta.get(COST_SHARES_KEY)
    if isinstance(shares, dict) and shares.get("labour") not in (None, ""):
        return True
    breakdown = meta.get("cost_breakdown")
    if isinstance(breakdown, dict) and any(str(k).lower() in _LABOUR_TYPES for k in breakdown):
        return True
    resources = meta.get("resources")
    if isinstance(resources, list):
        for resource in resources:
            if isinstance(resource, dict) and str(resource.get("type") or "").lower() in _LABOUR_TYPES:
                return True
    return False


def is_safety_line(pos: dict[str, Any]) -> bool:
    """Whether the line itself is a safety cost, by what its source says about it.

    The price-list import marks an item from the safety chapter
    (``prezzario.safety``), an XPWE bill marks a safety item of its list
    (``safety_item``, and the ``sicurezza`` cost type), and a line written by
    hand says so in its description.
    """
    if prezzario_block(pos).get("safety") is True:
        return True
    if _position_metadata(pos).get("safety_item") is True:
        return True
    classification = pos.get("classification")
    if isinstance(classification, dict) and str(classification.get("cost_type") or "").lower() == SAFETY_COST_TYPE:
        return True
    return bool(_SAFETY_TEXT_RE.search(str(pos.get("description") or "")))


def _safety_carried(context: ValidationContext) -> bool:
    """Whether the bill carries its safety costs on a line of their own."""
    data = context.data
    markups = data.get("markups") if isinstance(data, dict) else None
    if isinstance(markups, list):
        for markup in markups:
            if not isinstance(markup, dict) or not markup.get("is_active", True):
                continue
            if _SAFETY_TEXT_RE.search(str(markup.get("name") or "")):
                return True
    return any(is_safety_line(pos) for pos in _get_positions(context))


class PrezzarioVoceCodeFormatValid(ValidationRule):
    rule_id = "prezzario.voce_code_format_valid"
    name = "Prezzario Voce Code Is Well Formed"
    standard = ITALY_RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "A cited voce must read as a prezzario code (region, edition year, item path) or a nuovo prezzo"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_leaf_positions(context):
            code = voce_code(pos)
            if not code:
                # A missing voce is the presence rule's finding, not this one's.
                continue
            block = prezzario_block(pos)
            passed = voce_code_is_well_formed(code, block) or cites_the_files_own_price_list(pos)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=_ok(locale)
                    if passed
                    else translate(
                        "prezzario.voce_code_format_valid.fail",
                        locale=locale,
                        code=code,
                        ordinal=pos.get("ordinal", "?"),
                    ),
                    element_ref=pos.get("id"),
                    details={"given_code": code, "source_region": block.get("region")},
                    suggestion=None
                    if passed
                    else translate("prezzario.voce_code_format_valid.suggestion", locale=locale),
                )
            )
        return results


class PrezzarioVoceReferencePresent(ValidationRule):
    rule_id = "prezzario.voce_reference_present"
    name = "Prezzario Voce Cited"
    standard = ITALY_RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Every line of an Italian bill cites the prezzario voce it is priced from, or a nuovo prezzo"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_leaf_positions(context):
            code = voce_code(pos)
            passed = bool(code)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=_ok(locale)
                    if passed
                    else translate(
                        "prezzario.voce_reference_present.fail",
                        locale=locale,
                        ordinal=pos.get("ordinal", "?"),
                    ),
                    element_ref=pos.get("id"),
                    details={"given_code": code},
                    suggestion=None
                    if passed
                    else translate("prezzario.voce_reference_present.suggestion", locale=locale),
                )
            )
        return results


class PrezzarioCostiSicurezzaSeparated(ValidationRule):
    rule_id = "prezzario.costi_sicurezza_separated"
    name = "Safety Costs On A Line Of Their Own"
    standard = ITALY_RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "The safety costs not subject to the tender discount are carried separately from the works"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        leaves = _get_leaf_positions(context)
        if not any(is_italian_line(pos) for pos in leaves):
            return []
        locale = _get_locale(context)
        passed = _safety_carried(context)
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message=_ok(locale) if passed else translate("prezzario.costi_sicurezza_separated.fail", locale=locale),
                element_ref=None,
                details={"italian_lines": sum(1 for pos in leaves if is_italian_line(pos))},
                suggestion=None
                if passed
                else translate("prezzario.costi_sicurezza_separated.suggestion", locale=locale),
            )
        ]


class PrezzarioIncidenzaManodoperaDocumented(ValidationRule):
    rule_id = "prezzario.incidenza_manodopera_documented"
    name = "Labour Share Stated"
    standard = ITALY_RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Every line priced from a prezzario states its labour share (incidenza della manodopera)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        # A contract workflow (signature, claim, retention) validates the
        # schedule of values, whose lines carry a code and money and no cost
        # breakdown, so no line there could ever state a share. The share is
        # the bill's to state; asking the contract for it would be a warning
        # nobody can clear.
        if context.metadata.get("workflow"):
            return []
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for pos in _get_leaf_positions(context):
            if not is_italian_line(pos):
                continue
            passed = _has_labour_share(pos)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=_ok(locale)
                    if passed
                    else translate(
                        "prezzario.incidenza_manodopera_documented.fail",
                        locale=locale,
                        ordinal=pos.get("ordinal", "?"),
                        code=voce_code(pos) or "-",
                    ),
                    element_ref=pos.get("id"),
                    details={"given_code": voce_code(pos)},
                    suggestion=None
                    if passed
                    else translate("prezzario.incidenza_manodopera_documented.suggestion", locale=locale),
                )
            )
        return results


def _as_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value)) if value not in (None, "") else Decimal(0)
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _bill_wide_markups(context: ValidationContext) -> list[dict[str, Any]]:
    """The bill's markup lines that apply to the whole bill, in the order it compounds them."""
    data = context.data
    markups = data.get("markups") if isinstance(data, dict) else None
    if not isinstance(markups, list):
        return []
    lines = [m for m in markups if isinstance(m, dict) and not m.get("scope_position_id")]
    return sorted(lines, key=lambda m: _as_decimal(m.get("sort_order")))


def is_overhead_or_profit(markup: dict[str, Any]) -> bool:
    """Whether a markup line adds general expenses or profit, by its name or the profit category."""
    name = str(markup.get("name") or "")
    if _SAFETY_TEXT_RE.search(name):
        return False
    return bool(_OVERHEAD_PROFIT_RE.search(name)) or str(markup.get("category") or "") == "profit"


class _MarkupLine:
    """A markup dict read through the attributes the BOQ markup engine reads."""

    def __init__(self, markup: dict[str, Any]) -> None:
        self.id = None
        self.is_active = bool(markup.get("is_active", True))
        self.apply_to = markup.get("apply_to")
        self.markup_type = markup.get("markup_type")
        self.percentage = markup.get("percentage")
        self.fixed_amount = markup.get("fixed_amount")
        self.metadata_ = markup.get("metadata") or {}


def markup_amounts(markups: list[dict[str, Any]], direct: Decimal) -> list[Decimal]:
    """Each markup line's amount on ``direct``, as the bill computes it.

    The validate endpoint hands over the amounts the BOQ markup engine computed
    for the bill (``amount``: escalation factors, scoped overrides and currency
    included), and those are used as given. A caller that hands over only the
    lines gets them run through the same engine,
    :func:`app.modules.boq.service._calculate_markup_amounts`, so contingency
    before general expenses raises their base here exactly as on the bill.
    Nothing here re-derives a base or a rounding of its own.
    """
    active = [m for m in markups if m.get("is_active", True)]
    if active and all(m.get("amount") not in (None, "") for m in active):
        return [_as_decimal(m.get("amount")) if m.get("is_active", True) else Decimal(0) for m in markups]
    from app.modules.boq.service import _calculate_markup_amounts

    lines = [_MarkupLine(m) for m in markups]
    return [amount for _line, amount in _calculate_markup_amounts(direct, lines)]  # type: ignore[arg-type]


def added_share_percent(markups: list[dict[str, Any]], direct: Decimal) -> Decimal:
    """How much the general expenses and profit lines of ``markups`` add, in per cent of ``direct``.

    Every line of the stack goes through the engine, because a line before
    them (contingency, say) raises their base when they compound; only the
    amounts of the general expenses and profit lines are then counted.
    """
    if direct <= 0:
        return Decimal(0)
    amounts = markup_amounts(markups, direct)
    added = sum(
        (
            amount
            for markup, amount in zip(markups, amounts, strict=True)
            if markup.get("is_active", True) and is_overhead_or_profit(markup)
        ),
        Decimal(0),
    )
    return added / direct * 100


def _direct_cost(context: ValidationContext, leaves: list[dict[str, Any]]) -> Decimal:
    """The direct cost the markups were computed on: the engine's own when handed over, else the leaf totals."""
    data = context.data
    stated = data.get("markup_direct_cost") if isinstance(data, dict) else None
    if stated not in (None, ""):
        return _as_decimal(stated)
    return sum((_as_decimal(pos.get("total")) for pos in leaves), Decimal(0))


class PrezzarioOverheadsNotAppliedTwice(ValidationRule):
    rule_id = "prezzario.overheads_not_applied_twice"
    name = "General Expenses And Profit Not Added Twice"
    standard = ITALY_RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "A bill priced from a prezzario does not add general expenses and profit markups, "
        "which the regional rates already include"
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        leaves = _get_leaf_positions(context)
        # A line can cite its list and still carry a rate brought back to direct
        # cost (``rate_includes_overheads: false``), the way a bill priced net
        # of spese generali and utile states it; only list prices count here.
        from_list = [
            pos
            for pos in leaves
            if prezzario_block(pos) and prezzario_block(pos).get("rate_includes_overheads", True) is not False
        ]
        if not leaves or Decimal(len(from_list)) / Decimal(len(leaves)) < LIST_PRICED_SHARE:
            return []
        markups = _bill_wide_markups(context)
        counted = [m for m in markups if m.get("is_active", True) and is_overhead_or_profit(m)]
        direct = _direct_cost(context, leaves)
        exact = added_share_percent(markups, direct)
        # Whole per cent: the finding is about the order of size.
        shown = int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))
        passed = shown < 1
        locale = _get_locale(context)
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message=_ok(locale)
                if passed
                else translate("prezzario.overheads_not_applied_twice.fail", locale=locale, percent=shown),
                element_ref=None,
                details={
                    "markups": [str(m.get("name") or "") for m in counted],
                    "added_percent": shown,
                    "added_percent_exact": format(exact.quantize(Decimal("0.01")).normalize(), "f"),
                    "lines_from_price_list": len(from_list),
                    "leaf_lines": len(leaves),
                },
                suggestion=None
                if passed
                else translate("prezzario.overheads_not_applied_twice.suggestion", locale=locale),
            )
        ]


ITALY_PREZZARIO_RULES: tuple[type[ValidationRule], ...] = (
    PrezzarioVoceCodeFormatValid,
    PrezzarioVoceReferencePresent,
    PrezzarioCostiSicurezzaSeparated,
    PrezzarioIncidenzaManodoperaDocumented,
    PrezzarioOverheadsNotAppliedTwice,
)

__all__ = [
    "ITALY_PREZZARIO_RULES",
    "ITALY_RULE_SET",
    "LIST_PRICED_SHARE",
    "NUOVO_PREZZO_RE",
    "PREZZARIO_METADATA_KEY",
    "REGION_PREFIXES",
    "VOCE_CLASSIFICATION_KEY",
    "VOCE_CODE_RE",
    "cites_the_files_own_price_list",
    "added_share_percent",
    "is_italian_line",
    "is_overhead_or_profit",
    "is_safety_line",
    "markup_amounts",
    "looks_like_item_path",
    "prezzario_block",
    "voce_code",
    "voce_code_is_well_formed",
]
