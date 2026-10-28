// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Module catalogue for the OpenConstructionERP onboarding wizard.
 *
 * Each entry mirrors one of the 153 backend module manifests in
 * ``backend/app/modules/<mod>/manifest.py``. Keys follow the backend ``name``
 * minus the ``oe_`` prefix (snake_case). The wizard hands the key list to
 * ``useModuleStore.setModuleEnabled`` on finish.
 *
 * Groups partition the 153 modules into 19 user-facing buckets. The v3.0
 * 18-Modules Wave is broken across the new groups (sustainability_esg,
 * qms_compliance, bi_analytics, operations, commercial, bim_advanced).
 *
 * Modules with ``core: true`` are always enabled (toggle is disabled in UI).
 * These are platform infrastructure (auth, uploads, jobs, search, etc.) plus
 * the three "always on" Dashboards / Projects / Contacts entries.
 */

export interface ModuleDef {
  /** Wizard key — matches the backend manifest ``name`` minus the ``oe_``
   *  prefix (snake_case). The ``useModuleStore`` is tolerant of any string. */
  key: string;
  /** i18n key for the human-readable display name. */
  labelKey: string;
  /** i18n key for the one-line description shown in the toggle list. */
  descriptionKey: string;
  /** Group bucket — must match an ``id`` in ``MODULE_GROUPS``. */
  group: string;
  /** Whether the module is always on (toggle disabled). */
  core?: boolean;
}

export interface ModuleGroup {
  id: string;
  labelKey: string;
}

/* ── Groups ──────────────────────────────────────────────────────────────── */

export const MODULE_GROUPS: ModuleGroup[] = [
  { id: 'core', labelKey: 'onboarding.mod_group_core' },
  { id: 'estimation', labelKey: 'onboarding.mod_group_estimation' },
  { id: 'takeoff', labelKey: 'onboarding.mod_group_takeoff' },
  { id: 'bim_advanced', labelKey: 'onboarding.mod_group_bim_advanced' },
  { id: 'ai', labelKey: 'onboarding.mod_group_ai' },
  { id: 'planning', labelKey: 'onboarding.mod_group_planning' },
  { id: 'finance', labelKey: 'onboarding.mod_group_finance' },
  { id: 'commercial', labelKey: 'onboarding.mod_group_commercial' },
  { id: 'operations', labelKey: 'onboarding.mod_group_operations' },
  { id: 'communication', labelKey: 'onboarding.mod_group_communication' },
  { id: 'documents', labelKey: 'onboarding.mod_group_documents' },
  { id: 'quality', labelKey: 'onboarding.mod_group_quality' },
  { id: 'qms_compliance', labelKey: 'onboarding.mod_group_qms_compliance' },
  { id: 'field', labelKey: 'onboarding.mod_group_field' },
  { id: 'sustainability_esg', labelKey: 'onboarding.mod_group_sustainability_esg' },
  { id: 'bi_analytics', labelKey: 'onboarding.mod_group_bi_analytics' },
  { id: 'enterprise', labelKey: 'onboarding.mod_group_enterprise' },
  { id: 'regional', labelKey: 'onboarding.mod_group_regional' },
  { id: 'platform', labelKey: 'onboarding.mod_group_platform' },
];

/* ── 153-module catalogue ───────────────────────────────────────────────── */
/* One entry per backend manifest. Total: 153. */

