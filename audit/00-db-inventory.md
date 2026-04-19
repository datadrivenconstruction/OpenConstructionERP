# 00 — Database Schema Inventory (OpenConstructionERP)

Generated: 2026-04-18 · Branch: `main` · Source: 46 `backend/app/modules/*/models.py`

## 1. Base class & conventions

**All models inherit from** `backend/app/database.py::Base` — a single `DeclarativeBase` that provides:

| Column | Type | Default |
|--------|------|---------|
| `id` | `GUID` (UUID, stored as String(36) on SQLite, UUID on PG) | `uuid.uuid4` |
| `created_at` | `DateTime(timezone=True)` | `func.now()` |
| `updated_at` | `DateTime(timezone=True)` | `func.now()` + `onupdate=func.now()` |

> **No dedicated mixins exist** (no `AuditMixin`, no `OrgMixin`, no `TimestampMixin`, no `TenantMixin`). Audit fields are part of `Base` itself, and tenant scoping is **ad-hoc per-table** — see anomalies.

Table naming convention (enforced per `backend/CLAUDE.md`): `oe_{module}_{entity}`.

Constraint naming convention (auto-generated via `MetaData.naming_convention`):
`ix_%(column_0_label)s` · `uq_%(table_name)s_%(column_0_name)s` · `ck_%(table_name)s_%(constraint_name)s` · `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s` · `pk_%(table_name)s`.

---

## 2. Table list (86 tables total across 37 modules)

### Projects & WBS (3)
- `oe_projects_project` — name, description, region, classification_standard, currency, locale, validation_rule_sets(JSON), status, owner_id→users, parent_project_id→self, address(JSON), custom_fields(JSON), metadata_(JSON)
- `oe_projects_wbs` — project_id→projects, parent_id→self, code, name, level, sort_order, wbs_type, planned_cost(str), planned_hours(str)
- `oe_projects_milestone` — project_id→projects, name, milestone_type, planned_date, actual_date, status, linked_payment_pct

### BOQ (5)
- `oe_boq_boq` — project_id→projects, name, status, estimate_type, is_locked, parent_estimate_id→self
- `oe_boq_position` — boq_id→boq, parent_id→self, ordinal, description, unit, quantity(str), unit_rate(str), total(str), classification(JSON), source, confidence(str), cad_element_ids(JSON), validation_status, wbs_id(str), cost_code_id(str)
- `oe_boq_markup` — boq_id→boq, name, markup_type, category, percentage(str), fixed_amount(str), apply_to
- `oe_boq_activity_log` — project_id→projects, boq_id→boq, user_id→users, action, target_type, target_id, changes(JSON); composite indexes `(user_id, created_at)`, `(target_type, target_id)`
- `oe_boq_snapshot` — boq_id→boq, name, snapshot_data(JSON), created_by→users

### Costs / Catalog / Assemblies (4)
- `oe_costs_item` — code, description, descriptions(JSON), unit, rate(str), currency, source, classification(JSON), components(JSON), region; unique(code, region); index(source, region), index(is_active)
- `oe_catalog_resource` — resource_code, name, resource_type(idx), category(idx), unit, base_price(str), min_price(str), max_price(str), usage_count, source, region
- `oe_assemblies_assembly` — code(unique), name, unit, category, classification(JSON), total_rate(str), bid_factor(str), regional_factors(JSON), is_template, project_id→projects, owner_id
- `oe_assemblies_component` — assembly_id→assembly, cost_item_id→costs_item, catalog_resource_id→catalog_resource, description, factor(str), quantity(str), unit, unit_cost(str)

