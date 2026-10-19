# Egypt: VAT on construction and withholding on account of tax

Status: implemented on `wip/eg-tax-20261019`. Facts read 2026-10-19 from secondary
sources; every row that rests on one is marked for review, see "Unconfirmed".

## Scope

Two Egyptian tax facts a construction cost platform has to get right, built as
country-neutral mechanisms with Egypt as data.

1. **VAT.** The standard rate (14 percent) and the construction regimes, which
   changed on 2025-07-18:
   - before 2025-07-18, contracting works paid a 5 percent schedule tax with no
     input credit;
   - from 2025-07-18 (Law No. 157 of 2025), contracting works are standard rated
     at 14 percent with input credit;
   - a transitional option (Decree No. 418 of 2025) lets a contract signed
     before the cutoff pay 14 percent on 36 percent of the value, an effective
     5.04 percent, without input credit, under conditions.

   The scope of "construction services" (Decree No. 417 of 2025, 17 items)
   ships as data in English and Arabic.
2. **Withholding on account of tax.** Payments to contractors and suppliers are
   withheld at 1 percent (contracting), 1 percent (supplies), 3 percent
   (services) and 5 percent (commissions), on payments exceeding EGP 300, and
   declared quarterly on Form 41, by the end of the month following each
   quarter. A payee under the small-business regime of
   Law No. 6 of 2025 is exempt.
3. **Validation rules** for the regime choice, the claim date against the
   regime window, and an amount entered on a tax that does not arise.

Out of scope, with the facts recorded here so the next step does not redo the
reading:

- The VAT registration threshold, EGP 500 000 of turnover (VAT Law article 16).
  A reported cut to EGP 250 000 was not found in any source; Law No. 157 of
  2025 changed the base, not the threshold.
- The real-estate exemption, item 28 of the exempt list: sale and lease of
  vacant and agricultural land, buildings, and residential and non-residential
  units. It is a sale or lease of property, not a contracting service, so no
  construction bill row is exempted by it.
- Stamp tax on payments by government bodies (Law No. 111 of 1980, articles
  79 to 81): no current rate was read, so nothing ships.
- The VAT tax point of a construction advance. Only the general rule was found
  (tax is due when the taxable event occurs, and a sale includes payment in
  full or in part), so an advance plausibly triggers VAT; nothing
  construction-specific is coded and the point is listed for review below.

Also out of scope: e-invoice submission to the tax authority, and a screen for
choosing a regime or recording an exemption (the API and the stored fields are
there; the picker is follow-up work).

## Decisions

**One source for each rate.** VAT rates live in the tax seed
(`tax_configurations.json`), as for every other country. A VAT regime does not
repeat the rate. It names a seed `tax_code` and adds two country-neutral facts:
`base_fraction` (the share of the value taxed, 0.36 for the transitional
regime) and `input_credit`. The effective rate is computed, never stored.

**Dates decide, not flags.** The 5 percent row ends 2025-07-17 and the 14
percent construction row starts 2025-07-18. A bill priced on either date gets
the row in force on that date. A claim under a regime that was not in force on
its date is an error, with the regime that was in force named in the message.

