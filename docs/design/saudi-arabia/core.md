# Saudi Arabia: tax, contracts and labour data (stream `core`)

Stream `core` of the Saudi Arabia programme. Branch `wip/sa-core-20261019`, base
`integration/18.7.0-20261017`. Sibling streams: `sa-zatca` owns e-invoicing and Saudi party
identifiers, `eg-cal` owns `core/calendar.py` (and fixes the Saudi Eid spans there), `eg-contracts`
owns the country-neutral public procurement registry this stream adds Saudi rows to.

Name trap, stated once: `backend/app/modules/sa_pack/` is SOUTH AFRICA, and the `SA` key under `AU`
in `property_dev/data/tax_rates.yaml` is SOUTH AUSTRALIA. Saudi Arabia lives in `middle_east_pack`,
`packs/saudi-vision2030/` and in the country-keyed registries below.

## Scope

Fix data that is wrong today, and add the missing Saudi facts as data in the registries the platform
already has. Every number carries its source and the date it takes effect, and anything the research
marked unconfirmed ships flagged for expert review or is left out with the reason written here.

Out of scope: ZATCA e-invoicing (stream `sa-zatca`), calendars and holidays (stream `eg-cal`), the
partner pack's selection logic beyond correcting its citations, Saudi cost catalogues (no Saudi CWICR
base is published, so `cost_classification.catalogue_standard` stays MISSING for that reason).

## Sources

Primary text read: GTPL (Royal Decree M/128, 2019) and its Executive Regulations (Ministerial
Resolution 1242/1441 as amended by 3479 of 11/8/1441), MoF English text, Articles 41, 61, 69, 72, 108,
109, 111 and 113 quoted in the data rows; ZATCA VAT Guideline for Tax Invoicing and Records v3 (May
2026) for record language and retention. Secondary: PwC tax summaries (WHT, GOSI totals, RETT, no
stamp duty), KPMG (RETT), Gulf News / DLA Piper (midday ban), Covington / Chambers (decennial
liability), HFW (inherent defects insurance), Greenberg Traurig / imHORA / MEED (new procurement law).
Full table with confidence grades: programme research file `sa_research.md`.

## Decisions

**D1. Saudi Arabia gets its own markup stack, derived from the Gulf one.** `REGION_BY_COUNTRY["SA"]`
pointed at `GULF`, whose VAT line is 5: the UAE rate and Saudi Arabia's rate until 2020-06-30. A bill
whose tax seed resolves no row (a fresh install, or a country lookup that fails) fell back to 5 against
a real 15. The new `SA` stack is built from the `GULF` lines in code, with only the tax line set to 15,
so the GCC preliminaries convention is still written once. Kuwait and Qatar stay on `GULF` and keep
their recorded mismatch: changing them needs a source this stream did not read. The frontend region
picker gains an `SA` entry. The tax seed gains the missing 5 percent row for 2018-01-01 to 2020-06-30,
so a bill dated in 2019 resolves 5 from the seed instead of falling through to the stack.

**D2. Public works are the project's `works`, the private profile stays FIDIC.** Same mechanism as
France and Egypt: `COUNTRY_CONTRACT_DEFAULTS["SA"]` remains the FIDIC Red Book profile (private works)
and `WORKS_CONTRACT_DEFAULTS["SA"]["public"]` carries the GTPL figures the contract form pre-fills:
retention 10 percent of each invoice (IR Art. 111(1)), cap 10 percent for general construction (IR
Art. 111(2), the "final invoice" is a floor the deductions build up to and also the most that may be
deducted), released in full at initial delivery against the completion, zakat/tax and GOSI
certificates, payment period 70 working days expressed through the payment clock rather than as a
calendar figure (see D4), certificate name "Contractor invoice (مستخلص)".

