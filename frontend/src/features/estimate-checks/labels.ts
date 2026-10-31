// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Plain-language labels of the estimate check. Every string is an i18n key
 * with its English default here, so the UI never shows a raw key.
 */
import type { TFunction } from 'i18next';
import type { CheckStatus, KpiGroup, KpiResult, KpiUnit } from './api';

export const EN: Record<string, string> = {
  'estimate_checks.title': 'Estimate check',
  'estimate_checks.badge_hint': 'Sanity check of this estimate against your past estimates. Click to review.',
  'estimate_checks.badge_ok': 'Checks OK',
  'estimate_checks.badge_aria': '{{warning}} warnings, {{suspect}} to look at',
  'estimate_checks.panel_subtitle': 'Each figure is compared with your past estimates. Nothing here blocks you.',
  'estimate_checks.filter_issues': 'Only items to look at',
  'estimate_checks.filter_all': 'All checks',
  'estimate_checks.all_clear': 'Nothing stands out. All checks are within the usual range.',
  'estimate_checks.loading': 'Checking the estimate...',
  'estimate_checks.load_error': 'The check could not be loaded.',
  'estimate_checks.status.normal': 'Normal',
  'estimate_checks.status.suspect': 'Look at this',
  'estimate_checks.status.warning': 'Warning',
  'estimate_checks.status.no_data': 'Not enough data',
  'estimate_checks.status.accepted': 'Accepted',
  'estimate_checks.group.labour': 'Labour',
  'estimate_checks.group.equipment': 'Equipment',
  'estimate_checks.group.materials': 'Materials',
  'estimate_checks.group.subcontractors': 'Subcontractors',
  'estimate_checks.group.markup': 'Markup',
  'estimate_checks.group.data_quality': 'Data quality',
  'estimate_checks.kpi.labour_share': 'Labour share of direct cost',
  'estimate_checks.kpi.labour_cost_per_unit': 'Labour cost per unit of main quantity',
  'estimate_checks.kpi.avg_crew_rate': 'Average labour rate per hour',
  'estimate_checks.kpi.equipment_share': 'Equipment share of direct cost',
  'estimate_checks.kpi.equipment_to_labour_hours': 'Equipment hours per labour hour',
  'estimate_checks.kpi.material_share': 'Material share of direct cost',
  'estimate_checks.kpi.avg_waste_pct': 'Average material waste',
  'estimate_checks.kpi.subcontractor_share': 'Subcontractor share of direct cost',
  'estimate_checks.kpi.single_quote_items': 'Subcontract items with only one quote',
  'estimate_checks.kpi.overhead_pct': 'Overhead',
  'estimate_checks.kpi.profit_pct': 'Profit',
  'estimate_checks.kpi.risk_pct': 'Risk and contingency',
  'estimate_checks.kpi.total_markup_pct': 'Total markup on direct cost',
  'estimate_checks.kpi.zero_rate': 'Positions with a zero rate',
  'estimate_checks.kpi.zero_quantity': 'Positions with a zero quantity',
  'estimate_checks.kpi.duplicates': 'Possible duplicate positions',
  'estimate_checks.kpi.unpriced': 'Unpriced positions',
  'estimate_checks.kpi.rate_far_from_database': 'Rates far from the cost database',
  'estimate_checks.reason.within_history': 'In line with {{count}} comparable past estimates.',
  'estimate_checks.reason.outside_history': 'Outside the usual range of {{count}} comparable past estimates.',
  'estimate_checks.reason.within_default': 'Too few past estimates to compare, so a typical range is used. Within it.',
  'estimate_checks.reason.outside_default': 'Too few past estimates to compare, so a typical range is used. Outside it.',
  'estimate_checks.reason.within_custom': 'Within the range your company set.',
  'estimate_checks.reason.outside_custom': 'Outside the range your company set.',
  'estimate_checks.reason.count_none': 'None found.',
  'estimate_checks.reason.count_found': '{{count}} positions need a look.',
  'estimate_checks.reason.count_found_one': '1 position needs a look.',
  'estimate_checks.reason.count_found_other': '{{count}} positions need a look.',
  'estimate_checks.reason.not_measurable': 'This estimate has no data for this figure yet.',
  'estimate_checks.reason.too_few_comparables': 'Not enough past estimates to compare yet.',
  'estimate_checks.usual_range': 'Usual range {{low}} to {{high}}',
  'estimate_checks.expected_none': 'Expected: none',
  'estimate_checks.confidence.high': 'High confidence',
  'estimate_checks.confidence.medium': 'Medium confidence',
  'estimate_checks.confidence.low': 'Low confidence',
  'estimate_checks.show_positions': 'Show {{count}} positions',
  'estimate_checks.show_positions_one': 'Show 1 position',
  'estimate_checks.show_positions_other': 'Show {{count}} positions',
  'estimate_checks.hide_positions': 'Hide positions',
  'estimate_checks.accept': 'Accept',
  'estimate_checks.accept_hint': 'Keep this figure on purpose. Your reason is saved in the activity log.',
  'estimate_checks.accept_placeholder': 'Why is this figure right for this job?',
  'estimate_checks.accept_save': 'Save',
  'estimate_checks.cancel': 'Cancel',
  'estimate_checks.accepted_note': 'Accepted: {{reason}}',
  'estimate_checks.undo_accept': 'Undo',
  'estimate_checks.compared_scope.type_currency_region': 'Compared with estimates of the same project type, currency and region.',
  'estimate_checks.compared_scope.currency_region': 'Compared with estimates in the same currency and region.',
  'estimate_checks.compared_scope.currency': 'Compared with estimates in the same currency.',
  'estimate_checks.compared_scope.all': 'Compared with all past estimates.',
  'estimate_checks.open_settings': 'Settings',
  'estimate_checks.settings.title': 'Estimate check settings',
  'estimate_checks.settings.subtitle': 'Decide how much you see and which figures your company checks.',
  'estimate_checks.settings.display_title': 'What you see in the estimate',
  'estimate_checks.settings.display.all': 'All checks',
  'estimate_checks.settings.display.all_hint': 'Badge with a dot per group; the panel lists every check.',
  'estimate_checks.settings.display.issues': 'Only items to look at',
  'estimate_checks.settings.display.issues_hint': 'Badge with a dot per group; the panel lists flagged checks only.',
  'estimate_checks.settings.display.badge': 'Badge only',
  'estimate_checks.settings.display.badge_hint': 'A small badge with counts. Click it to open the panel.',
  'estimate_checks.settings.display.off': 'Off',
  'estimate_checks.settings.display.off_hint': 'Nothing is shown in the estimate.',
  'estimate_checks.settings.workspace_title': 'Checks for the whole company',
  'estimate_checks.settings.workspace_hint': 'Leave a range empty to use the usual range of your past estimates.',
  'estimate_checks.settings.comparables': 'Compare with',
  'estimate_checks.settings.comparables.auto': 'Similar estimates first (type, currency, region)',
  'estimate_checks.settings.comparables.currency': 'Estimates in the same currency',
  'estimate_checks.settings.comparables.all': 'All past estimates',
  'estimate_checks.settings.min_comparables': 'Past estimates needed before comparing',
  'estimate_checks.settings.db_tolerance': 'Allowed difference from the cost database rate (%)',
  'estimate_checks.settings.col_check': 'Check',
  'estimate_checks.settings.col_on': 'On',
  'estimate_checks.settings.col_low': 'Lowest',
  'estimate_checks.settings.col_high': 'Highest',
  'estimate_checks.settings.save': 'Save settings',
  'estimate_checks.settings.saved': 'Settings saved',
  'estimate_checks.settings.save_error': 'Settings could not be saved. Only managers can change company checks.',
  'estimate_checks.module_description': 'Traffic-light sanity check of an estimate against your past estimates before you submit it.',
};

