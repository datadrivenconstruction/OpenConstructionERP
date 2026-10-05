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

**A state's statute can lower the country's usual rate.** The rows here are
national, but in a federal country the retention law is often the state's. A
subdivision pack (one with a ``parent_pack``) states that law as data: a
retainage rule carrying ``per_payment_percent`` and ``works`` is a ceiling on
what may be withheld from each payment, binding contracts entered into on or
after its ``effective_date``. :func:`statutory_retention_ceiling` reads those
rules and :func:`resolve_contract_defaults` lowers the usual rate to the
ceiling where the rate runs above it. Nothing in this module names a state;
the state comes from the project address (:func:`subdivision_from_address`).
A contract does not record whether its works are public or private, so a
ceiling is applied only on a date when the subdivision caps both kinds; where
one kind is uncapped the national figure stands, since it may be lawful.

**Where the law follows the client, the project says which.** A project may
record its works as ``public`` or ``private`` (``Project.works``). A country
whose retention law differs between the two (France) carries a dated, cited
variant in :data:`WORKS_CONTRACT_DEFAULTS`, laid over its row by
:func:`resolve_contract_defaults`. A subcontract is always private works
(:func:`contract_works`). Works not recorded leave the country row, which then
cites both laws, as it is. The state ceilings above do not read the works yet.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.contracts.retention import (
    CANONICAL_RELEASE_EVENTS,
    RETENTION_BASES,
    RETENTION_BASIS_GROSS,
    RETENTION_BASIS_NET,
)

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

#: The kinds of works a statutory retention ceiling is written for. A ceiling
#: reaches a contract's defaults only when every kind here is capped, because
#: a contract does not record which kind it is.
CEILING_WORKS: tuple[str, ...] = ("private", "public")

#: The i18n key the note beside a rate lowered to a statutory ceiling is
#: rendered through, with ``note_params`` filling its placeholders. Kept out of
#: :data:`NOTE_KEY_PREFIX`: that namespace holds exactly one note per table
#: figure, and a test counts it.
STATUTORY_CEILING_NOTE_KEY = "contracts.statutory_ceiling.retention_percent.note"

#: That note's English text, word for word as ``en.ts`` carries it.
STATUTORY_CEILING_NOTE = (
    "Lowered to {{percent}} percent: on a contract entered into on or after {{since}}, public or private, the law "
    "of {{subdivision}} does not allow more than that to be withheld from each payment. The statute lists "
    "exceptions under which the parties may agree more."
)

#: An ISO 3166-2 code, the alpha-2 country, a hyphen, one to three alphanumerics.
_SUBDIVISION_CODE = re.compile(r"[A-Z]{2}-[A-Z0-9]{1,3}")

