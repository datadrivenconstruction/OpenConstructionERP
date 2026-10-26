// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { DASHBOARD_WIDGET_IDS } from '../widgetRegistry';
import { DASHBOARD_SETS, dashboardSetLayout } from '../dashboardSets';
import { DashboardLayoutManager } from '../DashboardLayoutManager';
import { useDashboardLayoutStore } from '@/stores/useDashboardLayoutStore';

beforeEach(() => {
  localStorage.clear();
  useDashboardLayoutStore.getState().reset();
});

describe('dashboard sets', () => {
  it('only name widgets the registry has', () => {
    for (const set of DASHBOARD_SETS) {
      for (const id of set.widgets) expect(DASHBOARD_WIDGET_IDS).toContain(id);
    }
  });

  it('puts the set first in its order, hides the rest and keeps every widget listed once', () => {
    const site = DASHBOARD_SETS.find((s) => s.id === 'site')!;
    const { order, hidden } = dashboardSetLayout(site, DASHBOARD_WIDGET_IDS);
    expect(order.slice(0, site.widgets.length)).toEqual([...site.widgets]);
    expect([...order].sort()).toEqual([...DASHBOARD_WIDGET_IDS].sort());
    expect(hidden).not.toContain('on_site_now');
    expect(hidden).toContain('finance_summary');
  });

  it('skips ids the registry no longer has', () => {
    const { order, hidden } = dashboardSetLayout(
      { id: 'site', labelKey: 'k', labelDefault: 'K', widgets: ['gone', 'today'] },
      ['today', 'kpi'],
    );
    expect(order).toEqual(['today', 'kpi']);
    expect(hidden).toEqual(['kpi']);
  });

  it('applies a set from the customise panel and Reset goes back to the default', () => {
    render(<DashboardLayoutManager />);
    fireEvent.click(screen.getByRole('button', { name: 'Site manager' }));
    const s = useDashboardLayoutStore.getState();
    expect(s.order[0]).toBe('today');
    expect(s.hidden).toContain('finance_summary');
    expect(s.hidden).not.toContain('weather_site');
    fireEvent.click(screen.getByRole('button', { name: 'Reset to default' }));
    expect(useDashboardLayoutStore.getState().order).toEqual([]);
  });
});
