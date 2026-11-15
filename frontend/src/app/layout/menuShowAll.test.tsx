// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, render, screen, fireEvent, waitFor, act, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn().mockResolvedValue({ demo_mode: true }) };
});
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: unknown; view?: string }) =>
      typeof opts?.defaultValue === 'string' ? opts.defaultValue.replace('{{view}}', opts.view ?? '') : key,
    i18n: { language: 'en' },
  }),
}));

import { MenuModeBar } from './MenuModeBar';
import { navGroups } from './navCatalog';
import { useMenuLayoutStore } from './useMenuLayoutStore';
import { backToView, showAllModules } from './menuShowAll';
import { demoProfile, demoModuleRoutes } from '@/shared/lib/demoProfiles';
import { demoModulesFor, useDemoModules } from '@/shared/lib/useDemoModules';
import { useDemoSessionStore } from '@/stores/useDemoSessionStore';

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  cleanup();
  sessionStorage.clear();
  useDemoSessionStore.getState().setDemo(null);
});

describe('Riyadh demo exposes the whole platform', () => {
  it('has no section trimming and every menu route is in its module list', () => {
    const riyadh = demoProfile('full-showcase-riyadh')!;
    expect(riyadh.menuMode).toBe('all');
    expect(riyadh.groups).toBeNull();
    expect(demoModulesFor(riyadh)).toBeNull();
    const routes = new Set(demoModuleRoutes(riyadh, navGroups));
    for (const g of navGroups) for (const i of g.items) expect(routes.has(i.to)).toBe(true);
  });

  it('is the only demo that opens with every module', () => {
    const open = ['residential-berlin', 'office-london', 'medical-us', 'condo-toronto', 'school-paris', 'office-shanghai'];
    for (const slug of open) {
      const p = demoProfile(slug)!;
      expect(p.menuMode === 'all' && p.groups === null).toBe(false);
    }
  });
});

describe('Show all modules', () => {
  it('lifts the London trimming and Back restores the demo view', async () => {
    useDemoSessionStore.getState().setDemo('office-london');
    useMenuLayoutStore.getState().dispatch({ type: 'setMode', mode: 'finance' });
    const { result } = renderHook(() => useDemoModules(), { wrapper });
    await waitFor(() => expect(result.current).not.toBeNull());

    act(() => showAllModules());
    await waitFor(() => expect(result.current).toBeNull());
    expect(useMenuLayoutStore.getState().layout.activeMode).toBe('all');

    act(() => backToView());
    await waitFor(() => expect(result.current).not.toBeNull());
    expect(useMenuLayoutStore.getState().layout.activeMode).toBe('finance');
  });

  it('survives a reload within the session and a later mode pick is kept', () => {
    useDemoSessionStore.getState().setDemo('office-london');
    showAllModules();
    expect(sessionStorage.getItem('oe_menu_restore_mode')).not.toBeNull();
    useMenuLayoutStore.getState().dispatch({ type: 'setMode', mode: 'estimator' });
    expect(useDemoSessionStore.getState().restoreMode).not.toBeNull();
    expect(useMenuLayoutStore.getState().layout.activeMode).toBe('estimator');
  });

  it('shows the control, then the way back', () => {
    useDemoSessionStore.getState().setDemo('office-london');
    render(<MenuModeBar mode="finance" onMode={() => {}} onArrange={() => {}} />);
    fireEvent.click(screen.getByTestId('menu-show-all'));
    expect(screen.queryByTestId('menu-show-all')).toBeNull();
    expect(screen.getByTestId('menu-back-to-view')).toBeTruthy();
  });

  it('is offered outside demos when the menu is narrowed, not when it is already all', () => {
    const { rerender } = render(<MenuModeBar mode="estimator" onMode={() => {}} onArrange={() => {}} />);
    expect(screen.getByTestId('menu-show-all')).toBeTruthy();
    rerender(<MenuModeBar mode="all" onMode={() => {}} onArrange={() => {}} />);
    expect(screen.queryByTestId('menu-show-all')).toBeNull();
  });
});
