// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The whole wizard, from the first screen to the app, the way a new user walks
// it. Each step has tests of its own; these hold the joins between them, which
// is where the wizard has broken before: what Back returns to, what a skip
// leaves behind, and above all what Finish tells the server and where it lands.
//
// The server is a small fake behind the api module: the onboarding record the
// POST writes is what the GETs read back, so a test can follow a choice from
// the card that made it to the request that saved it and the route the user
// ends on. Anything else the steps ask the server for fails the way an
// unreachable endpoint fails, which every step already has to survive.
//
// The sidebar a finished user lands on is covered in
// StepFinish.workspace.test.tsx; it is not mounted again here.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

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

// The welcome step switches the UI language as it mounts and the English
// escape hatch switches it again. The switch is asserted, not performed.
const changeLanguage = vi.hoisted(() => vi.fn(() => Promise.resolve()));
vi.mock('@/app/i18n', async () => {
  const actual = await vi.importActual<typeof import('@/app/i18n')>('@/app/i18n');
  return { ...actual, changeLanguage };
});

// The data step asks for the semantic model status and the cost-base
// catalogue. Neither is under test; both are stubbed off the wire.
const { embeddingModelStatus, installEmbeddingModel } = vi.hoisted(() => ({
  embeddingModelStatus: vi.fn(),
  installEmbeddingModel: vi.fn(),
}));
vi.mock('@/features/ai-estimator/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/ai-estimator/api')>();
  return {
    ...actual,
    aiEstimatorApi: { ...actual.aiEstimatorApi, embeddingModelStatus, installEmbeddingModel },
  };
});
vi.mock('@/features/costs/baseCatalog', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/costs/baseCatalog')>();
  return { ...actual, useBaseCatalog: () => ({ data: undefined }) };
});

import { OnboardingWizard } from '../OnboardingWizard';
import { ALL_MODULES, CORE_MODULE_KEYS } from '../modules';
import { meOnboardingQueryKey } from '@/app/layout/meOnboardingQuery';
import { useAuthStore } from '@/stores/useAuthStore';
import { useViewModeStore } from '@/stores/useViewModeStore';

interface Preset {
  key: string;
  label: string;
  description: string;
  icon: string;
  tags: string[];
  enabled_modules: string[];
  module_count: number;
}

function preset(key: string, label: string, enabled: string[]): Preset {
  return {
    key,
    label,
    description: `${label} description.`,
    icon: 'Building2',
    tags: [],
    enabled_modules: enabled,
    module_count: enabled.length,
  };
}

// The general contractor's real module set, core keys it re-lists included,
// so the counts below meet the same double listing the live catalogue has.
const GC_MODULES = [
  'boq', 'costs', 'assemblies', 'catalog', 'validation', 'takeoff', 'dwg_takeoff', 'schedule',
  'tasks', 'costmodel', 'finance', 'funding', 'procurement', 'changeorders', 'contracts',
  'variations', 'equipment', 'resources', 'daily_diary', 'subcontractors', 'payroll',
  'field_diary', 'meetings', 'rfi', 'submittals', 'transmittals', 'documents', 'cde', 'markups',
  'inspections', 'ncr', 'safety', 'punchlist', 'risk', 'qms', 'moc', 'fieldreports', 'reporting',
  'project_controls', 'bi_dashboards', 'bim_hub', 'cad',
];

const PRESETS: Preset[] = [
  preset('general_contractor', 'General Contractor', GC_MODULES),
  preset('subcontractor', 'Subcontractor / Trade Contractor', ['boq', 'costs', 'catalog', 'payroll']),
  preset('scheduler_planner', 'Planner / Scheduler', ['schedule', 'schedule_advanced', 'eac']),
  preset('full_enterprise', 'Full Enterprise', ['boq']),
];

const USER_ID = 'user-1';
const NON_CORE = ALL_MODULES.filter((m) => !m.core).map((m) => m.key);

/** The count every screen should print for a set of picked modules. */
const activeCount = (keys: string[]) => new Set([...keys, ...CORE_MODULE_KEYS]).size;

function Location() {
  return <span data-testid="location">{useLocation().pathname}</span>;
}

