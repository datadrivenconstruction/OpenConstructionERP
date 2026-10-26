// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** The reader-language wording of proportional scaling refusals and warnings. */

type Translate = (key: string, opts?: Record<string, unknown>) => string;

export function scalingErrorText(t: Translate, code: string): string {
  switch (code) {
    case 'scaling_nothing_to_scale':
      return t('boq.scaling.error_nothing_to_scale', {
        defaultValue: 'Nothing in this scope can be scaled: no matching resource norms on unlocked positions.',
      });
    case 'scaling_target_below_fixed':
      return t('boq.scaling.error_target_below_fixed', {
        defaultValue: 'The target is below what the locked and excluded positions already add up to.',
      });
    case 'scaling_target_negative':
      return t('boq.scaling.error_target_negative', { defaultValue: 'The target cannot be negative.' });
    case 'scaling_target_required':
      return t('boq.scaling.error_target_required', { defaultValue: 'Enter the new total first.' });
    case 'scaling_preview_stale':
      return t('boq.scaling.error_preview_stale', {
        defaultValue: 'The bill changed since the preview. Preview again before applying.',
      });
    case 'scaling_scope_not_found':
      return t('boq.scaling.error_scope_not_found', { defaultValue: 'The section no longer exists.' });
    default:
      return code;
  }
}

export function scalingWarningText(t: Translate, warning: { code: string; count?: number; units?: string[] }): string {
  switch (warning.code) {
    case 'mixed_units':
      return t('boq.scaling.warning_mixed_units', {
        defaultValue: 'The scaled norms are in different units ({{units}}); their total adds unlike quantities.',
        units: (warning.units ?? []).join(', '),
      });
    case 'unconverted_currency':
      return t('boq.scaling.warning_unconverted_currency', {
        defaultValue: 'Resource costs without an exchange rate to the project currency, left out: {{n}}.',
        n: warning.count ?? 0,
      });
    case 'rounded_to_zero':
      return t('boq.scaling.warning_rounded_to_zero', {
        defaultValue: 'Norms that round to zero with this rule: {{n}}. Choose more decimals to keep them.',
        n: warning.count ?? 0,
      });
    default:
      return warning.code;
  }
}
