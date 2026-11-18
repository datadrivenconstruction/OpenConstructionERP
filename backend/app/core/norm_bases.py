# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Norm bases and estimate pricing that a country pack supplies.

Several markets price every line against a national collection of estimating
norms: the line cites a norm code, the norm gives labour hours at an average
grade, machine hours and materials, and the labour is paid per hour at a rate
derived from a monthly estimate wage. The core knows none of those countries.
It answers, for whatever the pack declares:

* does a code have the shape the norm base prescribes, or does it use a
  retired prefix whose current form is known;
* what hourly rate a grade earns from a monthly wage, monthly hours and the
  grade coefficient table, with every intermediate figure kept so a person
  can check the derivation;
* which markup caps a funding class imposes, which labour location factors
  exist, and how many price quotes a material needs.

The data lives in the pack (manifest fields ``norm_bases`` and
``estimate_pricing``). A pack is found by being active, or, for a project
whose country no active pack covers, by declaring that country in its
metadata. Nothing here names a country, a prefix or a percentage.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "CodeCheck",
    "EstimatePricing",
    "FundingClass",
    "LabourGrading",
    "LocationFactor",
    "MarkupCap",
    "NormBase",
    "NormLine",
    "RateDerivation",
    "cost_components",
    "estimate_pricing_for",
    "graded_hourly_rate",
    "label_in",
    "norm_bases_for",
    "pack_for_country",
    "quantize_money",
]

_CENT = Decimal("0.01")


def quantize_money(value: Decimal) -> Decimal:
    """Round to cents, half up, the way an estimate states money."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def label_in(labels: Any, locale: str | None) -> str:
    """Pick a label from a ``{locale: text}`` mapping, falling back to English."""
    if isinstance(labels, str):
        return labels
    if not isinstance(labels, dict):
        return ""
    lang = (locale or "en").split("-")[0].split("_")[0].lower()
    return str(labels.get(lang) or labels.get("en") or next(iter(labels.values()), ""))


# ── Norm base: code shape and retired prefixes ──────────────────────────────


@dataclass(frozen=True)
class CodeCheck:
    """Verdict on one norm code.

    ``status`` is ``ok``, ``legacy`` (a retired prefix with a known current
    form, given in ``suggested``) or ``shape`` (not a code of this base).
    """

    status: str
    code: str
    old_prefix: str | None = None
    new_prefix: str | None = None
    suggested: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class NormBase:
    """A national collection of estimating norms, as a pack declares it."""

    key: str
    name: str
    classification_key: str
    code_pattern: re.Pattern[str]
    code_example: str
    char_map: dict[str, str]
    legacy_prefixes: tuple[tuple[str, str], ...]
    types: tuple[dict[str, Any], ...]
    labour_resource_type: str = "labor"
    grade_field: str = "grade"
    pack_slug: str | None = None
    #: Codes the pack's source quotes with a name: a code known to exist, not just well formed.
    norms: dict[str, str] = field(default_factory=dict, compare=False)

    @classmethod
    def from_document(cls, doc: dict[str, Any], *, pack_slug: str | None = None) -> NormBase:
        """Build from the pack's JSON. Raises ``ValueError`` on a broken file."""
        key = str(doc.get("key") or "").strip()
        pattern = str(doc.get("code_pattern") or "")
        if not key or not pattern:
            raise ValueError("norm base needs a key and a code_pattern")
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"norm base {key!r}: code_pattern does not compile: {exc}") from exc
        legacy = doc.get("legacy_prefixes") or {}
        # Longest first, so a two-letter retired prefix wins over its one-letter head.
        pairs = sorted(((str(o), str(n)) for o, n in legacy.items()), key=lambda p: -len(p[0]))
        labour = doc.get("labour") or {}
        return cls(
            key=key,
            name=str(doc.get("name") or key),
            classification_key=str(doc.get("classification_key") or key),
            code_pattern=compiled,
            code_example=str(doc.get("code_example") or ""),
            char_map={str(k): str(v) for k, v in (doc.get("code_char_map") or {}).items()},
            legacy_prefixes=tuple(pairs),
            types=tuple(t for t in doc.get("types") or [] if isinstance(t, dict)),
            labour_resource_type=str(labour.get("resource_type") or "labor"),
            grade_field=str(labour.get("grade_field") or "grade"),
            pack_slug=pack_slug,
            norms={
                str(n["code"]): str(n.get("title") or "")
                for n in doc.get("norms") or []
                if isinstance(n, dict) and n.get("code")
            },
        )

    def normalise(self, code: Any) -> str:
        """Strip whitespace, upper-case and map look-alike letters the pack names."""
        text = re.sub(r"\s+", "", str(code or "")).upper()
        return "".join(self.char_map.get(ch, ch) for ch in text)

    def code_of(self, position: dict[str, Any]) -> str:
        """The code a position cites under this base's classification key."""
        return self.normalise((position.get("classification") or {}).get(self.classification_key, ""))

    def check(self, code: Any) -> CodeCheck:
        """Classify a code as current, retired prefix or wrong shape."""
        norm = self.normalise(code)
        if self.code_pattern.match(norm):
            return CodeCheck(status="ok", code=norm, title=self.norms.get(norm) or None)
        for old, new in self.legacy_prefixes:
            if norm.startswith(old):
                candidate = new + norm[len(old) :]
                if self.code_pattern.match(candidate):
                    return CodeCheck(status="legacy", code=norm, old_prefix=old, new_prefix=new, suggested=candidate)
        return CodeCheck(status="shape", code=norm)