**Eligibility is checked, not assumed.** The transitional regime is selectable
per contract, but choosing it does not make it so. The rule reports, one
finding each: a contract signed on or after the cutoff, a missing signature
and start date, each missing piece of evidence (approved certificate,
e-invoice, and for a subcontract the main contractor's certificate), evidence
dated on or after the cutoff, and a scope increase beyond what the contract
itself allowed (which, per the decree, makes it a new contract). An increase
on a contract that states no allowance is a warning, because it cannot be
judged either way.

**Withholding rows are data files.** `payment_taxes.tables.rows_for` used to
name Turkey in code. It now finds `payment_taxes/data_<cc>.py` by country code,
so Egypt is one file and Turkey gets the very same tuple as before. Two
country-neutral fields were added to a rate row: `threshold_applies`
(`at_or_above`, the old behaviour and default, or `above`, Egypt's "exceeding
EGP 300") and `payee_exemption_codes` (exemption schemes that take a payee out
of the row). A document records the scheme its payee holds in
`payee_exemption_code`.

**An override still says what it overrode.** A person may enter an amount on
any figure, with a reason. When the row's own conditions would have said the
tax does not arise (threshold not exceeded, exempt payee, buyer class), the
overridden figure now carries that reason as `waived`, and the rule
`tax_withholding.statutory_override_not_due` warns. It is a warning and not an
error because the override already carries a stated reason, and blocking it
would leave no way to record a withholding the parties agreed.

**Missing payee class is not a new rule.** A withholding with no category
chosen is already held with reason `not_chosen`, and
`tax_withholding.statutory_line_held` warns on a draft and blocks confirmation.

**GCC untouched.** `middle_east_pack` is not changed; Egypt's rows do not pass
through it.

## Data model

| Where | What |
|---|---|
| `i18n_foundation/seed_data/tax_configurations.json` | EG `VAT` 13 % (2016-09-08 to 2017-06-30), 14 % (from 2017-07-01); EG `VAT_CONSTR` 5 % (to 2025-07-17, no credit), 14 % (from 2025-07-18, credit). Each row carries `metadata.source`, `metadata.review` and `metadata.vat_treatment`. |
| `core/tax.py` `_RAW["EG"]` | standard 0.14, zero 0.00 |
| `boq/markup_templates.py` | EG in `CONSTRUCTION_TIER_COUNTRIES`, tier code `VAT_CONSTR` |
| `core/vat_regimes/` (new, stdlib only) | `VatRegime`, `Eligibility`, `ContractFacts`, `Evidence`, `Finding`; `data_eg.py` with three regimes and the Decree 417 scope |
| `core/payment_taxes/data_eg.py` (new) | four rows W001, W002, W004, W006 (the e-invoice subtype codes), threshold EGP 300 `above`, exemption `EG_LAW_6_2025_SMALL_BUSINESS` |
| `oe_tax_withholding_statutory_calc.payee_exemption_code` | new column, String(64), default empty; migration `v195_eg_tax_payee_exemption` (down revision `v94_payment_release`), inspector guarded |
| contract `terms["vat_regime"]` | `{code, evidence: {kind: {reference, issued_on}}, allowed_increase_pct}`; no new column |
| `GET /api/v1/contracts/vat-regimes/?project_id=&on=` | the regimes offered on a date, rates read from the stored tax table |

Validation rules: `contracts.vat_regime_known`, `contracts.vat_regime_eligible`
(rule set `contracts`), `pay_application.vat_regime_in_force` (rule set
`pay_application`), `tax_withholding.statutory_override_not_due`. Messages in
the six contracts locales; reason sentences `not_above_threshold` and
`payee_exempt` in the printed certificate (tr, en) and all frontend locales.

Coverage probes: `tax.payment_withholding` and `tax.vat_regimes`.

## Sources

- Law No. 157 of 2025 amending VAT Law No. 67 of 2016: https://taxnews.ey.com/news/2025-1554
- Decrees No. 417 and 418 of 2025: https://taxnews.ey.com/news/2025-2316-egypt-introduces-significant-updates-to-vat-provisions
- Schedule tax on contracting before the change: https://eg.andersen.com/subcontractors-in-egypt/
- Withholding rates and threshold: https://taxsummaries.pwc.com/egypt/corporate/withholding-taxes
- Form 41 deadline: https://www.eta.gov.eg/ar/news/aqrar-drybt-almrtbat-alrb-snwy-wnmwdhj-41-khsm-wthsyl (2024-04-15)
- Registration threshold, VAT Law article 16 (English translation): https://consortiolawfirm.com/egypt-vat-law-67-2016-english-translation/
- Standard rate history: https://taxsummaries.pwc.com/egypt/corporate/other-taxes

All read 2026-10-19. None is the primary gazette text.

## Unconfirmed, for an Egyptian tax expert

1. The start date of the 5 percent schedule tax on contracting. Shipped as
   2016-09-08 (VAT Law 67 in force) and marked `needs_expert_review`.
2. Decree No. 418 was issued 2025-10-24 for contracts from 2025-07-18. Whether
   invoices issued between those dates may be restated under the transitional
   regime is open; the code lets the regime apply from 2025-07-18.
3. The ministerial decision that sets the withholding rates, likely Ministry
   of Finance Decree No. 405 of 2018 (one summary cites No. 310 of 2013), and
   the rates' start date. Rows start 2025-03-01 (Law No. 6 of 2025) and are
   marked `unconfirmed`, so confirming a document that uses them needs an
   explicit acknowledgement.
4. Whether the EGP 300 threshold is measured before VAT. Shipped as net.
5. Whether a construction advance is a VAT tax point under a specific rule,
   or only under the general one.

## Test plan

Each case is chosen so a wrong rule gives a different answer.

- Dates: a bill dated 2025-07-17 is priced at 5 percent, one dated 2025-07-18
  at 14 percent (`tests/pg/test_a_bill_is_priced_at_its_own_countrys_vat.py`,
  `tests/unit/test_egypt_vat_resolves_on_its_dates.py`).
- Regimes offered either side of the cutoff, with rates read from the stored
  table (`tests/pg/test_egypt_vat_regimes_offered.py`).
- Eligibility: signed 2025-07-17 passes, 2025-07-18 fails; evidence dated on
  the cutoff fails; a subcontract needs the main contractor's certificate; an
  increase of 25 percent passes against a 25 percent allowance, one unit more
  fails (`tests/unit/test_vat_regimes_egypt.py`,
  `tests/unit/test_contract_vat_regime_rules.py`).
- Withholding: EGP 300.00 is not withheld, 300.01 is; each payee class at its
  own rate; an exempt payee only for the scheme the row names; Turkey computes
  exactly as before (`tests/unit/test_payment_taxes_data_eg.py`).
- Persistence: a stored exemption survives a reread and keeps the figure not
  applicable (`tests/pg/test_statutory_tax_lines.py`).
- Overrides: an amount entered where the tax does not arise warns, a zero or a
  due one does not (`tests/unit/test_tax_withholding_module.py`).