#: A bare subdivision part, as a US address writes its state ("CA").
_SUBDIVISION_PART = re.compile(r"[A-Z0-9]{1,3}")

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
    # The row a French contract starts from when nobody recorded whether its
    # works are public or private. Its references name both laws, since loi
    # 71-584 governs private works only; WORKS_CONTRACT_DEFAULTS says which one
    # applies once the project records its works.
    "FR": {
        "standard_form": "NF P03-001 / CCAG-Travaux",
        "retention_percent": _figure(
            "5",
            "statute",
            "Loi n° 71-584 du 16 juillet 1971, art. 1 (private works); "
            "Code de la commande publique, art. R2191-33 (public contracts)",
            "The retenue de garantie is kept from each payment and may not exceed five percent of the contract amount.",
        ),
        "retention_cap_percent": _figure(
            "5",
            "statute",
            "Loi n° 71-584 du 16 juillet 1971, art. 1 (private works); "
            "Code de la commande publique, art. R2191-33 (public contracts)",
            "Five percent of the contract amount is a legal ceiling, not a usual figure.",
        ),
        "retention_release_split": _figure(
            _split(("defects_period_end", "100")),
            "statute",
            "Loi n° 71-584 du 16 juillet 1971, art. 2 (private works); "
            "Code de la commande publique, art. R2191-35 (public contracts)",
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


#: What retention, and the ceiling on it, is measured on, per country. A
#: country with no row here measures on the net, the price of the work before
#: VAT, which is what every market in the table above does except these.
#:
#: Kept out of :data:`CONTRACT_DEFAULT_FIELDS` on purpose. That tuple is what
#: a contract form pre-fills and a person may change, each figure with a note
#: translated in every locale. The basis is not a figure the parties pick: it
#: is how the country's law reads "ten percent of each payment", and every
#: claim on the contract follows it.
#:
#: Germany: § 17 Abs. 6 Nr. 1 VOB/B lets the client cut "jeweils die Zahlung"
#: by up to ten percent until the agreed security sum is reached, and its
#: second sentence leaves the VAT out only where the invoice carries none
#: under § 13b UStG, so the payment it means is the one with VAT in it. The
#: federal contract form states the security as "fünf Prozent der
#: Auftragssumme (inkl. Umsatzsteuer, ohne Nachträge)" (VHB Bund, Formblatt
#: 214 Nr. 4), so the ceiling is measured on the same base.
#:
#: ``subcontract_vat_percent`` is the VAT a subcontract's invoice is presumed
#: to carry when the contract states none. Between a main contractor and its
#: subcontractor German construction work is reverse charge: the recipient owes
#: the tax when it "nachhaltig entsprechende Leistungen erbringt" (§ 13b Abs. 2
#: Nr. 4, Abs. 5 Satz 2 UStG), which a main contractor does. The sub's invoice
#: then carries no USt and its retention is measured without it. A contract
#: that states its own rate overrides the presumption either way.
COUNTRY_RETENTION_BASIS: dict[str, dict[str, str]] = {
    "DE": {
        "basis": RETENTION_BASIS_GROSS,
        "reference": "§ 17 Abs. 6 Nr. 1 VOB/B; VHB Bund Formblatt 214 Nr. 4",
        "subcontract_vat_percent": "0",
        "subcontract_reference": "§ 13b Abs. 2 Nr. 4, Abs. 5 Satz 2 UStG",
    },
}


# ── Public or private works ──────────────────────────────────────────────

#: Where the notes of a works variant live in the client's locale files:
#: ``contracts.works_defaults.<CC>.<works>.<field>.note``. Kept out of
#: :data:`NOTE_KEY_PREFIX`, which holds exactly one note per table figure.
WORKS_NOTE_KEY_PREFIX = "contracts.works_defaults."

#: Where a country's law on retention depends on who the client is, the
#: figures that change once the project records its works (``public`` or
#: ``private``, the vocabulary of :data:`CEILING_WORKS`). A variant names only
#: what differs from the country row: ``standard_form``, whole figures (made
#: by :func:`_figure`, with a note under :data:`WORKS_NOTE_KEY_PREFIX`), and
#: ``references`` that re-cite a row figure whose value and note stand. Works
#: not recorded leave the country row as it is.
#:
#: France, read on legifrance.gouv.fr on 2026-10-05. Private works: loi
#: n° 71-584 du 16 juillet 1971, art. 1 (in force since 2020-01-01, ordonnance
#: n° 2019-964, art. 35) caps the retenue at "5 p. 100" of each interim
#: payment and lets a caution replace it; art. 2 (unchanged since 1971-07-17)
#: releases it one year after réception unless the client notified a reasoned
#: objection. Public contracts: Code de la commande publique, art. R2191-32 to
#: R2191-42. R2191-33 (as amended by décret n° 2024-1251, art. 1, for
#: consultations engaged from 2025-01-01, art. 7) caps the retenue at 5 % of
#: the initial contract amount plus modifications, and at 3 % where the
#: contractor is an SME (R2151-13) and the buyer is the State, a State
#: établissement public administratif other than a health body with operating
#: charges over 60 M EUR, or a local authority with operating expenditure over
#: 60 M EUR. That is a lower ceiling, not a set rate, and the platform records
#: neither the contractor's size nor the buyer's, so the note names it and the
#: figure stays at 5. R2191-34 withholds it in instalments from each payment
#: and the balance; R2191-35 repays it within 30 days of the end of the délai
#: de garantie, or of the lifting of reserves notified during it; R2191-36 lets
#: the contractor substitute a first-demand guarantee or, unless the buyer
#: objects, a caution. Neither text says whether the base is net or gross of
#: VAT, so no note claims either.
WORKS_CONTRACT_DEFAULTS: dict[str, dict[str, dict[str, Any]]] = {
    "FR": {
        "private": {
            "standard_form": "NF P03-001",
            "references": {
                "retention_percent": "Loi n° 71-584 du 16 juillet 1971, art. 1",
                "retention_cap_percent": "Loi n° 71-584 du 16 juillet 1971, art. 1",
                "retention_release_split": "Loi n° 71-584 du 16 juillet 1971, art. 2",
            },
        },
        "public": {
            "standard_form": "CCAG-Travaux 2021",
            "retention_percent": _figure(
                "5",
                "statute",
                "Code de la commande publique, art. R2191-33 and R2191-34",
                "The retenue de garantie is withheld in instalments from each interim payment and the final balance. "
                "It may not exceed five percent of the initial contract amount plus any modifications.",
            ),
            "retention_cap_percent": _figure(
                "5",
                "statute",
                "Code de la commande publique, art. R2191-33",
                "Five percent of the initial contract amount plus any modifications is a legal ceiling. Where the "
                "contractor is an SME and the buyer is the State, or a State public body or local authority with more "
                "than 60 million euros of operating expenditure, the ceiling is three percent.",
            ),
            "retention_release_split": _figure(
                _split(("defects_period_end", "100")),
                "statute",
                "Code de la commande publique, art. R2191-35 and R2191-36",
                "Paid back within 30 days after the warranty period (délai de garantie) ends, or within 30 days "
                "after reserves notified during it are lifted. The contractor may replace it with a first-demand "
                "guarantee or, unless the buyer objects, a joint and several surety.",
            ),
        },
    },
}


@dataclass(frozen=True)
class RetentionBasis:
    """What a contract's retention is measured on, and the VAT that makes it gross.

    ``vat_percent`` is ``None`` on a net basis and the rate added to the net
    on a gross one, ``0`` included: an invoice under reverse charge carries no
    VAT and its retention is measured without it (§ 17 Abs. 6 Nr. 1 Satz 2
    VOB/B). ``vat_source`` says where that rate came from.
    """

    basis: str
    vat_percent: Decimal | None
    vat_source: str
    reference: str | None = None


#: The basis of a country that measures retention on the net.
NET_RETENTION_BASIS = RetentionBasis(RETENTION_BASIS_NET, None, "not_applicable")


def _vat_percent(raw: Any) -> Decimal | None:
    """A VAT rate in percent from a stored value, or ``None`` when there is none to read."""
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw).strip())
    except (ArithmeticError, ValueError):
        return None
    if not value.is_finite() or value < 0 or value > 100:
        return None
    return value