### Documents / Takeoff / Markups / DWG (13)
- `oe_documents_document` — project_id→projects, name, category, file_size, mime_type, file_path, version, cde_state, suitability_code, revision_code, parent_document_id→self, discipline
- `oe_documents_photo` — project_id→projects, gps_lat/lon(Float), taken_at, category
- `oe_documents_sheet` — project_id→projects, page_number, sheet_number, discipline
- `oe_documents_bim_link` — document_id→document, bim_element_id→bim_element; unique(document_id, bim_element_id)
- `oe_takeoff_cad_session` — session_id(unique), filename, file_format, element_count, elements_data(JSON), expires_at, bim_model_id(str)
- `oe_takeoff_document` — project_id→projects, owner_id→users, file_path, extracted_text, page_data(JSON), analysis(JSON)
- `oe_takeoff_measurement` — project_id→projects, document_id(str), page, type, points(JSON), measurement_value(Float), depth(Float), volume(Float), scale_pixels_per_unit(Float)
- `oe_markups_markup` — project_id→projects, document_id(str), page, type, geometry(JSON), color, stamp_template_id→stamp_template, linked_boq_position_id(str), layer
- `oe_markups_scale_config` — document_id(str), page, pixels_per_unit(Float), real_distance(Float)
- `oe_markups_stamp_template` — project_id→projects, owner_id(str), name, text, color
- `oe_dwg_takeoff_drawing` — project_id→projects, name, file_format, file_path, status, thumbnail_key; idx(project_id, status)
- `oe_dwg_takeoff_drawing_version` — drawing_id→drawing, version_number, layers(JSON), entities_key(str), extents(JSON)
- `oe_dwg_takeoff_annotation` — project_id→projects, drawing_id→drawing, drawing_version_id→version, annotation_type, geometry(JSON), thickness(Float), layer_name; idx(drawing_id, annotation_type), idx(linked_task_id), idx(linked_punch_item_id)
- `oe_dwg_entity_group` — drawing_id→drawing, name, entity_ids(JSON); idx(drawing_id)

### BIM Hub / BIM Requirements (7)
- `oe_bim_model` — project_id, name, discipline, model_format, version, status, element_count, bounding_box(JSON), parent_model_id→self
- `oe_bim_element` — model_id→model, stable_id, element_type(idx), storey(idx), discipline(idx), properties(JSON), quantities(JSON), geometry_hash; idx(model_id, stable_id)
- `oe_bim_boq_link` — boq_position_id(uuid, no FK), bim_element_id→bim_element; unique(boq_position_id, bim_element_id)
- `oe_bim_quantity_map` — org_id(uuid, no FK), project_id(uuid, no FK), name, element_type_filter, property_filter(JSON), quantity_source, multiplier(str), unit, waste_factor_pct(str), boq_target(JSON)
- `oe_bim_model_diff` — old_model_id→model, new_model_id→model; unique(old, new)
- `oe_bim_element_group` — project_id(uuid, no FK), model_id→model, name, filter_criteria(JSON), element_ids(JSON), color; unique(project_id, name); idx(project_id)
- `oe_bim_requirement_set` + `oe_bim_requirement` — per-project requirement collections with 5-column universal model (element_filter, property_group, property_name, constraint_def, context)

### Users / Teams / Contacts / Collaboration (8)
- `oe_users_user` — email(unique), hashed_password, full_name, role, locale, last_login_at, password_changed_at, timezone, measurement_system, paper_size, number_format, date_format, currency_code
- `oe_users_api_key` — user_id→user, key_hash(unique), key_prefix, permissions(JSON), expires_at
- `oe_teams_team` — project_id(uuid, no FK), name, sort_order, is_default
- `oe_teams_membership` — team_id→team, user_id→user; unique(team_id, user_id)
- `oe_teams_visibility` — entity_type, entity_id, team_id→team; unique(entity_type, entity_id, team_id); idx(entity_type, entity_id)
- `oe_contacts_contact` — contact_type, is_platform_user, user_id→user (SET NULL), company_name, primary_email(idx), country_code, payment_terms_days
- `oe_collaboration_comment` — entity_type(idx), entity_id(idx), author_id→user, parent_comment_id→self, text, comment_type; idx(entity_type, entity_id)
- `oe_collaboration_mention` — comment_id→comment, mentioned_user_id(uuid, no FK), mention_type
- `oe_collaboration_viewpoint` — entity_type(idx), entity_id(idx), viewpoint_type, data(JSON), created_by(uuid), comment_id→comment (SET NULL)
- `oe_collab_lock` — org_id(uuid, nullable), entity_type, entity_id, user_id→user, locked_at, heartbeat_at, expires_at; unique(entity_type, entity_id); idx(expires_at), idx(user_id), idx(entity_type, entity_id)

