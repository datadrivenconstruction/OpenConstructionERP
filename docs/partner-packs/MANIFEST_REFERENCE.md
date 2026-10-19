# `PartnerPackManifest` — Field Reference

**Source:** `backend/app/core/partner_pack/manifest.py`
**Model:** Pydantic v2, `extra="forbid"`, `str_strip_whitespace=True`

This document lists every field on `PartnerPackManifest` and the nested
`PartnerBranding` model, with type, default, validation, and a worked
example. For onboarding context and install instructions see
[`README.md`](README.md).

The same schema backs both pack forms. A pip-installed pack builds a
`PartnerPackManifest` in `manifest.py` and exposes it via an entry point. A pack
dropped into the data dir or uploaded in-app ships the same data as a serialized
`manifest.json`, which the core validates against this model and never executes.
The quickest way to get a valid `manifest.json` to edit is
`openconstructionerp pack new <slug>`. The `model_config` uses `extra="forbid"`,
so an unknown field raises `ValidationError` and the pack is skipped at load
time with a logged warning.

---

## `PartnerPackManifest`

### `slug`

| | |
|---|---|
| Type | `str` |
| Default | _required_ |
| Validation | regex `^[a-z][a-z0-9\-]{2,40}$` (lowercase, kebab-case, 3–41 chars) |
| Purpose | Stable identifier. Used as the entry-point key, as the `OE_PARTNER_PACK` env-var value, and as the `/api/v1/partner-pack/by-slug/{slug}` path segment. It is authoritative for activation: for a dropped or uploaded pack the slug, not the folder or zip filename, decides which pack is installed. |
| Example | `"batimatech-ca"` |

### `partner_name`

| | |
|---|---|
| Type | `str` |
| Default | _required_ |
| Validation | `min_length=2`, `max_length=80` |
| Purpose | Display name shown in the co-brand chip, the dashboard banner, and the "About" modal. |
| Example | `"BIMHessen"` |

### `partner_url`

| | |
|---|---|
| Type | `str \| None` |
| Default | `None` |
| Purpose | Used as the link target on the partner logo strip. When `None`, the logo is rendered as a plain image. |
| Example | `"https://bimhessen.de"` |

### `pack_version`

| | |
|---|---|
| Type | `str` |
| Default | `"0.1.0"` |
| Validation | none enforced (use SemVer by convention) |
| Purpose | Independent of core version. Shown in admin diagnostics. |
| Example | `"1.2.3"` |

### `description`

| | |
|---|---|
| Type | `str` |
| Default | `""` |
| Validation | `max_length=800` |
| Purpose | One-paragraph human-readable description (English). Surfaced in `/api/v1/partner-pack/installed` and the admin pack-picker UI. |
| Example | `"Pre-configured for German BIM consultancies — DIN 276, GAEB X83/X86, VOB clauses, ISO 19650 CDE, BKI benchmarks."` |

---

## Locale & region

### `default_locale`

| | |
|---|---|
| Type | `str` |
| Default | `"en"` |
| Validation | `min_length=2`, `max_length=10`. BCP-47 by convention. |
| Purpose | Used as the new boot default locale. Frontend i18n loads this language first; falls back to English if a key is missing. |
| Example | `"fr-CA"` |

### `additional_locales`

| | |
|---|---|
| Type | `dict[str, str]` |
| Default | `{}` |
| Purpose | Maps BCP-47 locale code → path inside the pack package to a JSON file holding extra translation strings. Streamed via `GET /api/v1/partner-pack/locale/{code}`. |
| Constraint | The path is relative to the pack's Python package root (the directory containing `manifest.py`). |
| Example | `{"fr-CA": "locales/fr-CA.json", "en-CA": "locales/en-CA.json"}` |

### `cwicr_regions`

| | |
|---|---|
| Type | `list[str]` |
| Default | `[]` |
| Purpose | CWICR marketplace slugs to preload on first boot. Each entry must match an existing CWICR catalogue slug (see `backend/app/modules/costs/cwicr_v3_catalogue.py`). |
| Example | `["cwicr-eng-toronto", "cwicr-fra-montreal"]` |

### `default_currency`

| | |
|---|---|
| Type | `str` |
| Default | `"EUR"` |
| Validation | regex `^[A-Z]{3}$` — ISO 4217 |
| Purpose | Set as the project-creation default. Existing projects are not touched. |
| Example | `"CAD"` |

### `default_tax_template`

