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
    "enterprise_workflows.no_requests": "No approval requests",
    "enterprise_workflows.no_workflows": "No workflows yet",
    "modules.catalog.catalog": "Product & Resource Catalogue",
    "modules.catalog.supplier_catalogs": "Supplier Catalogues & Vendor Management",
    "modules.catalog.labor_rates": "Labour & Crew Rates",
    "dashboard.layout.customize": "Customise",
    "dashboard.layout.title": "Customise dashboard",
    "rebar_schedule.diameter": "Dia (mm)",
    "rebar_schedule.export": "Export .abs",
    "rebar_schedule.shapes": "Shapes",
    "rebar_schedule.total_weight": "Weight (kg)",
    "rfq_bidding.issue": "Issue",

    "costs.labor": "Labour",
    "boq.add_scoped_markup": "Add markup for section",
    "boq.scope_to_section": "Scope to section...",
    "boq.in_review": "In Review",
    "boq.request_changes": "Request Changes",
    "boq.returned_to_draft": "Returned to draft for changes",
    "boq.submit_for_review": "Submit for Review",
    "boq.submit_review_tooltip": "Submit this estimate for review and approval",
    "boq.submitted_for_review": "Submitted for review",
    "boq.import_preview.column_mapping": "Column mapping ({{mapped}} of {{total}} mapped)",
    "boq.import_preview.field_skip": "Skip",
    "auth.or": "or",
    "auth.sso_login": "Sign in with SSO",
    "schedule.activate": "Activate",
    "schedule.activated": "Schedule activated",
    "schedule.activity_deleted": "Activity deleted",
    "schedule.assignee": "Assignee",
    "schedule.confirm_delete": "This will permanently delete the schedule and all its activities. This cannot be undone.",
    "schedule.confirm_delete_title": "Delete schedule?",
    "schedule.delete_activity": "Delete activity",
    "schedule.deleted": "Schedule deleted",
    "schedule.no_assignee": "Unassigned",
    "schedule.no_parent": "Top level (no parent)",
    "schedule.parent_section": "Parent section",
    "about.dev_model_title": "Development and Contribution Model",
    "about.dev_model_p1": "OpenConstructionERP has been under continuous development for more than six years and has benefited from contributions, feedback, testing, and domain expertise from many different people.",
    "about.dev_model_p2": "To maintain a consistent architecture and reduce security, dependency, and integration risks, the project follows a centralised integration model. Most production code is ultimately reviewed, consolidated, tested, and published through a single maintainer account. As a result, the GitHub contributor history does not necessarily reflect the actual number of people who have contributed to the project.",
    "about.dev_model_p3": "Rather than allowing the codebase to evolve into a collection of loosely connected components, changes are integrated into one coherent development line and undergo review and testing before being merged into the main project. A single publishing account represents a controlled integration and release process designed to preserve stability, security, and architectural consistency.",
    "about.team_name": "DataDrivenConstruction",
    "about.team_role": "Automation, data and open standards for construction",
    "about.team_linkedin": "DataDrivenConstruction on LinkedIn",

    "subcontractors.cert_type.license": "Licence",
  }
} as { translation: Record<string, string> };

export default resource;
