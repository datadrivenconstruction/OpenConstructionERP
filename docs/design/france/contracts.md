# France, contracts stream: public and private works contracts

## 2. Public works (CCAG-Travaux 2021, Code de la commande publique)

France is a second row of the registries the Egypt contracts stream introduced, not a second structure:
`contracts/public_procurement.py` (`PUBLIC_WORKS_LIMITS["FR"]`), `contracts/price_adjustment.py`
(`fr_ccag_travaux_2021_art_10_5`) and the `contracts` rule set. Every figure carries its article, source
URL, read date and effective date.

| fact | value | source | effective |
|---|---|---|---|
| retention cap | 5 % of initial amount + modifications | CCP R2191-32, R2191-33 | 2019-04-01 |
| retention cap, SME with the State or a large public body | 3 % | CCP R2191-32 to R2191-36 (décret 2024-1251) | procedures from 2025-01-01 |
| advance | 5 % minimum, 30 % usual maximum | CCP R2191-7 | 2025-01-01 (range) |
| advance, SME minimum | 30 % with the State, 10 % with a State EPA or a local authority spending > EUR 60m | CCP R2191-7 (décret 2024-1251) | 2025-01-01 |
| late penalty | 1/3000 of the HT amount per calendar day, capped at 10 %, not applied when the total is EUR 1,000 or less | CCAG-Travaux 2021 art. 19.2.1 to 19.2.3 | 2021-04-01 |
| direct payment of a subcontractor | accepted subcontractor paid directly from EUR 600 TTC, cannot be waived | loi 75-1334 art. 6; CCP L2193-11, R2193-10 | |
| price revision | C = a + sum(b x I/I0), monthly, rounded up to the thousandth, base month of the offer | CCAG-Travaux 2021 art. 10.5; CCP R2112-13/14 | 2021-04-01 |

Decisions:

- The registry gained `OPTIONAL_LIMIT_FIELDS` (SME tiers, advance minimums, daily penalty divisor and
  waiver) instead of new mandatory fields, so the Egyptian row is untouched. A row may also name
  `derogable_fields`: general conditions the CCAP may change by listing a derogation. A finding on those
  (advance above 30 %, penalty cap above 10 %, a daily rate other than 1/3000) is a WARNING; the Egyptian
  row names none, so its findings keep their severity.
- New contract terms keys the rules read: `public_buyer_category` (`state`, `large_public_body`,
  `other`), `advance_payment_percent`, `procedure_launch_date`, `direct_payment`, `payment_guarantee`
  (`caution`, `delegation_de_paiement`) and `price_adjustment.firm_price`, plus the existing
  `contractor_is_sme`.
- Date effect: the SME tiers and the advance minimums apply when the procedure launched on or after their
  effective date (`procedure_launch_date`, else the contract start). An earlier procedure is not measured
  against them. The 20 % SME minimum of the earlier text is not encoded, so such a contract is silent
  rather than measured against a guess.
- An advance of zero is a renounced advance and passes. Whether an advance is owed at all (R2191-3) is
  UNCONFIRMED, so a missing advance is not reported.
- `delay_damages_amount("FR", value, days)` computes the CCAG penalty: EUR 900,000 HT late 120 days owes
  36,000.00, late 400 days hits the 10 % cap at 90,000.00, EUR 300,000 late 10 days (1,000.00) is waived.
- `contracts.subcontract_direct_payment` (ERROR when waived, WARNING when not recorded) reads
  `contracts/subcontract_protection.py`. It compares the subcontract's recorded total with EUR 600, so
  that total should be recorded including tax.
- Price revision is not mandatory by law in France (it depends on the raw-material share), so a contract
  longer than three months without weights is a WARNING with its own message, and a recorded firm price
  passes. The Egyptian mandatory regime keeps its ERROR.

Not encoded (UNCONFIRMED): the R2191-3 trigger for a mandatory advance (EUR 50k HT and more than two
months), advance recovery R2191-11/12, a higher advance against a first-demand guarantee, the 15-day
acceptance step of direct payment, loi 75-1334 art. 14-1, CCAG 2021 décompte général deadlines.

### Price revision

`compute_adjustment` stays the one engine. A regime may carry `coefficient_rounding`; the French regime
rounds C up (`ROUND_CEILING`, towards the contractor also when indices fall) to 0.001 before applying it.
The result then prints `revision_coefficient` and a `rounding_amount` line, so the items still add up to
the total; a regime without rounding prints neither and the Egyptian output is unchanged.

Worked example (tests): BT01, a = 0.125, b = 0.875, I0 = 120.0, I = 123.6 gives C = 1.02625, rounded up
to 1.027 (rounding to nearest would give 1.026). On EUR 100,000 of work the revision is 2,700.00:
2,625.00 from the index plus 75.00 from the rounding. With I = 116.4, C = 0.97375 rounds up to 0.974,
a deduction of 2,600.00.

INSEE BT/TP (base 2010) ship as `FR_REVISION_INDICES`: codes and names only (BT01, TP01). The INSEE series
identifiers are UNCONFIRMED and `None`; index values belong to the tenant's price index series.

### Pack manifest honesty

`code_commande_publique.json` enables `contracts.public_works_limits`, `contracts.price_adjustment_terms`
and `contracts.subcontract_direct_payment`. `ccp.avance_forfaitaire_min_20_pct` is removed (its 20 % is
outdated, and the advance is checked by the limits rule) and so is `ccp.delai_paiement_max_30_days`
(the public terms run as payment clock regimes); `superseded_rule_ids_note` says why. `nf_p_03_001.json`
enables `contracts.private_works_retention_cap` and `contracts.subcontract_payment_guarantee` and drops
`nfp03.retenue_garantie_max_5_pct` (the ceiling is the law's). `loi_mop.json`, `re_2020.json` and
`dtu_standards.json` now start their description with "Planned, not built". The manifest description and
the pack README say which checks run and which documents run nothing yet, and name the Code de la commande
publique instead of the repealed Code des marchés publics.

## 3. Private works, warranties and VAT

- Retenue de garantie 5 % (loi 71-584 art. 1): already in `WORKS_CONTRACT_DEFAULTS["FR"]["private"]`.
  `contracts.private_works_retention_cap` (ERROR) enforces it on a project recorded as private. It reads
  any country whose private works variant states a statutory ceiling, which today is France only; China's
  3 % ceiling is written for all works and stays outside this rule.
- Subcontract guarantee (loi 75-1334 art. 14): `contracts.subcontract_payment_guarantee` (WARNING) asks a
  private subcontract for a caution or a délégation de paiement.
- Warranties as limitation regimes of the defects register (`defects_liability/limitation.py`):
  `fr_civil_1792_6` parfait achèvement 12 months, `fr_civil_1792_3` biennale 24 months, `fr_civil_1792`
  décennale 120 months, all from réception. Dommages-ouvrage (C. assur. L242-1) and decennial insurance
  (L241-1) are obligations, not periods, and are named in the décennale note only.
- Reverse charge for subcontracted building works (CGI 283-2 nonies): already in `tax_withholding/data.py`.
- Renovation VAT 10 % / 5.5 % with the customer's certification mention since 2025-03-03, and VAT on
  retention due on collection: belong in the country-neutral VAT regime registry the Egypt tax stream is
  building (`app/core/vat_regimes/`), as a `data_fr.py`. Not shipped in this stream while that registry is
  uncommitted; see the report.


## VAT rates

This stream ships no VAT rate. French rates (20, 10, 5.5) are read from `backend/app/core/tax.py`, the canonical source; the works VAT selection table (dwelling older than two years, certification mention) is not built here.
