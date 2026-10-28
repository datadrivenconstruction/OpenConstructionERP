// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Human names for the engine's rule-set identifiers.
//
// The identifiers are how the validation engine talks to itself: `boq_quality`,
// `din276`, `masterformat`. They are not how a quantity surveyor talks, and
// three separate screens were printing them at a reader. The map used to live
// inside the validation page, so the one screen that had been thought about was
// the one that read correctly, while the chat renderer and the project settings
// pack list printed the identifier unchanged. A rule written once per caller is
// only ever tested at the caller that was already right.
//
// Translation keys are unchanged from where this map used to live, so the
// locale files already answer them.

/** The subset of `t` this module needs, so it stays free of react-i18next. */
export type Translate = (key: string, opts?: Record<string, unknown>) => string;

/**
 * A rule set's human name.
 *
 * An identifier with no entry is de-underscored rather than printed raw: a set
 * shipped by a pack we do not know about should still read as words. That is
 * also why the caller never needs the raw value as a fallback.
 */
export function ruleSetLabel(ruleSet: string, t: Translate): string {
  const map: Record<string, string> = {
    boq_quality: t('validation.rs_label_boq_quality', { defaultValue: 'BOQ quality' }),
    din276: t('validation.rs_label_din276', { defaultValue: 'DIN 276' }),
    gaeb: t('validation.rs_label_gaeb', { defaultValue: 'GAEB' }),
    nrm: t('validation.rs_label_nrm', { defaultValue: 'NRM' }),
    masterformat: t('validation.rs_label_masterformat', { defaultValue: 'MasterFormat' }),
    bim_compliance: t('validation.rs_label_bim', { defaultValue: 'BIM compliance' }),
    project_governance: t('validation.rs_label_project_governance', { defaultValue: 'Project governance' }),
    commitment_release: t('validation.rs_label_commitment_release', { defaultValue: 'Commitment release' }),
    economics: t('validation.rs_label_economics', { defaultValue: 'Economics' }),
    delivery_model: t('validation.rs_label_delivery_model', { defaultValue: 'Delivery model' }),
    permits: t('validation.rs_label_permits', { defaultValue: 'Permits' }),
    plant_register: t('validation.rs_label_plant_register', { defaultValue: 'Plant register' }),
    procurement_concept: t('validation.rs_label_procurement_concept', { defaultValue: 'Procurement concept' }),
    design_management: t('validation.rs_label_design_management', { defaultValue: 'Design management' }),
    stakeholders: t('validation.rs_label_stakeholders', { defaultValue: 'Stakeholders' }),
    quality_concept: t('validation.rs_label_quality_concept', { defaultValue: 'Quality concept' }),
    staffing: t('validation.rs_label_staffing', { defaultValue: 'Staffing' }),
    site_logistics: t('validation.rs_label_site_logistics', { defaultValue: 'Site logistics' }),
    engineering_brief: t('validation.rs_label_engineering_brief', { defaultValue: 'Engineering brief' }),
    hse_frame: t('validation.rs_label_hse_frame', { defaultValue: 'HSE frame' }),
    project_handbook: t('validation.rs_label_project_handbook', { defaultValue: 'Project handbook' }),
    project_completeness: t('validation.rs_label_completeness', { defaultValue: 'Completeness' }),
  };
  return map[ruleSet] ?? ruleSet.replace(/_/g, ' ');
}

/**
 * Split the stored `rule_set` column into the identifiers it packs.
 *
 * A report records the sets it ran as one plus-joined string. Readers that
 * printed the column verbatim showed `boq_quality+masterformat` on screen.
 */
export function splitRuleSets(raw: string | null | undefined): string[] {
  if (!raw) return [];
  return raw
    .split('+')
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

/** The human names of a plus-joined `rule_set` column, ready to print. */
export function ruleSetListLabel(raw: string | null | undefined, t: Translate): string {
  return splitRuleSets(raw)
    .map((set) => ruleSetLabel(set, t))
    .join(' · ');
}
