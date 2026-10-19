# OpenConstructionERP × Canada Batimatech

Partner pack pre-configuring [OpenConstructionERP](https://github.com/DataDrivenConstruction/openconstructionerp)
for Canadian construction companies.

> **Pré-configuré pour les entreprises canadiennes de construction —
> normes NBC, contrats CCDC, base de coûts canadienne.**

## What this pack does

When installed alongside the OCERP core, this pack registers via the
`openconstructionerp.partner_packs` entry-point and the host application:

- Switches the default locale to **fr-CA** (Canadian French, Québec
  terminology), with **en-CA** available as a secondary locale. Falls back
  to `en` for untranslated keys.
- Preloads the CWICR cost region **cwicr-eng-toronto** (the only Canadian
  snapshot live in the marketplace today; Montréal / Vancouver / Calgary /
  Halifax / Ottawa are flagged "upcoming" in the onboarding wizard and will
  auto-activate when published).
- Sets default currency to **CAD**. The pack does not set sales tax; the tax line is set on the estimate's markups.
- Enables **nine** Canadian validation rule packs:
  - `nbc_2020` — National Building Code of Canada 2020 (Parts 1–10)
  - `ccdc_2` — CCDC 2-2020 Stipulated Price Contract
  - `ccdc_5a` — CCDC 5A-2025 Construction Management for Services
  - `ccdc_14` — CCDC 14-2013 Design-Build Stipulated Price
  - `csa_a23_1` — CSA A23.1:19 Concrete Materials & Methods
  - `csa_a23_3` — CSA A23.3:19 Design of Concrete Structures
  - `csa_s16` — CSA S16:19 Design of Steel Structures
  - `quebec_ccq` — Québec CCQ / RBQ licensing & compliance (Loi R-20)
  - `ontario_obc` — Ontario Building Code (O. Reg. 332/12) + WSIB
- Applies batimatech branding (`#BE1B2F` red + `#0F2C5F` Canadian navy)
  and replaces the boot logo / favicon.
- Replaces the default first-login onboarding wizard with a 9-step
  Canadian workflow (firm profile + province, GST/QST/HST + RBQ/CCQ/WSIB
  registrations, NBC 2020 Parts, CCDC contract default, CWICR regions,
  team invites, bilingual EN-CA/FR-CA mode, summary).

The pack ships **no** new validation rule classes (Shape A) — it only
switches on rules already present in the OCERP core. No modules are hidden;
the full sidebar remains available.

## Install

```bash
pip install openconstructionerp-batimatech-ca
# then restart the OCERP backend — the pack is auto-discovered.
```

To deactivate, simply `pip uninstall openconstructionerp-batimatech-ca`
and restart.

## License

AGPL-3.0-or-later, same as the OCERP core. The batimatech name and red
brand colour are trademarks of batimatech and used under partnership
agreement.