### i18n Foundation (4)
- `oe_i18n_exchange_rate` — from_currency, to_currency, rate(str), rate_date; unique(from, to, rate_date)
- `oe_i18n_country` — iso_code(unique), iso_code_3, name_en, name_translations(JSON), currency_default, measurement_default, phone_code, region_group
- `oe_i18n_work_calendar` — country_code(idx), year, work_hours_per_day(str), work_days(JSON), exceptions(JSON); unique(country_code, year)
- `oe_i18n_tax_config` — country_code(idx), tax_name, rate_pct(str), tax_type, effective_from, effective_to; idx(country_code, tax_type)

### Construction Ops (12)
- `oe_rfi_rfi` — project_id→projects, rfi_number, subject, question, raised_by(uuid), assigned_to(uuid), status(idx), cost_impact(bool), schedule_impact(bool), linked_drawing_ids(JSON), change_order_id(str)
- `oe_punchlist_item` — project_id→projects, document_id(str), page, location_x/y(Float), title, priority, status(idx), due_date(DT), assigned_to(str), photos(JSON)
- `oe_submittals_submittal` — project_id→projects, submittal_number, title, submittal_type, status(idx), ball_in_court(uuid), reviewer_id(uuid), approver_id(uuid), linked_boq_item_ids(JSON)
- `oe_ncr_ncr` — project_id→projects, ncr_number, title, ncr_type, severity, root_cause, corrective_action, preventive_action, status(idx), cost_impact(str)
- `oe_correspondence_correspondence` — project_id→projects, reference_number, direction(idx), subject, from_contact_id(str), to_contact_ids(JSON), linked_document_ids(JSON), linked_rfi_id(str)
- `oe_changeorders_order` — project_id→projects, code, title, reason_category, status(idx), cost_impact(str), schedule_impact_days, variation_type, approved_amount(str)
- `oe_changeorders_item` — change_order_id→order, description, change_type, original_quantity(str), new_quantity(str), cost_delta(str)
- `oe_inspections_inspection` — project_id→projects, inspection_number, inspection_type, title, inspector_id(uuid), status(idx), result, checklist_data(JSON)
- `oe_fieldreports_report` — project_id→projects, report_date(Date, idx), report_type, weather_condition, temperature_c(Float), workforce(JSON), equipment_on_site(JSON), work_performed, delays, delay_hours(Float), photos(JSON), status(idx), signature_data, document_ids(JSON)
- `oe_fieldreports_workforce` — field_report_id→report, worker_type, headcount, hours_worked(str), overtime_hours(str)
- `oe_fieldreports_equipment` — field_report_id→report, equipment_description, hours_operational(str), hours_standby(str), hours_breakdown(str)
- `oe_safety_incident` — project_id→projects, incident_number, incident_date, incident_type, severity, description, injured_person_details(JSON), days_lost, corrective_actions(JSON), reported_to_regulator, status(idx)
- `oe_safety_observation` — project_id→projects, observation_number, observation_type, severity, likelihood, risk_score, status(idx)

### Risk / Meetings / Tasks / Requirements (6)
- `oe_risk_register` — project_id→projects, code, title, category, probability(str), impact_cost(str), impact_schedule_days, impact_severity, risk_score(str), status(idx), mitigation_strategy, risk_tier, mitigation_actions(JSON)
- `oe_meetings_meeting` — project_id→projects, meeting_number, meeting_type, title, meeting_date, attendees(JSON), agenda_items(JSON), action_items(JSON), minutes, status(idx), document_ids(JSON)
- `oe_tasks_task` — project_id→projects, task_type, title, checklist(JSON), responsible_id(uuid, idx), persons_involved(JSON), bim_element_ids(JSON), due_date, status(idx), priority, depends_on→self (SET NULL); idx(project_id, status), idx(responsible_id, status)
- `oe_requirements_set` — project_id→projects, name, source_type, status, gate_status(JSON)
- `oe_requirements_item` — requirement_set_id→set, entity, attribute, constraint_type, constraint_value, priority, linked_position_id→boq_position (SET NULL)
- `oe_requirements_gate_result` — requirement_set_id→set, gate_number, gate_name, status, score(Float), findings(JSON)