**D3. Statutory limits as two dated regimes, chosen by tender date.** The public works limits of a
country can change with a new law, and the law that governs a contract is the one in force when the
tender was floated, not when the contract was signed. Saudi Arabia is the first country with two:
the GTPL 2019 regime and the new Government Tenders and Procurement Law (Royal Decree M/76, published
2026-09-04, effective 120 days later, about 2027-01-02). The new law's figures come from law-firm
summaries only and its implementing regulations are not issued, so every figure of that regime is
`needs_expert_review` and its start date is flagged as approximate. The registry grows a dated list
per country (`PUBLIC_WORKS_LIMIT_REGIMES`) beside the single-row table; a country with one law keeps
its row unchanged. Fields Saudi Arabia needs that Egypt does not (total variation up and down, the
final-invoice floor for other contracts, the price adjustment trigger and cap, the three stages of the
payment cycle) are optional fields, validated the same way when present.

GTPL 2019 regime values: bid guarantee 1 to 2 percent (Law Art. 41), final guarantee 5 percent within
15 working days (Art. 61), advance up to 10 percent recovered pro rata from every invoice (IR Art.
108), retention up to 10 percent per invoice until the final invoice reaches 10 percent (works) or 5
(other) (IR Art. 111), variation +10 / -20 percent of contract value (Art. 69), delay penalty cap 6
percent supply and 20 percent other contracts (Art. 72), price adjustment (IR Art. 113) when a listed
raw material moves at least 10 percent per official index AND the contract cost changes by more than
3 percent of contract value, claim within 60 days, compensation capped at 20 percent. The English text
reads "over five percent (3%)": the figure in brackets is shipped, the conflict is recorded in the
note and the row is `needs_expert_review` until the Arabic text is checked.

**D4. The public payment cycle is a payment clock regime.** IR Art. 109: consultant 10 working days,
authority 15 working days to issue the payment order, Ministry of Finance 45 working days to pay. As a
`PAYMENT_REGIMES` row (`sa_gtpl_ir109`): due on the invoice date, payment order (the notice) 25
working days after it, final date 70 working days after it, on the Saudi Sunday to Thursday week.
Interest: Saudi courts do not enforce interest, so the row says the contract governs and the note says
a financing charge clause is unenforceable. No private regime ships: there is no Saudi prompt payment
statute (DLA Piper 2025).

**D5. Price adjustment is a trigger, not a formula.** Egypt's Art. 97 is an index formula and runs
through the `price_adjustment` engine. Saudi Art. 113 is a two-threshold test plus a cap, decided by a
committee. It ships as a regime row with the thresholds, the material list, the 60/21/45/45 day
procedure and the cap, and a pure function that answers whether a claim crosses both thresholds and
how much of it is payable under the cap. It does not compute an amount from indices.

**D6. Compliance pack.** `sa_compliance` runs `boq_quality` and `masterformat`, the classification
the registry, the partner pack and both Saudi demos already name. The GTPL limits run in the
`contracts` rule set on public works, as for Egypt.

**D7. Saudi Building Code 2024.** The partner pack cited SBC 2018 everywhere. SBC 2024 is mandatory
since 2025-06-30 after a 180-day transition. Citations, publication years and the onboarding text move
to 2024. The "derives from" lineage of each part was stated for the 2018 edition; the 2024 base
editions were not read, so each part keeps the old list under `derives_from_2018_edition` and says the
2024 lineage needs review, rather than guessing new I-code years. The Jeddah hospital demo moves to SBC
2024 as well, because a hospital designed in 2026 is designed to it.

**D8. Nitaqat claims without a source are removed from the prose and recorded as open.** "At least
Yellow" (the Yellow band was reportedly abolished in the 2026-04-26 phase) and "public tenders require
Green-Medium" (no source found) are taken out of the description. The rule ids stay planned, the two
that encode those claims are marked `needs_expert_review` with the reason, and the severity override
for the tender rule is dropped because no rule may claim ERROR on an unsourced requirement.

