# Egypt Construction Pack

A country pack for construction work in Egypt. It composes what the platform
already holds for the country and adds a Cairo demo project. It sets no tax
rate, calendar or contract limit of its own: those come from core registries
keyed by the project country, each with its source.

## What this pack configures

- **Currency EGP**, **MasterFormat** classification (the answer of the
  classification registry for Egypt) and the `egypt` estimating method
  (overhead 13, profit 10, VAT 14 percent, in that cascade).
- **Rule sets** `masterformat` and `boq_quality`.
- **Demo project**: a 180-apartment residential compound in New Cairo, priced
  in EGP at illustrative levels. It is a showcase, not a price list.
- **Reference documents** (`rule_packs/`): Public Contracts Law 182/2018,
  VAT on construction services (Law 157/2025) and Egyptian Tax Authority
  e-invoicing. Each cites its source and is marked provisional.
- **English default** (tenders are written in English) with Arabic titles in onboarding; the interface language is the user's choice.

## What the platform does for an Egyptian project, with or without the pack

- **VAT**: 14 percent standard. Contracting works carried 5 percent without
  input credit until 2025-07-17 and carry 14 percent with credit from
  2025-07-18; a transitional regime (Decree 418/2025, effective 5.04 percent)
  exists for contracts signed earlier. Resolved by the document date.
- **Calendar**: Sunday to Thursday week and Egyptian public holidays, Islamic
  dates computed.
- **Contracts**: FIDIC Red Book 2017 profile for private works; Law 182/2018
  limits (retention, advance payment, delay damages, security, price adjustment)
  checked on public works.
- **E-invoicing**: ETA v1.0 documents built from finance invoices, checked
  before they leave, signed through a pluggable eSeal signer.
- **Identifiers**: tax registration number, national ID and commercial register
  number validated by format.
- **Labour standards**: Labour Law 14/2025 hours, overtime and leave.

## Not in the pack yet

- **Cost base**: `EG_CAIRO_ar` is in the base registry but no data file is
  published to load, so `cwicr_regions` is empty.
- **Contractor grade limits** (EFCBC) and **social insurance deemed wage
  percentages** on contracts: not confirmed in a primary text, shipped empty and
  flagged for review.
- **Expert review**: none of this has been read by an Egyptian quantity
  surveyor or tax adviser yet.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Egypt Construction Pack", then Activate pack.

Nothing in this pack is legal or tax advice.
