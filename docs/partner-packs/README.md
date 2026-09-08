# Partner Packs — Onboarding & Reference Guide

**Status:** stable since v5.6.0 (2026-05-28)
**Audience:** integration partners, white-label resellers, regional consultancies
**Source code:** `backend/app/core/partner_pack/`
**Reference packs:** `packs/<slug>/`

---

## 1. What a partner pack is

A **partner pack** is a small, code-free preset bundle that pre-configures a
vanilla OpenConstructionERP install for a specific region, industry vertical,
or partner brand. It is the smallest possible unit of customisation: one
manifest plus a handful of static assets (logo, locale JSON, onboarding
script, validation rule-pack JSON files).

You can ship a pack three ways, all declarative and none of them requiring you
to write code: scaffold a folder with the `pack new` CLI command and drop it
into your install's data directory, zip that folder and upload it in-app, or
publish it as a pip wheel that registers through an entry point. The folder
form carries a serialized `manifest.json`; the pip form carries a `manifest.py`
that builds the same `PartnerPackManifest`. Either way the manifest is the only
required file and the core never executes any code from a pack. Section 4
covers all three install paths.

Conceptually, a pack answers seven questions at boot:

1. **Who am I?** (`partner_name`, `partner_url`, `slug`)
2. **What does the workspace look like?** (`branding.primary_color`,
   `branding.accent_color`, `branding.logo_path`, `branding.favicon_path`)
3. **What language and money?** (`default_locale`, `additional_locales`,
   `default_currency`, `default_tax_template`)
4. **Which cost catalogues should load first?** (`cwicr_regions`)
5. **Which validation rules apply by default?** (`validation_rule_sets`,
   and separately `validation_rule_packs` for the reference documents)
6. **Which modules should the sidebar emphasise / hide?** (`default_modules`,
   `hidden_modules`)
7. **How does a brand-new user get oriented?** (`onboarding_script_path`)

That's it. Packs are **declarative presets**, not plugins. Everything they
configure already exists in the core — they just flip switches and supply
brand assets.

### Why packs are not modules

| Concern | Modules (`backend/app/modules/<name>/`) | Partner packs (`packs/<slug>/`) |
|---|---|---|
| What they add | New tables, routes, frontend pages, business logic | Configuration of existing features |
| Installation | Drop folder into `backend/app/modules/`, restart | Drop a folder or zip into the data dir, upload in-app, or pip-install a wheel |
| Discovery | File-system scan by `core/module_loader.py` | Data-dir `packs/` scan, repo `packs/` scan, and the entry-points group `openconstructionerp.partner_packs` |
| Database | Owns Alembic migrations | None — packs MUST NOT touch the schema |
| Frontend | Owns React routes under `features/<name>/` | None — packs MUST NOT add routes |
| Activation | All enabled modules load simultaneously | **One pack is active per install**, applied in-app or via `OE_PARTNER_PACK` |
| Versioning | SemVer, independent per module | SemVer, independent per pack |

If you need a brand-new database table or a brand-new sidebar route, write a
module. If you need to ship "the German BIM consultancy edition" — colours,
locale, DIN rules pre-enabled — ship a pack.

---

## 2. Hard constraints (what packs CANNOT do)

These are enforced by the architecture, not by code review. Violating them
will not work — the loader has no path to register them. A pack dropped into
the data dir is loaded from its `manifest.json`, which is parsed as JSON and
validated against the Pydantic schema and never imported or executed. That is
the security crux of the drop-in and upload paths.

- **No new Python modules.** A pack is not scanned by `module_loader.py`.
  There is no entry-point group for modules.
- **No new frontend routes.** The React bundle is compiled at the core's
  build time (`frontend/dist/`). Packs cannot inject routes, components, or
  JS chunks at runtime.
- **No new database tables.** Packs ship no Alembic migrations and no
  SQLAlchemy models.
- **No new REST endpoints.** All HTTP surface lives in core modules; packs
  only configure existing endpoints.
- **No new validation rule classes.** Packs reference rule-pack **slugs** that
  already exist in `backend/app/core/validation/rules/`. The JSON files
  shipped under `rule_packs/` are reference data and documentation for the
  partner; they are not loaded as executable rules by the core.