def resolve_retention_basis(
    country_code: str | None,
    *,
    agreed_vat_rate: Any = None,
    project_vat_rate: Any = None,
    subcontract: bool = False,
) -> RetentionBasis:
    """What retention is measured on for a contract in ``country_code``.

    On a gross basis the VAT is, in order: the rate the contract agreed for
    its invoices (``metadata.einvoice.vat_rate``, where a public client's
    award states the VAT treatment, ``0`` for reverse charge), for a
    subcontract the rate the country presumes its invoices carry
    (``subcontract_vat_percent``), the project's default VAT rate, the
    country's standard rate. A gross basis whose VAT nobody can say is
    reported with ``vat_source`` ``"none"`` and no rate, and the caller
    measures on the net and says so rather than inventing one.
    """
    country = normalise_country(country_code)
    row = COUNTRY_RETENTION_BASIS.get(country)
    if row is None or row["basis"] != RETENTION_BASIS_GROSS:
        return NET_RETENTION_BASIS
    reference = row.get("reference")
    agreed = _vat_percent(agreed_vat_rate)
    if agreed is not None:
        return RetentionBasis(RETENTION_BASIS_GROSS, agreed, "contract_einvoice", reference)
    presumed = _vat_percent(row.get("subcontract_vat_percent")) if subcontract else None
    if presumed is not None:
        return RetentionBasis(
            RETENTION_BASIS_GROSS,
            presumed,
            "subcontract_presumed",
            f"{reference}; {row.get('subcontract_reference')}",
        )
    project_rate = _vat_percent(project_vat_rate)
    if project_rate is not None:
        return RetentionBasis(RETENTION_BASIS_GROSS, project_rate, "project_default", reference)
    from app.core.tax import VATNotApplicable, get_vat_rate  # noqa: PLC0415

    try:
        standard = get_vat_rate(country) * Decimal("100")
    except VATNotApplicable:
        return RetentionBasis(RETENTION_BASIS_GROSS, None, "none", reference)
    return RetentionBasis(RETENTION_BASIS_GROSS, standard, "country_standard", reference)


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


def _validate_table() -> None:
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
    for country, basis in COUNTRY_RETENTION_BASIS.items():
        if len(country) != 2 or not country.isupper():
            raise ValueError(f"retention basis key {country!r} is not ISO 3166-1 alpha-2")
        if basis.get("basis") not in RETENTION_BASES or not basis.get("reference"):
            raise ValueError(f"the retention basis of {country} must be one of {RETENTION_BASES} with a reference")
        if "subcontract_vat_percent" in basis:
            _check_percent(basis["subcontract_vat_percent"], f"{country}.subcontract_vat_percent")
            if not basis.get("subcontract_reference"):
                raise ValueError(f"{country}.subcontract_vat_percent must name its subcontract_reference")