# ── Estimate pricing: grades, caps, factors, evidence ───────────────────────


@dataclass(frozen=True)
class LabourGrading:
    """Grade coefficients for an hourly rate derived from a monthly wage."""

    base_grade: Decimal
    grade_min: Decimal
    grade_max: Decimal
    grade_step: Decimal
    coefficients: dict[Decimal, Decimal]
    status: str = "sourced"
    source: str = ""

    def coefficient(self, grade: Decimal) -> Decimal | None:
        """The coefficient the table holds for ``grade``, or ``None``."""
        return self.coefficients.get(grade.quantize(self.grade_step))

    def in_range(self, grade: Decimal) -> bool:
        """Whether the grade lies in range and on the table's step."""
        if grade < self.grade_min or grade > self.grade_max:
            return False
        return (grade / self.grade_step) == (grade / self.grade_step).to_integral_value()


@dataclass(frozen=True)
class MarkupCap:
    key: str
    label: dict[str, str]
    names: tuple[str, ...]
    category: str | None
    cap_percent: Decimal

    def matches(self, markup: dict[str, Any]) -> bool:
        """A markup line answers to this cap by name, or by category when named."""
        name = re.sub(r"\s+", " ", str(markup.get("name") or "")).strip().casefold()
        if any(name == n.casefold() or name.startswith(n.casefold()) for n in self.names):
            return True
        return bool(self.category) and str(markup.get("category") or "").strip().lower() == self.category


@dataclass(frozen=True)
class FundingClass:
    key: str
    label: dict[str, str]
    source: str
    markup_caps: tuple[MarkupCap, ...]
    investor_estimate_at_cap: bool
    min_quotes: int | None


@dataclass(frozen=True)
class LocationFactor:
    key: str
    label: dict[str, str]
    factor: Decimal
    source: str


