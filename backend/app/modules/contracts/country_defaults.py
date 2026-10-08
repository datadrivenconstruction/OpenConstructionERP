# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The payment terms a contract usually starts from, per country. Data, not branches.

A contract written in Germany, the United Kingdom or the Gulf does not start
from a blank page. Each market has a usual retention figure, a usual ceiling on
it, a usual way of paying it back, a payment period and a name for the interim
certificate. This module is the one place those figures are written down, so a
new contract can start from them instead of from a single platform-wide 5
percent that was, in effect, a German habit applied everywhere.

Rules this table keeps:

* **A default pre-fills and never locks.** Every figure here is what a contract
  starts from when its author states nothing. Anything the author sends wins,
  including a value equal to the default, and every value stays editable.
* **No country, no figures.** A country that has no row resolves to ``None``,
  not to Germany and not to an average. The caller must leave the field for a
  person to fill. :func:`resolve_contract_defaults` is the only reader, and it
  never falls back to another country's row.
* **Every figure says where it came from.** ``source`` is ``statute`` when a
  law states it, ``standard_form`` when a published contract form does, and
  ``industry_practice`` when it is the usual agreed figure and nothing more.
  ``reference`` names the clause, ``note`` says it in a sentence.
* **A field with no usual figure is ``None`` and says why.** Brazil has no
  days-to-pay rule, Russia leaves the period to the contract; the note says so
  rather than a number standing in for the silence.
* **Where a regional pack already writes the release events, the pack governs.**
  Germany and the United States carry their release events, with the documents
  each event needs, in the regional pack. Their rows here say
  ``"regional_pack"`` for the split and the resolver reads the percentages from
  the pack, so the two can never disagree.