- **No code execution at boot beyond manifest construction.** For a pip pack
  the `__init__.py` should expose `MANIFEST` and nothing else; side-effects
  there break test isolation and the discovery cache. A data-dir pack ships no
  Python at all, so there is nothing to execute.
- **No multi-tenant support yet.** One pack is active per install. Discovery
  lists every pack it finds, but listing a pack never activates or co-brands
  anything. A pack becomes active only when an admin applies it in-app, or when
  the `OE_PARTNER_PACK` env var names its slug. Hosted multi-tenant pack
  selection is reserved for a future major.

If a partner requires any of the above, the answer is "ship a module under
`backend/app/modules/`, not a pack." See `docs/module-development/quickstart.md`.

---

## 3. File layout of a pack

Every reference pack under `packs/` follows the same shape:

```
packs/<slug>/
├── pyproject.toml                              # build + entry-point registration
├── README.md                                   # (optional) partner-facing readme
└── src/
    └── openconstructionerp_<slug_underscored>/
        ├── __init__.py                         # exposes `MANIFEST`
        ├── manifest.py                         # PartnerPackManifest(...) builder
        ├── logo.svg                            # required — partner logo
        ├── favicon.ico                         # optional — browser favicon
        ├── onboarding.yaml                     # optional — first-login script
        ├── locales/
        │   ├── en.json                         # optional — extra locale strings
        │   └── de.json
        └── rule_packs/
            ├── <slug>.json                     # reference data for the partner
            └── ...
```

### Naming rules

- **Distribution name** in `pyproject.toml`: `openconstructionerp-<slug>` —
  hyphens, lowercase, kebab-case. Example: `openconstructionerp-batimatech-ca`.
- **Python package** under `src/`: `openconstructionerp_<slug_underscored>` —
  underscores, lowercase. Example: `openconstructionerp_batimatech_ca`.
- **Manifest slug** (`PartnerPackManifest.slug`): same as the distribution
  suffix, kebab-case. Example: `batimatech-ca`. Must match the regex
  `^[a-z][a-z0-9\-]{2,40}$`.
- **Entry-point key**: matches the slug exactly.

The three names are deliberately redundant so the loader can cross-check
them and fail fast if a pack is mis-wired.

The layout above is for the pip-wheel form. If you are shipping a pack as a
folder to drop in or upload, the shape is simpler: a `manifest.json` (the
serialized `PartnerPackManifest`) at the root, next to `logo.svg` and an
optional `onboarding.yaml`. The next section walks through that.

---

## 3a. Creating and installing your own pack

You do not need to clone the repo or build a wheel to make a pack. The fastest
path is the CLI scaffolder, and there are three ways to get a finished pack into
a running install.

### Scaffold with `pack new`

```bash
openconstructionerp pack new acme-co
```

This writes a ready-to-edit folder named after the slug with four files: a valid
`manifest.json` (the only required file, a serialized `PartnerPackManifest` with
sensible placeholders so it is guaranteed to validate), a placeholder `logo.svg`,
an `onboarding.yaml` stub, and a `README.md`. The slug must match
`^[a-z][a-z0-9\-]{2,40}$`; the command fails fast with a clear message if it does
not. Use `--out DIR` to choose where the folder is written and `--force` to
overwrite an existing one. Edit the placeholders (partner name, colours, locale,
currency, CWICR regions, validation rule packs) and the logo, and the pack is
done. There is no code to write.

Prefer to author it by hand? Create a folder with a `manifest.json` that matches
the schema in [`MANIFEST_REFERENCE.md`](MANIFEST_REFERENCE.md). The minimal
shape:

```json
{
  "slug": "acme-co",
  "partner_name": "ACME Construction",
  "default_currency": "GBP",
  "default_tax_template": "uk_vat",
  "branding": { "primary_color": "#0F2C5F", "logo_path": "logo.svg" },
  "onboarding_script_path": "onboarding.yaml"
}
```

### Three ways to install a pack

