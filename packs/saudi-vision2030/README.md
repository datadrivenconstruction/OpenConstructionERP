# OpenConstructionERP — Saudi Vision 2030 Pack

Partner pack pre-configuring [OpenConstructionERP](https://github.com/DataDrivenConstruction/openconstructionerp)
for Saudi Arabian mega-project contractors — NEOM, Red Sea Global,
Diriyah Gate, Qiddiya, PIF giga-projects, Saudi Aramco EPC, RCJY,
MoMRAH municipal works.

> **مهيأ مسبقاً لمقاولي المشاريع العملاقة في المملكة العربية السعودية —
> SBC 2024 (بكامل أجزائه)، MoMRAH وبلدي، أرامكو (SAES / SAMSS / 9COM)،
> معايير نيوم لصفر صافي الكربون، السعودة (نطاقات)، ISO 19650، مؤشرات رؤية 2030.**

## What this pack does

When installed alongside the OCERP core, this pack registers via the
`openconstructionerp.partner_packs` entry-point and the host application:

- **Switches the default locale to `ar` (Arabic, Modern Standard Arabic)** with
  RTL layout. Falls back to `en` for untranslated keys.
- **Preloads CWICR cost region: `cwicr-eng-riyadh`.** Jeddah, Dammam, Khobar,
  Makkah, Madinah, NEOM/Tabuk are surfaced as opt-in options in the
  onboarding wizard (resolved via the CWICR marketplace import).
- **Sets default currency to `SAR`** (ZATCA 15% VAT, not set by the pack).
- **Enables fourteen Saudi validation rule packs:**
  - Saudi Building Code 2024 (mandatory since 2025-06-30; replaced SBC 2018) — per-Part:
    - `sbc_201_energy` — Energy Conservation Code
    - `sbc_301_loads` — Loads & structural design (KSA seismic / wind / Hajj surcharge / sabkha)
    - `sbc_304_concrete` — Concrete (hot-weather, coastal / Gulf chloride exposure)
    - `sbc_401_electrical` — Electrical Code
    - `sbc_501_mechanical` — Mechanical (HVAC + Plumbing, with district cooling integration)
    - `sbc_801_fire` — Fire Code with Civil Defense approval gate
  - `momrah_urban_planning` — MoMRAH urban planning + Balady permit portal + contractor grade gate
  - `aramco_saes_samss` — Saudi Aramco SAES / SAMSS / GES engineering & materials standards
  - `aramco_approval_chain` — Proponent → Discipline → PMT → Inspection → AFC workflow
  - `aramco_pim_qualification` — Aramco AVL membership, Schedule Q, PIM validity, IKTVA gate
  - `neom_design_standards` — NEOM net-zero, no-ICE, 15-minute city, subzone-aware
  - `saudization_nitaqat` — Nitaqat band disclosure (band minimums for tenders await expert review)
  - `iso_19650_bim` — BIM Information Management (EIR / BEP / CDE / MIDP / TIDP)
  - `vision_2030_kpis` — IKTVA, Saudi Green Initiative, water / energy / waste targets
- **Applies Saudi flag green branding** (`#006C35` primary + `#FFFFFF` accent)
  and a bilingual Arabic + English wordmark.
- **Replaces the default first-login onboarding wizard** with a 9-step Saudi
  workflow: company profile (CR + ZATCA VAT) → MoMRAH grade + Aramco PIM + CITC
  → Nitaqat band → SBC Part toggles → primary client → CWICR regions →
  localisation (locale + Hijri calendar + bilingual exports + IKTVA) → review.

The pack ships **no** new validation rule classes (Shape A) — it only switches
on rules already present in the OCERP core. No modules are hidden; the full
sidebar remains available.

## Standards coverage

The lineage in brackets is the one stated for the 2018 edition. The base
editions the 2024 parts adopt were not confirmed when the pack moved to SBC
2024, so each rule pack keeps that list under `derives_from_2018_edition`.

| Layer | Standard | Rule pack |
|-------|----------|-----------|
| Energy | SBC 201 (derives IECC 2018 + ASHRAE 90.1-2016) | `sbc_201_energy` |
| Loads | SBC 301 (derives ASCE 7-16) | `sbc_301_loads` |
| Concrete | SBC 304 (derives ACI 318-14) | `sbc_304_concrete` |
| Electrical | SBC 401 (derives NEC NFPA 70-2017) | `sbc_401_electrical` |
| Mechanical | SBC 501 (derives IMC 2018 + ASHRAE 62.1-2016) | `sbc_501_mechanical` |
| Fire | SBC 801 (derives IFC 2018 + NFPA 1 / 101) | `sbc_801_fire` |
| Municipal | MoMRAH Urban Planning + Balady E-service | `momrah_urban_planning` |
| Aramco Engineering | SAES / SAMSS / GES (Eng Std Dept) | `aramco_saes_samss` |
| Aramco Workflow | Proponent → PMT → Inspection → AFC | `aramco_approval_chain` |
| Aramco Pre-qual | PIM / Schedule Q / AVL / IKTVA | `aramco_pim_qualification` |
| NEOM | NEOM Design Standards (THE LINE / Oxagon / Trojena / Sindalah / Magna) | `neom_design_standards` |
| Workforce | Nitaqat (Ministry of HRSD) | `saudization_nitaqat` |
| BIM | ISO 19650-1/-2/-5 | `iso_19650_bim` |
| Vision 2030 | IKTVA / SGI / energy-water-waste KPIs | `vision_2030_kpis` |

## Install

```bash
pip install openconstructionerp-saudi-vision2030
# then restart the OCERP backend — the pack is auto-discovered.
```

To deactivate, simply `pip uninstall openconstructionerp-saudi-vision2030`
and restart.

To run alongside other partner packs and explicitly select Saudi:

```bash
OE_PARTNER_PACK=saudi-vision2030 openconstructionerp serve
```

## License

AGPL-3.0-or-later, same as the OCERP core. Standards names (SBC, MoMRAH,
Balady, Saudi Aramco, SAES, SAMSS, NEOM, Nitaqat, IKTVA, Saudi Green
Initiative) are referenced for compatibility identification only — they
remain the trademarks of their respective Saudi authorities. The pack
does not redistribute any copyrighted standards text.