Release percentages follow the engine's own convention, which is the trap in
this table: ``release_percent_of_held`` is the percent of what is *held at that
event*, not of the original retention. "Half at completion, the rest at the
end of the defects period" is therefore ``50`` then ``100``. Writing ``50`` and
``50`` would leave a quarter of the retention with no event that ever pays it.
"""

from __future__ import annotations

import copy
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.contracts.retention import CANONICAL_RELEASE_EVENTS

#: The payment-term fields a country row can pre-fill, in the order a form shows them.
CONTRACT_DEFAULT_FIELDS: tuple[str, ...] = (
    "retention_percent",
    "retention_cap_percent",
    "retention_release_split",
    "payment_period_days",
    "valuation_interval",
    "certificate_name",
)

#: The fields that live in ``Contract.terms["payment_terms"]``; the retention
#: rate has a column of its own.
PAYMENT_TERM_FIELDS: tuple[str, ...] = tuple(f for f in CONTRACT_DEFAULT_FIELDS if f != "retention_percent")

#: Where a contract keeps the payment terms that have no column.
PAYMENT_TERMS_KEY = "payment_terms"

#: Where a contract records which of its figures came from this table.
DEFAULTS_STAMP_KEY = "country_defaults"

#: How often the work is valued for an interim payment.
VALUATION_INTERVALS: tuple[str, ...] = ("monthly", "four_weekly", "fortnightly", "weekly", "milestone")

#: What a figure's ``source`` may say.
SOURCES: tuple[str, ...] = ("statute", "standard_form", "industry_practice", "regional_pack")

#: The split's value when the regional pack's release events govern.
FROM_REGIONAL_PACK = "regional_pack"

#: The platform's historical figures, used only when a contract names no
#: retention and its country has no row. They are stamped as a fallback on the
#: contract so nobody reads them as a country's rule.
PLATFORM_FALLBACK: dict[str, Any] = {
    "retention_percent": "5",
    "retention_release_event": "substantial_completion",
}

#: Other spellings a project may carry for a country this table keys by ISO 3166-1.
COUNTRY_ALIASES: dict[str, str] = {"UK": "GB"}

#: Where the notes live in the client's locale files:
#: ``contracts.country_defaults.<CC>.<field>.note``.
NOTE_KEY_PREFIX = "contracts.country_defaults."


def _figure(value: Any, source: str, reference: str, note: str) -> dict[str, Any]:
    return {"value": value, "source": source, "reference": reference, "note": note}


def _split(*steps: tuple[str, str]) -> list[dict[str, str]]:
    return [{"event": event, "release_percent_of_held": percent} for event, percent in steps]


# FIDIC is written once and used for both Gulf markets, because the figures come
# from the form and its usual Contract Data entries, not from either country's law.
_FIDIC_GULF: dict[str, Any] = {
    "standard_form": "FIDIC Red Book 2017",
    "retention_percent": _figure(
        "10",
        "standard_form",
        "FIDIC Red Book 2017, Sub-Clause 14.3(iii) and the Contract Data",
        "The Contract Data states the percentage kept from each interim payment; ten percent is the usual "
        "Gulf entry, kept until the limit of retention money is reached.",
    ),
    "retention_cap_percent": _figure(
        "5",
        "standard_form",
        "FIDIC Red Book 2017, Sub-Clause 14.3(iii), Limit of Retention Money",
        "Retention stops at the limit stated in the Contract Data, usually five percent of the Accepted "
        "Contract Amount, so the ten percent rate stops biting at half the contract value.",
    ),
    "retention_release_split": _figure(
        _split(("substantial_completion", "50"), ("defects_period_end", "100")),
        "standard_form",
        "FIDIC Red Book 2017, Sub-Clause 14.9",
        "Half is paid back when the Taking-Over Certificate is issued and the rest when the Defects "
        "Notification Period expires.",
    ),
    "payment_period_days": _figure(
        56,
        "standard_form",
        "FIDIC Red Book 2017, Sub-Clause 14.7(b)",
        "Each interim payment is due within 56 days after the Engineer receives the Statement and its "
        "supporting documents.",
    ),
    "valuation_interval": _figure(
        "monthly",
        "standard_form",
        "FIDIC Red Book 2017, Sub-Clause 14.3",
        "The contractor submits a Statement after the end of each month.",
    ),
    "certificate_name": _figure(
        "Interim Payment Certificate (IPC)",
        "standard_form",
        "FIDIC Red Book 2017, Sub-Clause 14.6",
        "The Engineer certifies each interim payment on an IPC.",
    ),
}


#: The table. Keyed by ISO 3166-1 alpha-2. Every figure is a dict made by
#: :func:`_figure`; a figure whose ``value`` is ``None`` has no usual value in
#: that market and its note says why.
COUNTRY_CONTRACT_DEFAULTS: dict[str, dict[str, Any]] = {
    "DE": {
        "standard_form": "VOB/B",
        "retention_percent": _figure(
            "5",
            "industry_practice",
            "§ 17 Abs. 6 Nr. 1 VOB/B; § 9c Abs. 2 VOB/A",
            "VOB/B lets the client keep back up to ten percent of each payment until the agreed security sum "
            "is reached; five percent is the security most contracts agree, and the ceiling for public clients.",
        ),
        "retention_cap_percent": _figure(
            "5",
            "industry_practice",
            "§ 17 Abs. 6 Nr. 1 VOB/B; § 9c Abs. 2 Satz 1 VOB/A",
            "The cut stops at the agreed security sum, usually five percent of the contract sum. It binds "
            "where billed work runs past the contract sum, as on a remeasured contract.",
        ),
        "retention_release_split": _figure(
            FROM_REGIONAL_PACK,
            "regional_pack",
            "§ 17 Abs. 8 VOB/B",
            "Released at acceptance against a defects security, and that security two years after acceptance; "
            "the regional pack carries the events and the documents each one needs.",
        ),
        "payment_period_days": _figure(
            21,
            "standard_form",
            "§ 16 Abs. 1 Nr. 3 VOB/B",
            "Where the contract incorporates VOB/B, interim payments fall due within 21 days of the client "
            "receiving the statement of work. VOB/B binds only when agreed; a contract under the BGB alone "
            "follows its rules instead.",
        ),
        "valuation_interval": _figure(
            "monthly",
            "industry_practice",
            "§ 16 Abs. 1 Nr. 1 VOB/B",
            "VOB/B asks for intervals as short as possible; a monthly statement is the usual agreed rhythm.",
        ),
        "certificate_name": _figure(
            "Abschlagsrechnung",
            "standard_form",
            "§ 16 Abs. 1 VOB/B; § 632a BGB",
            "The interim invoice for work done, the basis of each interim payment.",
        ),
    },
    "GB": {
        "standard_form": "JCT 2016 / NEC4",
        "retention_percent": _figure(
            "3",
            "standard_form",
            "JCT SBC 2016, Contract Particulars, Retention Percentage",
            "Three percent applies under JCT when the parties state no other figure; five percent is common "
            "on smaller works, and NEC Option X16 leaves the figure to the Contract Data.",
        ),
        "retention_cap_percent": _figure(
            None,
            "standard_form",
            "JCT SBC 2016, section 4 (retention rules); NEC4 Option X16",
            "Neither form limits retention below its rate; a retention bond can replace it instead.",
        ),
        "retention_release_split": _figure(
            _split(("substantial_completion", "50"), ("defects_period_end", "100")),
            "standard_form",
            "JCT SBC 2016, section 4 (retention rules); NEC4 Option X16",
            "Half is paid back at practical completion (completion under NEC) and the rest when the "
            "certificate of making good is issued at the end of the rectification period.",
        ),
        "payment_period_days": _figure(
            14,
            "standard_form",
            "JCT SBC 2016, section 4 (interim payments); Housing Grants, Construction and Regeneration Act 1996, s.110",
            "The final date for payment is 14 days after the due date. The Act makes the contract set both "
            "dates; its statutory fallback in the Scheme applies only where the contract sets none.",
        ),
        "valuation_interval": _figure(
            "monthly",
            "standard_form",
            "JCT SBC 2016, section 4 (interim valuation dates); NEC4 clause 50.1",
            "Interim valuation dates fall monthly under JCT; NEC assesses at intervals of no more than five weeks.",
        ),
        "certificate_name": _figure(
            "Interim Certificate",
            "standard_form",
            "JCT SBC 2016, section 4 (interim payments)",
            "The architect or contract administrator issues an Interim Certificate for each valuation.",
        ),
    },
    "US": {
        "standard_form": "AIA A101/A201-2017",
        "retention_percent": _figure(
            "10",
            "industry_practice",
            "AIA A101-2017, § 5.1.7",
            "The agreement leaves retainage to the parties; ten percent, stepping down to five at half "
            "complete through the regional pack's ladder, is the common pattern.",
        ),
        "retention_cap_percent": _figure(
            None,
            "industry_practice",
            "AIA A101-2017, § 5.1.7",
            "No national cap. Several states limit retainage by statute, which the state packs hold.",
        ),
        "retention_release_split": _figure(
            FROM_REGIONAL_PACK,
            "regional_pack",
            "AIA A201-2017, § 9.8.5 and § 9.10.2",
            "Paid back at substantial completion, less a holdback for open items, and the rest at final "
            "completion; the regional pack carries the events and the documents each one needs.",
        ),
        "payment_period_days": _figure(
            30,
            "industry_practice",
            "AIA A101-2017, § 5.1.3",
            "Net 30 is the common agreed term. The agreement leaves the payment date to the parties, and "
            "state prompt payment acts set statutory periods.",
        ),
        "valuation_interval": _figure(
            "monthly",
            "standard_form",
            "AIA A101-2017, § 5.1.2",
            "One calendar month ending on the last day of the month, unless the parties write another period.",
        ),
        "certificate_name": _figure(
            "Application and Certificate for Payment",
            "industry_practice",
            "AIA A201-2017, § 9.3 and § 9.4",
            "The contractor's application with its continuation sheet, certified by the architect.",
        ),
    },
    "CA": {
        # Holdback is provincial law. This row is what a Canadian project with
        # no province recorded starts from, and it states the Ontario
        # Construction Act. A project that names its province reads the
        # province's own rate and release period from
        # SUBDIVISION_CONTRACT_DEFAULTS.
        "standard_form": "CCDC 2-2020",
        "retention_percent": _figure(
            "10",
            "statute",
            "Construction Act, R.S.O. 1990, c. C.30, s. 22; Builders Lien Act (BC), s. 4; "
            "Prompt Payment and Construction Lien Act (AB), s. 18",
            "The owner holds back ten percent of the value of work done under Ontario's Construction Act, and "
            "British Columbia and Alberta hold the same. Manitoba holds 7.5 percent; change the rate there.",
        ),
        "retention_cap_percent": _figure(
            None,
            "statute",
            "Construction Act, R.S.O. 1990, c. C.30, s. 22",
            "No ceiling. The holdback is a fixed share of every payment until it is released.",
        ),
        "retention_release_split": _figure(
            _split(("substantial_completion", "100"), ("final_completion", "100")),
            "statute",
            "Construction Act, R.S.O. 1990, c. C.30, ss. 26, 31 and 32",
            "Paid once the lien period after the published certificate of substantial performance expires "
            "with no lien preserved; holdback on work done after that is paid when the contract is "
            "completed. Ontario also releases holdback each contract year from 2026.",
        ),
        "payment_period_days": _figure(
            28,
            "statute",
            "Construction Act, R.S.O. 1990, c. C.30, s. 6.4; Federal Prompt Payment for Construction Work Act",
            "The owner pays a proper invoice within 28 days of receiving it, unless it gives a notice of non-payment.",
        ),
        "valuation_interval": _figure(
            "monthly",
            "statute",
            "Construction Act, R.S.O. 1990, c. C.30, s. 6.3",
            "The contractor gives a proper invoice every month, unless the contract sets another interval.",
        ),
        "certificate_name": _figure(
            "Certificate for Payment",
            "standard_form",
            "CCDC 2-2020, GC 5.2 and GC 5.3",
            "The Consultant certifies the contractor's monthly application for payment.",
        ),
    },
    "FR": {
        "standard_form": "NF P03-001 / CCAG-Travaux",
        "retention_percent": _figure(
            "5",
            "statute",
            "Loi n° 71-584 du 16 juillet 1971, art. 1",
            "The retenue de garantie is kept from each payment and may not exceed five percent of the contract amount.",
        ),
        "retention_cap_percent": _figure(
            "5",
            "statute",
            "Loi n° 71-584 du 16 juillet 1971, art. 1",
            "Five percent of the contract amount is a legal ceiling, not a usual figure.",
        ),
        "retention_release_split": _figure(
            _split(("defects_period_end", "100")),
            "statute",
            "Loi n° 71-584 du 16 juillet 1971, art. 2",
            "Paid back one year after acceptance (réception), at the end of the garantie de parfait "
            "achèvement, unless the client has objected. A bank guarantee (caution) can replace it.",
        ),
        "payment_period_days": _figure(
            30,
            "statute",
            "Code de la commande publique, art. R2192-10; Code de commerce, art. L441-10",
            "Public works are paid within 30 days. Private works agree their own period, at most 60 days "
            "from the invoice, and 30 is common.",
        ),
        "valuation_interval": _figure(
            "monthly",
            "standard_form",
            "NF P03-001; CCAG-Travaux, art. 12",
            "Work is valued in monthly progress statements.",
        ),
        "certificate_name": _figure(
            "Situation de travaux",
            "standard_form",
            "NF P03-001; CCAG-Travaux, art. 12",
            "The monthly progress statement each interim payment is made on.",
        ),
    },
    "RU": {
        "standard_form": None,
        "retention_percent": _figure(
            "5",
            "industry_practice",
            "Civil Code of the Russian Federation, art. 329 and 711",
            "A guarantee retention of five percent of each accepted amount is the usual contract term; the "
            "Civil Code leaves the security to the contract.",
        ),
        "retention_cap_percent": _figure(
            None,
            "industry_practice",
            "Civil Code of the Russian Federation, art. 329",
            "No usual ceiling; the contract states one where it wants one.",
        ),
        "retention_release_split": _figure(
            _split(("defects_period_end", "100")),
            "industry_practice",
            "Civil Code of the Russian Federation, art. 724 and 756",
            "Paid back when the guarantee period agreed in the contract ends.",
        ),
        "payment_period_days": _figure(
            None,
            "statute",
            "Federal Laws 44-FZ and 223-FZ",
            "No general period for private works. Public procurement contracts carry their own statutory "
            "periods, so the contract states the figure.",
        ),
        "valuation_interval": _figure(
            "monthly",
            "industry_practice",
            "Unified forms KS-2 and KS-3",
            "Work is accepted monthly on the act of acceptance and the statement of cost.",
        ),
        "certificate_name": _figure(
            "Акт КС-2 / Справка КС-3",
            "industry_practice",
            "Unified forms KS-2 and KS-3",
            "The act of acceptance of work done and the statement of its cost.",
        ),
    },
    "AE": copy.deepcopy(_FIDIC_GULF),
    "SA": copy.deepcopy(_FIDIC_GULF),
    "IN": {
        "standard_form": None,
        "retention_percent": _figure(
            "5",
            "industry_practice",
            "Contract conditions",
            "Five percent of each running account bill is the usual retention on private works; public works "
            "under government conditions deduct a security deposit from each bill instead.",
        ),
        "retention_cap_percent": _figure(
            "5",
            "industry_practice",
            "Contract conditions",
            "Retention usually stops at five percent of the contract value.",
        ),
        "retention_release_split": _figure(
            _split(("substantial_completion", "50"), ("defects_period_end", "100")),
            "industry_practice",
            "Contract conditions",
            "Half is paid back on completion and the rest after the defect liability period, usually 12 months.",
        ),
        "payment_period_days": _figure(
            30,
            "industry_practice",
            "MSMED Act 2006, s.15",
            "Thirty days is the common term. Where the contractor is a registered micro or small enterprise "
            "the Act caps the period at 45 days.",
        ),
        "valuation_interval": _figure(
            "monthly",
            "industry_practice",
            "Contract conditions",
            "Work is measured and billed monthly on running account bills.",
        ),
        "certificate_name": _figure(
            "Running Account Bill (RA Bill)",
            "industry_practice",
            "Contract conditions",
            "The interim bill for work measured to date.",
        ),
    },
    "BR": {
        "standard_form": None,
        "retention_percent": _figure(
            "5",
            "industry_practice",
            "Contract conditions; Lei 14.133/2021, art. 96 to 98",
            "A contractual retention of five percent of each measurement is usual on private works; public "
            "contracts take a guarantee under the procurement law instead.",
        ),
        "retention_cap_percent": _figure(
            None,
            "industry_practice",
            "Contract conditions",
            "No usual ceiling; the contract states one where it wants one.",
        ),
        "retention_release_split": _figure(
            _split(("final_completion", "100")),
            "industry_practice",
            "Lei 14.133/2021, art. 140",
            "Paid back on final acceptance (recebimento definitivo).",
        ),
        "payment_period_days": _figure(
            None,
            "statute",
            "Lei 14.133/2021, art. 141",
            "Public payments follow the order invoices were registered in rather than a number of days; "
            "private contracts state their own period.",
        ),
        "valuation_interval": _figure(
            "monthly",
            "industry_practice",
            "Contract conditions",
            "Work is measured monthly (medição mensal).",
        ),
        "certificate_name": _figure(
            "Boletim de Medição",
            "industry_practice",
            "Contract conditions",
            "The measurement statement each payment is made on.",
        ),
    },
    "CN": {
        "standard_form": "GF-2017-0201",
        "retention_percent": _figure(
            "3",
            "statute",
            "建设工程质量保证金管理办法 (建质〔2017〕138号), art. 7",
            "The quality guarantee deposit may not exceed three percent of the settled contract price.",
        ),
        "retention_cap_percent": _figure(
            "3",
            "statute",
            "建设工程质量保证金管理办法 (建质〔2017〕138号), art. 7",
            "Three percent of the settled price is a legal ceiling on the deposit.",
        ),
        "retention_release_split": _figure(
            _split(("defects_period_end", "100")),
            "statute",
            "建设工程质量保证金管理办法 (建质〔2017〕138号), art. 2 and art. 10",
            "Paid back when the defects liability period ends, usually 12 and at most 24 months.",
        ),
        "payment_period_days": _figure(
            14,
            "statute",
            "建设工程价款结算暂行办法 (财建〔2004〕369号), art. 13",
            "The progress payment is due within 14 days of the payment application on the confirmed measurement.",
        ),
        "valuation_interval": _figure(
            "monthly",
            "industry_practice",
            "建设工程价款结算暂行办法 (财建〔2004〕369号), art. 13",
            "Monthly settlement of progress is the usual mode.",
        ),
        "certificate_name": _figure(
            "工程进度款支付证书",
            "industry_practice",
            "GF-2017-0201, General Conditions 12.4",
            "The progress payment certificate.",
        ),
    },
}


# ── Validation at import ─────────────────────────────────────────────────


def _check_percent(value: Any, where: str) -> None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{where} is not a number: {value!r}") from exc
    if not parsed.is_finite() or not Decimal("0") <= parsed <= Decimal("100"):
        raise ValueError(f"{where} must be between 0 and 100, not {value!r}")


def validate_release_split(split: Any, where: str = "retention_release_split") -> list[dict[str, str]]:
    """Return ``split`` in canonical shape, or raise ``ValueError``.

    Each step names a canonical completion event and the percent of what is
    held at that event that it pays back. The last step must pay back all of
    what is left, otherwise some retention has no event that ever releases it.
    Events may not repeat.
    """
    if not isinstance(split, list) or not split:
        raise ValueError(f"{where} must be a non-empty list of release steps")
    seen: set[str] = set()
    steps: list[dict[str, str]] = []
    for index, step in enumerate(split):
        if not isinstance(step, dict):
            raise ValueError(f"{where}[{index}] must be an object naming event and release_percent_of_held")
        event = str(step.get("event") or "").strip().lower()
        if event not in CANONICAL_RELEASE_EVENTS:
            raise ValueError(f"{where}[{index}].event must be one of {', '.join(CANONICAL_RELEASE_EVENTS)}")
        if event in seen:
            raise ValueError(f"{where} names {event} twice")
        seen.add(event)
        percent = step.get("release_percent_of_held")
        _check_percent(percent, f"{where}[{index}].release_percent_of_held")
        steps.append({"event": event, "release_percent_of_held": format(Decimal(str(percent)).normalize(), "f")})
    if Decimal(steps[-1]["release_percent_of_held"]) != Decimal("100"):
        raise ValueError(f"{where}: the last step must release 100 percent of what is still held")
    return steps


# ── Below the country ────────────────────────────────────────────────────
#
# Where the law that sets a figure is provincial or state law, a project that
# records its ISO 3166-2 subdivision reads the subdivision's row over the
# country's. A subdivision row names only the fields that differ; the rest
# come from the country. ``release_period_days`` is how long the holdback is
# kept after the release event before it may be paid, the period lien rights
# run for. It is served with its source and never written onto a contract,
# because the release rule pays at the event and a person reads the period
# beside it.
SUBDIVISION_CONTRACT_DEFAULTS: dict[str, dict[str, Any]] = {
    "CA-ON": {
        "retention_percent": _figure(
            "10",
            "statute",
            "Construction Act, R.S.O. 1990, c. C.30, s. 22",
            "Ontario holds back ten percent of the value of work done.",
        ),
        "release_period_days": _figure(
            60,
            "statute",
            "Construction Act, R.S.O. 1990, c. C.30",
            "Paid once 60 days pass after the certificate of substantial performance is published with no "
            "lien preserved. Ontario also releases holdback each contract year from 2026.",
        ),
    },
    "CA-BC": {
        "retention_percent": _figure(
            "10",
            "statute",
            "Builders Lien Act, S.B.C. 1997, c. 45",
            "British Columbia holds back ten percent of the value of work done, kept in a holdback account "
            "on larger contracts.",
        ),
        # The Construction Prompt Payment Act (BC, 2025) would cut this to 46
        # days. It comes into force on a date set by regulation, and none was
        # set as of 2026-10; move the figure when it is.
        "release_period_days": _figure(
            55,
            "statute",
            "Builders Lien Act, S.B.C. 1997, c. 45",
            "Paid once 55 days pass after the certificate of completion with no lien filed.",
        ),
    },
    "CA-AB": {
        "retention_percent": _figure(
            "10",
            "statute",
            "Prompt Payment and Construction Lien Act, R.S.A. 2000, c. P-26.4",
            "Alberta holds back ten percent of the value of work done.",
        ),
        "release_period_days": _figure(
            60,
            "statute",
            "Prompt Payment and Construction Lien Act, R.S.A. 2000, c. P-26.4",
            "Paid once 60 days pass after the certificate of substantial performance, or 90 days for "
            "concrete supply and oil and gas well work.",
        ),
    },
    "CA-MB": {
        "retention_percent": _figure(
            "7.5",
            "statute",
            "The Builders' Liens Act, C.C.S.M. c. B91, s. 25",
            "Manitoba holds back 7.5 percent of each payment, not ten.",
        ),
        "release_period_days": _figure(
            60,
            "statute",
            "The Builders' Liens Act, C.C.S.M. c. B91, s. 25",
            "Paid once 60 days pass with no lien registered. The period was 40 days before 1 April 2024.",
        ),
    },
    "CA-QC": {
        "retention_percent": _figure(
            "10",
            "industry_practice",
            "Contract terms",
            "Quebec has no statutory holdback. Ten percent is the usual contractual retention; the contract sets it.",
        ),
        "payment_period_days": _figure(
            None,
            "industry_practice",
            "Contract terms",
            "No provincial prompt payment period applies to private work; the contract states it.",
        ),
        "release_period_days": _figure(
            None,
            "industry_practice",
            "Contract terms",
            "The contract sets when the retention is paid, usually after acceptance of the work.",
        ),
    },
}

#: Fields a subdivision row may name: the country fields plus the release period.
SUBDIVISION_FIELDS: tuple[str, ...] = (*CONTRACT_DEFAULT_FIELDS, "release_period_days")


def _validate_table() -> None:
    for code, sub_row in SUBDIVISION_CONTRACT_DEFAULTS.items():
        country, _, sub = code.partition("-")
        if country not in COUNTRY_CONTRACT_DEFAULTS or not sub or code != code.upper():
            raise ValueError(f"subdivision key {code!r} is not ISO 3166-2 under a country the table has")
        for field, figure in sub_row.items():
            where = f"{code}.{field}"
            if field not in SUBDIVISION_FIELDS:
                raise ValueError(f"{where} is not a field a subdivision can set")
            if not isinstance(figure, dict) or set(figure) != {"value", "source", "reference", "note"}:
                raise ValueError(f"{where} must be a figure with value, source, reference and note")
            if figure["source"] not in SOURCES or not figure["note"] or not figure["reference"]:
                raise ValueError(f"{where} must name its source, reference and note")
            value = figure["value"]
            if value is None:
                continue
            if field == "retention_percent":
                _check_percent(value, where)
            elif field in ("payment_period_days", "release_period_days") and (
                not isinstance(value, int) or isinstance(value, bool) or not 0 < value <= 365
            ):
                raise ValueError(f"{where} must be a whole number of days between 1 and 365")
    for country, row in COUNTRY_CONTRACT_DEFAULTS.items():
        if len(country) != 2 or not country.isupper():
            raise ValueError(f"country key {country!r} is not ISO 3166-1 alpha-2")
        for field in CONTRACT_DEFAULT_FIELDS:
            figure = row.get(field)
            where = f"{country}.{field}"
            if not isinstance(figure, dict) or set(figure) != {"value", "source", "reference", "note"}:
                raise ValueError(f"{where} must be a figure with value, source, reference and note")
            if figure["source"] not in SOURCES or not figure["note"] or not figure["reference"]:
                raise ValueError(f"{where} must name its source, reference and note")
            value = figure["value"]
            if value is None:
                continue
            if field in ("retention_percent", "retention_cap_percent"):
                _check_percent(value, where)
            elif field == "retention_release_split":
                if value != FROM_REGIONAL_PACK:
                    validate_release_split(value, where)
            elif field == "payment_period_days":
                if not isinstance(value, int) or isinstance(value, bool) or not 0 < value <= 365:
                    raise ValueError(f"{where} must be a whole number of days between 1 and 365")
            elif field == "valuation_interval":
                if value not in VALUATION_INTERVALS:
                    raise ValueError(f"{where} must be one of {', '.join(VALUATION_INTERVALS)}")
            elif field == "certificate_name" and not str(value).strip():
                raise ValueError(f"{where} must not be blank")


_validate_table()


# ── Reading ──────────────────────────────────────────────────────────────


def normalise_country(country_code: str | None) -> str:
    """Upper-case ISO code with the aliases this table knows folded in; ``""`` when blank."""
    code = (country_code or "").strip().upper()
    return COUNTRY_ALIASES.get(code, code)


def _pack_release_split(country: str) -> list[dict[str, str]] | None:
    """The completion events of the country's regional pack, as a split, or ``None``."""
    from app.core.regional_packs import resolve_progress_billing  # noqa: PLC0415

    billing = resolve_progress_billing(country_code=country) or {}
    rule = billing.get("release_events")
    events = rule.get("events") if isinstance(rule, dict) else None
    if not isinstance(events, list):
        return None
    steps = [
        {"event": str(e["event"]), "release_percent_of_held": str(Decimal(str(e["release_percent_of_held"])))}
        for e in events
        if isinstance(e, dict)
        and e.get("event") in CANONICAL_RELEASE_EVENTS
        and e.get("release_percent_of_held") not in (None, "")
    ]
    try:
        return validate_release_split(steps)
    except ValueError:
        return None