| | |
|---|---|
| Type | `str \| None` |
| Default | `None` |
| Purpose | Ignored; leave it unset. There is no tax template registry, so nothing resolves the value. VAT, public holidays, e-invoicing and statutory payment terms come from the platform's built-in registries by the project's country, and the activation preview shows them. The rate that reaches an estimate is the tax line of the market's markup stack, editable per project. The field is still accepted so older manifests keep loading. |
| Example | `None` |

---

## Validation rule presets

There are two fields here and they do different jobs. `validation_rule_sets`
switches rules on. `validation_rule_packs` names documents and switches nothing
on. Earlier revisions of this page said an entry in `validation_rule_packs`
that matched a built-in rule set would switch it on; that was never true, and
seven shipped packs wrote fifteen document ids on the strength of it.

### `validation_rule_sets`

| | |
|---|---|
| Type | `list[str]` |
| Default | `[]` |
| Purpose | Validation rule-set identifiers **as the engine registers them**. These are the names that make rules run: a project created while the pack is active inherits them, so the rules execute on its bills of quantities. Additive - the platform's baseline `boq_quality` is kept, the pack's sets are added to it. |
| Example | `["din276", "gaeb"]` |

Every entry is checked against the live registry when the pack is applied. An
identifier the registry does not know is refused there with an error naming the
spelling that works, so a misspelling stops the apply instead of quietly
enabling nothing. It cannot be checked when the manifest is constructed: pack
manifests are module-level constants built at import time, before any rule has
been registered, so a check there would read an empty registry and wave
everything through.

A rule set owned by a module - `formwork` is the one in the tree - exists only
while that module is loaded, because the loader imports a module's
`validators.py` only when it loads the module. Declaring it in a pack that also
enables the module is correct; declaring it in a pack that does not will be
refused.

### `validation_rule_packs`

| | |
|---|---|
| Type | `list[str]` |
| Default | `[]` |
| Purpose | The pack's own reference documents, one entry per `rule_packs/*.json` file the pack ships. **Documentation only: nothing here runs.** **Packs cannot ship new rule classes.** Each entry must match a file stem on disk, in both directions - a declared id with no file, and a shipped file no id names, are both test failures. |
| Example | `["din_276", "gaeb_x83_x86", "vob_2023"]` |

The example is a German pack listing three documents it ships. Note that
`din_276` here is a file name and `din276` in `validation_rule_sets` above is an
engine identifier; they look alike and mean unrelated things, which is exactly
how the fifteen ids got written into the wrong field. The installer flags that
pairing when it sees a document id one boundary away from a registered set and
no matching entry in `validation_rule_sets`.