_validate_table()


def _validate_works_table() -> None:
    """Hold each works variant to the rules its country row is held to."""
    for country, variants in WORKS_CONTRACT_DEFAULTS.items():
        if country not in COUNTRY_CONTRACT_DEFAULTS:
            raise ValueError(f"works variants for {country!r}, which has no country row")
        for works, variant in variants.items():
            where = f"{country}.{works}"
            if works not in CEILING_WORKS:
                raise ValueError(f"{where}: works must be one of {', '.join(CEILING_WORKS)}")
            unknown = set(variant) - {"standard_form", "references", *CONTRACT_DEFAULT_FIELDS}
            if unknown:
                raise ValueError(f"{where} names fields the table does not have: {sorted(unknown)}")
            for field in CONTRACT_DEFAULT_FIELDS:
                figure = variant.get(field)
                if figure is None:
                    continue
                if not isinstance(figure, dict) or set(figure) != {"value", "source", "reference", "note"}:
                    raise ValueError(f"{where}.{field} must be a figure with value, source, reference and note")
                if figure["source"] not in SOURCES or not figure["note"] or not figure["reference"]:
                    raise ValueError(f"{where}.{field} must name its source, reference and note")
                if field not in ("retention_percent", "retention_cap_percent", "retention_release_split"):
                    raise ValueError(f"{where}.{field}: a works variant changes retention figures only")
                if field == "retention_release_split":
                    validate_release_split(figure["value"], f"{where}.{field}")
                else:
                    _check_percent(figure["value"], f"{where}.{field}")
            for field, reference in (variant.get("references") or {}).items():
                if field not in CONTRACT_DEFAULT_FIELDS or field in variant or not str(reference).strip():
                    raise ValueError(f"{where}.references.{field} must re-cite a figure the variant leaves standing")


_validate_works_table()


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


def works_note_key(country: str, works: str, field: str) -> str:
    """The i18n key the note of a works variant's figure is translated under."""
    return f"{WORKS_NOTE_KEY_PREFIX}{country}.{works}.{field}.note"


def normalise_works(works: str | None) -> str | None:
    """``"public"`` or ``"private"``, or ``None`` when the works are not recorded or not one of those."""
    value = (works or "").strip().lower()
    return value if value in CEILING_WORKS else None


def contract_works(project_works: str | None, counterparty_type: str | None) -> str | None:
    """The kind of works a contract on a project is, for the law its defaults follow.

    A project's works say who its client is, and that reaches the contract
    with the client. A subcontract is never a public contract: the main
    contractor who lets it is not a public buyer, whoever the project's
    client is, so it is ``private``. A contract with the client on a project
    that records no works stays ``None``, unknown.
    """
    if (counterparty_type or "").strip().lower() == "subcontractor":
        return "private"
    return normalise_works(project_works)


def _apply_works(
    country: str,
    works: str | None,
    values: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    standard_form: Any,
) -> tuple[Any, str | None]:
    """Lay the country's works variant over its resolved row, in place.

    Returns the standard form and the works applied, ``None`` when the country
    has no variant for ``works`` and the row stands as it is.
    """
    variant = (WORKS_CONTRACT_DEFAULTS.get(country) or {}).get(works or "")
    if variant is None:
        return standard_form, None
    for field in CONTRACT_DEFAULT_FIELDS:
        figure = variant.get(field)
        if figure is not None:
            values[field] = copy.deepcopy(figure["value"])
            sources[field] = {
                "source": figure["source"],
                "reference": figure["reference"],
                "note": figure["note"],
                "note_key": works_note_key(country, str(works), field),
            }
    for field, reference in (variant.get("references") or {}).items():
        sources[field] = {**sources[field], "reference": reference}
    return variant.get("standard_form", standard_form), works


def _today() -> date:
    """Today in UTC. A seam, so a test can say which day a contract is entered into."""
    return datetime.now(UTC).date()