def note_key(country: str, field: str) -> str:
    """The i18n key a figure's ``note`` is translated under.

    ``note`` is English prose a person reads beside the figure, so it is
    served with a key the client renders it through; the English here is that
    key's ``en`` text, and a test holds the two equal. The reference (a clause,
    a form, a law) is data and is shown as written.
    """
    return f"{NOTE_KEY_PREFIX}{country}.{field}.note"


def normalise_subdivision(country: str, subdivision_code: str | None) -> str:
    """``"CA-MB"`` from ``"CA-MB"``, ``"ca-mb"`` or ``"MB"``; ``""`` when blank or in another country."""
    code = (subdivision_code or "").strip().upper()
    if not code or not country:
        return ""
    if "-" not in code:
        code = f"{country}-{code}"
    return code if code.partition("-")[0] == country else ""


def resolve_contract_defaults(country_code: str | None, subdivision_code: str | None = None) -> dict[str, Any] | None:
    """The usual payment terms of ``country_code``, or ``None`` when the table has no row.

    Returns:
        ``None`` for a blank or unknown country. Never another country's row.
        Otherwise a new dict: ``country_code``, ``standard_form``, ``values``
        (one entry per :data:`CONTRACT_DEFAULT_FIELDS`, ``None`` where the
        market has no usual figure), ``sources`` (per field: ``source``,
        ``reference``, ``note`` in English and ``note_key``, the i18n key the
        note is translated under) and ``release_split_source``, which is
        ``"regional_pack"`` when the split was read from the pack and
        ``"table"`` otherwise. ``subdivision_code`` is the ISO 3166-2 row
        read over the country's, or ``None``; ``release_period`` is that
        row's release period (value, source, reference, note, note_key), or
        ``None``.
    """
    country = normalise_country(country_code)
    row = COUNTRY_CONTRACT_DEFAULTS.get(country)
    if row is None:
        return None
    subdivision = normalise_subdivision(country, subdivision_code)
    sub_row = SUBDIVISION_CONTRACT_DEFAULTS.get(subdivision)
    if sub_row is None:
        subdivision = ""
    else:
        row = {**row, **sub_row}
    values: dict[str, Any] = {}
    sources: dict[str, dict[str, Any]] = {}
    split_source = "table"
    for field in CONTRACT_DEFAULT_FIELDS:
        figure = row[field]
        value = copy.deepcopy(figure["value"])
        if field == "retention_release_split" and value == FROM_REGIONAL_PACK:
            value = _pack_release_split(country)
            split_source = FROM_REGIONAL_PACK
        values[field] = value
        sources[field] = {
            "source": figure["source"],
            "reference": figure["reference"],
            "note": figure["note"],
            "note_key": note_key(subdivision if sub_row and field in sub_row else country, field),
        }
    period = (sub_row or {}).get("release_period_days")
    return {
        "country_code": country,
        "subdivision_code": subdivision or None,
        "standard_form": row.get("standard_form"),
        "values": values,
        "sources": sources,
        "release_split_source": split_source,
        "release_period": (
            {**copy.deepcopy(period), "note_key": note_key(subdivision, "release_period_days")} if period else None
        ),
    }


