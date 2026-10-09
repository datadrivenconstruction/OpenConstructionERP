#!/usr/bin/env python3
"""Refuse a new collection endpoint that answers with a bare array.

The pagination programme migrates registers one wave at a time, from a bare
``list[...]`` to ``{items, total, offset, limit}``. Waves subtract; nothing
stopped the tree from adding. Every new module shipped another handful of
routes that answer with the first page and say nothing about the rest, so the
only metered side of the account was the side doing the work.

This is the other side. Every bare-list GET that existed when the guard was
written is in ``ALLOWED`` and stays legal until someone migrates it. A route
that is not in that list is new, and new is where the line is drawn: writing
one costs a conversation now rather than a wave later.

``ALLOWED`` is also the census. It is exact, it is checked both ways, and its
size is printed on every successful run, so the number falls as registers are
migrated and anyone can see it fall. An entry that no longer names a bare-list
route fails the run rather than lingering, because a list that keeps entries it
has outgrown stops being a count of anything and starts quietly re-permitting
whatever later takes the same name.

A second list, ``CANNOT_TRUNCATE``, holds the routes that must keep answering
with the whole set because a partial answer from them would be wrong rather
than short. Those two lists mean opposite things, so they are disjoint and the
countdown is the size of ``ALLOWED`` alone: it targets zero. ``--dump`` rewrites
``ALLOWED`` and never touches ``CANNOT_TRUNCATE``, which is what keeps a
justification attached to the entry it justifies.

Definition of a bare-list endpoint, matching the census this list was built
from: a function decorated with ``@router.get(...)`` whose ``response_model``
is a ``list[...]`` subscript, or which declares no ``response_model`` and whose
return annotation is ``list[...]``. Parsed with ast rather than a regex, so a
decorator split over several lines and a return annotation on a line of its own
are both read correctly.

Usage::

    python scripts/check_no_new_bare_list_endpoints.py
    python scripts/check_no_new_bare_list_endpoints.py --dump   # regenerate ALLOWED
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULES_DIR = REPO_ROOT / "backend" / "app" / "modules"

# A scan that walks nothing prints a clean tree, so the run refuses to report
# success unless it opened at least this many files. The tree held 2083 when
# the guard was written; the floor is deliberately far below that, because it
# is here to catch a broken path, not to track growth.
MIN_FILES_SCANNED = 500

# Routes that answer with a bare array and always will, because the set they
# return cannot be cut short without the answer becoming wrong.
#
# This list is written by hand and --dump never prints it. That is the whole
# point of its existing. The reason an entry belongs here is the only thing
# keeping it here, and a reason has to survive the next regeneration of
# ALLOWED; stored between ALLOWED's braces it does not, because --dump
# reproduces entries and nothing else. What is left behind after such a
# regeneration is a bare route name, indistinguishable from the hundreds
# genuinely waiting their turn, and the next wave migrates it.
#
# The bar is high, and it is not "the list is short". It is not "the list is
# bounded by its parent" either: both of those still have a state in which the
# caller holds part of the set, which is exactly the state an envelope exists
# to report. The bar is that a partial answer would be a correctness bug
# rather than a page.
#
# The census subtracts these, so the number printed on a clean run counts down
# towards zero rather than towards the size of this list.
CANNOT_TRUNCATE: frozenset[str] = frozenset(
    {
        # A fixed taxonomy, not a register. WORKING_TIME_REGIMES in
        # field_time/working_time.py is a frozen tuple of statutes compiled into
        # the source, today just MiLoG (German minimum wage act) section 17 (1);
        # it gains an entry when a developer implements another jurisdiction's
        # recording duty, never at runtime and never per tenant. The route is a
        # comprehension over the whole tuple, so there is no query, no LIMIT and
        # no state in which it answers with part of the set. An envelope here
        # would carry a total that is len(items) by construction and an
        # "incomplete page" branch no caller could ever reach, and it would
        # advertise a truncation this endpoint must not have: a worker choosing
        # which statute their hours are recorded under has to see every statute
        # on offer, so a short answer would be a correctness bug, not a page.
        "field_time/router.py::list_working_time_regimes",
        # An aggregate over a closed vocabulary, not a register. The route
        # answers one row per bar diameter present in one import, produced by a
        # GROUP BY in weight_by_diameter, so its length is the number of
        # distinct diameters in that file: a handful, bounded by the diameters
        # a mill rolls rather than by anything a user can add to. There is no
        # query parameter, no LIMIT and no state in which it holds part of the
        # answer. And a short answer here is not a page, it is the wrong steel:
        # the summary exists to be ordered and cut from, so a caller that
        # received the first few diameters and no sign there were more would
        # order short and find out on site. An envelope would carry a total
        # equal to len(items) by construction and an incomplete-page branch
        # nothing could reach, while advertising a truncation this endpoint
        # must never have.
        "rebar_schedule/router.py::cutting_summary",
        # A fixed registry of EN 16931 country profiles the build supports.
        # The list is compiled from profiles.py, gains an entry when a developer
        # adds a new country profile, and is never user-expandable. The route
        # returns the whole PROFILES dict, so there is no query, no LIMIT and no
        # state in which it answers with part of the set.
        "einvoice/router.py::list_profiles",
    }
)

# Every bare-list GET route in backend/app/modules when this guard was written,
# as "<path under modules>::<function>". Regenerate with --dump after a
# migration wave, and let the diff show the routes that left.
#
# Nothing but entries goes between the braces below. The region is machine
# written, so a comment placed inside it is deleted by the next --dump while
# the entry it explains survives without it; main() refuses a run that finds
# one. Notes about particular entries belong up here, and a note saying an
# entry must never be migrated belongs in CANNOT_TRUNCATE above instead.
#
# The qms trio is here rather than in CANNOT_TRUNCATE. list_calibrations,
# list_expiring_calibrations and list_itp_templates have no frontend caller at
# all, which is why they stayed behind while the other eight moved: no wrapper
# means no census of who reads them, and backend tests do, so the readers have
# to be enumerated before the shape changes under them. That is work not yet
# done, not work that must not be done.
#
# Regenerate from a clean checkout, not from the working tree. This repository
# is worked by several sessions at once, so the tree on disk holds routes that
# are not committed yet. The first draft of this list was taken from the tree
# and picked up one such route; CI reads the commit, found no such route, and
# the guard would have arrived red through no fault of the tree. A census of
# what is committed is the only census the gate can hold itself to.
ALLOWED: frozenset[str] = frozenset(
    {
        "accommodation/router.py::list_accommodations",
        "accommodation/router.py::list_charges",
        "accommodation/router.py::list_rooms",
        "ai/router.py::list_ai_providers",
        "ai_agents/router.py::list_agents_endpoint",
        "ai_agents/router.py::list_automated_runs",
        "ai_agents/router.py::list_custom_agents",
        "ai_agents/router.py::list_event_triggers_endpoint",
        "ai_agents/router.py::list_grantable_tools_endpoint",
        "ai_agents/router.py::list_runs",
        "ai_agents/router.py::list_tools_endpoint",
        "ai_agents/router.py::project_insights",
        "ai_estimator/router.py::get_steps",
        "ai_estimator/router.py::list_catalogues",
        "ai_estimator/router.py::list_project_types",
        "allowances/router.py::list_allowances",
        "allowances/router.py::list_drawdowns",
        "approval_routes/router.py::list_delegations",
        "approval_routes/router.py::list_instances",
        "approval_routes/router.py::list_routes",
        "architecture_map/router.py::list_connections",
        "architecture_map/router.py::list_modules",
        "authority_submission/router.py::list_profiles",
        "authority_submission/router.py::list_submissions",
        "bcf/opencde_router.py::list_projects",
        "bcf/router.py::list_topics",
        "bi_dashboards/router.py::list_alerts",
        "bi_dashboards/router.py::list_dashboards",
        "bi_dashboards/router.py::list_filters",
        "bi_dashboards/router.py::list_kpis",
        "bi_dashboards/router.py::list_reports",
        "bi_dashboards/router.py::list_schedules",
        "bid_management/router.py::list_bidders",
        "bid_management/router.py::list_invitations",
        "bid_management/router.py::list_line_items",
        "bid_management/router.py::list_packages",
        "bid_management/router.py::list_qa",
        "bid_management/router.py::list_submission_lines",
        "bid_management/router.py::list_submissions",
        "bim_hub/router.py::get_column_values",
        "bim_hub/router.py::get_dataframe_schema",
        "bim_hub/router.py::list_element_groups",
        "bim_requirements/router.py::list_sets",
        "boq/router.py::get_anomalies",
        "boq/router.py::get_cost_rollup",
        "boq/router.py::get_line_items",
        "boq/router.py::list_boq_variables",
        "boq/router.py::list_boqs",
        "boq/router.py::list_custom_columns",
        "boq/router.py::list_position_copilot_messages",
        "boq/router.py::list_quantity_links",
        "boq/router.py::list_snapshots",
        "boq/router.py::list_templates",
        "carbon/router.py::list_embodied",
        "carbon/router.py::list_epd",
        "carbon/router.py::list_factors",
        "carbon/router.py::list_inventories",
        "carbon/router.py::list_life_cycle_cost",
        "carbon/router.py::list_operational_carbon",
        "carbon/router.py::list_reports",
        "carbon/router.py::list_scope1",
        "carbon/router.py::list_scope2",
        "carbon/router.py::list_scope3",
        "carbon/router.py::list_targets",
        "cases/router.py::list_my_cases",
        "cases/router.py::list_my_pins",
        "catalog/router.py::list_catalog_regions",
        "cde/router.py::get_container_history",
        "cde/router.py::get_container_transmittals",
        "cde/router.py::list_containers",
        "cde/router.py::list_revisions",
        "certified_payroll/router.py::list_assignments",
        "certified_payroll/router.py::list_determinations",
        "certified_payroll/router.py::list_weeks",
        "changeorders/router.py::get_approvals",
        "changeorders/router.py::list_change_orders",
        "clash/router.py::list_clusters",
        "clash/router.py::list_models",
        "clash/router.py::list_profiles",
        "clash/router.py::list_rule_suggestions",
        "clash/router.py::list_rules",
        "clash/router.py::list_runs",
        "collaboration/router.py::get_thread",
        "collaboration_locks/router.py::list_my_locks",
        "commissioning/router.py::list_checklists",
        "commissioning/router.py::list_issues",
        "commissioning/router.py::list_items",
        "commissioning/router.py::list_systems",
        "compliance_docs/router.py::list_compliance_docs",
        "compliance_docs/router.py::list_expiring_soon",
        "connectors/router.py::list_sources",
        "construction_control/router.py::list_asbuilt",
        "construction_control/router.py::list_criteria",
        "construction_control/router.py::list_gates",
        "construction_control/router.py::list_handover_packages",
        "construction_control/router.py::list_inspections",
        "construction_control/router.py::list_materials",
        "construction_control/router.py::list_test_results",
        "contracts/router.py::list_claim_lines",
        "contracts/router.py::list_clause_template_versions",
        "contracts/router.py::list_clause_templates",
        "contracts/router.py::list_compliance_rule_packs",
        "contracts/router.py::list_contract_documents",
        "contracts/router.py::list_contract_lines",
        "contracts/router.py::list_contract_milestones",
        "contracts/router.py::list_contract_parties",
        "contracts/router.py::list_contract_securities",
        "contracts/router.py::list_contract_signing_sessions",
        "contracts/router.py::list_eot_claims",
        "contracts/router.py::list_lien_waivers",
        "contracts/router.py::list_type_configurations",
        "cost_match/router.py::list_result_decisions",
        "cost_match/router.py::list_runs",
        "cost_recovery/router.py::list_project_back_charges",
        "costmodel/router.py::list_budget_lines",
        "costmodel/router.py::list_control_accounts",
        "costmodel/router.py::list_cost_lines",
        "costmodel/router.py::list_snapshots",
        "costs/router.py::autocomplete_cost_items",
        "costs/router.py::get_category_tree",
        "costs/router.py::list_available_databases",
        "costs/router.py::list_categories",
        "costs/router.py::list_cost_catalogs",
        "costs/router.py::list_loaded_databases",
        "costs/router.py::list_loaded_regions",
        "costs/router.py::list_regional_indices",
        "costs/router.py::region_stats",
        "costs/router.py::semantic_search",
        "costs/router.py::vector_region_stats",
        "credentials/router.py::list_credentials",
        "credentials/router.py::list_expiring_soon",
        "credentials/router.py::list_requirements",
        "crm/router.py::account_tree",
        "crm/router.py::activity_timeline",
        "crm/router.py::list_accounts",
        "crm/router.py::list_activities",
        "crm/router.py::list_leads",
        "crm/router.py::list_opportunities",
        "crm/router.py::list_reasons",
        "crm/router.py::list_stages",
        "crm/router.py::opportunity_history",
        "cvr/router.py::list_cashflow_points",
        "cvr/router.py::list_lines",
        "daily_diary/router.py::list_archive_signatures",
        "daily_diary/router.py::list_drone_surveys",
        "daily_diary/router.py::list_productivity_trades",
        "daily_diary/router.py::list_reality_captures",
        "daily_diary/router.py::list_videos",
        "daily_diary/router.py::weather_today",
        "defects_liability/router.py::list_defects",
        "defects_liability/router.py::list_warranties",
        "design_options/router.py::list_sets",
        "documents/router.py::list_disciplines",
        "documents/router.py::list_document_share_links",
        "documents/router.py::list_recent_photos",
        "dwg_takeoff/router.py::get_entities",
        "dwg_takeoff/router.py::get_pins",
        "dwg_takeoff/router.py::list_annotations",
        "dwg_takeoff/router.py::list_drawing_versions",
        "dwg_takeoff/router.py::list_drawings",
        "dwg_takeoff/router.py::list_entity_groups",
        "eac/aliases/router.py::list_aliases_route",
        "eac/router.py::list_block_graphs",
        "eac/router.py::list_rules",
        "eac/router.py::list_rulesets",
        "eac/router.py::list_run_results",
        "eac/router.py::list_runs",
        "einvoice_clearance/router.py::list_clearance_documents",
        "einvoice_clearance/router.py::list_clearance_events",
        "einvoice_clearance/router.py::list_registrations",
        "equipment/router.py::expiring_inspections",
        "equipment/router.py::generate_due_work_orders",
        "equipment/router.py::list_damage_reports",
        "equipment/router.py::list_inspections",
        "equipment/router.py::list_parts_logs",
        "equipment/router.py::list_rentals",
        "equipment/router.py::list_schedules",
        "equipment/router.py::list_telemetry",
        "erp_chat/router.py::get_messages",
        "esg/router.py::list_entries",
        "esg/router.py::list_metric_definitions",
        "field_diary/router.py::field_roster",
        "field_diary/router.py::list_entries",
        "field_diary/router.py::list_schedule_activities",
        "field_diary/router.py::sync_ops",
        "fieldreports/router.py::get_calendar",
        "fieldreports/router.py::get_linked_documents",
        "fieldreports/router.py::list_equipment_logs",
        "fieldreports/router.py::list_reports",
        "fieldreports/router.py::list_templates",
        "fieldreports/router.py::list_workforce_logs",
        "file_approvals/router.py::list_stamp_templates",
        "file_approvals/router.py::list_workflows",
        "file_favorites/router.py::list_my_favorites",
        "file_tags/router.py::list_project_tags",
        "file_tags/router.py::list_tags_for_file",
        "file_transmittals/router.py::list_transmittals",
        "file_versions/router.py::list_versions",
        "finance/router.py::list_connector_types",
        "forms/router.py::list_categories",
        "forms/router.py::list_submissions",
        "forms/router.py::list_templates",
        "formwork/router.py::list_assignments",
        "formwork/router.py::list_schedule_lines",
        "formwork/router.py::list_systems",
        "geo_hub/router.py::list_anchored_projects",
        "geo_hub/router.py::list_anchors",
        "geo_hub/router.py::list_diary_photo_pins",
        "geo_hub/router.py::list_hse_pins",
        "geo_hub/router.py::list_imagery_layers",
        "geo_hub/router.py::list_overlays",
        "geo_hub/router.py::list_punchlist_pins",
        "geo_hub/router.py::list_raster_overlays",
        "geo_hub/router.py::list_terrain_sources",
        "geo_hub/router.py::list_tile_jobs",
        "geo_hub/router.py::list_tilesets",
        "geo_hub/router.py::list_viewpoints",
        "hse_advanced/router.py::list_audits",
        "hse_advanced/router.py::list_capas",
        "hse_advanced/router.py::list_certifications",
        "hse_advanced/router.py::list_corrective_actions",
        "hse_advanced/router.py::list_expiring_certifications",
        "hse_advanced/router.py::list_findings",
        "hse_advanced/router.py::list_investigations",
        "hse_advanced/router.py::list_jsa",
        "hse_advanced/router.py::list_jsa_templates",
        "hse_advanced/router.py::list_permits",
        "hse_advanced/router.py::list_ppe",
        "hse_advanced/router.py::list_toolbox_talks",
        "hse_advanced/router.py::list_topics",
        "integrations/router.py::list_deliveries",
        "integrations/router.py::list_webhooks",
        "interface_management/router.py::list_actions",
        "interface_management/router.py::list_interfaces",
        "labor_rates/router.py::list_templates",
        "markups/router.py::list_markup_comments",
        "markups/router.py::list_markups",
        "markups/router.py::list_scales",
        "markups/router.py::list_stamp_templates",
        "match_elements/router.py::list_attribute_keys",
        "match_elements/router.py::list_categories",
        "match_elements/router.py::list_project_bim_models",
        "match_elements/router.py::list_prompt_templates",
        "match_elements/router.py::list_sessions",
        "match_elements/router.py::list_templates",
        "meetings/router.py::list_attendance",
        "meetings/router.py::list_meetings",
        "meetings/router.py::open_action_items",
        "methodology/router.py::list_dimensions",
        "methodology/router.py::list_funding_sources",
        "methodology/router.py::list_methodologies",
        "methodology/router.py::list_templates",
        "moc/router.py::list_moc_entries",
        "moc/router.py::list_moc_impacts",
        "norm_expansion/router.py::list_norms",
        "notifications/router.py::list_event_types",
        "notifications/router.py::list_preferences",
        "notifications/router.py::list_webhook_targets",
        "opencde_api/router.py::bcf_list_comments",
        "opencde_api/router.py::bcf_list_projects",
        "opencde_api/router.py::bcf_list_topics",
        "opencde_api/router.py::bcf_list_viewpoints",
        "payment_clock/router.py::get_applications",
        "payment_clock/router.py::get_events",
        "payment_clock/router.py::get_notices",
        "payment_clock/router.py::get_regimes",
        "payroll/router.py::list_batches",
        "phonelog/router.py::list_phone_logs",
        "pipelines/router.py::list_node_types",
        "pipelines/router.py::list_pipelines",
        "pipelines/router.py::list_runs",
        "portal/router.py::admin_document_access_log",
        "portal/router.py::portal_me_accessible",
        "portfolio/router.py::get_tree",
        "portfolio/router.py::list_cross_links",
        "prefab/router.py::list_unit_events",
        "prefab/router.py::list_units",
        "preliminaries/router.py::list_items",
        "price_index/router.py::list_location_factors",
        "price_index/router.py::list_series",
        "progress/router.py::list_entries",
        "progress/router.py::list_plan",
        "project_intelligence/router.py::list_actions",
        "project_route/router.py::get_route_options",
        "project_route/router.py::get_work_types",
        "project_route/router.py::list_assessments",
        "projects/router.py::dashboard_cards",
        "projects/router.py::file_manager_tree",
        "projects/router.py::list_folder_permissions",
        "projects/router.py::list_milestones",
        "projects/router.py::list_project_members_endpoint",
        "projects/router.py::list_project_modules",
        "projects/router.py::list_projects",
        "projects/router.py::list_wbs_nodes",
        "projects/router.py::list_wizard_presets",
        "projects/router.py::project_activity",
        "projects/router.py::project_status_history",
        "property_dev/portal_router.py::list_buyer_portal_tokens",
        "property_dev/router.py::list_blocks",
        "property_dev/router.py::list_brokers",
        "property_dev/router.py::list_buyers",
        "property_dev/router.py::list_commission_accruals",
        "property_dev/router.py::list_commission_agreements",
        "property_dev/router.py::list_contract_parties",
        "property_dev/router.py::list_developments",
        "property_dev/router.py::list_escrow_accounts",
        "property_dev/router.py::list_escrow_transactions",
        "property_dev/router.py::list_handovers",
        "property_dev/router.py::list_house_type_catalogue",
        "property_dev/router.py::list_house_types",
        "property_dev/router.py::list_instalments",
        "property_dev/router.py::list_jurisdictions",
        "property_dev/router.py::list_leads",
        "property_dev/router.py::list_option_groups",
        "property_dev/router.py::list_options",
        "property_dev/router.py::list_payment_schedule_templates",
        "property_dev/router.py::list_payment_schedules",
        "property_dev/router.py::list_phases",
        "property_dev/router.py::list_plots",
        "property_dev/router.py::list_price_lists",
        "property_dev/router.py::list_price_matrices",
        "property_dev/router.py::list_pricing_rules",
        "property_dev/router.py::list_reservations",
        "property_dev/router.py::list_sales_contracts",
        "property_dev/router.py::list_selections",
        "property_dev/router.py::list_snags",
        "property_dev/router.py::list_variants",
        "property_dev/router.py::list_warranty_claims",
        "property_dev/router.py::portal_list_my_snags",
        "property_dev/router.py::portal_list_my_warranty_claims",
        "qms/router.py::list_calibrations",
        "qms/router.py::list_expiring_calibrations",
        "qms/router.py::list_itp_templates",
        "reconciliation/router.py::list_project_record_links",
        "reporting/router.py::list_kpi_history",
        "reporting/router.py::list_reports",
        "reporting/router.py::list_scheduled_templates",
        "reporting/router.py::list_templates",
        "requirements/router.py::list_gates",
        "requirements/router.py::list_position_links",
        "requirements/router.py::list_requirement_deliverables",
        "requirements/router.py::list_requirements_by_bim_element",
        "requirements/router.py::list_sets",
        "requirements/router.py::requirements_for_position",
        "resource_summary/router.py::list_resource_snapshots",
        "resources/resource_depth_router.py::list_rates",
        "resources/router.py::board_conflicts",
        "resources/router.py::list_assignments_for_activity",
        "resources/router.py::list_assignments_for_resource",
        "resources/router.py::list_certifications_for_resource",
        "resources/router.py::list_expiring_certifications",
        "resources/router.py::list_links_for_resource",
        "resources/router.py::list_requests",
        "resources/router.py::list_resource_skills",
        "resources/router.py::list_skills",
        "resources/router.py::list_windows",
        "review_authority/router.py::list_cycles",
        "review_authority/router.py::list_remarks",
        "review_authority/router.py::repeat_radar",
        "review_authority/router.py::stale_remarks",
        "rom_estimate/router.py::list_estimates",
        "safety/router.py::list_observations",
        "saved_views/router.py::list_views",
        "schedule/codes_router.py::list_activity_codes",
        "schedule/codes_router.py::list_activity_udf_values",
        "schedule/codes_router.py::list_code_dictionaries",
        "schedule/codes_router.py::list_code_values",
        "schedule/codes_router.py::list_layouts",
        "schedule/codes_router.py::list_library_dictionaries",
        "schedule/codes_router.py::list_udfs",
        "schedule/progress_router.py::list_steps",
        "schedule/router.py::critical_path_activities",
        "schedule/router.py::list_activities_by_bim_element",
        "schedule/router.py::list_baselines",
        "schedule/router.py::list_progress_updates",
        "schedule/router.py::list_relationships",
        "schedule/router.py::list_work_orders",
        "schedule/router_4d.py::list_progress_history",
        "schedule_advanced/router.py::get_takt_violations",
        "schedule_advanced/router.py::list_baselines",
        "schedule_advanced/router.py::list_calendars",
        "schedule_advanced/router.py::list_commitments",
        "schedule_advanced/router.py::list_constraints",
        "schedule_advanced/router.py::list_delay_analyses",
        "schedule_advanced/router.py::list_look_aheads",
        "schedule_advanced/router.py::list_master_schedules",
        "schedule_advanced/router.py::list_phase_plans",
        "schedule_advanced/router.py::list_rncs",
        "schedule_advanced/router.py::list_takt_activities",
        "schedule_advanced/router.py::list_takt_schedules",
        "schedule_advanced/router.py::list_weekly_work_plans",
        "schedule_advanced/router.py::look_ahead_readiness",
        "schedule_advanced/router.py::project_ppc_trend",
        "service/router.py::list_assets",
        "service/router.py::list_checklists",
        "service/router.py::list_contracts",
        "service/router.py::list_recurring_schedules",
        "service/router.py::list_schedules",
        "service/router.py::list_slas",
        "signing/router.py::expiring_certs",
        "signing/router.py::list_sessions",
        "site_inventory/router.py::list_items",
        "site_inventory/router.py::list_locations",
        "site_inventory/router.py::list_movements",
        "site_logistics/router.py::list_deliveries",
        "site_logistics/router.py::list_gates",
        "site_logistics/router.py::list_zones",
        "site_prep/router.py::list_items",
        "site_supervision/router.py::change_links",
        "site_supervision/router.py::hidden_works",
        "site_supervision/router.py::list_visit_entries",
        "site_supervision/router.py::list_visits",
        "smart_views/router.py::list_smart_view_presets",
        "smart_views/router.py::list_smart_views",
        "source_data/router.py::list_blocking_schedule",
        "source_data/router.py::list_checklist",
        "source_data/router.py::list_documents",
        "source_data/router.py::list_expiring_soon",
        "subcontractors/router.py::list_agreements",
        "subcontractors/router.py::list_certificates",
        "subcontractors/router.py::list_expiring_certificates",
        "subcontractors/router.py::list_lien_waivers",
        "subcontractors/router.py::list_payment_applications",
        "subcontractors/router.py::list_prequalifications",
        "subcontractors/router.py::list_ratings",
        "subcontractors/router.py::list_subcontractor_contacts",
        "subcontractors/router.py::list_work_packages",
        "subcontractors/router.py::retention_ledger",
        "submittals/router.py::list_submittal_attachments",
        "submittals/router.py::list_submittals",
        "supplier_catalogs/router.py::list_commodity_codes",
        "supplier_catalogs/router.py::list_tolerance_profiles",
        "supplier_catalogs/router.py::list_vendor_kyc",
        "supplier_catalogs/router.py::list_vendor_scorecards",
        "supplier_catalogs/router.py::list_warehouse_balances",
        "supplier_catalogs/router.py::list_warehouses",
        "supplier_catalogs/router.py::price_comparison",
        "takeoff/router.py::cad_data_list_sessions",
        "takeoff/router.py::list_documents",
        "takeoff/router.py::list_measurements",
        "takeoff/router.py::plan_read_proposals",
        "tax_withholding/router.py::list_deductions",
        "tax_withholding/router.py::list_determinations",
        "tax_withholding/router.py::list_expiring_party_statuses",
        "tax_withholding/router.py::list_party_statuses",
        "tax_withholding/router.py::list_regimes",
        "tax_withholding/router.py::list_reverse_charge_rules",
        "teams/router.py::list_entity_types",
        "teams/router.py::list_members",
        "teams/router.py::list_restricted_entities",
        "teams/router.py::list_team_visibility",
        "teams/router.py::list_teams",
        "teams/router.py::list_teams_by_query",
        "temporary_works/router.py::list_items",
        "temporary_works/router.py::list_permits",
        "tendering/router.py::list_bids",
        "tendering/router.py::list_package_addenda",
        "tendering/router.py::list_package_recipients",
        "tendering/router.py::list_packages",
        "tendering/router.py::list_tenders_root",
        "users/router.py::get_onboarding_presets",
        "users/router.py::get_onboarding_size_presets",
        "users/router.py::list_my_api_keys",
        "users/router.py::list_users",
        "validation/router.py::list_reports",
        "validation/router.py::list_rule_sets",
        "variations/router.py::list_contract_standards",
        "variations/router.py::list_final_accounts",
        "voice/router.py::list_targets",
        "waste_factors/router.py::list_factors",
        "webhook_leads/router.py::list_logs",
        "webhook_leads/router.py::list_mappings",
        "webhook_leads/router.py::list_sources",
    }
)


def _is_bare_list(node: ast.AST | None) -> bool:
    """True when the annotation is ``list[...]``, ``List[...]`` or ``Sequence[...]``."""
    if isinstance(node, ast.Subscript):
        base = node.value
        name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
        return name in {"list", "List", "Sequence"}
    return False


def bare_list_routes(tree: ast.AST) -> list[str]:
    """The names of the GET routes in one parsed module that answer with an array."""
    found: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for dec in fn.decorator_list:
            if not isinstance(dec, ast.Call) or getattr(dec.func, "attr", "") != "get":
                continue
            response_model = next((k.value for k in dec.keywords if k.arg == "response_model"), None)
            if response_model is not None:
                if _is_bare_list(response_model):
                    found.append(fn.name)
            elif _is_bare_list(fn.returns):
                found.append(fn.name)
    return found


def scan() -> tuple[set[str], int]:
    """Every bare-list GET route in the module tree, and how many files were read."""
    found: set[str] = set()
    files = 0
    for path in sorted(MODULES_DIR.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        files += 1
        rel = path.relative_to(MODULES_DIR).as_posix()
        found.update(f"{rel}::{name}" for name in bare_list_routes(tree))
    return found, files


def self_test() -> None:
    """Prove the scanner can both accept and refuse before it is trusted to scan.

    A guard that has quietly stopped matching looks exactly like a clean tree,
    and this one matches on a narrow shape that a later tightening could easily
    silence. So every real run is preceded by a run against known answers.
    """
    refused = """