**Drop it into the data directory.** Place the folder, or a `<slug>.zip` of it,
into your install's data directory under `packs/`. By default that is
`~/.openestimate/packs/`, next to the database. So the manifest ends up at
`~/.openestimate/packs/acme-co/manifest.json`. Then open Modules, Partner Packs
and click Rescan. No restart is needed. A dropped `.zip` is safely extracted in
place on the scan; extraction is hardened against Zip-Slip and friends
(absolute paths, `..` traversal, drive letters, backslash separators and symlink
members are all rejected), and a broken or invalid archive is skipped with a log
line rather than crashing discovery.

**Upload the zip in-app.** Zip the folder and upload the `.zip` directly on the
Partner Packs tab using the in-app installer. This is admin-only. The upload
goes through the same member-by-member safety validation, the `manifest.json` is
validated before anything lands in a scanned path, and the validated pack is
filed under the manifest's own slug, so it appears immediately. If a pack with
that slug is already installed the upload is refused with a clear message rather
than clobbering it.

**Ship it as a pip wheel.** To distribute on PyPI instead of as a folder or zip,
expose the manifest through the entry-point group so it is discovered after a
`pip install`. This is the only path that may need a one-time backend restart
before the pack appears.

```toml
[project.entry-points."openconstructionerp.partner_packs"]
acme-co = "openconstructionerp_acme_co:MANIFEST"
```

Packs dropped into the data dir, and the reference packs under the repo `packs/`
folder, are picked up by Rescan with no restart. Only a brand-new pip-installed
pack may still need one.

### Activate it

Discovering a pack never co-brands the app. Once the pack is listed, open
Modules, Partner Packs, find it and press Activate (Apply). Activation sets the
currency, default and additional languages, validation standards, module
visibility and branding, and can install a demo project. It is reversible:
Deactivate restores the previous state at any time. You can also pin the active
pack from the environment with `OE_PARTNER_PACK=<slug>`; the in-app applied pack
takes precedence over the env var.

---

## 4. The 10 reference packs

All ten live under `packs/` in the monorepo. They install as separate
wheels and are independent of the core release cycle.

| Slug | Region | Currency | Locale(s) | Rule packs | Notes |
|---|---|---|---|---|---|
| `batimatech-ca` | Canada | CAD | fr-CA, en-CA | NBC 2020, CCDC 2, CSA A23 | Full reference — favicon + bilingual locales + onboarding |
| `bimhessen-de` | Germany (Hessen) | EUR | de | DIN 276, GAEB X83/X86, VOB 2023, ISO 19650 CDE, BKI | German BIM consultancy preset |
| `doker-formwork` | Germany | EUR | de | DIN 18218, formwork-cycle rules | Formwork-supplier vertical |
| `uk-jct` | United Kingdom | GBP | en-GB | NRM 1, 2 and 3, JCT contract suite, Construction Act payments, CIS and the VAT reverse charge, CDM 2015, Building Safety Act 2022 | Two engine rule sets, `nrm` and `uk_statutory`; no commercial price book bundled |
| `us-costdata` | United States | USD | en-US | MasterFormat 2020, AIA A201-2017, US city cost index | US GC preset |
| `aus-nzs` | Australia / NZ | AUD | en-AU | AS 1684, NZS 3604, Rawlinsons, AS 4000 | AU/NZ residential + commercial |
| `brazil-sinapi` | Brazil | BRL | pt-BR | NBR 12721, RPS PDF, SINAPI | Latam tier-1 |
| `india-cpwd` | India | INR | en, hi | CPWD Specifications and DSR, IS 456, IS 800, the IS 1893 seismic bundle, IS 1200 measurement, NBC 2016, RERA, GST and TDS | Central PWD works; state SoRs are named, not shipped |
| `hungary-hu` | Hungary | HUF | en | Building and infrastructure item orders, material and fee split, VAT | Runs in English: no Hungarian UI bundle ships yet |
| `russia-gesn` | Russia | RUB | ru | GESN/FER norm base, resource decomposition, price level, overhead and profit on payroll | Ships a Russian UI; carries the `cwicr-ru-stpetersburg` cost database |
| `saudi-vision2030` | Saudi Arabia | SAR | ar, en | SBC, MoMRAH, Aramco standards | KSA mega-projects |
| `renewables-epc` | Cross-region | EUR | en | IEC 61400 wind, IEC 61730 PV, MV cables, LCOE, grid compliance | Renewables EPC vertical |