def apply_contract_defaults(
    explicit: dict[str, Any],
    defaults: dict[str, Any] | None,
    *,
    country_code: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge what the author sent with the country's defaults. Pure.

    Args:
        explicit: The fields the author actually sent, ``None`` values already
            dropped. Every one of them wins, including a value equal to the
            default.
        defaults: :func:`resolve_contract_defaults` for the project's country.
        country_code: The project's country, recorded on the stamp even when
            the table has no row for it.

    Returns:
        ``(values, stamp)``. ``values`` holds one entry per field that has a
        value from either side; a field neither side fills is absent, never
        invented. ``stamp`` is what the contract records under
        :data:`DEFAULTS_STAMP_KEY`: the country, which fields the defaults
        filled (``applied``) with the value and source of each, and whether
        the split is the regional pack's (``release_split_source``), in which
        case the split is not written onto the contract and the pack keeps
        governing.
    """
    values: dict[str, Any] = dict(explicit)
    applied: dict[str, Any] = {}
    sources: dict[str, Any] = {}
    default_values = (defaults or {}).get("values") or {}
    pack_split = (defaults or {}).get("release_split_source") == FROM_REGIONAL_PACK
    for field in CONTRACT_DEFAULT_FIELDS:
        if field in explicit:
            continue
        value = default_values.get(field)
        if value is None:
            continue
        applied[field] = copy.deepcopy(value)
        sources[field] = copy.deepcopy(((defaults or {}).get("sources") or {}).get(field))
        if field == "retention_release_split" and pack_split:
            # Shown and stamped, not written: the pack's own events, with the
            # documents each one asks for, keep governing the release.
            continue
        values[field] = copy.deepcopy(value)
    stamp: dict[str, Any] = {
        "country_code": normalise_country(country_code) or None,
        "has_country_defaults": defaults is not None,
        "applied": applied,
        "sources": sources,
        "release_split_source": (defaults or {}).get("release_split_source"),
    }
    return values, stamp


def subcontract_retention_default(defaults: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """The flat rate a subcontract agreement starts from, and the figure it was read from.

    A subcontract agreement holds one rate on every payment application and
    carries no ceiling, so it cannot do what the contract above it does with
    "ten percent until five percent of the sum is held". Given the country's
    rate it would hold ten percent for the whole job, twice the limit the same
    row states. Where the country's cap is below its rate, the agreement
    therefore starts from the cap: the highest flat rate that never holds more
    than the limit on work billed up to the agreement's value.

    Returns:
        ``(rate, field)``, where ``field`` names the table figure the rate is
        (``"retention_percent"`` or ``"retention_cap_percent"``), so the form
        can show that figure's own source. ``(None, None)`` when the country
        has no row or no usual rate.
    """
    values = (defaults or {}).get("values") or {}
    rate = values.get("retention_percent")
    if rate is None:
        return None, None
    cap = values.get("retention_cap_percent")
    if cap is not None and Decimal(str(cap)) < Decimal(str(rate)):
        return str(cap), "retention_cap_percent"
    return str(rate), "retention_percent"


def forget_overridden(stamp: Any, changed: dict[str, Any]) -> Any:
    """Drop from a stamp the fields a later edit set to something else.

    A contract that says "default for Germany" beside a figure somebody has
    since typed over would be telling its reader something false. ``changed``
    maps field names to the new values; a field set to the value it was
    defaulted to keeps its stamp.
    """
    if not isinstance(stamp, dict) or not isinstance(stamp.get("applied"), dict):
        return stamp
    result = copy.deepcopy(stamp)
    for field, new in changed.items():
        if field not in result["applied"]:
            continue
        old = result["applied"][field]
        if _same(old, new):
            continue
        result["applied"].pop(field, None)
        if isinstance(result.get("sources"), dict):
            result["sources"].pop(field, None)
    fallback = result.get("fallback")
    if isinstance(fallback, list):
        result["fallback"] = [f for f in fallback if f not in changed]
    return result


def _same(old: Any, new: Any) -> bool:
    try:
        return Decimal(str(old)) == Decimal(str(new))
    except (InvalidOperation, ValueError, TypeError):
        return old == new


__all__ = [
    "CONTRACT_DEFAULT_FIELDS",
    "COUNTRY_ALIASES",
    "COUNTRY_CONTRACT_DEFAULTS",
    "DEFAULTS_STAMP_KEY",
    "FROM_REGIONAL_PACK",
    "NOTE_KEY_PREFIX",
    "PAYMENT_TERMS_KEY",
    "PAYMENT_TERM_FIELDS",
    "PLATFORM_FALLBACK",
    "SUBDIVISION_CONTRACT_DEFAULTS",
    "VALUATION_INTERVALS",
    "apply_contract_defaults",
    "forget_overridden",
    "normalise_country",
    "normalise_subdivision",
    "note_key",
    "resolve_contract_defaults",
    "subcontract_retention_default",
    "validate_release_split",
]