### Finance / Cost Model / EVM (9)
- `oe_finance_invoice` — project_id(uuid, no FK), contact_id(str), invoice_direction(idx), invoice_number, invoice_date, amount_total(str), status(idx), tax_config_id(str); idx(project_id, invoice_direction), idx(project_id, status)
- `oe_finance_invoice_item` — invoice_id→invoice, description, quantity(str), unit_rate(str), amount(str)
- `oe_finance_payment` — invoice_id→invoice, payment_date, amount(str), exchange_rate_snapshot(str)
- `oe_finance_budget` — project_id(uuid, no FK), wbs_id(str), category, original_budget(str), committed(str), actual(str); unique(project_id, wbs_id, category)
- `oe_finance_evm_snapshot` — project_id(uuid, no FK), snapshot_date, bac/pv/ev/ac(str), spi/cpi(str), eac/vac/etc/tcpi(str)
- `oe_costmodel_snapshot` — project_id→projects, period, planned_cost(str), earned_value(str), actual_cost(str), spi(str), cpi(str)
- `oe_costmodel_budget_line` — project_id→projects, boq_position_id(uuid, no FK), activity_id(uuid, no FK), category(idx), planned_amount(str), committed_amount(str)
- `oe_costmodel_cash_flow` — project_id→projects, period, planned_inflow/outflow(str), actual_inflow/outflow(str), cumulative_planned/actual(str)
- `oe_evm_forecast` — project_id(uuid, no FK), forecast_date, etc(str), eac(str), vac(str), tcpi(str), forecast_method

### Procurement / RFQ / Tendering (6)
- `oe_procurement_po` — project_id(uuid, no FK), vendor_contact_id(str), po_number, po_type, amount_total(str), status(idx)
- `oe_procurement_po_item` — po_id→po, description, quantity(str), unit_rate(str), amount(str)
- `oe_procurement_goods_receipt` — po_id→po, receipt_date, received_by_id(uuid, no FK), status(idx)
- `oe_procurement_gr_item` — receipt_id→goods_receipt, po_item_id→po_item (SET NULL), quantity_ordered(str), quantity_received(str), quantity_rejected(str)
- `oe_rfq_rfq` — project_id(uuid, no FK), rfq_number, title, status(idx), issued_to_contacts(JSON)
- `oe_rfq_bid` — rfq_id→rfq, bidder_contact_id(str), bid_amount(str), is_awarded(bool)
- `oe_tendering_package` — project_id(uuid, no FK), boq_id(uuid, no FK), name, status(idx), deadline
- `oe_tendering_bid` — package_id→package, company_name, contact_email, total_amount(str), line_items(JSON)

### Schedule & CPM (6)
- `oe_schedule_schedule` — project_id→projects, name, schedule_type, status, data_date
- `oe_schedule_activity` — schedule_id→schedule, parent_id→self, name, wbs_code, start_date, end_date, duration_days, progress_pct(str), status(idx), dependencies(JSON), resources(JSON), boq_position_ids(JSON), early_start/finish, late_start/finish, total_float, free_float, is_critical, bim_element_ids(JSON)
- `oe_schedule_work_order` — activity_id→activity, assembly_id(uuid, no FK), boq_position_id(uuid, no FK), code, planned_cost(str), actual_cost(str)
- `oe_schedule_relationship` — schedule_id→schedule, predecessor_id→activity, successor_id→activity, relationship_type, lag_days; unique(predecessor_id, successor_id)
- `oe_schedule_baseline` — project_id(uuid, no FK), schedule_id(uuid, no FK), name, baseline_date, snapshot_data(JSON), is_active
- `oe_schedule_progress` — project_id(uuid, no FK), activity_id(uuid, no FK), update_date, progress_pct(str), status

### CDE / Transmittals (6)
- `oe_cde_container` — project_id→projects, container_code, originator_code, cde_state(idx), suitability_code, title
- `oe_cde_revision` — container_id→container, revision_code, revision_number, content_hash, file_name, storage_key, status, approved_by(uuid), document_id(str, cross-link)
- `oe_cde_state_transition` — container_id→container, from_state, to_state, gate_code, user_id(str), user_role, transitioned_at (own DateTime column, server-default now())
- `oe_transmittals_transmittal` — project_id(uuid, no FK), transmittal_number, subject, sender_org_id(uuid, no FK), purpose_code, status(idx), is_locked
- `oe_transmittals_recipient` — transmittal_id→transmittal, recipient_org_id(uuid, no FK), recipient_user_id(uuid, no FK), acknowledged_at(DT), responded_at(DT)
- `oe_transmittals_item` — transmittal_id→transmittal, document_id(uuid, no FK), revision_id(uuid, no FK, idx), item_number