> The `v5_6_0_release.md` memory mentions 5 packs (the first wave). Five more
> were added in the same wave as additional reference implementations. Total
> shipped in v5.6.0 = **10 packs**.

### Quick install — single pack

```bash
pip install openconstructionerp openconstructionerp-batimatech-ca
# pin which pack is active (or apply it in-app from the Partner Packs tab)
export OE_PARTNER_PACK=batimatech-ca   # PowerShell: $env:OE_PARTNER_PACK="batimatech-ca"
openconstructionerp serve
# log line: "Active partner pack (env-selected): batimatech-ca"
```

### Install commands for every reference pack

> The reference packs are not (yet) on PyPI as separate distributions —
> they live in the monorepo and are installed editable from a clone. To
> publish a pack to PyPI, follow the same workflow as the core
> (`pyproject.toml` → `python -m build` → trusted publishing).

From a fresh clone of the monorepo:

```bash
# Core (PyPI)
pip install openconstructionerp

# Packs (editable, from the clone)
pip install -e packs/aus-nzs
pip install -e packs/batimatech-ca
pip install -e packs/bimhessen-de
pip install -e packs/brazil-sinapi
pip install -e packs/doker-formwork
pip install -e packs/hungary-hu
pip install -e packs/russia-gesn
pip install -e packs/india-cpwd
pip install -e packs/renewables-epc
pip install -e packs/saudi-vision2030
pip install -e packs/uk-jct
pip install -e packs/us-costdata
```

After `pip install -e packs/<slug>` you can `pip uninstall
openconstructionerp-<slug>` to remove it.

### Install many — pick one as active

Multiple packs can be installed or dropped in simultaneously. Discovery lists
all of them, but only one is active at a time, and discovery alone never
activates a pack. Precedence:

1. The in-app applied pack, persisted in `partner_pack_state.json` beside the
   database (set by Activate on the Partner Packs tab, cleared by Deactivate).
2. `OE_PARTNER_PACK=<slug>` env var (exact match against `manifest.slug`).
3. None — runs in vanilla OCERP mode.

To switch packs, apply a different one from the Partner Packs tab, or restart
with a different `OE_PARTNER_PACK` value. The in-app applied pack wins over the
env var when both are set.

---

## 5. The manifest in 60 seconds

Every pack's `manifest.py` builds one `PartnerPackManifest` instance and
assigns it to a module-level name (conventionally `MANIFEST`). The
`__init__.py` re-exports it.

```python
# src/openconstructionerp_acme/manifest.py
from __future__ import annotations
from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="acme",
    partner_name="Acme Construction",
    partner_url="https://acme.example",
    pack_version="0.1.0",
    description="Acme’s preset — French + EUR + DIN 276.",
    default_locale="fr",
    additional_locales={"fr": "locales/fr.json"},
    cwicr_regions=["cwicr-fr-paris"],
    default_currency="EUR",
    # The reference documents the pack ships under rule_packs/, one per
    # file stem. These are documentation; the engine does not execute them.
    validation_rule_packs=["din_276"],
    # The engine rule sets to switch on. These are what make rules run.
    validation_rule_sets=["din276"],
    branding=PartnerBranding(
        primary_color="#003366",
        accent_color="#FF6600",
        logo_path="logo.svg",
        favicon_path="favicon.ico",
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={"country": "FR", "support_email": "support@acme.example"},
)
```

```python
# src/openconstructionerp_acme/__init__.py
from openconstructionerp_acme.manifest import MANIFEST

__all__ = ["MANIFEST"]
```

```toml
# pyproject.toml
[project.entry-points."openconstructionerp.partner_packs"]
acme = "openconstructionerp_acme:MANIFEST"

[tool.setuptools.package-data]
openconstructionerp_acme = [
    "logo.svg",
    "favicon.ico",
    "onboarding.yaml",
    "locales/*.json",
    "rule_packs/*.json",
]
```