@dataclass(frozen=True)
class EstimatePricing:
    """The pack's pricing rules: grading, funding classes, location factors."""

    key: str
    currency: str | None
    grading: LabourGrading | None
    default_monthly_hours: Decimal | None
    funding_classes: tuple[FundingClass, ...]
    location_factors: tuple[LocationFactor, ...]
    pack_slug: str | None = None
    #: Column layout of the market's estimate sheet, read by the neutral exporter.
    export_layout: dict[str, Any] | None = field(default=None, compare=False)
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_document(cls, doc: dict[str, Any], *, pack_slug: str | None = None) -> EstimatePricing:
        """Build from the pack's JSON. Raises ``ValueError`` on a broken file."""
        key = str(doc.get("key") or "").strip()
        if not key:
            raise ValueError("estimate pricing without a key")
        grading = None
        g = doc.get("labour_grading")
        if isinstance(g, dict):
            coeffs: dict[Decimal, Decimal] = {}
            for grade, k in (g.get("coefficients") or {}).items():
                gd, kd = _dec(grade), _dec(k)
                if gd is None or kd is None or kd <= 0:
                    raise ValueError(f"estimate pricing {key!r}: bad coefficient {grade!r}: {k!r}")
                coeffs[gd] = kd
            parts = [_dec(g.get(f)) for f in ("base_grade", "grade_min", "grade_max", "grade_step")]
            if any(p is None for p in parts):
                raise ValueError(f"estimate pricing {key!r}: grading needs base, min, max and step")
            base, lo, hi, step = parts  # type: ignore[misc]
            if base not in coeffs:
                raise ValueError(f"estimate pricing {key!r}: the base grade has no coefficient")
            grading = LabourGrading(
                base, lo, hi, step, coeffs, str(g.get("status") or "sourced"), str(g.get("source") or "")
            )
        classes = []
        for fc in doc.get("funding_classes") or []:
            caps = tuple(
                MarkupCap(
                    key=str(c["key"]),
                    label=dict(c.get("label") or {}),
                    names=tuple(str(n) for n in c.get("names") or []),
                    category=(str(c["category"]).lower() if c.get("category") else None),
                    cap_percent=Decimal(str(c["cap_percent"])),
                )
                for c in fc.get("markup_caps") or []
            )
            evidence = fc.get("price_evidence") or {}
            classes.append(
                FundingClass(
                    key=str(fc["key"]),
                    label=dict(fc.get("label") or {}),
                    source=str(fc.get("source") or ""),
                    markup_caps=caps,
                    investor_estimate_at_cap=bool(fc.get("investor_estimate_at_cap")),
                    min_quotes=int(evidence["min_quotes"]) if evidence.get("min_quotes") else None,
                )
            )
        factors = tuple(
            LocationFactor(
                key=str(f["key"]),
                label=dict(f.get("label") or {}),
                factor=Decimal(str(f["factor"])),
                source=str(f.get("source") or ""),
            )
            for f in doc.get("labour_location_factors") or []
        )
        defaults = doc.get("defaults") or {}
        return cls(
            key=key,
            currency=doc.get("currency"),
            grading=grading,
            default_monthly_hours=_dec(defaults.get("monthly_hours")),
            funding_classes=tuple(classes),
            location_factors=factors,
            pack_slug=pack_slug,
            export_layout=doc["export_layout"] if isinstance(doc.get("export_layout"), dict) else None,
            raw=doc,
        )

    def funding_class(self, key: Any) -> FundingClass | None:
        return next((f for f in self.funding_classes if f.key == key), None)

    def location_factor(self, key: Any) -> LocationFactor | None:
        return next((f for f in self.location_factors if f.key == key), None)


@dataclass(frozen=True)
class RateDerivation:
    """An hourly rate and every figure it was derived from."""

    grade: Decimal
    base_grade: Decimal
    base_rate: Decimal
    grade_one_rate: Decimal
    coefficient: Decimal
    rate: Decimal


def graded_hourly_rate(
    monthly_wage: Decimal,
    monthly_hours: Decimal,
    grade: Decimal,
    grading: LabourGrading,
) -> RateDerivation:
    """Hourly rate for ``grade`` from a monthly wage paid at the base grade.

    ``V(base) = wage / hours``, ``V(1) = V(base) / k(base)``,
    ``V(g) = V(1) x k(g)``, each rounded to cents as the estimate states it.
    The base grade's own rate is ``V(base)`` itself, not re-derived through
    ``V(1)``, so the two cannot drift by a cent.

    Raises:
        ValueError: hours not positive, grade off the scale, or no coefficient.
    """
    if monthly_hours <= 0:
        raise ValueError("monthly hours must be positive")
    if not grading.in_range(grade):
        raise ValueError(f"grade {grade} is outside the scale")
    k = grading.coefficient(grade)
    k_base = grading.coefficient(grading.base_grade)
    if k is None or k_base is None:
        raise ValueError(f"grade {grade} has no coefficient in the table")
    base_rate = quantize_money(monthly_wage / monthly_hours)
    grade_one = quantize_money(base_rate / k_base)
    rate = base_rate if grade == grading.base_grade else quantize_money(grade_one * k)
    return RateDerivation(grade, grading.base_grade, base_rate, grade_one, k, rate)