export const ALL_MODULES: ModuleDef[] = [
  // ── Core (always on) ─────────────────────────────────────────────────
  { key: 'projects', labelKey: 'projects.title', descriptionKey: 'onboarding.mod_projects_desc', group: 'core', core: true },
  { key: 'contacts', labelKey: 'contacts.title', descriptionKey: 'onboarding.mod_contacts_desc', group: 'core', core: true },
  { key: 'dashboards', labelKey: 'onboarding.mod_dashboards', descriptionKey: 'onboarding.mod_dashboards_desc', group: 'core', core: true },

  // ── Estimation ───────────────────────────────────────────────────────
  { key: 'boq', labelKey: 'boq.title', descriptionKey: 'onboarding.mod_boq_desc', group: 'estimation' },
  { key: 'design_options', labelKey: 'nav.design_options', descriptionKey: 'onboarding.mod_design_options_desc', group: 'estimation' },
  { key: 'costs', labelKey: 'costs.title', descriptionKey: 'onboarding.mod_costs_desc', group: 'estimation', core: true },
  { key: 'assemblies', labelKey: 'nav.assemblies', descriptionKey: 'onboarding.mod_assemblies_desc', group: 'estimation', core: true },
  { key: 'catalog', labelKey: 'catalog.title', descriptionKey: 'onboarding.mod_catalog_desc', group: 'estimation', core: true },
  { key: 'validation', labelKey: 'validation.title', descriptionKey: 'onboarding.mod_validation_desc', group: 'estimation' },
  { key: 'cost_match', labelKey: 'onboarding.mod_cost_match', descriptionKey: 'onboarding.mod_cost_match_desc', group: 'estimation' },
  { key: 'match', labelKey: 'onboarding.mod_match', descriptionKey: 'onboarding.mod_match_desc', group: 'estimation' },
  { key: 'cost-benchmark', labelKey: 'nav.benchmarks', descriptionKey: 'onboarding.mod_cost_benchmark_desc', group: 'estimation' },

  // ── Takeoff & CAD ────────────────────────────────────────────────────
  { key: 'takeoff', labelKey: 'nav.takeoff_overview', descriptionKey: 'onboarding.mod_takeoff_desc', group: 'takeoff' },
  { key: 'dwg_takeoff', labelKey: 'onboarding.mod_dwg_takeoff', descriptionKey: 'onboarding.mod_dwg_takeoff_desc', group: 'takeoff' },
  { key: 'cad', labelKey: 'onboarding.mod_cad', descriptionKey: 'onboarding.mod_cad_desc', group: 'takeoff' },

  // ── BIM Advanced ─────────────────────────────────────────────────────
  { key: 'bim_hub', labelKey: 'nav.bim_viewer', descriptionKey: 'onboarding.mod_bim_desc', group: 'bim_advanced' },
  { key: 'bim_requirements', labelKey: 'onboarding.mod_bim_requirements', descriptionKey: 'onboarding.mod_bim_requirements_desc', group: 'bim_advanced' },
  { key: 'match_elements', labelKey: 'onboarding.mod_match_elements', descriptionKey: 'onboarding.mod_match_elements_desc', group: 'bim_advanced' },
  { key: 'opencde_api', labelKey: 'onboarding.mod_opencde_api', descriptionKey: 'onboarding.mod_opencde_api_desc', group: 'bim_advanced' },
  { key: 'coordination_hub', labelKey: 'nav.coordination_hub', descriptionKey: 'onboarding.mod_coordination_hub_desc', group: 'bim_advanced' },
  { key: 'clash', labelKey: 'nav.clash_detection', descriptionKey: 'onboarding.mod_clash_desc', group: 'bim_advanced' },
  { key: 'geo_hub', labelKey: 'sidebar.geo_hub', descriptionKey: 'onboarding.mod_geo_hub_desc', group: 'bim_advanced' },
  { key: 'pointcloud', labelKey: 'nav.point_cloud', descriptionKey: 'onboarding.mod_pointcloud_desc', group: 'bim_advanced' },

  // ── AI ───────────────────────────────────────────────────────────────
  { key: 'ai', labelKey: 'nav.ai_estimate', descriptionKey: 'onboarding.mod_ai_estimate_desc', group: 'ai' },
  { key: 'project_intelligence', labelKey: 'nav.project_intelligence', descriptionKey: 'onboarding.mod_pci_desc', group: 'ai', core: true },
  { key: 'erp_chat', labelKey: 'onboarding.mod_erp_chat', descriptionKey: 'onboarding.mod_erp_chat_desc', group: 'ai' },
  { key: 'compliance_ai', labelKey: 'onboarding.mod_compliance_ai', descriptionKey: 'onboarding.mod_compliance_ai_desc', group: 'ai' },
  { key: 'ai_agents', labelKey: 'nav.ai_agents', descriptionKey: 'onboarding.mod_ai_agents_desc', group: 'ai' },
  { key: 'pipelines', labelKey: 'nav.pipelines', descriptionKey: 'onboarding.mod_pipelines_desc', group: 'ai' },

  // ── Planning ─────────────────────────────────────────────────────────
  { key: 'schedule', labelKey: 'schedule.title', descriptionKey: 'onboarding.mod_schedule_desc', group: 'planning' },
  { key: 'schedule_advanced', labelKey: 'onboarding.mod_schedule_advanced', descriptionKey: 'onboarding.mod_schedule_advanced_desc', group: 'planning' },
  { key: 'tasks', labelKey: 'tasks.title', descriptionKey: 'onboarding.mod_tasks_desc', group: 'planning' },
  { key: 'costmodel', labelKey: 'nav.5d_cost_model', descriptionKey: 'onboarding.mod_5d_desc', group: 'planning' },
  { key: 'eac', labelKey: 'onboarding.mod_eac', descriptionKey: 'onboarding.mod_eac_desc', group: 'planning' },
  { key: 'portfolio', labelKey: 'portfolio.title', descriptionKey: 'onboarding.mod_portfolio_desc', group: 'planning' },

  // ── Finance ──────────────────────────────────────────────────────────
  { key: 'finance', labelKey: 'finance.title', descriptionKey: 'onboarding.mod_finance_desc', group: 'finance' },
  { key: 'funding', labelKey: 'funding.title', descriptionKey: 'onboarding.mod_funding_desc', group: 'finance' },
  { key: 'procurement', labelKey: 'procurement.title', descriptionKey: 'onboarding.mod_procurement_desc', group: 'finance' },
  { key: 'tendering', labelKey: 'tendering.title', descriptionKey: 'onboarding.mod_tendering_desc', group: 'finance' },
  { key: 'changeorders', labelKey: 'nav.change_orders', descriptionKey: 'onboarding.mod_changeorders_desc', group: 'finance' },
  { key: 'cvr', labelKey: 'nav.cvr', descriptionKey: 'onboarding.mod_cvr_desc', group: 'finance' },

  // ── Commercial / Sales ──────────────────────────────────────────────
  { key: 'bid_management', labelKey: 'onboarding.mod_bid_management', descriptionKey: 'onboarding.mod_bid_management_desc', group: 'commercial' },
  { key: 'contracts', labelKey: 'onboarding.mod_contracts', descriptionKey: 'onboarding.mod_contracts_desc', group: 'commercial' },
  { key: 'variations', labelKey: 'onboarding.mod_variations', descriptionKey: 'onboarding.mod_variations_desc', group: 'commercial' },
  { key: 'crm', labelKey: 'onboarding.mod_crm', descriptionKey: 'onboarding.mod_crm_desc', group: 'commercial' },
  { key: 'supplier_catalogs', labelKey: 'onboarding.mod_supplier_catalogs', descriptionKey: 'onboarding.mod_supplier_catalogs_desc', group: 'commercial' },
  { key: 'property_dev', labelKey: 'onboarding.mod_property_dev', descriptionKey: 'onboarding.mod_property_dev_desc', group: 'commercial' },
  { key: 'moc', labelKey: 'moc.title', descriptionKey: 'onboarding.mod_moc_desc', group: 'commercial' },
  { key: 'accommodation', labelKey: 'nav.accommodation', descriptionKey: 'onboarding.mod_accommodation_desc', group: 'commercial' },

  // ── Operations ───────────────────────────────────────────────────────
  { key: 'service', labelKey: 'onboarding.mod_service', descriptionKey: 'onboarding.mod_service_desc', group: 'operations' },
  { key: 'equipment', labelKey: 'onboarding.mod_equipment', descriptionKey: 'onboarding.mod_equipment_desc', group: 'operations' },
  { key: 'resources', labelKey: 'onboarding.mod_resources', descriptionKey: 'onboarding.mod_resources_desc', group: 'operations' },
  { key: 'daily_diary', labelKey: 'onboarding.mod_daily_diary', descriptionKey: 'onboarding.mod_daily_diary_desc', group: 'operations' },
  { key: 'subcontractors', labelKey: 'onboarding.mod_subcontractors', descriptionKey: 'onboarding.mod_subcontractors_desc', group: 'operations' },
  { key: 'portal', labelKey: 'onboarding.mod_portal', descriptionKey: 'onboarding.mod_portal_desc', group: 'operations' },
  { key: 'prefab', labelKey: 'nav.prefab', descriptionKey: 'onboarding.mod_prefab_desc', group: 'operations' },
  { key: 'site_logistics', labelKey: 'nav.site_logistics', descriptionKey: 'onboarding.mod_site_logistics_desc', group: 'operations' },
  { key: 'assets', labelKey: 'nav.assets', descriptionKey: 'onboarding.mod_assets_desc', group: 'operations' },

  // ── Communication ────────────────────────────────────────────────────
  { key: 'meetings', labelKey: 'meetings.title', descriptionKey: 'onboarding.mod_meetings_desc', group: 'communication' },
  { key: 'rfi', labelKey: 'rfi.title', descriptionKey: 'onboarding.mod_rfi_desc', group: 'communication' },
  { key: 'submittals', labelKey: 'submittals.title', descriptionKey: 'onboarding.mod_submittals_desc', group: 'communication' },
  { key: 'transmittals', labelKey: 'transmittals.title', descriptionKey: 'onboarding.mod_transmittals_desc', group: 'communication' },
  { key: 'correspondence', labelKey: 'correspondence.title', descriptionKey: 'onboarding.mod_correspondence_desc', group: 'communication' },
  { key: 'notifications', labelKey: 'onboarding.mod_notifications', descriptionKey: 'onboarding.mod_notifications_desc', group: 'communication', core: true },

  // ── Documents ────────────────────────────────────────────────────────
  { key: 'documents', labelKey: 'nav.documents', descriptionKey: 'onboarding.mod_documents_desc', group: 'documents' },
  { key: 'cde', labelKey: 'cde.title', descriptionKey: 'onboarding.mod_cde_desc', group: 'documents' },
  { key: 'markups', labelKey: 'nav.markups', descriptionKey: 'onboarding.mod_markups_desc', group: 'documents' },

  // ── Quality & Safety ─────────────────────────────────────────────────
  { key: 'inspections', labelKey: 'inspections.title', descriptionKey: 'onboarding.mod_inspections_desc', group: 'quality' },
  { key: 'ncr', labelKey: 'ncr.title', descriptionKey: 'onboarding.mod_ncr_desc', group: 'quality' },
  { key: 'safety', labelKey: 'safety.title', descriptionKey: 'onboarding.mod_safety_desc', group: 'quality' },
  { key: 'punchlist', labelKey: 'nav.punchlist', descriptionKey: 'onboarding.mod_punchlist_desc', group: 'quality' },
  { key: 'risk', labelKey: 'nav.risk_register', descriptionKey: 'onboarding.mod_risks_desc', group: 'quality' },
  { key: 'hse_advanced', labelKey: 'onboarding.mod_hse_advanced', descriptionKey: 'onboarding.mod_hse_advanced_desc', group: 'quality' },
  { key: 'construction_control', labelKey: 'construction_control.title', descriptionKey: 'onboarding.mod_construction_control_desc', group: 'quality' },
  { key: 'commissioning', labelKey: 'nav.commissioning', descriptionKey: 'onboarding.mod_commissioning_desc', group: 'quality' },
  { key: 'closeout', labelKey: 'closeout.title', descriptionKey: 'onboarding.mod_closeout_desc', group: 'quality' },
  { key: 'forms', labelKey: 'nav.forms', descriptionKey: 'onboarding.mod_forms_desc', group: 'quality' },

  // ── QMS & Compliance ────────────────────────────────────────────────
  { key: 'qms', labelKey: 'onboarding.mod_qms', descriptionKey: 'onboarding.mod_qms_desc', group: 'qms_compliance' },
  { key: 'compliance', labelKey: 'onboarding.mod_compliance', descriptionKey: 'onboarding.mod_compliance_desc', group: 'qms_compliance' },
  { key: 'compliance_docs', labelKey: 'onboarding.mod_compliance_docs', descriptionKey: 'onboarding.mod_compliance_docs_desc', group: 'qms_compliance' },
  { key: 'requirements', labelKey: 'nav.requirements', descriptionKey: 'onboarding.mod_requirements_desc', group: 'qms_compliance' },

  // ── Field ────────────────────────────────────────────────────────────
  { key: 'fieldreports', labelKey: 'nav.field_reports', descriptionKey: 'onboarding.mod_field_reports_desc', group: 'field' },
  { key: 'collaboration', labelKey: 'nav.collaboration', descriptionKey: 'onboarding.mod_collaboration_desc', group: 'field' },
  { key: 'field_diary', labelKey: 'onboarding.mod_field_diary', descriptionKey: 'onboarding.mod_field_diary_desc', group: 'field' },
  { key: 'payroll', labelKey: 'nav.payroll', descriptionKey: 'onboarding.mod_payroll_desc', group: 'field' },
  { key: 'field_time', labelKey: 'nav.field_time', descriptionKey: 'onboarding.mod_field_time_desc', group: 'field' },

  // ── Sustainability / ESG ────────────────────────────────────────────
  { key: 'carbon', labelKey: 'onboarding.mod_carbon', descriptionKey: 'onboarding.mod_carbon_desc', group: 'sustainability_esg' },
  { key: 'sustainability', labelKey: 'nav.sustainability', descriptionKey: 'onboarding.mod_sustainability_desc', group: 'sustainability_esg' },
  { key: 'esg', labelKey: 'nav.esg', descriptionKey: 'onboarding.mod_esg_desc', group: 'sustainability_esg' },

  // ── BI & Analytics ──────────────────────────────────────────────────
  { key: 'bi_dashboards', labelKey: 'onboarding.mod_bi_dashboards', descriptionKey: 'onboarding.mod_bi_dashboards_desc', group: 'bi_analytics' },
  { key: 'reporting', labelKey: 'nav.reporting', descriptionKey: 'onboarding.mod_reporting_desc', group: 'bi_analytics' },
  { key: 'project_controls', labelKey: 'nav.project_controls', descriptionKey: 'onboarding.mod_project_controls_desc', group: 'bi_analytics' },

  // ── Enterprise ──────────────────────────────────────────────────────
  { key: 'enterprise_workflows', labelKey: 'onboarding.mod_enterprise_workflows', descriptionKey: 'onboarding.mod_enterprise_workflows_desc', group: 'enterprise' },
  { key: 'full_evm', labelKey: 'onboarding.mod_full_evm', descriptionKey: 'onboarding.mod_full_evm_desc', group: 'enterprise' },
  { key: 'rfq_bidding', labelKey: 'onboarding.mod_rfq_bidding', descriptionKey: 'onboarding.mod_rfq_bidding_desc', group: 'enterprise' },
  { key: 'integrations', labelKey: 'onboarding.mod_integrations', descriptionKey: 'onboarding.mod_integrations_desc', group: 'enterprise' },

  // ── Regional Packs ──────────────────────────────────────────────────
  { key: 'dach_pack', labelKey: 'onboarding.mod_dach_pack', descriptionKey: 'onboarding.mod_dach_pack_desc', group: 'regional' },
  { key: 'uk_pack', labelKey: 'onboarding.mod_uk_pack', descriptionKey: 'onboarding.mod_uk_pack_desc', group: 'regional' },
  { key: 'us_pack', labelKey: 'onboarding.mod_us_pack', descriptionKey: 'onboarding.mod_us_pack_desc', group: 'regional' },
  { key: 'us_tx_pack', labelKey: 'onboarding.mod_us_tx_pack', descriptionKey: 'onboarding.mod_us_tx_pack_desc', group: 'regional' },
  { key: 'us_ca_pack', labelKey: 'onboarding.mod_us_ca_pack', descriptionKey: 'onboarding.mod_us_ca_pack_desc', group: 'regional' },
  { key: 'india_pack', labelKey: 'onboarding.mod_india_pack', descriptionKey: 'onboarding.mod_india_pack_desc', group: 'regional' },
  { key: 'middle_east_pack', labelKey: 'onboarding.mod_middle_east_pack', descriptionKey: 'onboarding.mod_middle_east_pack_desc', group: 'regional' },
  { key: 'latam_pack', labelKey: 'onboarding.mod_latam_pack', descriptionKey: 'onboarding.mod_latam_pack_desc', group: 'regional' },
  { key: 'asia_pac_pack', labelKey: 'onboarding.mod_asia_pac_pack', descriptionKey: 'onboarding.mod_asia_pac_pack_desc', group: 'regional' },
  { key: 'russia_pack', labelKey: 'onboarding.mod_russia_pack', descriptionKey: 'onboarding.mod_russia_pack_desc', group: 'regional' },

  // ── Platform (infrastructure — always on) ───────────────────────────
  { key: 'users', labelKey: 'onboarding.mod_users', descriptionKey: 'onboarding.mod_users_desc', group: 'platform', core: true },
  { key: 'teams', labelKey: 'onboarding.mod_teams', descriptionKey: 'onboarding.mod_teams_desc', group: 'platform', core: true },
  { key: 'uploads', labelKey: 'onboarding.mod_uploads', descriptionKey: 'onboarding.mod_uploads_desc', group: 'platform', core: true },
  { key: 'jobs', labelKey: 'onboarding.mod_jobs', descriptionKey: 'onboarding.mod_jobs_desc', group: 'platform', core: true },
  { key: 'search', labelKey: 'onboarding.mod_search', descriptionKey: 'onboarding.mod_search_desc', group: 'platform', core: true },
  { key: 'backup', labelKey: 'onboarding.mod_backup', descriptionKey: 'onboarding.mod_backup_desc', group: 'platform', core: true },
  { key: 'admin', labelKey: 'onboarding.mod_admin', descriptionKey: 'onboarding.mod_admin_desc', group: 'platform', core: true },
  { key: 'i18n_foundation', labelKey: 'onboarding.mod_i18n_foundation', descriptionKey: 'onboarding.mod_i18n_foundation_desc', group: 'platform', core: true },
  { key: 'collaboration_locks', labelKey: 'onboarding.mod_collaboration_locks', descriptionKey: 'onboarding.mod_collaboration_locks_desc', group: 'platform', core: true },
  { key: 'architecture_map', labelKey: 'onboarding.mod_architecture_map', descriptionKey: 'onboarding.mod_architecture_map_desc', group: 'platform', core: true },

  // ── Estimation (extended) ────────────────────────────────────────────
  { key: 'allowances', labelKey: 'onboarding.mod_allowances', descriptionKey: 'onboarding.mod_allowances_desc', group: 'estimation' },
  { key: 'cost_explorer', labelKey: 'onboarding.mod_cost_explorer', descriptionKey: 'onboarding.mod_cost_explorer_desc', group: 'estimation' },
  { key: 'estimate_basis', labelKey: 'onboarding.mod_estimate_basis', descriptionKey: 'onboarding.mod_estimate_basis_desc', group: 'estimation' },
  { key: 'estimate_rollup', labelKey: 'onboarding.mod_estimate_rollup', descriptionKey: 'onboarding.mod_estimate_rollup_desc', group: 'estimation' },
  { key: 'formwork', labelKey: 'onboarding.mod_formwork', descriptionKey: 'onboarding.mod_formwork_desc', group: 'estimation' },
  { key: 'labor_rates', labelKey: 'onboarding.mod_labor_rates', descriptionKey: 'onboarding.mod_labor_rates_desc', group: 'estimation' },
  { key: 'methodology', labelKey: 'onboarding.mod_methodology', descriptionKey: 'onboarding.mod_methodology_desc', group: 'estimation' },
  { key: 'norm_expansion', labelKey: 'onboarding.mod_norm_expansion', descriptionKey: 'onboarding.mod_norm_expansion_desc', group: 'estimation' },
  { key: 'preliminaries', labelKey: 'onboarding.mod_preliminaries', descriptionKey: 'onboarding.mod_preliminaries_desc', group: 'estimation' },
  { key: 'rom_estimate', labelKey: 'onboarding.mod_rom_estimate', descriptionKey: 'onboarding.mod_rom_estimate_desc', group: 'estimation' },
  { key: 'waste_factors', labelKey: 'onboarding.mod_waste_factors', descriptionKey: 'onboarding.mod_waste_factors_desc', group: 'estimation' },

  // ── BIM Advanced (extended) ──────────────────────────────────────────
  { key: 'bcf', labelKey: 'onboarding.mod_bcf', descriptionKey: 'onboarding.mod_bcf_desc', group: 'bim_advanced' },
  { key: 'bimlv', labelKey: 'onboarding.mod_bimlv', descriptionKey: 'onboarding.mod_bimlv_desc', group: 'bim_advanced' },
  { key: 'clash_ai_triage', labelKey: 'onboarding.mod_clash_ai_triage', descriptionKey: 'onboarding.mod_clash_ai_triage_desc', group: 'bim_advanced' },
  { key: 'clash_cost_impact', labelKey: 'onboarding.mod_clash_cost_impact', descriptionKey: 'onboarding.mod_clash_cost_impact_desc', group: 'bim_advanced' },

  // ── AI (extended) ────────────────────────────────────────────────────
  { key: 'ai_estimator', labelKey: 'onboarding.mod_ai_estimator', descriptionKey: 'onboarding.mod_ai_estimator_desc', group: 'ai' },
  { key: 'voice', labelKey: 'onboarding.mod_voice', descriptionKey: 'onboarding.mod_voice_desc', group: 'ai' },

  // ── Planning (extended) ──────────────────────────────────────────────
  { key: 'interface_management', labelKey: 'onboarding.mod_interface_management', descriptionKey: 'onboarding.mod_interface_management_desc', group: 'planning' },
  { key: 'progress', labelKey: 'onboarding.mod_progress', descriptionKey: 'onboarding.mod_progress_desc', group: 'planning' },
  { key: 'timeline', labelKey: 'onboarding.mod_timeline', descriptionKey: 'onboarding.mod_timeline_desc', group: 'planning' },

  // ── Finance (extended) ───────────────────────────────────────────────
  { key: 'fx', labelKey: 'onboarding.mod_fx', descriptionKey: 'onboarding.mod_fx_desc', group: 'finance' },
  { key: 'postcalc', labelKey: 'onboarding.mod_postcalc', descriptionKey: 'onboarding.mod_postcalc_desc', group: 'finance' },
  { key: 'price_index', labelKey: 'onboarding.mod_price_index', descriptionKey: 'onboarding.mod_price_index_desc', group: 'finance' },
  { key: 'reconciliation', labelKey: 'onboarding.mod_reconciliation', descriptionKey: 'onboarding.mod_reconciliation_desc', group: 'finance' },

  // ── Commercial (extended) ────────────────────────────────────────────
  { key: 'change_intelligence', labelKey: 'onboarding.mod_change_intelligence', descriptionKey: 'onboarding.mod_change_intelligence_desc', group: 'commercial' },
  { key: 'claims_evidence', labelKey: 'onboarding.mod_claims_evidence', descriptionKey: 'onboarding.mod_claims_evidence_desc', group: 'commercial' },
  { key: 'cost_recovery', labelKey: 'onboarding.mod_cost_recovery', descriptionKey: 'onboarding.mod_cost_recovery_desc', group: 'commercial' },
  { key: 'value', labelKey: 'onboarding.mod_value', descriptionKey: 'onboarding.mod_value_desc', group: 'commercial' },

  // ── Operations (extended) ────────────────────────────────────────────
  { key: 'approval_routes', labelKey: 'onboarding.mod_approval_routes', descriptionKey: 'onboarding.mod_approval_routes_desc', group: 'operations' },

  // ── Communication (extended) ─────────────────────────────────────────
  { key: 'phonelog', labelKey: 'onboarding.mod_phonelog', descriptionKey: 'onboarding.mod_phonelog_desc', group: 'communication' },

  // ── Documents (extended) ─────────────────────────────────────────────
  { key: 'plan_room', labelKey: 'onboarding.mod_plan_room', descriptionKey: 'onboarding.mod_plan_room_desc', group: 'documents' },
  { key: 'signing', labelKey: 'onboarding.mod_signing', descriptionKey: 'onboarding.mod_signing_desc', group: 'documents' },

  // ── Quality & Safety (extended) ──────────────────────────────────────
  { key: 'defects_liability', labelKey: 'onboarding.mod_defects_liability', descriptionKey: 'onboarding.mod_defects_liability_desc', group: 'quality' },

  // ── QMS & Compliance (extended) ──────────────────────────────────────
  { key: 'authority_submission', labelKey: 'onboarding.mod_authority_submission', descriptionKey: 'onboarding.mod_authority_submission_desc', group: 'qms_compliance' },

  // ── Field (extended) ─────────────────────────────────────────────────
  { key: 'site_inventory', labelKey: 'onboarding.mod_site_inventory', descriptionKey: 'onboarding.mod_site_inventory_desc', group: 'field' },
  { key: 'site_prep', labelKey: 'onboarding.mod_site_prep', descriptionKey: 'onboarding.mod_site_prep_desc', group: 'field' },
  { key: 'site_supervision', labelKey: 'onboarding.mod_site_supervision', descriptionKey: 'onboarding.mod_site_supervision_desc', group: 'field' },
  { key: 'temporary_works', labelKey: 'onboarding.mod_temporary_works', descriptionKey: 'onboarding.mod_temporary_works_desc', group: 'field' },

  // ── Regional Packs (extended) ────────────────────────────────────────
  { key: 'mexico_pack', labelKey: 'onboarding.mod_mexico_pack', descriptionKey: 'onboarding.mod_mexico_pack_desc', group: 'regional' },
  { key: 'sa_pack', labelKey: 'onboarding.mod_sa_pack', descriptionKey: 'onboarding.mod_sa_pack_desc', group: 'regional' },
  // backend/app/modules/china_pack has shipped since before this list was
  // written and was the only one of the thirteen regional modules with no
  // line here, so the picker offered twelve and China could not be chosen at
  // the one moment a new user is asked what they work on.
  { key: 'china_pack', labelKey: 'onboarding.mod_china_pack', descriptionKey: 'onboarding.mod_china_pack_desc', group: 'regional' },
  // The fourteenth regional module, and the last one that had no line here.
  // It does not carry the ``_pack`` suffix the other thirteen share, which is
  // why a sweep for the country packs kept missing it, so the gate that now
  // guards this list keys on the backend manifest's own ``category`` instead.
  { key: 'payment_clock', labelKey: 'onboarding.mod_payment_clock', descriptionKey: 'onboarding.mod_payment_clock_desc', group: 'regional' },
];

export const CORE_MODULE_KEYS = new Set(ALL_MODULES.filter((m) => m.core).map((m) => m.key));

/** Total count of modules surfaced in the wizard. Mirrors the 153 backend
 *  manifests in ``backend/app/modules/<mod>/manifest.py``. */
export const TOTAL_MODULE_COUNT = ALL_MODULES.length;