def _percent_text(value: Any) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def subdivision_from_address(country_code: str | None, address: Any) -> str | None:
    """The ISO 3166-2 code of the state an address names, or ``None``.

    Read from ``address["state"]``, where an address in a country with states
    keeps it (see ``app.core.validation.address``). Three spellings are
    accepted and nothing else: the full code of this country (``"XX-YY"``),
    the bare part a postal address writes (``"YY"``), and the exact name a
    subdivision pack of this country declares as ``subdivision_name``. An
    abbreviation or a misspelling answers ``None`` rather than a guess, and so
    does a code of another country.
    """
    country = normalise_country(country_code)
    if not country or not isinstance(address, dict):
        return None
    raw = str(address.get("state") or "").strip()
    if not raw:
        return None
    code = raw.upper()
    if _SUBDIVISION_CODE.fullmatch(code):
        return code if code.startswith(f"{country}-") else None
    if _SUBDIVISION_PART.fullmatch(code):
        return f"{country}-{code}"
    from app.core.regional_packs import packs_for_country  # noqa: PLC0415

    for config in packs_for_country(country):
        name = str(config.get("subdivision_name") or "").strip()
        sub_code = str(config.get("subdivision_code") or "").strip().upper()
        if config.get("parent_pack") and sub_code and name.casefold() == raw.casefold():
            return sub_code
    return None


def _subdivision_name(country: str, subdivision_code: str) -> str:
    """The name the subdivision's pack declares, else the code itself."""
    from app.core.regional_packs import packs_for_country  # noqa: PLC0415

    for config in packs_for_country(country):
        if str(config.get("subdivision_code") or "").strip().upper() == subdivision_code:
            return str(config.get("subdivision_name") or subdivision_code)
    return subdivision_code


def _commenced(rule: dict[str, Any], as_of: date) -> bool:
    """Whether a ceiling binds a contract entered into on ``as_of``.

    Only a full ISO date can say so. A rule whose commencement is a bare year
    or was not established is never applied: a ceiling read a day early takes
    money the parties lawfully agreed to hold.
    """
    try:
        return date.fromisoformat(str(rule.get("effective_date"))) <= as_of
    except ValueError:
        return False


def statutory_retention_ceiling(
    country_code: str | None,
    subdivision_code: str | None,
    *,
    as_of: date,
) -> dict[str, Any] | None:
    """The ceiling a subdivision's statute puts on retention per payment, for any kind of works.

    Reads the retainage rules of the subdivision pack, through the same
    resolver the progress billing reads, and keeps the ones that carry
    ``per_payment_percent`` and a ``works`` from :data:`CEILING_WORKS`. For
    each kind of works the tightest rule in force on ``as_of`` binds. A
    contract does not record its kind of works, so the answer is the most
    permissive of those, and ``None`` when any kind has no ceiling in force:
    then the country's usual figure may be lawful and is not lowered.

    Args:
        country_code: The project's ISO 3166-1 country.
        subdivision_code: The project's ISO 3166-2 subdivision, or ``None``.
        as_of: The day the contract is entered into. A draft created today is
            entered into today at the earliest.

    Returns:
        ``None``, or ``percent`` (a decimal string), ``subdivision_code``,
        ``subdivision_name``, ``since`` (the ISO date from which every kind of
        works is capped), ``as_of`` and ``rules`` (one per kind of works:
        ``code``, ``works``, ``percent``, ``statute_reference``,
        ``effective_date``).
    """
    country = normalise_country(country_code)
    wanted = (subdivision_code or "").strip().upper()
    if not country or not wanted:
        return None
    from app.core.regional_packs import resolve_progress_billing  # noqa: PLC0415

    subdivision = (resolve_progress_billing(country_code=country, subdivision_code=wanted) or {}).get("subdivision")
    if not isinstance(subdivision, dict):
        return None
    rules = [
        rule
        for rule in subdivision.get("retainage") or []
        if isinstance(rule, dict)
        and rule.get("per_payment_percent") not in (None, "")
        and rule.get("works") in CEILING_WORKS
    ]
    binding: list[dict[str, Any]] = []
    for works in CEILING_WORKS:
        in_force = [rule for rule in rules if rule["works"] == works and _commenced(rule, as_of)]
        if not in_force:
            return None
        binding.append(min(in_force, key=lambda rule: Decimal(str(rule["per_payment_percent"]))))
    ceiling = max(Decimal(str(rule["per_payment_percent"])) for rule in binding)
    return {
        "percent": _percent_text(ceiling),
        "subdivision_code": wanted,
        "subdivision_name": _subdivision_name(country, wanted),
        "since": max(str(rule["effective_date"]) for rule in binding),
        "as_of": as_of.isoformat(),
        "rules": [
            {
                "code": rule.get("code"),
                "works": rule["works"],
                "percent": _percent_text(rule["per_payment_percent"]),
                "statute_reference": rule.get("statute_reference"),
                "effective_date": rule.get("effective_date"),
            }
            for rule in binding
        ],
    }