**D9. Real estate is VAT exempt with RETT, not zero-rated.** `property_dev` modelled the first
residential sale as zero-rated. Since 2020-10-04 a real estate disposal is exempt from VAT (VATEX-SA-30,
VAT IR Art. 30) and carries the 5 percent Real Estate Transaction Tax. The class becomes `exempt`,
dated 2020-10-04, applying to real estate sales; the `zero_rated` class is removed so a caller still
asking for it is refused instead of receiving a mislabelled zero. The relief for a first home (the
state bears RETT up to SAR 1 million) is a buyer-side relief the engine has no input for; it is
written in the note, not computed. The "stamp-duty-style bands" finding was the South Australia row
under `AU` and is correct; nothing changes there.

**D10. Non-resident withholding tax is a payment tax table.** `app/core/payment_taxes/data_sa.py`
carries `income_withholding` rows: management fees 20, royalties 15, related-party services 15,
technical and consulting services 5, rent 5, other payments 15, dividends 5, interest 5 (Income Tax
Law Art. 68, IR Art. 63, PwC). The condition on every row: the payee is not resident and has no
permanent establishment in the Kingdom; a tax treaty may reduce the rate. Rows are `unconfirmed`
(read in a reliable secondary source, not the regulation). Remittance by the 10th of the following
month is in the note. Resident-to-resident payments carry no withholding, which is why no domestic
row exists.

**D11. Social insurance contributions are a new country-neutral table.** No registry held statutory
payroll contributions. `app/core/social_contributions.py` holds dated rows per country, scheme, payer
and cohort, with the contributory wage cap, and a resolver that picks the rows in force on a date for
a cohort. Saudi rows: legacy cohort annuities 9 + 9, SANED 0.75 + 0.75, occupational hazards 2
employer; new-entrant cohort (Social Insurance Law, in force 2024-07-03) annuities stepping 9.5 /
10 / 10.5 / 11 percent each side every July 2025 to 2028 (secondary sources, one disagrees on the
2026 step, so the stepped rows are `needs_expert_review`); non-Saudi employees 2 percent hazards,
employer only; wage cap SAR 45,000 a month.

**D12. Outdoor work restrictions are a new country-neutral table, read by a field-time warning.**
`app/core/work_restrictions.py` holds seasonal outdoor work bans: Saudi Arabia 12:00 to 15:00 from 15
June to 15 September (HRSD annual decision; exemptions for oil and gas and emergency work). A new
field-time rule `field_time.outdoor_heat_ban` warns on any timesheet line whose recorded hours overlap
the window on a day inside the season in the project's country. It is a warning, never an error: the
timesheet does not record whether the work was outdoors, and exemptions exist.

**D13. Record keeping obligations are a new country-neutral table.** `app/core/record_keeping.py`
holds retention periods (Saudi: 6 years from the end of the tax period for VAT records and invoices,
capital asset records for the adjustment period plus 5 years, real estate records 15 years, VAT IR
Art. 66) and the language requirement for invoices and records (Arabic required, other languages
allowed beside it, Arabic authoritative, VAT IR Art. 66(2)). The ZATCA stream reads the language row
if its pre-clearance validator checks Arabic fields; this stream does not touch the e-invoice
validators.

**D14. Decennial liability is a limitation regime; inherent defects insurance is data beside it.**
`sa_sbc_decennial`: 10 years from completion (occupancy), contractor, designer and supervising
consultant jointly liable for collapse and defects threatening stability or safety, Saudi Building
Code Application Law (Royal Decree M/43) Art. 29. Mandatory inherent defects insurance (Cabinet
Resolution 509, from 2020-05-02, initially main cities of five regions) is a data row with its current
scope flagged for review.

## Implementation notes (as built)

The Saudi regimes live in `contracts/public_procurement_sa.py` and are registered as
`PUBLIC_WORKS_LIMIT_REGIMES["SA"]`; Egypt's single row in `PUBLIC_WORKS_LIMITS` is untouched. A figure
may carry `needs_expert_review`, and `limit_value` answers `None` for such a figure, so the whole 2026
regime is visible and never enforced. The rule reads the tender date from `terms.tender_date`, falls
back to the contract start date (the latest day the tender can have been floated, which leans towards
the unenforced regime and so never blocks wrongly), then to today.

