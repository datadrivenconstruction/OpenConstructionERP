// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Where the wizard leaves a user, checked against the menu they land on.
//
// The last step used to switch the user to Simple mode and, in the same
// handler, tell the server `interface_mode: 'advanced'`. And it wrote the
// chosen profile to the server without telling the sidebar, whose copy of the
// onboarding record is the one the dashboard fetched before sending the user
// here: no profile, not completed. So these tests mount the sidebar next to
// the step, seed that stale record, and watch the menu change on Finish.

import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';

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

// The suite-wide mock calls `.replace` on an undefined defaultValue, which the
// menu rows pass; labels are not what these tests read. Interpolation is kept
// so the workspace sentence reads with its name in it.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (typeof opts?.defaultValue !== 'string') return key;
      return opts.defaultValue.replace(/\{\{(\w+)\}\}/g, (_m: string, name: string) =>
        String(opts[name] ?? ''),
      );
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

vi.mock('@/shared/lib/useI18nReady', () => ({ useI18nReady: () => 0 }));
vi.mock('@/app/layout/CustomBranding', () => ({
  CustomBranding: () => null,
  BrandingEditorModal: () => null,
}));
vi.mock('@/shared/ui/UpdateChecker', () => ({ UpdateNotification: () => null }));
vi.mock('@/shared/ui/ArticleNewsCard', () => ({ ArticleNewsCard: () => null }));
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

import { StepFinish } from '../OnboardingWizard';
import { Sidebar } from '@/app/layout/Sidebar';
import { meOnboardingQueryKey } from '@/app/layout/meOnboardingQuery';
import { useAuthStore } from '@/stores/useAuthStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { useViewModeStore } from '@/stores/useViewModeStore';

type Presets = Parameters<typeof StepFinish>[0]['presets'];

const PRESETS: Presets = [
  {
    key: 'general_contractor',
    label: 'General Contractor',
    description: 'We build projects end to end.',
    icon: 'Building2',
    tags: [],
    enabled_modules: ['boq', 'contracts', 'subcontractors'],
    module_count: 3,
  },
  {
    key: 'estimator',
    label: 'Cost Estimator / Quantity Surveyor',
    description: 'We price work.',
    icon: 'Calculator',
    tags: [],
    enabled_modules: ['boq'],
    module_count: 1,
  },
];

const USER_ID = 'user-1';

function Location() {
  return <span data-testid="location">{useLocation().pathname}</span>;
}

/** The step and the menu in one tree, over a cache holding what the dashboard
 *  read before it sent the user to the wizard. */
function renderFinish(companyType: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(meOnboardingQueryKey(USER_ID), { completed: false, company_type: null });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/onboarding']}>
        <Sidebar />
        <StepFinish
          onBack={() => undefined}
          companyType={companyType}
          enabledModules={new Set(PRESETS.find((p) => p.key === companyType)!.enabled_modules)}
          presets={PRESETS}
        />
        <Location />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

function onboardingPost(): Record<string, unknown> {
  const call = api.apiPost.mock.calls.find(([path]) => path === '/v1/users/me/onboarding/');
  expect(call).toBeTruthy();
  return call![1] as Record<string, unknown>;
}

const workspaceHrefs = () =>
  within(screen.getByTestId('sidebar-workspace'))
    .getAllByRole('link')
    .map((a) => a.getAttribute('href'));

/** How many times the menu asked the server for the onboarding record. */
const onboardingReads = () =>
  api.apiGet.mock.calls.filter(([path]) => path === '/v1/users/me/onboarding/').length;

beforeEach(() => {
  localStorage.clear();
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  // A small server: the onboarding record the POST writes is what a GET reads.
  let record: Record<string, unknown> = { completed: false, company_type: null };
  api.apiGet.mockImplementation((path: string) => {
    if (path === '/v1/users/me/onboarding/') return Promise.resolve(record);
    // The module-preferences read-back has nothing to add; every list is empty.
    return Promise.resolve(path === '/v1/users/me/module-preferences/' ? { modules: {} } : []);
  });
  api.apiPost.mockImplementation((path: string, body: Record<string, unknown>) => {
    if (path !== '/v1/users/me/onboarding/') return Promise.resolve({});
    record = { completed: true, company_type: body.company_type, enabled_modules: body.enabled_modules };
    return Promise.resolve(record);
  });
  useAuthStore.setState({ isAuthenticated: true, userRole: 'editor', userId: USER_ID });
  useModuleStore.setState({ enabledModules: {}, hiddenGroups: [] });
  // Somebody who had tried Advanced before re-running the wizard.
  useViewModeStore.getState().setMode('advanced');
});

afterEach(() => cleanup());

describe('finishing the wizard as a general contractor', () => {
  it('says what the menu will show before the user sees it', () => {
    renderFinish('general_contractor');

    expect(screen.getByTestId('onboarding-finish-workspace').textContent).toBe(
      'The sidebar opens on your General Contractor workspace. Every other screen is one click away under More modules.',
    );
  });

  it('lands in Simple mode on the workspace, with the profile saved and no mode claimed', async () => {
    const client = renderFinish('general_contractor');
    // Advanced before Finish, so the stale record shows no workspace yet.
    expect(screen.queryByTestId('sidebar-workspace')).toBeNull();
    await waitFor(() => expect(onboardingReads()).toBe(1));

    fireEvent.click(screen.getByRole('button', { name: /Start Working/ }));

    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/'));
    expect(useViewModeStore.getState().mode).toBe('simple');

    const body = onboardingPost();
    expect(body.company_type).toBe('general_contractor');
    expect(body.completed).toBe(true);
    expect('interface_mode' in body).toBe(false);

    // The menu that was already on screen follows at once: the answer went
    // into the shared cache entry, and the menu did not have to ask again.
    expect(workspaceHrefs().slice(0, 6)).toEqual([
      '/',
      '/inbox',
      '/projects',
      '/boq',
      '/finance?tab=budgets',
      '/contracts',
    ]);
    expect(onboardingReads()).toBe(1);
    expect(localStorage.getItem('oe_company_type')).toBe('general_contractor');
    // The dashboard's first-run check reads the same entry, so it sees the
    // wizard as done and does not send the user back into it.
    expect(client.getQueryData(meOnboardingQueryKey(USER_ID))).toMatchObject({
      completed: true,
      company_type: 'general_contractor',
    });
  });
});

describe('finishing the wizard with a profile that has no workspace', () => {
  it('lands in Simple mode as before, with no workspace line and no mode claimed', async () => {
    renderFinish('estimator');
    expect(screen.queryByTestId('onboarding-finish-workspace')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /Start Working/ }));

    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/'));
    expect(useViewModeStore.getState().mode).toBe('simple');
    expect('interface_mode' in onboardingPost()).toBe(false);
    expect(screen.queryByTestId('sidebar-workspace')).toBeNull();
    expect(screen.queryByTestId('sidebar-more-modules')).toBeNull();
  });
});