### Enterprise Workflows / Integrations / Notifications / AI / Chat / Reporting / Validation (15)
- `oe_workflows_approval` — project_id(uuid, no FK, idx), entity_type, name, steps(JSON)
- `oe_workflows_request` — workflow_id→workflow, entity_type(idx), entity_id(idx), current_step, status(idx), requested_by(uuid, idx), decided_by(uuid)
- `oe_integrations_webhook` — user_id→user, project_id→projects, url, secret, events(JSON); idx(user_id, is_active)
- `oe_integrations_delivery` — webhook_id→webhook, event_type, payload(JSON), status_code, duration_ms; idx(webhook_id, created_at)
- `oe_integrations_config` — user_id→user, project_id(uuid, no FK, idx), integration_type(idx), config(JSON), events(JSON); idx(user_id, is_active), idx(user_id, integration_type)
- `oe_notifications_notification` — user_id→user, notification_type(idx), entity_type, entity_id, title_key, body_key, body_context(JSON), is_read(idx); idx(user_id, is_read), idx(user_id, created_at)
- `oe_ai_settings` — user_id(uuid, no FK, unique), 17 × provider_api_key(str 500), preferred_model
- `oe_ai_estimate_job` — user_id(uuid, no FK, idx), project_id(uuid, no FK, idx), input_type, input_text, status, result(JSON), tokens_used
- `oe_erp_chat_session` — user_id(uuid, no FK, idx), project_id(uuid, no FK, idx), title
- `oe_erp_chat_message` — session_id→session, role, content(Text), tool_calls(JSON), tool_results(JSON), renderer_data(JSON)
- `oe_reporting_kpi_snapshot` — project_id(uuid, no FK, idx), snapshot_date, cpi(str), spi(str), open_defects, open_rfis; unique(project_id, snapshot_date)
- `oe_reporting_template` — name, report_type, template_data(JSON), is_system, created_by(uuid, no FK)
- `oe_reporting_generated` — project_id(uuid, no FK, idx), template_id(uuid, no FK), report_type, title, storage_key, data_snapshot(JSON)
- `oe_validation_report` — project_id(uuid, no FK, idx), target_type(idx), target_id(str, idx), rule_set, status(idx), score(str), passed/warning/error_count, results(JSON); idx(target_type, target_id)

**Module `architecture_map`**: no DB models (read-only from JSON).

---

## 3. Foreign-key graph (cross-module edges)

**Total hard FKs**: 89 (enforced `ForeignKey(...)`). **Total soft-FKs**: ~55 (stored as `GUID`/`String(36)` without constraint).

### Hub: `oe_projects_project` (25 inbound hard FKs)
BOQ(`oe_boq_boq`, `oe_boq_activity_log`), Assembly, Documents(document, photo, sheet), Takeoff(document, measurement), DWG(drawing, annotation), Markups(markup, stamp_template), BIM requirements, RFI, Punchlist, Submittal, NCR, Correspondence, ChangeOrder, Inspection, FieldReport, SafetyIncident, SafetyObservation, RiskItem, Meeting, Task, RequirementSet, CDE container, Schedule, Integrations(webhook), projects(self — `parent_project_id`).

**Missing hard FKs on project_id** (stored as `GUID`/`uuid` only — should be FK): `oe_teams_team`, `oe_bim_model`, `oe_bim_element_group`, `oe_bim_quantity_map`, `oe_validation_report`, `oe_ai_estimate_job`, `oe_erp_chat_session`, `oe_transmittals_transmittal`, `oe_rfq_rfq`, `oe_tendering_package`, `oe_procurement_po`, `oe_finance_invoice`, `oe_finance_budget`, `oe_finance_evm_snapshot`, `oe_costmodel_*` (some have FK), `oe_evm_forecast`, `oe_workflows_approval`, `oe_integrations_config` (project), `oe_reporting_*`, `oe_schedule_baseline`, `oe_schedule_progress`.