The Article 113 trigger is `PRICE_ADJUSTMENT_TRIGGERS["sa_gtpl_ir113"]` with `assess_trigger_claim`,
kept apart from `PRICE_ADJUSTMENT_REGIMES` so the index formula endpoint and the coefficient rule never
see it.

The payment clock counted business days Monday to Friday only. `app.core.day_basis.add_days` now takes
the working week, and `compute_schedule` passes the regime country's week from the table in
`app.core.calendar` (read, not edited). Every business-day regime shipped before this is in a Monday to
Friday country, so their dates do not move.

Not built: a payment release gate for the zakat/tax and GOSI certificates of IR Art. 111. The gate
applies to every contract of a country, Article 111 binds public contracts only, and no certificate
type for a zakat/tax clearance exists yet. The certificates are named in the release note instead.

## Test plan (distinguishing cases)

1. Markup: `resolve_region_lines(region_key_for_country("SA"))` has one tax line at 15, every other
   line identical to `GULF`; `AE` still resolves to `GULF` at 5. The drift test no longer excuses SA.
2. Tax seed: SA resolves 5 on 2019-06-01 and 15 on 2020-07-01, with no overlap.
3. Contracts: `resolve_contract_defaults("SA", works="public")` gives retention 10, cap 10, release
   100 at substantial completion; `works="private"` and unrecorded give FIDIC (10 capped 5, 56 days).
   A subcontract on a public project resolves private.
4. Limits: `public_works_limits("SA", tender_date=2026-12-31)` is the 2019 regime (delay cap other 20,
   variation up 10); `tender_date=2027-01-02` is the new regime (delay cap 15, variation up 20, every
   figure `needs_expert_review`). Egypt answers its single row for any date.
5. Price adjustment trigger: item +10 and contract +3.01 triggers; item +9.99 or contract +3.00 does
   not; a claim of 25 percent is payable at 20 with 5 left to the court.
6. Payment clock: an invoice submitted on Sunday 2026-11-01 has its payment order due 25 Saudi working
   days later and its final date 70 working days later, on the Sunday to Thursday week.
7. Property: SA `exempt` on 2020-10-04 is 0.00 and is refused on 2020-10-03; `zero_rated` is refused.
8. WHT: every SA row validates, management fees 20, technical services 5; a lookup on a date before
   the earliest row is held.
9. GOSI: a Saudi legacy employee on 2026-10-19 resolves employee 9.75 and employer 11.75; a new
   entrant on 2026-08-01 resolves annuities 10 each side; a non-Saudi resolves employer 2 and
   employee 0; the cap is 45,000.
10. Heat ban: a line 10:00-16:00 on 2026-07-01 in a Saudi project warns; the same line on 2026-09-16
    does not; 06:00-12:00 does not; a German project with the same line does not.
11. Record keeping: SA invoices 6 years, real estate 15; required language for an SA tax invoice is
    Arabic.
12. Decennial: an SA regime from completion 2026-01-15 ends 2036-01-15.
13. Coverage: `country_coverage.py SA` reports `payment.prompt_payment_regime` and
    `contract.compliance_pack` covered.

## Open questions for a Saudi expert or the founder

- IR Art. 113 contract impact threshold: the English text says "five percent (3%)"; which figure does
  the Arabic text give? Also whether MoF Decision 257 (September 2026) replaced Art. 113.
- New procurement law: exact entry into force, delay cap 15 percent, final guarantee exemption up to
  SAR 300,000, and the implementing regulations when issued.
- GOSI new-entrant step dates (one source puts 9.5 percent in July 2026).
- Nitaqat 2026 phase: whether the Yellow band is gone, construction thresholds, and whether any public
  tender requires a minimum band.
- Inherent defects insurance scope in 2025-2026; decennial claim window.
- WHT per-service mapping beyond the PwC buckets (rent at 5 versus 15 in some summaries).
