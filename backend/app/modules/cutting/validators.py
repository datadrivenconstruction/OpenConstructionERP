# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for cutting jobs and plans (rule set ``cutting``).

A cutting plan becomes a purchase quantity and a shop instruction, so the job is
checked before it is optimised and the plan after:

``cutting.has_pieces`` / ``cutting.has_stock``
    Nothing to optimise without a cut list and something to cut it from.
``cutting.sheet_dimensions``
    A sheet job needs both dimensions on every piece and stock entry.
``cutting.piece_fits_stock``
    Every piece fits at least one stock entry after trim. A piece longer than any
    bar is otherwise silently missing from the order.
``cutting.grain_allows_fit``
    A sheet piece locked to the grain that would only fit turned across it.
``cutting.kerf_set``
    A zero saw kerf overstates the yield of every multi-cut bar.
``cutting.min_offcut_set``
    Without a minimum usable offcut every remnant counts as waste.
``cutting.stock_priced``
    Purchasable stock without a unit cost leaves the plan without a cost.
``cutting.stock_sufficient``
    The plan placed every piece; limited stock can leave some unplaced.
``cutting.yield_threshold``
    The plan's yield reaches the job's threshold.

Messages resolve through :func:`app.core.i18n.t` under ``cutting.validation``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.i18n import t
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

RULE_SET = "cutting"
_STANDARD = "universal"


def _locale(context: ValidationContext) -> str | None:
    return context.metadata.get("locale") or None


def _job(context: ValidationContext) -> Any:
    data = context.data
    return data.get("job") if isinstance(data, dict) else None


def _plan(context: ValidationContext) -> Any:
    data = context.data
    return data.get("plan") if isinstance(data, dict) else None


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _result(
    rule: ValidationRule,
    *,
    passed: bool,
    locale: str | None,
    element_ref: str | None = None,
    details: dict[str, Any] | None = None,
    **params: Any,
) -> RuleResult:
    key = rule.rule_id.split(".", 1)[1]
    if passed:
        message = t("cutting.validation.ok", locale=locale)
        suggestion = None
    else:
        message = t(f"cutting.validation.{key}.fail", locale=locale, **params)
        suggestion = t(f"cutting.validation.{key}.suggestion", locale=locale)
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=element_ref,
        details=details or {},
        suggestion=suggestion,
    )


def piece_fits(job: Any, piece: Any, *, allow_rotation: bool | None = None) -> bool:
    """Whether a piece fits at least one stock entry of the job after trim."""
    trim = _dec(job.trim_mm)
    rotate = piece.rotatable if allow_rotation is None else allow_rotation
    for stock in job.stocks:
        if job.kind == "sheet":
            if piece.width_mm is None or stock.width_mm is None:
                continue
            sw, sh = _dec(stock.length_mm) - 2 * trim, _dec(stock.width_mm) - 2 * trim
            pl, pw = _dec(piece.length_mm), _dec(piece.width_mm)
            if (pl <= sw and pw <= sh) or (rotate and pw <= sw and pl <= sh):
                return True
        elif _dec(piece.length_mm) <= _dec(stock.length_mm) - trim:
            return True
    return False


class HasPieces(ValidationRule):
    """The job has at least one demanded piece."""

    rule_id = "cutting.has_pieces"
    name = "Cut list present"
    standard = _STANDARD
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        job = _job(context)
        if job is None:
            return []
        return [_result(self, passed=bool(job.pieces), locale=_locale(context), element_ref=f"job:{job.id}")]


class HasStock(ValidationRule):
    """The job offers at least one stock entry."""

    rule_id = "cutting.has_stock"
    name = "Stock present"
    standard = _STANDARD
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        job = _job(context)
        if job is None:
            return []
        return [_result(self, passed=bool(job.stocks), locale=_locale(context), element_ref=f"job:{job.id}")]


class SheetDimensions(ValidationRule):
    """Every piece and stock entry of a sheet job carries a width."""

    rule_id = "cutting.sheet_dimensions"
    name = "Sheet dimensions complete"
    standard = _STANDARD
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        job = _job(context)
        if job is None or job.kind != "sheet":
            return []
        out = []
        for kind, rows in (("piece", job.pieces), ("stock", job.stocks)):
            for row in rows:
                if row.width_mm is None:
                    out.append(
                        _result(
                            self, passed=False, locale=_locale(context), element_ref=f"{kind}:{row.ref}", ref=row.ref
                        )
                    )
        return out or [_result(self, passed=True, locale=_locale(context), element_ref=f"job:{job.id}")]