### Hub: `oe_users_user`
Hard FK from: `oe_users_api_key`, `oe_projects_project.owner_id`, `oe_boq_activity_log.user_id`, `oe_boq_snapshot.created_by`, `oe_takeoff_document.owner_id`, `oe_contacts_contact.user_id`, `oe_teams_membership.user_id`, `oe_collaboration_comment.author_id`, `oe_collab_lock.user_id`, `oe_notifications_notification.user_id`, `oe_integrations_webhook.user_id`, `oe_integrations_config.user_id`.

### Cross-module edges (the ones that matter)
- `oe_assemblies_component.cost_item_id` → `oe_costs_item.id`
- `oe_assemblies_component.catalog_resource_id` → `oe_catalog_resource.id`
- `oe_documents_bim_link` = bridge between `oe_documents_document` ↔ `oe_bim_element`
- `oe_requirements_item.linked_position_id` → `oe_boq_position.id` (SET NULL)
- `oe_markups_markup.stamp_template_id` → `oe_markups_stamp_template.id`
- `oe_dwg_takeoff_annotation.drawing_version_id` → `oe_dwg_takeoff_drawing_version.id`
- `oe_schedule_relationship.predecessor_id/successor_id` → `oe_schedule_activity.id`
- `oe_cde_revision.document_id` — cross-link to Documents hub as **soft** `String(36)` (documented comment: safe across PG/SQLite)
- `oe_bim_boq_link.boq_position_id` is **soft** — no FK to `oe_boq_position` (comment: cross-module decoupling)

### Self-referential hierarchies
- `oe_projects_project.parent_project_id` → self (SET NULL)
- `oe_projects_wbs.parent_id` → self (SET NULL)
- `oe_boq_boq.parent_estimate_id` → self (SET NULL)
- `oe_boq_position.parent_id` → self (SET NULL)
- `oe_documents_document.parent_document_id` → self (SET NULL)
- `oe_collaboration_comment.parent_comment_id` → self (CASCADE)
- `oe_schedule_activity.parent_id` → self (SET NULL)
- `oe_tasks_task.depends_on` → self (SET NULL)
- `oe_bim_model.parent_model_id` → self (SET NULL)

---

## 4. Mixin usage matrix

**There are no custom mixins**. Every model exclusively inherits from `Base`. The practical effect:

| Field provided by Base | Coverage |
|------|----------|
| `id` UUID PK | 100% (86/86 tables) |
| `created_at` | 100% |
| `updated_at` | 100% |
| `org_id` (multi-tenant) | **1%** (only `oe_collab_lock`, `oe_bim_quantity_map` — both nullable with no FK) |
| `created_by` audit | ~55% (ad-hoc — mostly `String(36)` without FK; some `GUID` without FK; only a handful are true FKs to users) |

---

## 5. Anomalies

### 5a. Multi-tenant bypass risk — **NO org_id on 84/86 tables**
The entire schema is effectively single-tenant. Only `oe_collab_lock` and `oe_bim_quantity_map` have a nullable `org_id` column, neither with a FK or NOT NULL. There is no `oe_organizations` / `oe_tenants` table at all. Isolation is currently done implicitly via `project_id`. **If multi-tenancy becomes a product requirement, every table needs `org_id` + RLS — this is a cross-cutting migration risk.**

### 5b. Audit-trail gaps — missing timestamps
**None found.** All 86 tables inherit `created_at` + `updated_at` from `Base`. However, `oe_cde_state_transition` defines its **own** `transitioned_at` column in addition (intentional — "who crossed which gate when").

### 5c. `created_by` — inconsistent typing (74 tables use it)
Three different patterns coexist:
- `GUID()` with `ForeignKey("oe_users_user.id")` — correct: `api_key`, `activity_log`, `boq_snapshot`, `takeoff.*`, `collab_lock`, `notifications`, `integrations.*`, a few more (~10 tables)
- `GUID()` without FK — soft reference: `rfq_rfq`, `schedule_schedule`, `schedule_baseline`, `transmittal`, `reporting_generated`, `finance_invoice` (~15 tables)
- `String(36)` — weakest (no FK, no type-level UUID check): ~40 tables: `rfi`, `punchlist`, `submittal`, `ncr`, `correspondence`, `changeorders`, `inspections`, `fieldreports`, `safety.*`, `meetings`, `tasks`, `requirements`, `documents.*`, `cde.*`, `ai.*`, etc.