@router.get("/things/", response_model=list[ThingResponse])
async def list_things() -> list[ThingResponse]: ...
"""
    also_refused = """
@router.get("/things/")
async def list_things() -> list[ThingResponse]: ...
"""
    accepted = """
@router.get("/things/", response_model=ThingListResponse)
async def list_things() -> ThingListResponse: ...
"""
    single = """
@router.get("/things/{thing_id}", response_model=ThingResponse)
async def get_thing(thing_id: UUID) -> ThingResponse: ...
"""
    writer = """
@router.post("/things/", response_model=list[ThingResponse])
async def bulk_create() -> list[ThingResponse]: ...
"""
    cases = [
        ("a list response_model", refused, ["list_things"]),
        ("a bare return annotation", also_refused, ["list_things"]),
        ("an envelope", accepted, []),
        ("a single-item read", single, []),
        ("a writer that returns rows", writer, []),
    ]
    for label, source, expected in cases:
        actual = bare_list_routes(ast.parse(source))
        if actual != expected:
            print(
                f"SELF-TEST FAILED on {label}: expected {expected}, got {actual}.\n"
                "The scanner no longer measures what this guard claims to measure, "
                "so its verdict on the tree means nothing. Fix the scanner.",
                file=sys.stderr,
            )
            raise SystemExit(2)
    # The sorting of routes across the two lists, which no scanner case above
    # can reach. The first of these is the mechanism itself: an exempt route is
    # present in the tree on every single run, so if it were reported as new the
    # gate would turn red the moment an entry moved out of ALLOWED, and the only
    # way back to green would be putting it back.
    allowed = frozenset({"a/router.py::list_a"})
    exempt = frozenset({"b/router.py::list_b"})
    both = {"a/router.py::list_a", "b/router.py::list_b"}
    splits = [
        ("an exempt route present in the tree", both, ([], [], [])),
        (
            "a route in neither list",
            both | {"c/router.py::list_c"},
            (["c/router.py::list_c"], [], []),
        ),
        (
            "a migrated entry from ALLOWED",
            {"b/router.py::list_b"},
            ([], ["a/router.py::list_a"], []),
        ),
        (
            "an exempt entry that stopped being a bare list",
            {"a/router.py::list_a"},
            ([], [], ["b/router.py::list_b"]),
        ),
    ]
    for label, found, expected in splits:
        split = classify(found, allowed, exempt)
        if split != expected:
            print(
                f"SELF-TEST FAILED on {label}: expected {expected}, got {split}.\n"
                "The two lists are no longer being read as opposites, so the census "
                "counts the wrong routes.",
                file=sys.stderr,
            )
            raise SystemExit(2)

    # And the overlap check, whose whole job is to refuse. It never fires on the
    # real lists, so it is the one part of this file that could rot unobserved.
    if double_counted(allowed, exempt):
        print(
            "SELF-TEST FAILED: two disjoint lists were reported as overlapping.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if double_counted(allowed, exempt | allowed) != ["a/router.py::list_a"]:
        print(
            "SELF-TEST FAILED: a route in both lists was not reported.\n"
            "The check cannot refuse, so it cannot keep the census honest.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    # To stderr, so that --dump writes nothing to stdout but the list itself.
    print(
        "SELF-TEST OK: refuses a list response_model and a bare return annotation,\n"
        "             accepts an envelope, ignores single-item reads and writers,\n"
        "             sorts routes across the waiting and exempt lists, and refuses\n"
        "             a route claimed by both.",
        file=sys.stderr,
    )


def envelope_advice(key: str) -> str:
    """The class to write instead, named for the module the route lives in."""
    module = key.split("/", 1)[0]
    cls = "".join(part.title() for part in module.split("_")) + "ListResponse"
    return (
        f"      write {cls} in backend/app/modules/{module}/schemas.py:\n"
        f"          class {cls}(BaseModel):\n"
        f"              items: list[<Row>Response]\n"
        f"              total: int\n"
        f"              offset: int = 0\n"
        f"              limit: int = 50\n"
        f"      and have the route return it, with total counting the rows the\n"
        f"      filters matched rather than the rows on the page. Declare it after\n"
        f"      the row class it names: `from __future__ import annotations` makes\n"
        f"      the field a string, so a forward reference parses and then fails\n"
        f"      when Pydantic builds the model."
    )


def double_counted(allowed: frozenset[str], exempt: frozenset[str]) -> list[str]:
    """Routes claimed by both lists.

    The lists mean opposite things and only one of them is the countdown, so a
    route in both is at once waiting and never waiting, and the number printed
    on a clean run is wrong by however many there are.

    Args:
        allowed: Routes waiting their turn to be migrated.
        exempt: Routes that must never be migrated.

    Returns:
        The routes named by both, sorted.
    """
    return sorted(allowed & exempt)


def classify(
    found: set[str], allowed: frozenset[str], exempt: frozenset[str]
) -> tuple[list[str], list[str], list[str]]:
    """Split a scan of the tree across the two declared lists.

    Args:
        found: Bare-list routes the scan saw.
        allowed: Routes waiting their turn to be migrated.
        exempt: Routes that must never be migrated.

    Returns:
        The routes in neither list, the ``allowed`` entries that no longer name
        a bare-list route, and the ``exempt`` entries that no longer name one.
        Three lists rather than two, because the remedy for the last is not the
        remedy for the middle one: ``--dump`` cannot prune an ``exempt`` entry,
        it does not print that list at all.
    """
    return (
        sorted(found - allowed - exempt),
        sorted(allowed - found),
        sorted(exempt - found),
    )


def commented_lines_inside_allowed() -> list[int]:
    """Line numbers of comments written between the braces of ``ALLOWED``.

    ``--dump`` reproduces that region entry by entry and nothing else, so a
    comment placed there is erased by the next regeneration while the entry it
    explains stays behind. A route documented as unmigratable then reads as one
    more route waiting its turn, which is the failure ``CANNOT_TRUNCATE``
    exists to prevent; leaving the region writable to comments would let the
    same thing happen again with the next one.

    Returns:
        The offending line numbers, empty when the region holds entries only.

    Raises:
        SystemExit: If this file no longer declares ``ALLOWED``, since then the
            check is passing by failing to look.
    """
    source = Path(__file__).resolve()
    text = source.read_text(encoding="utf-8")
    lines = text.splitlines()
    for node in ast.parse(text).body:
        target = getattr(node, "target", None)
        if isinstance(target, ast.Name) and target.id == "ALLOWED":
            end = node.end_lineno or node.lineno
            return [n for n in range(node.lineno, end + 1) if lines[n - 1].lstrip().startswith("#")]
    print(
        f"ERROR: no ALLOWED assignment found in {source}, so the check that keeps\n"
        "comments out of the machine-written region cannot have looked at it.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def main() -> int:
    if not MODULES_DIR.is_dir():
        print(f"ERROR: no module tree at {MODULES_DIR}", file=sys.stderr)
        return 2

    self_test()
    found, files = scan()

    if files < MIN_FILES_SCANNED:
        print(
            f"ERROR: only {files} python files were read under {MODULES_DIR}.\n"
            "That is too few to be the real tree, so a clean result here would be\n"
            "the scan failing rather than the tree passing.",
            file=sys.stderr,
        )
        return 2

    if "--dump" in sys.argv:
        # The exempt routes are bare-list routes and the scan finds them, but
        # printing them here would fold them back into ALLOWED at the next
        # regeneration, and their justification does not come with them.
        waiting = sorted(found - CANNOT_TRUNCATE)
        for key in waiting:
            print(f'        "{key}",')
        print(
            f"\n# {len(waiting)} bare-list GET routes waiting, of {len(found)} found"
            f" across {files} files\n"
            f"# ({len(CANNOT_TRUNCATE)} exempt and deliberately not printed; paste the"
            " lines above between the braces of ALLOWED,\n"
            "# replacing what is there, and leave CANNOT_TRUNCATE alone)",
            file=sys.stderr,
        )
        return 0

    both = double_counted(ALLOWED, CANNOT_TRUNCATE)
    if both:
        print(
            f"\n{len(both)} route(s) are in ALLOWED and in CANNOT_TRUNCATE at once.\n"
            "One list says the route is waiting its turn and the other says its turn\n"
            "never comes, so the countdown printed on a clean run is wrong and a wave\n"
            "may migrate a route documented as unmigratable. Delete the ALLOWED entry:\n"
            "the reason lives with the CANNOT_TRUNCATE one.\n",
            file=sys.stderr,
        )
        for key in both:
            print(f"  {key}", file=sys.stderr)
        return 2

    stray = commented_lines_inside_allowed()
    if stray:
        print(
            f"\n{len(stray)} comment line(s) sit between the braces of ALLOWED, at line"
            f" {', '.join(str(n) for n in stray)}.\n"
            "That region is rewritten wholesale by --dump, which prints entries and\n"
            "nothing else, so the next regeneration deletes the comment and keeps the\n"
            "entry. Whatever the comment was there to say stops being said, and the\n"
            "entry it explained becomes one more anonymous route awaiting a wave.\n"
            "Move it above the frozenset. If it says the route must never be migrated,\n"
            "move the entry to CANNOT_TRUNCATE and take the comment with it.\n",
            file=sys.stderr,
        )
        return 2

    added, departed, stale_exempt = classify(found, ALLOWED, CANNOT_TRUNCATE)

    if added:
        print(
            f"\n{len(added)} new GET route(s) answer with a bare array.\n"
            "A list that answers with an array cannot tell the reader it was cut\n"
            "short: the caller gets the first page and no way to know there is a\n"
            "second. Answer with a page envelope instead.\n",
            file=sys.stderr,
        )
        for key in added:
            print(f"  {key}", file=sys.stderr)
            print(envelope_advice(key), file=sys.stderr)
        print(
            "\nIf a short answer from the route would be a correctness bug rather than\n"
            "a page - a fixed taxonomy, an enum, a set the reader has to see all of -\n"
            "add it to CANNOT_TRUNCATE in this file, with a comment saying why.\n"
            "\n"
            "Not to ALLOWED. That block is rewritten by --dump, which prints entries\n"
            "and nothing else, so a comment written between its braces is erased at\n"
            "the next regeneration while the entry it explains survives, and the entry\n"
            "then reads as one more route waiting its turn. CANNOT_TRUNCATE is never\n"
            "machine-written, which is what keeps the reason attached to the route.\n"
            "\n"
            "Being short today is not the test, and being bounded by a parent is not\n"
            "the test either. Both still have a state in which the caller holds part\n"
            "of the set, and reporting that state is what the envelope is for.",
            file=sys.stderr,
        )
        return 1

    if departed:
        print(
            f"\n{len(departed)} entr(y/ies) in ALLOWED no longer name a bare-list route.\n"
            "That is what a finished migration looks like, so this is a prompt to\n"
            "prune rather than a fault: remove them from ALLOWED in the same commit\n"
            "that migrated them, or the count stops meaning anything and the freed\n"
            "names silently re-permit whatever takes them next.\n",
            file=sys.stderr,
        )
        for key in departed:
            print(f"  {key}", file=sys.stderr)
        print(
            "\nRegenerate with: python scripts/check_no_new_bare_list_endpoints.py --dump",
            file=sys.stderr,
        )
        return 1

    if stale_exempt:
        print(
            f"\n{len(stale_exempt)} entr(y/ies) in CANNOT_TRUNCATE no longer name a\n"
            "bare-list route. Unlike the ALLOWED case this is not a finished migration\n"
            "to be tidied up after, because these were declared unable to truncate:\n"
            "either the route was renamed or deleted, or it was migrated to an envelope\n"
            "against the reason recorded beside it. Read that reason before deciding.\n"
            "Do not reach for --dump here; it does not print this list.\n",
            file=sys.stderr,
        )
        for key in stale_exempt:
            print(f"  {key}", file=sys.stderr)
        return 1

    print(f"\nfiles read under backend/app/modules: {files}")
    print(
        f"OK: no new bare-list GET routes. {len(ALLOWED)} still waiting to be migrated, {len(CANNOT_TRUNCATE)} exempt."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
