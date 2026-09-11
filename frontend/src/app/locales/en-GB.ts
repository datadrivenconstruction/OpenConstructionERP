// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// British English (en-GB). Overrides only, not a copy of en.ts.
//
// i18next resolves en-GB before en, so a key absent from this file is answered
// by en.ts. The same arrangement as en-US.ts, and for the same reason: a key
// copied across unchanged would have to be kept in step with en.ts forever for
// no gain.
//
// What en-GB is FOR, and it is mostly not this file. Plain `en` claims no
// region, so it prints `3/14/2026` and `$1,234.50` and starts its week on
// Sunday, because CLDR has no region-free English and unqualified `en`
// inherits the American reading. Picking English (UK) is what turns those into
// `14/03/2026`, `US$1,234.50` and a Monday-first week. Every one of those
// comes from the locale tag rather than from a string, so this file is small
// by design and would still be doing its job if it were empty.
//
// What is in it, and what is deliberately not. en.ts is not written in one
// variety: measured on 2026-09-08 it carries `colour` 29 times against `color`
// 41, `labour` 118 against `labor` 62, and `catalogue` 150 against `catalog`
// 469. So there are keys where a British reader is shown the American spelling
// and en-US.ts has nothing to override, because en.ts was already American
// there. 241 keys are in that state, over a closed list of unambiguous pairs
// (colour, labour, catalogue, organisation, cancelled, fulfil, analyse and the
// -ise verbs); `program`/`programme`, `metre`/`meter`, `licence`/`license` and
// `centre`/`center` are excluded from that count because each needs the
// sentence read rather than a rule applied.
//
// The nine below are the navigation and module labels out of those 241 - the
// words a British estimator reads on every screen rather than inside a
// paragraph. The remaining 232 are a spelling pass over prose, and they are
// left as a named piece of work rather than done by substitution: a global
// replace over 35,865 values is how a link with `/catalog` in it or a
// `program` that means software gets quietly broken, and nothing on screen
// would show it.
//
// Locale source. Edit this file directly: nothing generates it.
// ../i18n-fallbacks.ts deliberately does not import it, because the tests that
// iterate that object assume a locale carries the whole key set.

const resource = {
  "translation": {
    "nav.catalog": "Resource Catalogue",
    "nav.resource_catalog": "Resource Catalogue",
    "nav.supplier_catalogs": "Supplier Catalogues",
    "nav.labor_rates": "Labour Rates",
    "modules.catalog.catalog": "Product & Resource Catalogue",
    "modules.catalog.supplier_catalogs": "Supplier Catalogues & Vendor Management",
    "modules.catalog.labor_rates": "Labour & Crew Rates",
    "dashboard.layout.customize": "Customise",
    "dashboard.layout.title": "Customise dashboard",
    "boq.import_preview.back": "Back",
    "boq.import_preview.cancel": "Cancel",
    "boq.import_preview.col_description": "Description",
    "boq.import_preview.col_ordinal": "Pos. / Code",
    "boq.import_preview.col_quantity": "Qty",
    "boq.import_preview.col_total": "Total",
    "boq.import_preview.col_unit": "Unit",
    "boq.import_preview.col_unit_rate": "Unit Rate",
    "boq.import_preview.confirm_button": "Import",
    "boq.import_preview.confirm_summary": "Import {{positions}} positions ({{sections}} sections) in {{currency}} from {{format}}?",
    "boq.import_preview.confirm_warnings": "{{count}} warning(s) were detected during parsing. The import will proceed.",
    "boq.import_preview.continue": "Continue",
    "boq.import_preview.drop_hint": "GAEB XML, Excel, PDF or CSV",
    "boq.import_preview.drop_zone": "Drop file here or click to browse",
    "boq.import_preview.errors_title": "{{count}} error(s)",
    "boq.import_preview.import_success": "Imported {{count}} positions",
    "boq.import_preview.import_timeout": "Server did not respond within 90 seconds.",
    "boq.import_preview.parse_timeout": "Server did not respond within 90 seconds. The file may be too large.",
    "boq.import_preview.parsing": "Parsing file...",
    "boq.import_preview.skipped_count": "{{count}} row(s) skipped (empty or unreadable)",
    "boq.import_preview.stats_currency": "Currency",
    "boq.import_preview.stats_format": "Format",
    "boq.import_preview.stats_positions": "Positions",
    "boq.import_preview.stats_sections": "Sections",
    "boq.import_preview.title": "Import preview",
    "boq.import_preview.truncated": "... and {{count}} more position(s)",
    "boq.import_preview.upload_hint": "Choose a file to preview before importing into this BOQ.",
    "boq.import_preview.warnings_title": "{{count}} warning(s)",
  }
} as { translation: Record<string, string> };

export default resource;