### 5d. Decimal/money columns — **NO Numeric/Decimal anywhere**
Every monetary, quantity, and rate field is stored as `String(50)`. Grep confirms zero usage of `Numeric`, `Decimal`, or `DECIMAL` across all `models.py` files (only string comments reference "Decimal as string for SQLite compat"). Affected columns (non-exhaustive, ~220 occurrences):
- `quantity`, `unit_rate`, `total`, `percentage`, `fixed_amount` (BOQ)
- `rate`, `base_price`, `min_price`, `max_price`, `total_rate` (costs/catalog/assemblies)
- `bac`, `pv`, `ev`, `ac`, `spi`, `cpi`, `eac`, `vac`, `etc`, `tcpi` (EVM)
- `amount_total`, `tax_amount`, `retention_amount`, `exchange_rate_snapshot` (finance)
- `contract_value`, `budget_estimate`, `contingency_pct` (projects)
- `risk_score`, `probability`, `impact_cost` (risk)

**Precision/scale enforcement is entirely the application's responsibility.** No DB-side protection against corrupt/non-numeric values. Stated reason: SQLite compatibility.

### 5e. String columns — all bounded
No unbounded `String()` in use (`grep String,` = 0 hits). All columns specify a `max_length` — good. Largest seen: `String(1000)` (file_path, url).

### 5f. JSONB / JSON columns — schema drift candidates (~105 uses)
Every table carries a `metadata_` JSON (86 tables). Additional freeform JSON columns with no schema validation at the DB layer:
- `classification` (Position, CostItem, Assembly)
- `components`, `tags`, `cad_element_ids`, `bim_element_ids`, `entity_ids`, `layers`, `attendees`, `agenda_items`, `action_items`, `checklist`, `dependencies`, `resources`, `points`, `geometry`, `extents`, `snapshot_data`, `results`, `findings`, `filter_criteria`, `template_data`, `page_data`, `analysis`, `changes`, `workforce`, `equipment_on_site`, `photos`, `materials_used`, `tool_calls`, `tool_results`, `renderer_data`, `body_context`, `injured_person_details`, `corrective_actions`, `mitigation_actions`, `linked_*_ids` (6 variants), `to_contact_ids`, `document_ids`, `elements_data`, `columns_metadata`, `issued_to_contacts`, `line_items`, `checklist_data`, `specifications`, `regional_factors`, `custom_fields`, `address`, `name_translations`, `descriptions`, `name_en` translations, `payload`, `result`, `config`, `events`, `gate_status`, `steps`, `validation_rule_sets`, `bounding_box`, `lod_variants`, `property_filter`, `element_filter`, `constraint_def`, `context`, `boq_target`, `diff_summary`, `diff_details`, `weather_data`, `workforce_log`, `equipment_log`, `calibration_points`, `exceptions`, `work_days`, `address_format_template`, `tax_name_translations`.

**Risk**: Any producer change breaks consumers silently. No JSON schema validation at DB or ORM layer.

### 5g. Uses `JSON` not `JSONB` on PG
The `JSON` SQLAlchemy type is portable (string-encoded on PG, not binary JSONB). Tradeoff: no GIN index on JSON contents. If queries filter on JSON fields in PG (e.g. by `classification.din276`), there is no index-level support.

### 5h. Soft cross-module FKs (missing enforcement)
Several IDs are `GUID`/`String(36)` without a real FK (orphan-row risk on deletes):
- All `bim_*` project_id / org_id (no FK to projects)
- `finance_invoice.project_id`, `finance_invoice.contact_id`, `finance_budget.project_id`
- `tendering.project_id`, `rfq.project_id`, `procurement.project_id`
- `transmittals.project_id`, `transmittals.*.recipient_*_id`
- `bim_boq_link.boq_position_id` (intentional cross-module)
- All `created_by String(36)` references
- `wbs_id`, `cost_code_id`, `activity_id`, `milestone_id`, `meeting_id` on tasks/BOQ (all soft)
- `change_order_id`, `linked_rfi_id`, `linked_inspection_id` on NCR/correspondence/RFI
- `linked_boq_position_id`, `linked_task_id`, `linked_punch_item_id` on markups/annotations

### 5i. Inconsistent ondelete policies
Mixing `CASCADE`, `SET NULL`, and missing policies even for similar relationships — e.g. `Project.owner_id` is `CASCADE` (deleting a user deletes their projects — dangerous), while `Contact.user_id` is `SET NULL` (safe). Worth a dedicated sweep.