/** Translate an estimate-check key with its English default. */
export function tx(t: TFunction, key: string, opts: Record<string, unknown> = {}): string {
  return t(key, { defaultValue: EN[key] ?? key, ...opts }) as string;
}

export const GROUP_ORDER: KpiGroup[] = ['labour', 'equipment', 'materials', 'subcontractors', 'markup', 'data_quality'];

export type DotTone = CheckStatus | 'accepted';

export function toneOf(k: KpiResult): DotTone {
  return k.accepted ? 'accepted' : k.status;
}

export const DOT_CLASS: Record<DotTone, string> = {
  normal: 'bg-emerald-500',
  suspect: 'bg-amber-400',
  warning: 'bg-red-500',
  no_data: 'bg-gray-300 dark:bg-gray-600',
  accepted: 'bg-gray-400 dark:bg-gray-500',
};

/** Worst status in a group, for the per-group dot. */
export function worstTone(items: KpiResult[]): DotTone {
  const tones = items.map(toneOf);
  if (tones.includes('warning')) return 'warning';
  if (tones.includes('suspect')) return 'suspect';
  if (tones.includes('normal')) return 'normal';
  if (tones.includes('accepted')) return 'accepted';
  return 'no_data';
}

export function confidenceKey(c: number): string {
  if (c >= 0.7) return 'estimate_checks.confidence.high';
  if (c >= 0.45) return 'estimate_checks.confidence.medium';
  return 'estimate_checks.confidence.low';
}

/** Format a KPI number for its unit in the active language. */
export function formatValue(
  value: number | null,
  unit: KpiUnit,
  locale: string,
  currency: string,
  unitLabel?: string | null,
): string {
  if (value === null || value === undefined) return '-';
  if (unit === 'pct') {
    return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value)} %`;
  }
  if (unit === 'count') return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value);
  if (unit === 'ratio') return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
  const money = new Intl.NumberFormat(locale, { maximumFractionDigits: 2, minimumFractionDigits: 2 }).format(value);
  const cur = currency ? ` ${currency}` : '';
  return unitLabel ? `${money}${cur} / ${unitLabel}` : `${money}${cur}`;
}
