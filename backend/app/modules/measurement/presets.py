# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Presentation and interchange presets for measurement sheets.

The sheet model is country-neutral. A preset only fixes labelling and the
rounding convention used when a quantity is written out. REB 23.003 (the German
measurement rules, sheets DA11 detailed and DA12 summary) and OENORM A 2063
(the Austrian data exchange) round to three decimals and are the DACH
conventions; the international preset is the sensible default elsewhere. Adding
a convention is one entry in ``PRESETS``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.modules.measurement.model import MeasurementSheet, _dec


@dataclass(frozen=True)
class Preset:
    """Labelling and rounding convention for a measurement sheet.

    Attributes:
        name: Machine key, e.g. ``"reb"`` or ``"international"``.
        label: Human-readable title shown at the top of a rendered sheet.
        region: ISO 3166-1 alpha-2 country code, or ``"international"``.
        decimals: Number of decimal places for quantity rounding.
        standard: Name of the measurement standard, if any.
    """

    name: str
    label: str
    region: str
    decimals: int = 3
    standard: str = ""


_INTERNATIONAL = Preset(
    name="international",
    label="Measurement sheet",
    region="international",
    decimals=3,
    standard="",
)
_REB = Preset(
    name="reb",
    label="REB 23.003 measurement (DA11/DA12)",
    region="DE",
    decimals=3,
    standard="REB 23.003",
)
_OENORM = Preset(
    name="oenorm",
    label="OENORM A 2063 measurement",
    region="AT",
    decimals=3,
    standard="OENORM A 2063",
)

PRESETS: dict[str, Preset] = {p.name: p for p in (_INTERNATIONAL, _REB, _OENORM)}


def get_preset(name: str | None) -> Preset:
    """Look up a preset by name, falling back to the international default.

    Args:
        name: Preset key (case-insensitive), or ``None`` for the default.

    Returns:
        The matching :class:`Preset`, or the international preset if *name*
        is unknown or ``None``.
    """
    return PRESETS.get((name or "").strip().lower(), _INTERNATIONAL)


#: ``region`` -> preset name, built from the presets themselves so a preset
#: added with a region is reachable without a second list to keep in step.
#:
#: "international" is skipped rather than indexed: it is the fallback below,
#: which is what a market with no convention of its own should get anyway.
#:
#: There is no alias table here, unlike the price-breakdown presets, which need
#: one because they tag the British convention "UK" while the country column
#: holds the ISO code "GB". Every measurement preset is tagged with the ISO
#: code already, so an alias table would be an empty dict. The omission is
#: measured, not overlooked.
_PRESET_BY_REGION: dict[str, str] = {
    preset.region.upper(): name
    for name, preset in PRESETS.items()
    if preset.region and preset.region.lower() != "international"
}


def preset_for_country(country_code: str | None) -> str:
    """Name of the preset a project in this country should be measured with.

    The sibling of :func:`app.modules.price_breakdown.presets.preset_for_country`
    and deliberately the same mechanism: ``Preset.region`` is the market table,
    and this reads it. A measurement sheet is a document an auditor checks
    against their own market's rules, and REB 23.003 and OENORM A 2063 are
    those rules in Germany and Austria. Both presets have shipped since the
    module was written and nothing selected either one: the endpoints defaulted
    to the international preset by name, so a German quantity surveyor got the
    international sheet unless they knew to type ``preset=reb`` into a query
    string.

    Germany and Austria are separate rows on purpose. They share a language and
    not a form, and handing an Austrian project the German sheet because the
    words look familiar is the substitution the neutral preset exists to avoid.
    Switzerland shares the language too and has no measurement preset of its
    own, so it gets the neutral one.

    Args:
        country_code: ISO 3166-1 alpha-2, case-insensitive, or ``None``.

    Returns:
        A key of :data:`PRESETS`. ``"international"`` for a market with no
        preset of its own, and for no market at all, which are the same answer
        here: the neutral preset is the one that assumes nothing.
    """
    code = (country_code or "").strip().upper()
    if not code:
        return _INTERNATIONAL.name
    return _PRESET_BY_REGION.get(code, _INTERNATIONAL.name)


def _q(value: Decimal, decimals: int) -> str:
    quant = Decimal(1).scaleb(-decimals)  # 10**-decimals
    return str(_dec(value).quantize(quant, rounding=ROUND_HALF_UP))


def render_markdown(sheet: MeasurementSheet, *, preset: str = "international") -> str:
    """Render a measurement sheet as a Markdown table.

    Every line shows its formula, factor, sign and resulting quantity,
    rounded according to the preset's convention.

    Args:
        sheet: The measurement sheet to render.
        preset: Preset name controlling rounding and heading labels.

    Returns:
        A complete Markdown document with a heading, table and total.
    """
    p = get_preset(preset)
    out: list[str] = []
    heading = f"# {p.label}: {sheet.item_ref} {sheet.description}".rstrip()
    out.append(heading)
    out.append("")
    out.append(f"Unit: {sheet.unit}")
    out.append("")
    out.append("| Ref | Description | Formula | Factor | Sign | Quantity |")
    out.append("| --- | --- | --- | ---: | :---: | ---: |")
    for ln in sheet.lines:
        formula = ln.formula if not ln.error else f"{ln.formula}  [error: {ln.error}]"
        out.append(
            f"| {ln.ref} | {ln.description} | {formula} | "
            f"{_dec(ln.factor, '1')} | {'-' if str(ln.sign).strip() == '-' else '+'} | "
            f"{_q(ln.raw_quantity, p.decimals)} |"
        )
    out.append("")
    out.append(f"Total quantity: {_q(sheet.total_quantity, p.decimals)} {sheet.unit}")
    return "\n".join(out)


def render_csv(sheet: MeasurementSheet, *, preset: str = "international") -> str:
    """Render a measurement sheet as CSV (RFC 4180 quoting).

    Suitable for spreadsheet import. Includes a header row, one row per
    line, and a TOTAL row at the bottom.

    Args:
        sheet: The measurement sheet to render.
        preset: Preset name controlling quantity rounding.

    Returns:
        A CSV string with ``\\r\\n`` line endings.
    """
    p = get_preset(preset)
    rows: list[str] = []
    rows.append(_csv_row(["ref", "description", "formula", "factor", "sign", "unit", "quantity", "error"]))
    for ln in sheet.lines:
        rows.append(
            _csv_row(
                [
                    ln.ref,
                    ln.description,
                    ln.formula,
                    str(_dec(ln.factor, "1")),
                    "-" if str(ln.sign).strip() == "-" else "+",
                    ln.unit or sheet.unit,
                    _q(ln.raw_quantity, p.decimals),
                    ln.error,
                ]
            )
        )
    rows.append(_csv_row(["", "TOTAL", "", "", "", sheet.unit, _q(sheet.total_quantity, p.decimals), ""]))
    return "\r\n".join(rows) + "\r\n"


def _csv_row(fields: list[str]) -> str:
    out: list[str] = []
    for raw in fields:
        text = str(raw if raw is not None else "")
        if any(ch in text for ch in (",", '"', "\n", "\r")):
            text = '"' + text.replace('"', '""') + '"'
        out.append(text)
    return ",".join(out)