def _ceiling_source(ceiling: dict[str, Any]) -> dict[str, Any]:
    """The source of a rate lowered to a statutory ceiling, shaped like a table figure's."""
    params = {
        "percent": ceiling["percent"],
        "subdivision": ceiling["subdivision_name"],
        "since": ceiling["since"],
    }
    note = STATUTORY_CEILING_NOTE
    for name, value in params.items():
        note = note.replace("{{" + name + "}}", str(value))
    return {
        "source": "statute",
        "reference": "; ".join(str(rule["statute_reference"]) for rule in ceiling["rules"]),
        "note": note,
        "note_key": STATUTORY_CEILING_NOTE_KEY,
        "note_params": params,
    }


def resolve_contract_defaults(
    country_code: str | None,
    *,
    subdivision_code: str | None = None,
    as_of: date | None = None,
    works: str | None = None,
) -> dict[str, Any] | None:
    """The usual payment terms of ``country_code``, or ``None`` when the table has no row.

    With ``works`` (``"public"`` or ``"private"``) and a variant for it in
    :data:`WORKS_CONTRACT_DEFAULTS`, the figures that law changes are laid
    over the country row; without it the row stands.

    With a ``subdivision_code`` whose pack states a retention ceiling in force
    on ``as_of`` (today when not given) for every kind of works, a usual rate
    above it is lowered to it, and its source names the statutes
    (:func:`statutory_retention_ceiling`).

    Returns:
        ``None`` for a blank or unknown country. Never another country's row.
        Otherwise a new dict: ``country_code``, ``standard_form``, ``values``
        (one entry per :data:`CONTRACT_DEFAULT_FIELDS`, ``None`` where the
        market has no usual figure), ``sources`` (per field: ``source``,
        ``reference``, ``note`` in English and ``note_key``, the i18n key the
        note is translated under) and ``release_split_source``, which is
        ``"regional_pack"`` when the split was read from the pack and
        ``"table"`` otherwise, and ``statutory_ceiling``: ``None``, or what
        :func:`statutory_retention_ceiling` answered for the subdivision,
        and ``works``: the variant applied, ``None`` when the row stands.
    """
    country = normalise_country(country_code)
    row = COUNTRY_CONTRACT_DEFAULTS.get(country)
    if row is None:
        return None
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
            "note_key": note_key(country, field),
        }
    standard_form, applied_works = _apply_works(
        country, normalise_works(works), values, sources, row.get("standard_form")
    )
    ceiling = (
        statutory_retention_ceiling(country, subdivision_code, as_of=as_of or _today()) if subdivision_code else None
    )
    rate = values.get("retention_percent")
    if ceiling is not None and rate is not None and Decimal(str(rate)) > Decimal(ceiling["percent"]):
        values["retention_percent"] = ceiling["percent"]
        sources["retention_percent"] = _ceiling_source(ceiling)
    return {
        "country_code": country,
        "standard_form": standard_form,
        "values": values,
        "sources": sources,
        "release_split_source": split_source,
        "statutory_ceiling": ceiling,
        "works": applied_works,
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
    "CEILING_WORKS",
    "CONTRACT_DEFAULT_FIELDS",
    "COUNTRY_ALIASES",
    "COUNTRY_CONTRACT_DEFAULTS",
    "COUNTRY_RETENTION_BASIS",
    "DEFAULTS_STAMP_KEY",
    "FROM_REGIONAL_PACK",
    "NET_RETENTION_BASIS",
    "NOTE_KEY_PREFIX",
    "PAYMENT_TERMS_KEY",
    "PAYMENT_TERM_FIELDS",
    "PLATFORM_FALLBACK",
    "STATUTORY_CEILING_NOTE",
    "STATUTORY_CEILING_NOTE_KEY",
    "VALUATION_INTERVALS",
    "WORKS_CONTRACT_DEFAULTS",
    "WORKS_NOTE_KEY_PREFIX",
    "RetentionBasis",
    "apply_contract_defaults",
    "contract_works",
    "forget_overridden",
    "normalise_country",
    "normalise_works",
    "note_key",
    "resolve_contract_defaults",
    "resolve_retention_basis",
    "statutory_retention_ceiling",
    "subcontract_retention_default",
    "subdivision_from_address",
    "validate_release_split",
    "works_note_key",
]
