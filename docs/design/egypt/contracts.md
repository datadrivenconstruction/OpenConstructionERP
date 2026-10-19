# Egypt: contracts, payment and procurement rules

Stream `contracts` of the Egypt programme. Branch `wip/eg-contracts-20261019`, base
`integration/18.7.0-20261017`.

## Scope

Egyptian contract and payment rules written as data into the registries the platform already has,
plus the two country-neutral capabilities that were missing:

1. Public works under the Public Contracts Law 182/2018 and its Executive Regulations (Minister of
   Finance Decree 692/2019): guarantees, advance payment, interim payment at 95 percent, stored
   materials at 75 percent, the 60 day payment clock, quantity variation, delay damages caps and the
   mandatory quarterly price adjustment.
2. Private works: the FIDIC family, retention as the Contract Data states it, and the decennial
   liability of the Civil Code (Art. 651, claim lapse Art. 654).
3. Social insurance on contracting (Law 148/2019, Decree 152/2019): the clearance certificate that
   must be shown before an interim or final payment is released.
4. Contractor classification (EFCBC grades 1 to 7) as reference data.

Out of scope here: VAT and withholding (stream `tax`), calendars (stream `cal`), e-invoicing, the
pack itself (the lead selects and configures it last).

## Sources

Primary text read for this stream: the consolidated English translation of Law 182/2018 with the
Executive Regulations, Andersen Egypt, January 2026,
https://eg.andersen.com/wp-content/uploads/2026/01/Law-No.-182-of-2018.pdf (read 2026-10-19).
Articles quoted in the data rows: Law Art. 16, 40, 44, 45, 46, 47, 48; Executive Regulations
Art. 92, 93, 96, 97, 98. Everything else comes from the programme research file and carries its
confidence; anything marked UNCONFIRMED there is shipped only as data flagged
`needs_expert_review`, or left out with the reason recorded below.

The commencement dates of Law 182/2018 and Decree 692/2019 were not established from a primary
text, so every row says `effective_date: None` ("commencement not established"), the convention the
DACH pack already uses. No row invents a date.

## Decisions

**D1. Public versus private is the project's `works`, not a second country.** The contracts module
already lays a works variant over a country row (`WORKS_CONTRACT_DEFAULTS`, France). The EG country
row is the private FIDIC profile; the `public` variant carries Law 182. A works variant could until
now only change retention figures. Egypt's public payment period (60 days) and certificate name
(مستخلص) also differ, so the variant may now also set `payment_period_days` and `certificate_name`.
That is a two-line relaxation of `_validate_works_table`; `_apply_works` was already generic.

**D2. Private retention has no Egyptian number.** FIDIC leaves the percentage and the limit of
retention money to the Contract Data, and the 5 to 10 percent practice figure is low confidence. The
private row therefore says `None` for both with a note, instead of borrowing the Gulf's 10 percent.
Public works: 5 percent of every interim (ExReg Art. 93, "at a rate of 95%"), no ceiling, released
at provisional acceptance (`substantial_completion`), when the final statement pays what is due.

**D3. One price adjustment engine for every country.** Egypt's Art. 97 formula
`V x sum(c_i x (I_i,t - I_i,0) / I_i,0)` is algebraically the FIDIC 13.8 adjustment
`V x (a + sum(b_i x I_i,t / I_i,0) - 1)` with `a = 1 - sum(b_i)`. The engine
(`contracts/price_adjustment.py`) is pure Decimal math over weighted indices. A regime row
(`PRICE_ADJUSTMENT_REGIMES`) holds what differs per law: the period (3 contractual months), the
minimum contract duration (6 months), the coefficient constraint (each above zero, sum below one),
the base date (opening of technical envelopes), the index publisher (CAPMAS PPI) and the settlement
period (60 days). Index values are not shipped; a tenant keeps them as `price_index` series and the
endpoint reads the points by period, so there is one store of index numbers.