@dataclass(frozen=True)
class NormLine:
    """One resource of a norm-priced line: labour hours, machine hours or a material."""

    kind: str  # "labor" | "machine" | "material"
    quantity: Decimal
    rate: Decimal


def cost_components(lines: list[NormLine], labour_factor: Decimal = Decimal("1")) -> dict[str, Decimal]:
    """Labour, machine and material totals of norm-priced resources.

    Each resource amount is rounded to cents. A labour location factor applies
    to the labour amounts only, after rounding each, so machines and materials
    never carry it.
    """
    totals = {"labor": Decimal("0"), "machine": Decimal("0"), "material": Decimal("0")}
    for line in lines:
        amount = quantize_money(line.quantity * line.rate)
        if line.kind == "labor" and labour_factor != 1:
            amount = quantize_money(amount * labour_factor)
        totals[line.kind] = totals.get(line.kind, Decimal("0")) + amount
    totals["direct"] = totals["labor"] + totals["machine"] + totals["material"]
    return totals


# ── Finding the pack ────────────────────────────────────────────────────────


def pack_for_country(country_code: str | None) -> Any | None:
    """The pack whose norm data applies to a project in ``country_code``.

    The active pack wins when it carries norm data and covers the country (or
    the project has no country). Otherwise a discovered country pack that
    declares the country in its metadata answers, so a Ukrainian project in a
    workspace running another pack is still checked against its own base.
    """
    try:
        from app.core.partner_pack.discovery import discover_packs, get_active_pack
    except ImportError:  # pragma: no cover - the pack system is part of the core
        return None
    country = (country_code or "").strip().upper()

    def _carries(pack: Any) -> bool:
        return bool(getattr(pack, "norm_bases", None) or getattr(pack, "estimate_pricing", None))

    def _country(pack: Any) -> str:
        return str((getattr(pack, "metadata", None) or {}).get("country") or "").upper()

    active = get_active_pack()
    if active is not None and _carries(active) and (not country or _country(active) == country):
        return active
    if not country:
        return None
    try:
        packs = discover_packs()
    except Exception:  # noqa: BLE001 - discovery failure must not break validation
        logger.warning("Pack discovery failed while resolving norm data", exc_info=True)
        return None
    return next((p for p in packs if _carries(p) and _country(p) == country), None)


def _read_json(pack: Any, rel: str) -> dict[str, Any] | None:
    from app.core.partner_pack.discovery import read_pack_file

    raw = read_pack_file(pack.slug, rel)
    if raw is None:
        logger.warning("Pack %s names %s but does not carry it", pack.slug, rel)
        return None
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        logger.warning("Pack %s file %s cannot be read: %s", pack.slug, rel, exc)
        return None
    return doc if isinstance(doc, dict) else None


def norm_bases_for(country_code: str | None) -> list[NormBase]:
    """Norm bases that apply to a project in ``country_code``; empty when none."""
    pack = pack_for_country(country_code)
    if pack is None:
        return []
    bases: list[NormBase] = []
    for rel in getattr(pack, "norm_bases", None) or []:
        doc = _read_json(pack, rel)
        if doc is None:
            continue
        try:
            bases.append(NormBase.from_document(doc, pack_slug=pack.slug))
        except ValueError as exc:
            logger.warning("Pack %s norm base %s is not valid: %s", pack.slug, rel, exc)
    return bases


def estimate_pricing_for(country_code: str | None) -> EstimatePricing | None:
    """The pricing rules for a project in ``country_code``, or ``None``."""
    pack = pack_for_country(country_code)
    rel = getattr(pack, "estimate_pricing", None) if pack is not None else None
    if not rel:
        return None
    doc = _read_json(pack, rel)
    if doc is None:
        return None
    try:
        return EstimatePricing.from_document(doc, pack_slug=pack.slug)
    except (ValueError, KeyError, InvalidOperation) as exc:
        logger.warning("Pack %s estimate pricing is not valid: %s", pack.slug, exc)
        return None