See the [README §7](README.md#7-validation-rule-packs--what-those-json-files-actually-are)
for the list of rule sets the core currently implements.

---

## Module presets

### `default_modules`

| | |
|---|---|
| Type | `list[str]` |
| Default | `[]` |
| Purpose | Sidebar emphasis. When empty (`[]`), all installed modules are visible. When non-empty, **only** the listed modules show up as default, but users can still re-enable hidden ones via the sidebar menu editor. |
| Example | `["projects", "boq", "takeoff", "costs", "validation"]` |

### `hidden_modules`

| | |
|---|---|
| Type | `list[str]` |
| Default | `[]` |
| Purpose | Inverse of `default_modules`. Modules listed here are hidden from the sidebar by default. Users can re-enable via the sidebar editor. |
| Note | If a module appears in both `default_modules` and `hidden_modules`, `hidden_modules` wins. |
| Example | `["bim_hub", "carbon"]` |

---

## Branding (nested `PartnerBranding`)

### `branding`

| | |
|---|---|
| Type | `PartnerBranding` |
| Default | `PartnerBranding()` (all sub-fields defaulted) |
| Purpose | Container for runtime visual overrides. |

#### `branding.primary_color`

| | |
|---|---|
| Type | `str` |
| Default | `"#0F2C5F"` |
| Purpose | Hex `#RRGGBB`. Replaces the CSS variable `--oe-primary` at boot. |
| Example | `"#BE1B2F"` (Batimatech red) |

#### `branding.accent_color`

| | |
|---|---|
| Type | `str \| None` |
| Default | `None` |
| Purpose | Optional secondary brand colour. Replaces `--oe-accent` when set. |
| Example | `"#FF6600"` |

#### `branding.logo_path`

| | |
|---|---|
| Type | `str` |
| Default | `"logo.svg"` |
| Purpose | Path **inside the pack package** to the partner logo. Streamed via `GET /api/v1/partner-pack/logo`. Supported formats: `.svg`, `.png`, `.webp`, `.jpg`, `.jpeg` (Content-Type sniffed from extension). |
| Constraint | Must be listed in `pyproject.toml`'s `[tool.setuptools.package-data]` so it ships in the wheel. |
| Example | `"logo.svg"` |

#### `branding.favicon_path`

| | |
|---|---|
| Type | `str \| None` |
| Default | `None` |
| Purpose | Optional favicon. When set, streamed via `GET /api/v1/partner-pack/favicon` and swapped into the `<link rel="icon">` tag at boot. |
| Example | `"favicon.ico"` |

#### `branding.powered_by_text`

| | |
|---|---|
| Type | `str \| None` |
| Default | `None` (resolves to the AGPL co-brand string) |
| Purpose | Override the co-brand line shown next to the partner logo. When `None`, defaults to `"Powered by OpenConstructionERP · In partnership with {partner_name}"`. |
| Constraint | Any override MUST still credit OpenConstructionERP in the string. Removing the credit violates AGPL §5(d). |
| Example | `"Solution by Acme — built on OpenConstructionERP"` |

---

## Onboarding

### `onboarding_script_path`

| | |
|---|---|
| Type | `str \| None` |
| Default | `None` |
| Purpose | Path inside the pack package to a YAML or JSON onboarding script. When set, the frontend `OnboardingWizard` fetches it via `GET /api/v1/partner-pack/onboarding-script` and renders partner-specific steps instead of the default sequence. |
| Format | YAML or JSON list of step objects. Schema is intentionally open. |
| Example | `"onboarding.yaml"` |

---

## Free-form

### `metadata`

| | |
|---|---|
| Type | `dict[str, Any]` |
| Default | `{}` |
| Purpose | Free-form bag for partners who want to surface extra structured data through `/api/v1/partner-pack/current` and `/installed`. The frontend ignores unknown keys. |
| Suggested keys | `country` (ISO 3166-1 alpha-2), `country_name_en`, `regulator_refs` (list of strings), `support_email`, `support_phone`, `partner_tier` |
| Example | `{"country": "CA", "country_name_en": "Canada", "regulator_refs": ["NBC 2020", "CCDC 2"], "support_email": "support@batimatech.ca"}` |

---

## Derived properties (read-only)

### `effective_powered_by` (property)

Returns `branding.powered_by_text` if set, else the default
`"Powered by OpenConstructionERP · In partnership with {partner_name}"`.
This is what the frontend displays in the co-brand chip.

### `to_public_dict()`

Serialises the manifest for the `/api/v1/partner-pack/current` and
`/installed` endpoints. Strips file paths (those get streamed via
dedicated endpoints) and reports `branding.has_logo` / `has_favicon` as
booleans. Used by `router.py`; you should not call it manually.

---

## Full worked example

```python
from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    # Identity
    slug="batimatech-ca",
    partner_name="batimatech",
    partner_url="https://batimatech.ca",
    pack_version="0.1.0",
    description=(
        "Pre-configured partner pack for Canadian construction companies — "
        "NBC 2020, CCDC 2, Canadian construction cost index, bilingual fr-CA / en-CA UI."
    ),
    # Locale & region
    default_locale="fr-CA",
    additional_locales={
        "fr-CA": "locales/fr-CA.json",
        "en-CA": "locales/en-CA.json",
    },
    cwicr_regions=["cwicr-eng-toronto", "cwicr-fra-montreal"],
    default_currency="CAD",
    default_tax_template=None,
    # Validation - the engine identifiers that make rules run ...
    validation_rule_sets=["boq_quality"],
    # ... and the reference documents the pack ships, which run nothing
    validation_rule_packs=["nbc_2020", "ccdc_2", "csa_a23"],
    # Modules
    default_modules=[],          # show all by default
    hidden_modules=[],
    # Branding
    branding=PartnerBranding(
        primary_color="#BE1B2F",   # Batimatech red
        accent_color="#FFFFFF",
        logo_path="logo.svg",
        favicon_path="favicon.ico",
        powered_by_text=None,      # use default co-brand string
    ),
    # Onboarding
    onboarding_script_path="onboarding.yaml",
    # Free-form
    metadata={
        "country": "CA",
        "country_name_en": "Canada",
        "regulator_refs": ["NBC 2020", "CCDC 2", "CSA A23"],
        "support_email": "contact@batimatech.ca",
    },
)
```

Strict-mode reminder: the model uses `extra="forbid"`. Any unknown field
raises `ValidationError` at import time, and the boot-time discovery
loader logs the failure and skips the pack.
