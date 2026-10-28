// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Ready-made widget sets for the dashboard: one click shows the sections a
 * role works from, in that order, and hides the rest. They only fill the same
 * order / hidden lists the customise panel edits, so everything stays editable.
 */
export interface DashboardSet {
  id: 'site' | 'estimator' | 'manager';
  labelKey: string;
  labelDefault: string;
  widgets: readonly string[];
}

export const DASHBOARD_SETS: readonly DashboardSet[] = [
  {
    id: 'site',
    labelKey: 'dashboard.layout.set_site',
    labelDefault: 'Site manager',
    widgets: [
      'today', 'continue_work', 'on_site_now', 'weather_site', 'inbox', 'punch_quality',
      'inspections_quality', 'rfi_turnaround', 'submittals_pending', 'upcoming_milestones',
      'latest_photos', 'quick_upload', 'activity',
    ],
  },
  {
    id: 'estimator',
    labelKey: 'dashboard.layout.set_estimator',
    labelDefault: 'Estimator',
    widgets: [
      'continue_work', 'projects', 'estimate_resources', 'kpi', 'validation_portfolio',
      'finance_summary', 'bim_coverage', 'quick_upload', 'regional_pack',
    ],
  },
  {
    id: 'manager',
    labelKey: 'dashboard.layout.set_manager',
    labelDefault: 'Project manager',
    widgets: [
      'today', 'kpi', 'finance_summary', 'portfolio', 'operations_snapshot', 'upcoming_milestones',
      'rfi_turnaround', 'analytics', 'map', 'activity',
    ],
  },
];

/** Order and hidden list for a set, against the widgets the registry really has. */
export function dashboardSetLayout(
  set: DashboardSet,
  registryIds: readonly string[],
): { order: string[]; hidden: string[] } {
  const known = new Set(registryIds);
  const shown = set.widgets.filter((id) => known.has(id));
  const shownSet = new Set(shown);
  const rest = registryIds.filter((id) => !shownSet.has(id));
  return { order: [...shown, ...rest], hidden: rest };
}
