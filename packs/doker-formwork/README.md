# OpenConstructionERP × Doker — Formwork Partner Pack

Pre-configures OpenConstructionERP for **formwork (Schalung) and concrete
contractors** in the DACH region.

## What it does

When installed alongside `openconstructionerp`, this pack:

- Sets German (`de`) as the default locale, with **80+ formwork-trade
  term overrides** (Schalung, Schaltafel, Schalungsanker, Frischbetondruck,
  Aufschüttungsgeschwindigkeit, Nutzungshäufigkeit, Taktzeit, Sichtbeton,
  Bewehrung, Biegeliste, Sichtbeton-Klassen SB1–SB4 …)
- Preloads three CWICR cost regions — Berlin (national average),
  München (Bavaria / Doker HQ), Düsseldorf (NRW)
- German VAT (19 %) is not set by the pack
- Enables **eight** validation rule packs:
  - `din_18218_formwork_pressure` — fresh-concrete pressure σ_h_max
    against pour rate v (m/h), consistency class F1–F6/SCC, concrete
    temperature, retarder factor
  - `din_en_12812_falsework` — Traggerüste load classes A/B1/B2,
    deflection L/500, γ_F ≥ 1.5, lateral stability
  - `din_en_13670_concrete_execution` — execution classes EXC-1/2/3,
    curing classes NBK-1/2/3/4, concrete cover c_nom, hot/cold weather
  - `concrete_din_en_206` — strength class C-/LC-, exposure classes
    XC/XD/XS/XF/XA/XM, consistency, max aggregate, chloride class,
    min cement content and max w/c per exposure
  - `vob_c_din_18331_concrete_works` — Abrechnungseinheiten,
    Nebenleistungen, Sichtbeton-Klassen, Öffnungs-Abzugsschwelle 2,5 m²
  - `dguv_101_008_formwork_safety` — fall protection ≥ 2 m, guardrail
    1 m, toe board, platform load class, crane lift plan ≥ 500 kg
  - `formwork_cycle_quality` — phase completeness, stripping time,
    prop release order
  - `formwork_cycle_economics` — reuse factor (Nutzungshäufigkeit),
    takt time per element, module-raster efficiency ≥ 0.85,
    abandonment cost on incomplete cycles
- Ships a curated **catalogue of 8 formwork system types** — light and
  standard steel frame panels, aluminium frame panels, timber beam slab
  formwork, slab tables, adjustable column formwork, crane-climbed
  climbing formwork and shoring towers — with their DIN 18218 classes,
  max pressures, panel modules and typical reuse counts.
  Loaded into `metadata.doker_systems` at boot.
- Replaces the default onboarding wizard with a **6-step Schalung flow**
  that asks the questions a formwork contractor actually needs to answer
  (company size, project type, systems in inventory, default pour rate,
  default consistency class, BG-BAU membership, VOB/B vs BGB default)
- Applies Doker branding — primary `#003D7A` (industrial blue),
  accent `#F58220` (safety orange)

## Install

```bash
pip install openconstructionerp-doker-formwork
```

The pack is discovered automatically via the
`openconstructionerp.partner_packs` entry-point group. To force-select
it when multiple packs are installed:

```bash
export OE_PARTNER_PACK=doker-formwork
```

## Standards covered

| Standard | Scope |
| --- | --- |
| DIN 18218:2010-01 | Frischbetondruck auf lotrechte Schalungen |
| DIN EN 12812:2008 | Traggerüste — Anforderungen, Bemessung |
| DIN EN 13670:2011-03 | Ausführung von Betontragwerken |
| DIN EN 206:2021-06 | Beton — Festlegung, Eigenschaften, Herstellung |
| DIN 1045-2 / -3 | National application of EN 206 / EN 13670 |
| VOB/C DIN 18331:2019-09 | Betonarbeiten (ATV) |
| VOB/C DIN 18299:2019-09 | Allgemeine Regelungen für Bauarbeiten |
| DGUV-Regel 101-008 | Schalungsarbeiten (vormals BGR 106) |
| BetrSichV | Betriebssicherheitsverordnung |

## License

AGPL-3.0-or-later, same as the OpenConstructionERP core.
