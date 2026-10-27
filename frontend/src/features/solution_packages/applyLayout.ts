// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * After an install: put the packages' menu rows first in the sidebar's pinned
 * section and show their dashboard widgets. Pins the user already made are
 * kept; the packages only add rows that are not pinned yet.
 */
import { useDashboardLayoutStore } from '@/stores/useDashboardLayoutStore';
import { DASHBOARD_WIDGET_IDS } from '@/features/dashboard/widgetRegistry';
import { dashboardSetLayout } from '@/features/dashboard/dashboardSets';
import type { SolutionPackage } from './api';
import { mergedMenu, mergedWidgets } from './logic';

/** Same key the sidebar reads its pinned rows from. */
export const PINNED_ROUTES_KEY = 'oce-pinned-routes';

export function pinPackageMenu(packages: SolutionPackage[], ids: string[]): string[] {
  let current: string[] = [];
  try {
    const raw = localStorage.getItem(PINNED_ROUTES_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (Array.isArray(parsed)) current = parsed.filter((r): r is string => typeof r === 'string');
  } catch {
    current = [];
  }
  const next = [...current];
  for (const route of mergedMenu(packages, ids)) if (!next.includes(route)) next.push(route);
  try {
    localStorage.setItem(PINNED_ROUTES_KEY, JSON.stringify(next));
  } catch {
    // storage blocked: the sidebar keeps its own order
  }
  return next;
}

export function applyPackageLayout(packages: SolutionPackage[], ids: string[]): void {
  pinPackageMenu(packages, ids);
  const widgets = mergedWidgets(packages, ids);
  if (widgets.length) {
    useDashboardLayoutStore.setState(
      dashboardSetLayout(
        { id: 'manager', labelKey: '', labelDefault: '', widgets },
        DASHBOARD_WIDGET_IDS,
      ),
    );
  }
}