class PieceFitsStock(ValidationRule):
    """Every piece fits at least one stock entry after trim."""

    rule_id = "cutting.piece_fits_stock"
    name = "Piece fits stock"
    standard = _STANDARD
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        job = _job(context)
        if job is None or not job.stocks:
            return []
        out = []
        for piece in job.pieces:
            if job.kind == "sheet" and piece.width_mm is None:
                continue
            if not piece_fits(job, piece, allow_rotation=True):
                size = f"{piece.length_mm}" if job.kind != "sheet" else f"{piece.length_mm} x {piece.width_mm}"
                out.append(
                    _result(
                        self,
                        passed=False,
                        locale=_locale(context),
                        element_ref=f"piece:{piece.ref}",
                        details={"ref": piece.ref, "size_mm": size},
                        ref=piece.ref,
                        size=size,
                    )
                )
        return out or [_result(self, passed=True, locale=_locale(context), element_ref=f"job:{job.id}")]


class GrainAllowsFit(ValidationRule):
    """A grain-locked sheet piece is not one that would only fit turned."""

    rule_id = "cutting.grain_allows_fit"
    name = "Grain direction allows fit"
    standard = _STANDARD
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        job = _job(context)
        if job is None or job.kind != "sheet" or not job.stocks:
            return []
        out = []
        for piece in job.pieces:
            if piece.rotatable or piece.width_mm is None:
                continue
            if not piece_fits(job, piece, allow_rotation=False) and piece_fits(job, piece, allow_rotation=True):
                out.append(
                    _result(
                        self, passed=False, locale=_locale(context), element_ref=f"piece:{piece.ref}", ref=piece.ref
                    )
                )
        return out or [_result(self, passed=True, locale=_locale(context), element_ref=f"job:{job.id}")]


class KerfSet(ValidationRule):
    """The saw kerf is set."""

    rule_id = "cutting.kerf_set"
    name = "Saw kerf set"
    standard = _STANDARD
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        job = _job(context)
        if job is None:
            return []
        return [_result(self, passed=_dec(job.kerf_mm) > 0, locale=_locale(context), element_ref=f"job:{job.id}")]


class MinOffcutSet(ValidationRule):
    """A minimum usable offcut is set, so remnants can be kept."""

    rule_id = "cutting.min_offcut_set"
    name = "Minimum offcut set"
    standard = _STANDARD
    severity = Severity.INFO
    category = RuleCategory.COMPLETENESS

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        job = _job(context)
        if job is None:
            return []
        return [_result(self, passed=_dec(job.min_offcut_mm) > 0, locale=_locale(context), element_ref=f"job:{job.id}")]


class StockPriced(ValidationRule):
    """Every purchasable stock entry carries a unit cost."""

    rule_id = "cutting.stock_priced"
    name = "Stock priced"
    standard = _STANDARD
    severity = Severity.INFO
    category = RuleCategory.COMPLETENESS

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        job = _job(context)
        if job is None:
            return []
        out = [
            _result(self, passed=False, locale=_locale(context), element_ref=f"stock:{s.ref}", ref=s.ref)
            for s in job.stocks
            if not s.is_offcut and _dec(s.unit_cost) <= 0
        ]
        return out or [_result(self, passed=True, locale=_locale(context), element_ref=f"job:{job.id}")]


class StockSufficient(ValidationRule):
    """The plan placed every demanded piece."""

    rule_id = "cutting.stock_sufficient"
    name = "Stock sufficient"
    standard = _STANDARD
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        plan = _plan(context)
        if plan is None:
            return []
        missing = int(plan.pieces_unplaced or 0)
        return [
            _result(
                self,
                passed=missing == 0,
                locale=_locale(context),
                element_ref="plan",
                details={"unplaced": list(plan.unplaced or [])},
                count=missing,
            )
        ]


class YieldThreshold(ValidationRule):
    """The plan's yield reaches the job's threshold."""

    rule_id = "cutting.yield_threshold"
    name = "Yield threshold"
    standard = _STANDARD
    severity = Severity.WARNING
    category = RuleCategory.QUALITY

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        plan = _plan(context)
        job = _job(context)
        if plan is None or job is None or not plan.stock_count:
            return []
        actual = _dec(plan.yield_pct)
        threshold = _dec(job.yield_threshold_pct)
        return [
            _result(
                self,
                passed=actual >= threshold,
                locale=_locale(context),
                element_ref="plan",
                details={"yield_pct": str(actual), "threshold_pct": str(threshold)},
                actual=actual,
                threshold=threshold,
            )
        ]


RULES: tuple[type[ValidationRule], ...] = (
    HasPieces,
    HasStock,
    SheetDimensions,
    PieceFitsStock,
    GrainAllowsFit,
    KerfSet,
    MinOffcutSet,
    StockPriced,
    StockSufficient,
    YieldThreshold,
)


def register_rules() -> None:
    """Register the ``cutting`` rule set (called from the startup hook, not at import)."""
    for rule_class in RULES:
        rule_registry.register(rule_class(), rule_sets=[RULE_SET])


__all__ = ["RULES", "RULE_SET", "piece_fits", "register_rules"]