---

## 6. Alembic migrations (12 revisions)

| Rev | File | Lines | Notes |
|-----|------|-------|-------|
| `129188e46db8` | `_init_create_all_tables.py` | 29 | Baseline **NO-OP** — tables are auto-created by `Base.metadata.create_all()` at app startup, migration is only an Alembic marker |
| `v090_new_modules` | `v090_add_all_new_modules.py` | **1288** | **Giant migration** — adds all Phase 0.9 modules (i18n, contacts, finance, BIM hub, CDE, safety, ...). Uses `_create_if_not_exists` + `_add_column_safe` idempotent helpers. Downgrade drops these tables |
| `1f58eec86764` | `_add_tasks_bim_element_ids_column.py` | 74 | Adds `bim_element_ids JSON` to `oe_tasks_task`. Drops on downgrade |
| `a1b2c3d4e5f6` | `_add_collab_lock_table.py` | 125 | Creates `oe_collab_lock` table |
| `b2f4e1a3c907` | `_gate_result_score_to_float.py` | 105 | **Type change**: `oe_requirements_gate_result.score` String → Float. Uses batch_op for SQLite |
| `f22fa2934807` | `_add_bim_element_group_table.py` | 95 | Creates `oe_bim_element_group` |
| `ffe3f561e2c1` | `_add_documents_bim_link_table.py` | 108 | Creates `oe_documents_bim_link` |
| `v100_...` | `v100_add_bim_requirements_tables.py` | 94 | Creates `oe_bim_requirement_set`, `oe_bim_requirement` |
| `v191_cde_audit` | `v191_cde_audit.py` | 192 | Creates `oe_cde_state_transition`, adds `revision_id` and `document_id` to CDE. Downgrade drops columns (batch) |
| `v191_dwg_entity_groups` | `v191_dwg_entity_groups.py` | 72 | Creates `oe_dwg_entity_group` |
| `v191_meetings_document_ids` | `v191_meetings_document_ids.py` | 62 | Adds `document_ids JSON` to meetings. Downgrade drops |
| `v192_dwg_annotation_thickness_layer` | `v192_dwg_annotation_thickness_layer.py` | 85 | Adds `thickness`, `layer_name` to `oe_dwg_takeoff_annotation`. Downgrade drops both |

### Migration risks
- **v090 is monolithic (1288 LOC).** It contains ~25 new tables + `_add_column_safe` for pre-existing ones. Any PG failure mid-migration leaves a partial schema that `_create_if_not_exists` can patch on re-run but only for tables (not columns).
- **b2f4e1a3c907** changes a column type (String→Float). Batch operation required for SQLite — possible on-disk table rewrite.
- **All drops found are in `downgrade()` functions** (safe rollback paths), not `upgrade()`. No migration drops data as part of forward migration.
- **No rename operations found** anywhere.
- **Init migration is a no-op** — DDL is owned by SQLAlchemy, not Alembic. This means fresh installations rely on `Base.metadata.create_all()`, and divergence between models and migrations is possible.

---

## 7. Summary numbers

| Metric | Value |
|--------|-------|
| Modules with models | 37 (of 46 module dirs; `architecture_map` has no models, region packs are route-only, `cad`, `backup`, `opencde_api`, `project_intelligence` have no models.py) |
| ORM model classes | 86 |
| Tables (same count) | 86 |
| Hard FK columns | 89 |
| Soft FK columns (UUID/String without FK) | ~55 |
| Self-referential tables | 9 |
| Explicit composite / named indexes | ~30 (+ single-column `index=True` on ~140 columns) |
| Unique constraints | ~20 |
| Tables without `org_id` | **84** (98%) |
| Tables missing `created_at`/`updated_at` | **0** |
| Tables with `metadata_` JSON | 86 |
| Decimal/Numeric columns | **0** (all money/quantity stored as `String(50)`) |
| Unbounded `String()` columns | **0** |
| Migration files | 12 |
| Giant migrations (>500 LOC) | **1** (`v090_add_all_new_modules.py`, 1288 LOC) |
| Migrations dropping columns on upgrade | 0 |
| Migrations dropping tables on upgrade | 0 |
| Migrations renaming columns | 0 |