**D4. Statutory public works limits are one registry, read by contract rules.**
`contracts/public_procurement.py` holds `PUBLIC_WORKS_LIMITS["EG"]`, each figure with article,
source URL and read date. Two new rules in the existing `contracts` rule set read it and stay silent
unless the project is in a country that has a row and records `works = public`:
`contracts.public_works_limits` (retention, advance payment, delay damages cap, performance
security) and `contracts.price_adjustment_terms` (coefficients present and valid on works of six
months or more). The contract rule context gained the fields these rules need (security amount and
percent, the LD clauses, contract value and dates, the project's country and works). It is additive.

**D5. The clearance gate is a generic "payment release requires a certificate" capability.** The
packs already state what a payee must hold before being paid (`progress_billing.sub_payment_
requirements.requirements`, evidence `certificate`, with a closed certificate vocabulary that already
names `social_security_clearance`). A requirement now opts into the payment release gate with
`"gates": ["payment_release"]` and says `release_effect: "block" | "warn"`. Rule V19
`payment_release.release_certificates` checks every open interim or final invoice of a contract: the
contract's counterparty (a subcontractor record, found by its id or by its contact) must hold a
certificate of that type that is not revoked and is valid on the release date. A blocking finding is
an ERROR and stops the release the way every other payment release error does; a warning is shown
and does not stop it. Opt-in by data keeps the US and DACH requirements (which describe the GC claim
rollup) from suddenly blocking releases.

A contract can override the pack per contract through the payment terms
(`release_certificates_enforcement`: `pack`, `block`, `warn`, `off`), stored in the existing
`PaymentTerms.metadata` JSON, so no migration.

**D6. Egypt's clearance gate ships as a warning.** Decree 152/2019 Art. 206(3) suspends each interim
and final payment until the contractor shows the social insurance certificate, but the research
could not confirm that the decree stands unchanged under Law 148/2019 and its regulations
(UNCONFIRMED). The requirement is therefore `release_effect: "warn"` with
`needs_expert_review: true`. A company that confirms it switches a contract to `block`.

**D7. Things left out on purpose, with the reason.**
- Table 8 wage percentages of Decree 152/2019: only a secondary source, research says not to ship
  them as data without the official table. The mechanism is described in data with every percentage
  `None` and `needs_expert_review`.
- The current contracting multiplier under Law 148/2019 (18, 18.25 or 18.75 percent): sources
  disagree. Not shipped.
- EFCBC grade value limits (Decree 439/2022): not read. Grades 1 to 7 ship with
  `max_project_value: None`, `needs_expert_review: true`.
- Bid (provisional) guarantee 1.5 percent: a tender figure, and the contract records no bid
  security type. Shipped as data in the limits row; no contract rule reads it.
- Stored materials at 75 percent: shipped in the progress billing block. The retention engine has no
  "valuation percent" for stored materials, and mapping 75 percent to a 25 percent retention would
  hold money past installation, so nothing applies it yet.
- Civil Code Arts. 661 and 662 (subcontracting): UNCONFIRMED, not shipped.

**D8. Where the data lives.**

| Data | Registry |
|---|---|
| Private and public contract defaults | `contracts/country_defaults.py` (`COUNTRY_CONTRACT_DEFAULTS["EG"]`, `WORKS_CONTRACT_DEFAULTS["EG"]`) |
| Public works limits, EFCBC grades, contracting social insurance mechanism | `contracts/public_procurement.py` |
| Price adjustment regimes and engine | `contracts/price_adjustment.py` |
| 60 and 30 day payment clocks, late payment financing at the CBE rate | `payment_clock/data.py` (`eg_law182_works`, `eg_law182_supplies`) |
| Progress billing (public retention rate, stored materials, clearance requirement, billing cycle) | `middle_east_pack/config.py` `progress_billing["EG"]` |
| Contract compliance pack | `contracts/compliance_packs.py` (`eg_compliance`) |
| Decennial liability regime | `defects_liability/limitation.py` (`eg_civil_651`, 120 months from delivery) |
| Clearance gate | `payment_release/validators.py` rule V19 |

## Data model

No new table and no migration. New JSON shapes:

- `Contract.terms["price_adjustment"]`: `{"regime": "eg_law182_art97", "base_date": "YYYY-MM-DD",
  "coefficients": [{"item": "cement", "coefficient": "0.15", "index_series_id": "<uuid>"}]}`.
- `PaymentTerms.metadata["release_certificates_enforcement"]`: `pack | block | warn | off`.
- Requirement entries in `sub_payment_requirements.requirements` may carry `gates`,
  `release_effect`, `applies_to_kinds` and `needs_expert_review`.

## Worked example (price adjustment, Art. 97)

Value of works executed in the quarter at bid prices: EGP 10,000,000. Coefficients from the
technical envelope: cement 0.15, reinforcing steel 0.25, labour 0.20 (sum 0.60, below one; the
remaining 0.40 is fixed). CAPMAS PPI at the opening of technical envelopes and at settlement:
cement 200 to 230 (+15 percent), steel 300 to 270 (-10 percent), labour 150 to 165 (+10 percent).

    cement   0.15 x  0.15 =  0.0225
    steel    0.25 x -0.10 = -0.0250
    labour   0.20 x  0.10 =  0.0200
    sum                   =  0.0175
    10,000,000 x 0.0175   = EGP 175,000.00 owed to the contractor

The same inputs with a steel coefficient of 0.70 (sum 1.05) are refused, because Art. 97 requires
the coefficients of an item to add up to less than one. A contract of five months gets no adjustment
periods at all; one of nine months starting 2026-01-15 adjusts at 2026-04-15, 2026-07-15 and
2026-10-15.

## Test plan (distinguishing cases)

Each case below fails on the code before this change and passes after; each pair differs in exactly
the input the rule depends on.

1. Public versus private profile. `resolve_contract_defaults("EG", works="public")` gives retention 5,
   payment period 60, certificate مستخلص, release at `substantial_completion`; with works `private`
   or unrecorded it gives the FIDIC row (56 days, IPC, 50 then 100, retention `None`). A subcontract
   on a public project resolves private.
2. Retention release. Public split releases 100 percent at provisional acceptance; private releases
   50 at taking over and 100 of the remainder at the end of the defects period.
3. Price adjustment quarter calculation: the worked example above to the piastre, the
   sum-of-coefficients refusal, a zero coefficient refusal, the five versus nine month period
   schedule, and the index lookup by period from a `price_index` series.
4. Payment blocked without clearance. Same EG contract and invoice, enforcement `block`: without a
   `social_security_clearance` certificate V19 is an ERROR on the invoice and `release_invoice`
   answers 409 `release_blocked_by_findings`; with a valid certificate it passes; with an expired or
   revoked one it fails again; with the pack default (`warn`) it is a WARNING and the release goes
   through; with `off` nothing is reported; a German project with the same data reports nothing,
   because its requirements do not opt into the gate.
5. Public works limits. On an EG public project: retention 6 percent is an error and 5 passes; an
   advance payment bond of 30 percent is an error, 25 passes, 40 passes when the terms record an SME
   contractor (cap 50) and 30 passes with Minister of Finance approval recorded; an LD clause capped
   at 20 percent of the contract value is an error and 15 passes; no performance security is a
   warning and a 5 percent one passes. The same contract on a private EG project or a German public
   project reports nothing.
6. Price adjustment terms. EG public works of nine months without coefficients is an error; of five
   months it is silent; coefficients summing to one or more, or one at zero, are errors.
7. Payment clock: `eg_law182_works` gives a final date 60 calendar days after submission.
8. Coverage: `country_coverage.py EG` reports `payment.prompt_payment_regime` and
   `contract.compliance_pack` covered.

## Open questions for a local expert or the founder

- Does Decree 152/2019 Art. 206(3) still bind under Law 148/2019 and PM Decree 2437/2021? If yes,
  switch the Egyptian requirement to `block`.
- The official Table 8 wage percentages and the current contracting multiplier.
- EFCBC grade value limits under Decree 439/2022.
- Commencement dates of Law 182/2018 and Decree 692/2019 for the `effective_date` fields.
- Typical private-sector retention and limit of retention money in Egyptian FIDIC Particular
  Conditions.