For the full field list, types, defaults, and examples, see
[`MANIFEST_REFERENCE.md`](MANIFEST_REFERENCE.md).

---

## 6. The four runtime surfaces a pack exposes

A pack does not register routes. Instead, the **core** mounts five
read-only endpoints under `/api/v1/partner-pack/` that read from the
active pack:

| Endpoint | Purpose | Source attribute |
|---|---|---|
| `GET /api/v1/partner-pack/current` | Active manifest (public dict) | `PartnerPackManifest.to_public_dict()` |
| `GET /api/v1/partner-pack/installed` | All discovered packs + which one is active | `discover_packs()` + `get_active_pack()` |
| `GET /api/v1/partner-pack/logo` | Stream the partner logo | `branding.logo_path` |
| `GET /api/v1/partner-pack/favicon` | Stream the favicon (404 if not shipped) | `branding.favicon_path` |
| `GET /api/v1/partner-pack/onboarding-script` | Stream the onboarding YAML/JSON | `onboarding_script_path` |
| `GET /api/v1/partner-pack/locale/{code}` | Stream a pack-shipped locale JSON | `additional_locales[code]` |
| `GET /api/v1/partner-pack/by-slug/{slug}` | Public manifest of any installed pack | `get_pack_by_slug()` |

The frontend hook `usePartnerPack` calls `/current` on app boot. If a pack
is active, the hook returns the manifest and the `PartnerLogoBadge`
component renders the co-brand chip in the header and the dashboard banner.

---

## 7. Validation rule packs — what those JSON files actually are

Each pack ships zero or more JSON files under `rule_packs/`. **These are
not loaded as executable validation rules.** The core ships all rule
*classes*; the pack's JSON files are:

- **Documentation for the partner** — they describe which clauses the rule
  references, the source standard, the regulatory citation.
- **Reference data** the partner can quote in audits.
- **Future-compatible scaffold** — when v7.0 introduces declarative rule
  packs (Shape B), these JSON files can become runtime-loadable without
  changing the manifest schema.

Two manifest fields decide what a pack validates, and they are not
interchangeable. Knowing which one you are writing is the whole of it.

`validation_rule_packs=[...]` lists the pack's own `rule_packs/*.json`
documents, one entry per file stem. The engine never executes those files, so
naming one here switches nothing on; the installer reports them as
documentation-only, and a test asserts the list matches the files on disk.

`validation_rule_sets=[...]` lists engine rule-set identifiers, and those are
the names that make rules run. Every project created while the pack is active
inherits them, additively - a pack widens what a project validates against and
never narrows it. The identifiers are checked against the live registry when the
pack is applied, and one the engine does not register is refused there with a
message naming the spelling that would have worked. It is refused rather than
ignored because a rule set the registry has never heard of runs no rules and
raises no error, which is indistinguishable from a pack that enables nothing on
purpose.

The failure this separation exists to prevent is writing the name of a standard
the engine implements, spelled the way the document is spelled, and expecting
the rules to run. `din_276` is the DIN 276 reference document; `din276` is the
rule set. Seven shipped packs wrote fifteen document ids and no rule sets at
all, and the installer's only complaint was "no built-in engine match", which
reads as though the engine had nothing for DIN 276. Write both: the document id
in `validation_rule_packs` because the file exists, and the engine identifier in
`validation_rule_sets` because the rules should run. Read the rules before you
do - several of them are error severity and will fail bills of quantities that
pass today.

The rule sets the core registers on its own are these. These names come from
`rule_registry.list_rule_sets()`, which is what the installer consults, and not
from the `standard` attribute on the rule classes; the two lists differ by five
names in both directions, and reading the wrong one is how this section came to
teach identifiers that were never rule sets at all.

