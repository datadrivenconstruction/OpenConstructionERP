// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Plain, translated titles for validation rules.
//
// The engine names its rules in English ("Unit Rate Anomaly Detection",
// "Every Bill States Its Base Date") and stores that English name in every
// report. Printed as is, a German or Russian estimator reads English headings
// over findings that are otherwise in their own language. The rules every BOQ
// report runs (the universal BOQ checks, project completeness and the
// classification sets the page sends) are mapped here to locale keys. Each
// call is a literal t() so the i18n guards can see every key.
//
// A rule with no entry (a pack rule, a rule added after this map) falls back
// to its English engine name, and when the engine sent only the id, to the id
// turned into words. The raw id is never the label.

import type { Translate } from './ruleSetLabels';

function ruleTitleMap(t: Translate): Record<string, string> {
  return {
    'boq_quality.position_has_quantity': t('validation.rule_title_boq_quality_position_has_quantity', { defaultValue: 'Position has a quantity' }),
    'boq_quality.position_has_unit_rate': t('validation.rule_title_boq_quality_position_has_unit_rate', { defaultValue: 'Position has a unit rate' }),
    'boq_quality.position_has_description': t('validation.rule_title_boq_quality_position_has_description', { defaultValue: 'Position has a description' }),
    'boq_quality.no_duplicate_ordinals': t('validation.rule_title_boq_quality_no_duplicate_ordinals', { defaultValue: 'Position numbers are unique' }),
    'boq_quality.unit_rate_in_range': t('validation.rule_title_boq_quality_unit_rate_in_range', { defaultValue: 'Unusually high unit rate' }),
    'boq_quality.negative_values': t('validation.rule_title_boq_quality_negative_values', { defaultValue: 'No negative quantities or rates' }),
    'boq_quality.unrealistic_rate': t('validation.rule_title_boq_quality_unrealistic_rate', { defaultValue: 'Unrealistic unit rate' }),
    'boq_quality.total_mismatch': t('validation.rule_title_boq_quality_total_mismatch', { defaultValue: 'Total equals quantity times rate' }),
    'boq_quality.resource_split_mismatch': t('validation.rule_title_boq_quality_resource_split_mismatch', { defaultValue: 'Resources add up to the unit rate' }),
    'boq_quality.empty_unit': t('validation.rule_title_boq_quality_empty_unit', { defaultValue: 'Position has a unit' }),
    'boq_quality.unit_system_consistency': t('validation.rule_title_boq_quality_unit_system_consistency', { defaultValue: 'One unit system throughout' }),
    'boq_quality.section_without_items': t('validation.rule_title_boq_quality_section_without_items', { defaultValue: 'Section contains positions' }),
    'boq_quality.rate_vs_benchmark': t('validation.rule_title_boq_quality_rate_vs_benchmark', { defaultValue: 'Unit rate compared with benchmark' }),
    'boq_quality.lump_sum_ratio': t('validation.rule_title_boq_quality_lump_sum_ratio', { defaultValue: 'Share of lump sum positions' }),
    'boq_quality.cost_concentration': t('validation.rule_title_boq_quality_cost_concentration', { defaultValue: 'Cost concentrated in few positions' }),
    'boq_quality.currency_consistency': t('validation.rule_title_boq_quality_currency_consistency', { defaultValue: 'One currency throughout' }),
    'boq_quality.measurement_consistency': t('validation.rule_title_boq_quality_measurement_consistency', { defaultValue: 'Consistent units of measurement' }),
    'boq_quality.revision_cost_impact_review': t('validation.rule_title_boq_quality_revision_cost_impact_review', { defaultValue: 'Revision cost change needs a variation' }),
    'boq_quality.base_date_readable': t('validation.rule_title_boq_quality_base_date_readable', { defaultValue: 'Base date can be read' }),
    'classification_nudge.country_mismatch': t('validation.rule_title_classification_nudge_country_mismatch', { defaultValue: 'Classification standard fits the country' }),
    'din276.cost_group_required': t('validation.rule_title_din276_cost_group_required', { defaultValue: 'DIN 276 cost group assigned' }),
    'din276.valid_cost_group': t('validation.rule_title_din276_valid_cost_group', { defaultValue: 'DIN 276 cost group is valid' }),
    'din276.hierarchy': t('validation.rule_title_din276_hierarchy', { defaultValue: 'DIN 276 cost group hierarchy' }),
    'din276.completeness': t('validation.rule_title_din276_completeness', { defaultValue: 'DIN 276 main cost groups present' }),
    'gaeb.ordinal_format': t('validation.rule_title_gaeb_ordinal_format', { defaultValue: 'GAEB position number format' }),
    'gaeb.lv_structure': t('validation.rule_title_gaeb_lv_structure', { defaultValue: 'GAEB structure of the bill' }),
    'gaeb.einheitspreis_sanity': t('validation.rule_title_gaeb_einheitspreis_sanity', { defaultValue: 'GAEB unit price is plausible' }),
    'gaeb.trade_section_code': t('validation.rule_title_gaeb_trade_section_code', { defaultValue: 'GAEB trade section code' }),
    'gaeb.quantity_decimals': t('validation.rule_title_gaeb_quantity_decimals', { defaultValue: 'GAEB quantity decimals' }),
    'nrm.classification_required': t('validation.rule_title_nrm_classification_required', { defaultValue: 'NRM element code assigned' }),
    'nrm.valid_element': t('validation.rule_title_nrm_valid_element', { defaultValue: 'NRM element code is valid' }),
    'nrm.completeness': t('validation.rule_title_nrm_completeness', { defaultValue: 'NRM main groups present' }),
    'nrm.base_date_declared': t('validation.rule_title_nrm_base_date_declared', { defaultValue: 'NRM cost plan base date stated' }),
    'nrm.cost_plan_stage_declared': t('validation.rule_title_nrm_cost_plan_stage_declared', { defaultValue: 'NRM cost plan stage stated' }),
    'nrm.contractor_costs_present': t('validation.rule_title_nrm_contractor_costs_present', { defaultValue: 'Preliminaries, overheads and profit included' }),
    'nrm.risk_allowance_present': t('validation.rule_title_nrm_risk_allowance_present', { defaultValue: 'Risk allowance included' }),
    'masterformat.classification_required': t('validation.rule_title_masterformat_classification_required', { defaultValue: 'MasterFormat code assigned' }),
    'masterformat.valid_division': t('validation.rule_title_masterformat_valid_division', { defaultValue: 'MasterFormat division is valid' }),
    'masterformat.completeness': t('validation.rule_title_masterformat_completeness', { defaultValue: 'MasterFormat core divisions present' }),
    'project_completeness.country_set': t('validation.rule_title_project_completeness_country_set', { defaultValue: 'Project country is set' }),
    'project_completeness.currency_set': t('validation.rule_title_project_completeness_currency_set', { defaultValue: 'Project currency is set' }),
    'project_completeness.currency_matches_bill': t('validation.rule_title_project_completeness_currency_matches_bill', { defaultValue: 'Project currency matches the BOQ' }),
    'project_completeness.priced_bill_present': t('validation.rule_title_project_completeness_priced_bill_present', { defaultValue: 'Project has a BOQ with positions' }),
    'project_completeness.bill_base_date_set': t('validation.rule_title_project_completeness_bill_base_date_set', { defaultValue: 'Every BOQ states its base date' }),
    'project_completeness.classification_standard_set': t('validation.rule_title_project_completeness_classification_standard_set', { defaultValue: 'Classification standard is set' }),
    'project_completeness.planned_dates_set': t('validation.rule_title_project_completeness_planned_dates_set', { defaultValue: 'Planned start and end dates are set' }),
    'project_completeness.planned_dates_ordered': t('validation.rule_title_project_completeness_planned_dates_ordered', { defaultValue: 'Planned start is before planned end' }),
    'project_completeness.client_recorded': t('validation.rule_title_project_completeness_client_recorded', { defaultValue: 'Client is recorded' }),
    'project_completeness.procurement_started': t('validation.rule_title_project_completeness_procurement_started', { defaultValue: 'Procurement started after estimating' }),
  };
}

/** Turn an engine id such as `boq_quality.unit_rate_in_range` into words. */
export function humaniseRuleId(ruleId: string): string {
  const tail = ruleId.split('.').pop() ?? ruleId;
  const words = tail.replace(/[_-]+/g, ' ').trim();
  if (!words) return ruleId;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * The title a reader sees for a rule: the translated title when the rule is
 * mapped, else the engine's own name, else the id turned into words.
 */
export function ruleTitle(ruleId: string, ruleName: string | null | undefined, t: Translate): string {
  const mapped = ruleTitleMap(t)[ruleId];
  if (mapped) return mapped;
  if (ruleName && ruleName !== ruleId) return ruleName;
  return humaniseRuleId(ruleId);
}

/** The rule ids that carry a translated title (exported for tests). */
export function mappedRuleIds(): string[] {
  return Object.keys(ruleTitleMap((_key, opts) => String(opts?.defaultValue ?? '')));
}
