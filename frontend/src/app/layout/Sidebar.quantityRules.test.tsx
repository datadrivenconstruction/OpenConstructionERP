// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Quantity Rules entry. Release 17c62d2fa dropped it from the menu, which
// left the compliance "BIM Rules" row (?mode=requirements, which hides the
// Quantity Rules tab) as the only way in, and that row sits in a group the
// simple view hides. Simple is the default view, so a new user had no menu
// path to quantity rules at all. This renders the real sidebar in both views.

import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: unknown }) =>
      typeof opts?.defaultValue === 'string' ? opts.defaultValue : key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

vi.mock('@/shared/lib/useI18nReady', () => ({ useI18nReady: () => 0 }));
vi.mock('./CustomBranding', () => ({ CustomBranding: () => null }));
// Each notice renders its own name, so a test can read which one the sidebar
// chose without the version check behind them (pinned in updateBadge.test.tsx).
vi.mock('@/shared/ui/UpdateChecker', () => ({
  UpdateNotification: () => 'update-card',
  UpdateBadge: () => 'update-badge',
}));
vi.mock('@/features/modules/RequestCustomModuleDialog', () => ({
  RequestCustomModuleDialog: () => null,
}));
vi.mock('@/shared/hooks/useSidebarBadges', () => ({
  useSidebarBadges: () => ({ tasks: 0, rfi: 0, safety: 0 }),
}));
vi.mock('@/shared/hooks/useHiddenModules', () => ({
  useHiddenModules: () => ({ hiddenModules: [], setHiddenModules: vi.fn() }),
}));
vi.mock('@/features/projects/useProjectProfile', () => ({
  useActiveProjectProfile: () => ({ projectId: null, profile: undefined, isLoading: false }),
  buildModuleGate: () => ({ active: false, byRoute: () => null }),
}));

import { Sidebar } from './Sidebar';
import { useAuthStore } from '@/stores/useAuthStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { useSidebarCollapseStore } from '@/stores/useSidebarCollapseStore';

function renderSidebar() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <Sidebar />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const hrefs = () => Array.from(document.querySelectorAll('a')).map((a) => a.getAttribute('href') ?? '');

beforeEach(() => {
  localStorage.clear();
  api.apiGet.mockReset();
  api.apiGet.mockImplementation((path: string) =>
    path === '/v1/users/me/onboarding/'
      ? Promise.resolve({ completed: true, company_type: null })
      : Promise.resolve([]),
  );
  useAuthStore.setState({ isAuthenticated: true, userRole: 'editor', userId: 'user-a', accessToken: null });
  useModuleStore.setState({ enabledModules: {}, hiddenGroups: [] });
  useSidebarCollapseStore.getState().setIconified(false);
});

afterEach(() => cleanup());

describe('the Quantity rules menu entry', () => {
  it('is in the simple view, which is the default, without the compliance row', () => {
    useViewModeStore.getState().setMode('simple');
    renderSidebar();
    expect(hrefs()).toContain('/bim/rules');
    expect(hrefs()).not.toContain('/bim/rules?mode=requirements');
  });

  // Quantity maps are BIM Hub; the compliance requirements are their own
  // module. Switching one off must not take the other's row with it.
  const modulesOff = (...names: string[]) =>
    api.apiGet.mockImplementation((path: string) =>
      path === '/v1/users/me/onboarding/'
        ? Promise.resolve({ completed: true, company_type: null })
        : path === '/v1/modules/'
          ? Promise.resolve(names.map((name) => ({ name, enabled: false, is_core: false })))
          : Promise.resolve([]),
    );

  // The compliance view has two tabs from two modules: Requirements
  // (oe_requirements) and the Rule Library (oe_bim_requirements). Its row
  // goes only when neither is left. `oe_clash` goes off in every case as a
  // marker: once its row is gone the module list has arrived, so a row that
  // is still there stayed on purpose, not because nothing was loaded yet.
  it.each([
    { off: [], compliance: true },
    { off: ['oe_requirements'], compliance: true },
    { off: ['oe_bim_requirements'], compliance: true },
    { off: ['oe_requirements', 'oe_bim_requirements'], compliance: false },
  ])('with $off switched off the compliance row shows: $compliance', async ({ off, compliance }) => {
    modulesOff('oe_clash', ...off);
    useViewModeStore.getState().setMode('advanced');
    renderSidebar();
    await waitFor(() => expect(hrefs()).not.toContain('/clash'));
    expect(hrefs().includes('/bim/rules?mode=requirements')).toBe(compliance);
    expect(hrefs()).toContain('/bim/rules');
  });

  it('goes with BIM Hub, while the compliance row stays', async () => {
    modulesOff('oe_bim_hub');
    useViewModeStore.getState().setMode('advanced');
    renderSidebar();
    await waitFor(() => expect(hrefs()).not.toContain('/bim/rules'));
    expect(hrefs()).toContain('/bim/rules?mode=requirements');
  });

  it('sits next to the compliance row in the advanced view', () => {
    useViewModeStore.getState().setMode('advanced');
    renderSidebar();
    expect(hrefs()).toContain('/bim/rules');
    expect(hrefs()).toContain('/bim/rules?mode=requirements');
  });
});
