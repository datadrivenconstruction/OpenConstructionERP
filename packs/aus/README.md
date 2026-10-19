# OpenConstructionERP — Australia Partner Pack (`aus`)

Pre-configures OpenConstructionERP for **Australian** general contractors.

## What's inside

- **Locale**: `en-AU` (Australian English overrides — tradies, EBA, RDO, BAS, ABN).
- **Currency**: `AUD` (GST 10%, not set by the pack).
- **CWICR regions pre-loaded**: Sydney, Melbourne, Brisbane, Perth, Adelaide.
- **Standards & validation rule packs**:
  - `ncc_2022` — National Construction Code 2022 (Vol 1 commercial, Vol 2 housing, Vol 3 plumbing, Section J energy uplift).
  - `as_1684_timber` — AS 1684 Parts 1-4 (Design Criteria, Non-Cyclonic Span Tables, Cyclonic, Simplified).
  - `as_3600_concrete` — AS 3600:2018 concrete structures.
  - `as_4100_steel` — AS 4100:2020 steel structures.
  - `as_4000_contracts` — AS 4000-1997 / AS 4902-2000 contract suite (Annexure Parts A + B).
  - `rawlinsons_benchmarks` — Rawlinsons Australian Construction Handbook 2024 cost benchmarks.
- **Onboarding wizard** — six steps covering company profile (ABN/ACN), state builder licence (NSW Fair Trading / VBA / QBCC / WA / SA / TAS / ACT / NT), NCC volume selection + compliance path, AS 1684 wind class & BAL, AS 4000 contract variant, cost-data subscriptions.
- **Branding**: Australian green (#00843D) primary, gold (#FFCD00) accent.

## New Zealand?

Use the separate `openconstructionerp-nzs` pack — NZD (15% GST), NZBC, NZS 3604:2011, NZS 3910:2023, MBIE acceptable solutions, Rawlinsons NZ.

The legacy `openconstructionerp-aus-nzs` pack is **deprecated** in favour of these two single-jurisdiction packs.

## Install

```bash
pip install openconstructionerp-aus
export OE_PARTNER_PACK=aus
```

## Licence

AGPL-3.0-or-later — same as OpenConstructionERP core.