| Slug | What it checks |
|---|---|
| `boq_quality` | Universal bill of quantities hygiene |
| `estimate_audit` | Estimate-level audit checks |
| `schedule_quality` | Programme quality |
| `sheet_completeness` | Drawing index against issue register |
| `project_completeness` | The project record itself: country and currency set, a priced bill in that currency, a base date on every bill, a classification standard, planned dates in order, a client, and a contract or tender once past estimating |
| `classification_nudge` | Suggests a classification when none is set |
| `ai_estimator` | Guards on machine-produced estimate lines |
| `field_time` | Site time capture |
| `procurement` | Purchase orders and reconciliation |
| `rfq_issue` | Enquiry at the point of issue |
| `rfq_award` | Enquiry at the point of award |
| `subcontract` | Subcontract packages |
| `submittal` | Submittals |
| `property_dev` | Development appraisal |
| `pipeline` | Opportunity pipeline |
| `din276` | DIN 276 cost groups (DE) |
| `gaeb` | GAEB LV structure and ordinals (DE) |
| `onorm` | ÖNORM (AT) |
| `nrm` | NRM 1 and 2 (UK) |
| `uk_statutory` | UK statute on the estimate: contract form, Construction Act payment regime, retention, CDM 2015 duty holders, Building Safety Act higher-risk test, VAT treatment |
| `masterformat` | MasterFormat divisions (US) |
| `dpgf` | DPGF (FR) |
| `bc3` | FIEBDC-3 / BC3 (ES) |
| `mexico` | Mexican estimating conventions |
| `sinapi` | SINAPI codes (BR) |
| `nbr` | ABNT NBR (BR) |
| `cpwd` | CPWD and IS 1200 (IN) |
| `gbt50500` | GB/T 50500 (CN) |
| `sekisan` | Sekisan (JP) |
| `birimfiyat` | Birim Fiyat (TR) |
| `gesn` | GESN (RU) |
| `hungary` | Hungarian item orders, material and fee split (HU) |

Modules add more. Anything with a `validators.py` registers its own sets when it
loads, `formwork` and `carbon_6d` among them, and several of them register
additional rules into sets that already exist. So the list an installation
actually has is longer than the one above and depends on
which modules are enabled. Read it from the installation rather than from here
when it matters, and note that no rule count is published in this table for the
same reason: the number changes with what is loaded, so it would describe the
reader's process and not the software.

If a partner needs a rule class that is not here, it has to be written in the
core. Packs cannot ship executable rules, only the JSON documents that describe
them.

---

## 8. Branding and AGPL co-brand obligation

OpenConstructionERP is AGPL-3.0. Section 5(d) of AGPL requires that
"appropriate legal notices" remain on each "interactive user interface."
For partner packs, this is satisfied by the **co-brand string**:

```
Powered by OpenConstructionERP · In partnership with <partner_name>
```

The string is computed by `PartnerPackManifest.effective_powered_by` and
displayed:

- In the header chip (xl+ viewport, centered, max-w-14rem).
- On the dashboard landing page banner.
- In the "About" modal.

A pack MAY override the wording via `branding.powered_by_text`, but the
override MUST still credit OpenConstructionERP somewhere in the string.
Removing the credit is an AGPL violation. The default value is the safe
choice and is recommended for all packs.

**Logo handling**

- The pack's `logo.svg` (or `.png`, `.webp`, `.jpg`) is streamed via
  `/api/v1/partner-pack/logo`. The frontend renders it in the co-brand
  chip alongside the OpenConstructionERP wordmark.
- The OpenConstructionERP wordmark MUST remain visible. Partners may not
  use CSS to hide it.

**Favicon**

- A pack may ship a `favicon.ico` (or any browser-supported favicon
  format). When present, the frontend swaps it on boot via the
  `<link rel="icon">` tag.

---

## 9. Onboarding script

A pack may ship a single `onboarding.yaml` (or `onboarding.json`) at the
path declared in `onboarding_script_path`. When set, the
`OnboardingWizard` component fetches it from
`/api/v1/partner-pack/onboarding-script` on first login and renders the
partner-specific steps instead of the default wizard.

The script schema is open. Conventionally a YAML list of step objects
with `id`, `title`, `body`, `cta`, `next` fields. See
`packs/batimatech-ca/src/openconstructionerp_batimatech_ca/onboarding.yaml`
for a worked example.

The script is rendered client-side. No business logic — only UI text and
flow.

---

## 10. Local development workflow

Develop your pack alongside the core:

```bash
# 1. Clone the monorepo
git clone https://github.com/DataDrivenConstruction/openconstructionerp
cd openconstructionerp

# 2. Editable install of the core + your pack
# The distribution lives in backend/, there is no pyproject.toml at the clone root.
pip install -e backend
pip install -e packs/your-pack

# 3. Activate it
export OE_PARTNER_PACK=your-pack   # PowerShell: $env:OE_PARTNER_PACK="your-pack"

# 4. Run the backend with autoreload. Autoreload is a uvicorn flag, not one of
#    ours: the CLI has no --reload, and it serves on 8080 rather than 8000.
cd backend
uvicorn app.main:create_app --factory --reload --port 8000
# Expect log line: "Active partner pack (env-selected): your-pack"

# 5. Hit the API
curl http://localhost:8000/api/v1/partner-pack/current | jq
```

### Unit tests

The core ships `backend/tests/test_partner_pack_core.py` with 13 unit
tests covering manifest validation, discovery precedence, broken-pack
tolerance, and every router endpoint. Run them after every pack change:

```bash
cd backend
pytest tests/test_partner_pack_core.py -v
```

Add your own pack-specific assertions in `packs/<slug>/tests/` (mirror
the layout of `packs/batimatech-ca/tests/` once that exists).

---

## 11. Publishing a pack to PyPI

Packs are independent distributions. The core's PyPI trusted-publishing
workflow does NOT publish packs.

```bash
cd packs/your-pack
python -m build              # produces dist/openconstructionerp_your_pack-0.1.0-py3-none-any.whl
twine check dist/*
twine upload dist/*          # or set up trusted publishing per-pack
```

Use a `requires-python = ">=3.12"` pin and a `dependencies = [
"openconstructionerp>=5.6.0" ]` floor so the pack refuses to install
against a core version that predates the entry-point group.

---

## 12. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/api/v1/partner-pack/current` returns `{"active": false}` after install | Entry-point not registered | Verify `pyproject.toml` has the `[project.entry-points."openconstructionerp.partner_packs"]` table and that you reinstalled after editing it |
| Logs say `Partner pack 'X' failed to load: ...` | `MANIFEST` is malformed or `manifest.py` raises at import | Run `python -c "from openconstructionerp_x import MANIFEST; print(MANIFEST)"` to reproduce; fix the validation error |
| Wrong pack is active when multiple are installed | An in-app applied pack takes precedence over the env var | Deactivate it on the Partner Packs tab, or set `OE_PARTNER_PACK=<slug>` and remove the applied state |
| A dropped folder or uploaded zip does not appear | The scan has not run, or the archive has no valid `manifest.json` | Click Rescan on the Partner Packs tab; confirm `manifest.json` is at the pack root and validates |
| `/api/v1/partner-pack/logo` returns 404 | `logo_path` points at a missing file or the file is not in `package-data` | Ensure `pyproject.toml`'s `[tool.setuptools.package-data]` lists `"logo.svg"` (or your filename), then reinstall |
| Co-brand chip overlaps header buttons at 1366×768 | Pre-v5.6.0 layout bug | Upgrade core to ≥ v5.6.0 (header chip is `xl:flex` + `max-w-14rem`) |
| Pack works in test but not after `pip install` | Editable install picked up dev-only files | Add the missing globs to `[tool.setuptools.package-data]` and rebuild the wheel |

---

## 13. Where to look next

- **Field reference for every manifest property**:
  [`MANIFEST_REFERENCE.md`](MANIFEST_REFERENCE.md)
- **Why this design (Shape A vs Shape B, single- vs multi-tenant)**:
  [`docs/adr/2026-05-28-partner-pack-architecture.md`](../adr/2026-05-28-partner-pack-architecture.md)
- **Module SDK** (when you outgrow packs): `docs/module-development/quickstart.md`
- **Core source**: `backend/app/core/partner_pack/`
  - `manifest.py` — Pydantic schema
  - `discovery.py` — entry-point loader, env-var precedence, caching
  - `router.py` — five public endpoints
- **Reference packs**: `packs/<slug>/`

For partnership inquiries: <info@datadrivenconstruction.io>.
