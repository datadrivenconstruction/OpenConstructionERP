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
    "rfq_bidding.issue_confirm_title": "Issue this RFQ?",
    "rfq_bidding.issue_confirm_message": "Vendors can bid once it is issued. An issued RFQ is no longer a draft and cannot be deleted.",
    "rfq_bidding.issue_needs_scope": "Add at least one scope line before issuing",

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
    "notifications.permits.condition_assigned.title": "A permit condition was assigned to you",
    "notifications.permits.condition_assigned.body": "Permit condition {{number}} is now yours to resolve.",
    "notifications.permits.condition_breach.title": "A permit condition was breached",
    "notifications.permits.condition_breach.body": "A permit condition you own has been marked as breached.",
    "notifications.permits.condition_overdue.title": "A permit condition is overdue",
    "notifications.permits.condition_overdue.body": "Permit condition {{number}} was due on {{due_date}} and is still open.",
    "notifications.permits.condition_escalated.title": "A permit condition was escalated",
    "notifications.permits.condition_escalated.body": "Permit condition {{number}} (due {{due_date}}) is overdue and has been escalated to your area.",
    "notifications.site_logistics.permit_expired.title": "A logistics permit has expired",
    "notifications.site_logistics.permit_expired.body": "Permit {{reference}} expired on {{valid_to}}.",
    "notifications.site_logistics.permit_expiring.title": "A logistics permit is about to expire",
    "notifications.site_logistics.permit_expiring.body": "Permit {{reference}} is valid until {{valid_to}}.",
    "notifications.site_logistics.neighbour_issue_overdue.title": "A neighbour issue is overdue",
    "notifications.site_logistics.neighbour_issue_overdue.body": "A neighbour {{kind}} issue was due for a response by {{due}}.",
    "dwg_takeoff.drawing_span": "Drawing size at this scale: {{w}} m x {{h}} m",
    "dwg_takeoff.drawing_span_implausible": "That is unusual for a construction drawing, so the unit stored in the file may be wrong. Check it with Calibrate: pick two points and type their real distance.",
    "dwg_takeoff.conv_converter_said": "Converter report",
    "demo_banner.strip_uploads_off": "Uploads are off here: please use the demo data only",
    "demo_uploads.refused": "Uploads are turned off on the public demo. Please use the demo projects and their example data, or install the platform to work with your own files.",
    "procurement.requisitions.merge_conflict_unit_cost": "unit cost",
    "procurement.requisitions.merge_conflict_currency": "currency",
    "procurement.requisitions.merge_conflict_cost_line": "cost line",
    "procurement.requisitions.merge_conflict_title": "These lines are not alike",
    "procurement.requisitions.merge_conflict_message": "The selected lines differ in {{what}}. Every source keeps its own cost line, and the merged line is priced at the mean cost only when the currency is the same. Merge anyway?",
    "procurement.requisitions.merge_conflict_confirm": "Merge anyway",
    "procurement.requisitions.col_unit_cost": "Estimated unit cost",
    "procurement.requisitions.col_unit_cost_hint": "Indicative, from the BOQ rates. The price is agreed when the order is placed.",
    "procurement.requisitions.cost_unavailable": "Indicative cost unavailable",
    "procurement.requisitions.over_allocation_reason": "Reason if this goes over the BOQ quantity (optional)",
    "resourceSummary.buyList.col.covered": "On requisitions",
    "resourceSummary.buyList.col.remaining": "Remaining",
    "resourceSummary.requisition.use_remaining": "Request only what is not yet on a submitted requisition. Untick to request the whole BOQ quantity.",
    "resourceSummary.requisition.nothing_left": "Everything selected is already on requisitions.",
    "resourceSummary.requisition.col_unit_cost": "Estimated unit cost",
    "resourceSummary.requisition.cost_unavailable": "Indicative cost unavailable",
  }
} as { translation: Record<string, string> };

export default resource;
