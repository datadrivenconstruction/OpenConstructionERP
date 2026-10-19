# OpenConstructionERP — New Zealand Partner Pack (`nzs`)

Pre-configures OpenConstructionERP for **New Zealand** contractors.

## What's inside

- **Locale**: `en-NZ` (NZ English with Kiwi construction vocabulary — chippie, sparkie, smoko, bach, gib board, LBP).
- **Currency**: `NZD` (GST 15%, not set by the pack).
- **CWICR regions pre-loaded**: Auckland, Wellington, Christchurch.
- **Standards & validation rule packs**:
  - `nzbc_acceptable_solutions` — New Zealand Building Code (B1, B2, C, E2, E3, F2, F4, G12, H1 acceptable solutions; PS1-PS4 producer statements).
  - `nzs_3604_timber` — NZS 3604:2011 timber-framed buildings (wind zones Low → Specific Engineering Design, earthquake Z 0.13-0.6, exposure zones B/C/D + sea spray, snow load zones, H-class treatment).
  - `nzs_3910_2023_contracts` — NZS 3910:2023 Conditions of Contract (replaced 2013 edition Oct 2023; Contract Administrator / Independent Certifier split; HSWA 2015 + CCA 2002 alignment).
  - `rawlinsons_nz_benchmarks` — Rawlinsons NZ Construction Handbook cost benchmarks.
- **Onboarding wizard** — six steps covering company profile (NZBN / IRD), LBP class registration, NZBC compliance path (AS/VM/Alt-Solution), NZS 3604 wind/EQ/exposure zones, NZS 3910:2023 selection + HSWA acknowledgement, cost-data subscriptions.
- **Branding**: NZ black (#000000) primary, silver-fern red (#C8102E) accent.

## Australia?

Use the separate `openconstructionerp-aus` pack — AUD (10% GST), NCC 2022, AS 1684/3600/4100, AS 4000/4902, Rawlinsons AU.

The legacy `openconstructionerp-aus-nzs` pack is **deprecated** in favour of these two single-jurisdiction packs.

## Install

```bash
pip install openconstructionerp-nzs
export OE_PARTNER_PACK=nzs
```

## Licence

AGPL-3.0-or-later.