function renderWizard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/onboarding']}>
        <Routes>
          <Route path="/onboarding" element={<OnboardingWizard />} />
          <Route path="*" element={<Location />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

const heading = (name: string) => screen.findByRole('heading', { name });
const click = (name: string | RegExp) => fireEvent.click(screen.getByRole('button', { name }));
const stepLabel = () => screen.getByText(/^Step \d of 6$/).textContent;

/** The module step's switch for one module, found through the search box and
 *  then by the switch's own name. Found by visible text instead, the finance
 *  module collided with the finance group header, which the search also opens
 *  and which the test locale names the same. */
function moduleSwitch(key: string): HTMLElement {
  const search = screen.getByRole('searchbox', { name: 'Search modules' });
  fireEvent.change(search, { target: { value: key } });
  return screen.getByRole('switch', { name: key });
}

/** Welcome -> start choice -> the profile step, catalogue loaded. */
async function toProfileStep() {
  await heading('Welcome to OpenConstructionERP');
  click(/Get Started/);
  await heading('How would you like to start?');
  click(/Choose Your Profile/);
  await heading('What does your company do?');
  await screen.findByTestId('profile-card-general_contractor');
}

/** Module step -> data step -> summary, taking the data step's skip. */
async function fromModulesToSummary() {
  click('Continue');
  await heading('Data Setup');
  click('Skip - set up later');
  await heading("You're All Set!");
}

async function startWorking() {
  click(/Start Working/);
  await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/'));
}

const posts = (path: string) => api.apiPost.mock.calls.filter(([p]) => p === path);
const onboardingPost = () => {
  const calls = posts('/v1/users/me/onboarding/');
  expect(calls).toHaveLength(1);
  return calls[0]![1] as { company_type: string | null; enabled_modules: string[] } & Record<string, unknown>;
};

beforeEach(() => {
  localStorage.clear();
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  changeLanguage.mockClear();
  embeddingModelStatus.mockReset();
  embeddingModelStatus.mockRejectedValue(new Error('not in this test'));
  installEmbeddingModel.mockReset();
  installEmbeddingModel.mockResolvedValue({});

  let record: Record<string, unknown> = { completed: false, company_type: null };
  let prefs: Record<string, boolean> = {};
  api.apiGet.mockImplementation((path: string) => {
    if (path === '/v1/users/onboarding-presets/') return Promise.resolve(PRESETS);
    if (path === '/v1/users/me/onboarding/') return Promise.resolve(record);
    if (path === '/v1/users/me/module-preferences/') return Promise.resolve({ modules: prefs });
    return Promise.reject(new Error(`no fake for GET ${path}`));
  });
  api.apiPost.mockImplementation((path: string, body: Record<string, unknown> | undefined) => {
    if (path === '/v1/users/me/onboarding/') {
      record = {
        completed: body!.completed,
        company_type: body!.company_type,
        company_size: null,
        enabled_modules: body!.enabled_modules,
      };
      prefs = Object.fromEntries((body!.enabled_modules as string[]).map((k) => [k, true]));
      return Promise.resolve(record);
    }
    if (path === '/v1/users/me/onboarding/complete/') {
      record = { ...record, completed: true };
      return Promise.resolve(record);
    }
    return Promise.resolve({});
  });

  useAuthStore.setState({ isAuthenticated: true, userRole: 'editor', userId: USER_ID });
  useViewModeStore.getState().setMode('advanced');
});

afterEach(() => cleanup());

describe('the onboarding wizard, first screen to the app', () => {
  it('walks every step as a general contractor and saves exactly what was picked', async () => {
    const client = renderWizard();

    await heading('Welcome to OpenConstructionERP');
    expect(stepLabel()).toBe('Step 1 of 6');
    click(/Get Started/);
    await heading('How would you like to start?');
    expect(stepLabel()).toBe('Step 2 of 6');
    click(/Choose Your Profile/);
    await heading('What does your company do?');
    expect(stepLabel()).toBe('Step 3 of 6');

    const card = await screen.findByTestId('profile-card-general_contractor');
    // One count for the profile everywhere it is printed: the card, the module
    // step and the summary. The preset re-lists three core modules, which
    // used to be counted twice on the last two.
    const expected = activeCount(GC_MODULES);
    expect(within(card).getByText(`${expected} modules`)).toBeTruthy();
    fireEvent.click(card);
    click('Continue');

    await heading('Your Modules');
    expect(stepLabel()).toBe('Step 4 of 6');
    expect(screen.getByText(new RegExp(`^${expected} / ${ALL_MODULES.length}`))).toBeTruthy();
    expect(moduleSwitch('contracts').getAttribute('aria-checked')).toBe('true');
    expect(moduleSwitch('crm').getAttribute('aria-checked')).toBe('false');

    click('Continue');
    await heading('Data Setup');
    expect(stepLabel()).toBe('Step 5 of 6');
    click('Skip - set up later');

    await heading("You're All Set!");
    expect(stepLabel()).toBe('Step 6 of 6');
    expect(screen.getByText('General Contractor')).toBeTruthy();
    expect(screen.getByText(`${expected} modules`)).toBeTruthy();
    // Nothing is saved before the last click.
    expect(posts('/v1/users/me/onboarding/')).toHaveLength(0);

    await startWorking();

    const body = onboardingPost();
    expect(body.company_type).toBe('general_contractor');
    expect([...body.enabled_modules].sort()).toEqual([...GC_MODULES].sort());
    expect(body.completed).toBe(true);
    // No team size is asked for, so none is sent, and the stored one stays.
    expect('company_size' in body).toBe(false);
    expect('interface_mode' in body).toBe(false);

    // What the app is left with: the menu reads its profile from this cache
    // entry and its switches from the module-preferences read-back, the
    // dashboard reads `completed` from the same entry, and the Modules page
    // opens on the stored profile.
    expect(client.getQueryData(meOnboardingQueryKey(USER_ID))).toMatchObject({
      completed: true,
      company_type: 'general_contractor',
    });
    expect(api.apiGet.mock.calls.some(([p]) => p === '/v1/users/me/module-preferences/')).toBe(true);
    expect(localStorage.getItem('oe_company_type')).toBe('general_contractor');
    expect(localStorage.getItem('oe_onboarding_completed')).toBe('true');
    expect(posts('/v1/users/me/onboarding/complete/')).toHaveLength(1);
    expect(useViewModeStore.getState().mode).toBe('simple');
  });

  it('goes back one step at a time from the summary to the welcome screen, keeping the pick', async () => {
    renderWizard();
    await toProfileStep();
    fireEvent.click(screen.getByTestId('profile-card-subcontractor'));
    click('Continue');
    await heading('Your Modules');
    await fromModulesToSummary();

    click('Back');
    await heading('Data Setup');
    click('Back');
    await heading('Your Modules');
    expect(moduleSwitch('payroll').getAttribute('aria-checked')).toBe('true');
    click('Back');
    await heading('What does your company do?');
    expect(screen.getByTestId('profile-card-subcontractor').getAttribute('aria-pressed')).toBe('true');
    click('Back');
    await heading('How would you like to start?');
    click('Back');
    await heading('Welcome to OpenConstructionERP');

    // And forward again to the end, where the pick made at the start is saved.
    click(/Get Started/);
    await heading('How would you like to start?');
    click(/Choose Your Profile/);
    await heading('What does your company do?');
    expect(screen.getByTestId('profile-card-subcontractor').getAttribute('aria-pressed')).toBe('true');
    click('Continue');
    await heading('Your Modules');
    await fromModulesToSummary();
    await startWorking();
    expect(onboardingPost().company_type).toBe('subcontractor');
  });

  it('saves a job profile picked from the folded group as that profile', async () => {
    renderWizard();
    await toProfileStep();
    click(/Or pick by your role/);
    fireEvent.click(screen.getByTestId('profile-card-scheduler_planner'));
    click('Continue');
    await heading('Your Modules');
    await fromModulesToSummary();
    expect(screen.getByText('Planner / Scheduler')).toBeTruthy();
    await startWorking();

    const body = onboardingPost();
    expect(body.company_type).toBe('scheduler_planner');
    expect([...body.enabled_modules].sort()).toEqual(['eac', 'schedule', 'schedule_advanced']);
  });
});

describe('the ways out of the wizard', () => {
  it('Skip setup in the header goes to the summary and saves the whole platform', async () => {
    renderWizard();
    await heading('Welcome to OpenConstructionERP');
    // Not offered on the first screen, where there is nothing to skip past.
    expect(screen.queryByRole('button', { name: 'Skip setup' })).toBeNull();
    click(/Get Started/);
    await heading('How would you like to start?');
    click('Skip setup');

    await heading("You're All Set!");
    expect(screen.queryByRole('button', { name: 'Skip setup' })).toBeNull();
    await startWorking();

    const body = onboardingPost();
    expect(body.company_type).toBe('full_enterprise');
    expect(new Set(body.enabled_modules)).toEqual(new Set(NON_CORE));
    expect(localStorage.getItem('oe_company_type')).toBe('full_enterprise');
  });

  it('the English escape hatch leaves at once, marks the wizard done and saves no profile', async () => {
    renderWizard();
    await heading('Welcome to OpenConstructionERP');
    click('Skip setup - open in English');

    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/dashboard'));
    expect(changeLanguage).toHaveBeenLastCalledWith('en');
    expect(localStorage.getItem('oe_lang_explicit')).toBe('1');
    expect(localStorage.getItem('oe_onboarding_completed')).toBe('true');
    expect(posts('/v1/users/me/onboarding/complete/')).toHaveLength(1);
    expect(posts('/v1/users/me/onboarding/')).toHaveLength(0);
  });

  it('Quick Start skips the profile and module steps, Back returns to the start', async () => {
    renderWizard();
    await heading('Welcome to OpenConstructionERP');
    click(/Get Started/);
    await heading('How would you like to start?');
    click(/Quick Start/);

    await heading('Data Setup');
    expect(stepLabel()).toBe('Step 5 of 6');
    click('Back');
    await heading('How would you like to start?');

    click(/Quick Start/);
    await heading('Data Setup');
    click('Skip - set up later');
    await heading("You're All Set!");
    // The summary names the profile that is about to be saved, although none
    // was picked on the way here.
    expect(screen.getByText('Full Enterprise')).toBeTruthy();
    await startWorking();
    expect(onboardingPost().company_type).toBe('full_enterprise');
  });

  it('a wizard already finished on this browser sends the user straight to the app', async () => {
    localStorage.setItem('oe_onboarding_completed', 'true');
    renderWizard();
    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/'));
    expect(screen.queryByRole('heading', { name: 'Welcome to OpenConstructionERP' })).toBeNull();
  });
});

describe('module choices the user makes by hand survive Finish', () => {
  it('Configure individually saves the modules left on, with no profile', async () => {
    // Left over from an earlier run on this browser.
    localStorage.setItem('oe_company_type', 'general_contractor');
    renderWizard();
    await toProfileStep();
    click('Configure individually');
    await heading('Your Modules');
    // Nothing was picked, so everything starts on.
    expect(screen.getByText(new RegExp(`^${ALL_MODULES.length} / ${ALL_MODULES.length}`))).toBeTruthy();

    const finance = moduleSwitch('finance');
    fireEvent.click(finance);
    expect(finance.getAttribute('aria-checked')).toBe('false');

    await fromModulesToSummary();
    // No profile to name on the summary.
    expect(screen.queryByText('Full Enterprise')).toBeNull();
    await startWorking();

    const body = onboardingPost();
    // Not full_enterprise: the server pins that one to every module, and the
    // switch turned off above would come back on.
    expect(body.company_type).toBeNull();
    expect(body.enabled_modules).not.toContain('finance');
    expect(body.enabled_modules).toContain('boq');
    expect(localStorage.getItem('oe_company_type')).toBeNull();
  });

  it('Full Enterprise with a module switched off is saved as the modules chosen', async () => {
    renderWizard();
    await toProfileStep();
    fireEvent.click(screen.getByTestId('profile-card-full_enterprise'));
    click('Continue');
    await heading('Your Modules');
    fireEvent.click(moduleSwitch('crm'));

    await fromModulesToSummary();
    await startWorking();

    const body = onboardingPost();
    expect(body.company_type).toBeNull();
    expect(body.enabled_modules).not.toContain('crm');
    expect(body.enabled_modules).toContain('finance');
  });

  it('a picked profile keeps its name when the user trims its modules', async () => {
    renderWizard();
    await toProfileStep();
    fireEvent.click(screen.getByTestId('profile-card-general_contractor'));
    click('Continue');
    await heading('Your Modules');
    fireEvent.click(moduleSwitch('payroll'));

    await fromModulesToSummary();
    expect(screen.getByText(`${activeCount(GC_MODULES) - 1} modules`)).toBeTruthy();
    await startWorking();

    const body = onboardingPost();
    expect(body.company_type).toBe('general_contractor');
    expect(body.enabled_modules).not.toContain('payroll');
  });
});
