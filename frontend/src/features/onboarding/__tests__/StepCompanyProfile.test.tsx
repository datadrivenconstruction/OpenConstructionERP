// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The second step of the wizard asks what the company does. It used to ask how
// big the team was, and these tests hold the new question in place: the step
// shows business profiles, never size tiers, and it does not even fetch them.
//
// The pick is not the step's own state. The wizard owns companyType and
// enabledModules and hands them to the module step, so a test of the step on
// its own would prove a click fires a callback and nothing about what the user
// then reviews. These tests mount the whole wizard, walk it to the step, pick a
// profile and read the module step's switches, which is where a wrong module
// set would show.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, fireEvent, cleanup, waitFor } from '@testing-library/react';
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

// The welcome step switches the UI language as it mounts. The switch itself is
// not under test, and the real one would load a locale bundle.
vi.mock('@/app/i18n', async () => {
  const actual = await vi.importActual<typeof import('@/app/i18n')>('@/app/i18n');
  return { ...actual, changeLanguage: vi.fn(() => Promise.resolve()) };
});

import { OnboardingWizard } from '../OnboardingWizard';
import { COMPANY_PROFILE_ORDER } from '../profileGroups';

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
    tags: ['BOQ'],
    enabled_modules: enabled,
    module_count: enabled.length,
  };
}

// Served in backend order, which is not the order the step shows. One key is
// filed nowhere, the shape of a profile the backend adds before anyone sorts it.
const PRESETS: Preset[] = [
  preset('scheduler_planner', 'Planner / Scheduler', ['schedule', 'schedule_advanced', 'eac']),
  preset('mep_contractor', 'MEP / Building Services Contractor', ['boq', 'bim_hub', 'submittals']),
  preset('general_contractor', 'General Contractor', ['boq', 'costs', 'contracts', 'subcontractors']),
  preset('demolition_contractor', 'Demolition Contractor', ['boq', 'safety']),
  preset('subcontractor', 'Subcontractor / Trade Contractor', ['boq', 'costs', 'catalog', 'payroll']),
  preset('full_enterprise', 'Full Enterprise', ['boq']),
];

const SIZE_PRESETS: Preset[] = [preset('size_solo', 'Solo / Freelancer', ['boq'])];

function renderWizard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/onboarding']}>
        <OnboardingWizard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Welcome -> start choice -> the profile step. */
async function openProfileStep() {
  renderWizard();
  fireEvent.click(screen.getByRole('button', { name: /Get Started/ }));
  fireEvent.click(await screen.findByRole('button', { name: /Choose Your Profile/ }));
  await screen.findByRole('heading', { name: 'What does your company do?' });
  // The catalogue arrives after the first paint.
  await screen.findByTestId('profile-card-general_contractor');
}

/** The module step's switch for one module, found through the search box and
 *  then by the switch's own name, so a group header that reads the same as a
 *  module cannot answer for it. */
function moduleSwitch(key: string): HTMLElement {
  const search = screen.getByRole('searchbox', { name: 'Search modules' });
  fireEvent.change(search, { target: { value: key } });
  return screen.getByRole('switch', { name: key });
}

const sizeFetches = () =>
  api.apiGet.mock.calls.filter(([path]) => String(path).includes('/onboarding-presets/sizes/')).length;

beforeEach(() => {
  localStorage.clear();
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  api.apiGet.mockImplementation((path: string) => {
    if (path === '/v1/users/onboarding-presets/') return Promise.resolve(PRESETS);
    if (path === '/v1/users/onboarding-presets/sizes/') return Promise.resolve(SIZE_PRESETS);
    return Promise.resolve([]);
  });
  api.apiPost.mockResolvedValue({});
});

afterEach(() => cleanup());

describe('the profile step', () => {
  it('asks what the company does and offers businesses, not team sizes', async () => {
    await openProfileStep();

    expect(screen.queryByText('How big is your team?')).toBeNull();
    expect(screen.queryByText('Solo / Freelancer')).toBeNull();
    expect(screen.queryByTestId('profile-card-size_solo')).toBeNull();
    expect(sizeFetches()).toBe(0);

    // Businesses in the declared order, the unfiled key after them, and the
    // job profile nowhere in this group.
    const companies = within(screen.getByTestId('profile-companies'))
      .getAllByRole('button')
      .map((b) => b.getAttribute('data-testid'));
    const ordered = COMPANY_PROFILE_ORDER.filter((k) => PRESETS.some((p) => p.key === k));
    expect(companies).toEqual([
      ...ordered.map((k) => `profile-card-${k}`),
      'profile-card-demolition_contractor',
    ]);
    expect(screen.getByTestId('profile-card-full_enterprise')).toBeTruthy();
  });

  it('keeps job profiles in a folded group that opens on request', async () => {
    await openProfileStep();

    expect(screen.queryByTestId('profile-card-scheduler_planner')).toBeNull();
    const toggle = screen.getByRole('button', { name: /Or pick by your role/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');

    fireEvent.click(toggle);

    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    const roles = within(screen.getByTestId('profile-roles')).getAllByRole('button');
    expect(roles.map((b) => b.getAttribute('data-testid'))).toEqual(['profile-card-scheduler_planner']);

    // With a job profile picked the toggle still folds the group: it used to
    // be held open, and the button did nothing when clicked. The pick stays
    // named in the preview.
    fireEvent.click(screen.getByTestId('profile-card-scheduler_planner'));
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByTestId('profile-card-scheduler_planner')).toBeNull();
    expect(
      within(screen.getByTestId('profile-preview')).getByText('What Planner / Scheduler switches on'),
    ).toBeTruthy();
  });

  it('says on each card how many modules it turns on, and names them once picked', async () => {
    await openProfileStep();

    const card = screen.getByTestId('profile-card-subcontractor');
    // payroll plus the core modules, with costs and catalog (core, re-listed
    // by the preset) counted once.
    expect(within(card).getByText(/^\d+ modules$/)).toBeTruthy();
    expect(screen.queryByTestId('profile-preview')).toBeNull();
    const continueButton = screen.getByRole('button', { name: /Continue/ });
    expect((continueButton as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(card);

    expect(card.getAttribute('aria-pressed')).toBe('true');
    const preview = screen.getByTestId('profile-preview');
    expect(
      within(preview).getByText('What Subcontractor / Trade Contractor switches on'),
    ).toBeTruthy();
    // The preview names the profile's own modules; core ones sit in the
    // "always included" line rather than among them.
    expect(within(preview).getByText('Payroll')).toBeTruthy();
    expect(within(preview).queryByText('Catalog')).toBeNull();
    expect((continueButton as HTMLButtonElement).disabled).toBe(false);
  });

  it("hands the picked profile's modules to the module step, and a new pick replaces them", async () => {
    await openProfileStep();

    fireEvent.click(screen.getByTestId('profile-card-subcontractor'));
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
    await screen.findByRole('heading', { name: 'Your Modules' });

    expect(moduleSwitch('payroll').getAttribute('aria-checked')).toBe('true');
    expect(moduleSwitch('bim_hub').getAttribute('aria-checked')).toBe('false');

    fireEvent.click(screen.getByRole('button', { name: /Back/ }));
    await screen.findByRole('heading', { name: 'What does your company do?' });
    // The earlier pick is still marked on the way back.
    expect(screen.getByTestId('profile-card-subcontractor').getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(screen.getByTestId('profile-card-mep_contractor'));
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
    await screen.findByRole('heading', { name: 'Your Modules' });

    expect(moduleSwitch('bim_hub').getAttribute('aria-checked')).toBe('true');
    expect(moduleSwitch('payroll').getAttribute('aria-checked')).toBe('false');
  });

  it('opens the role group on the way back when a job profile was picked', async () => {
    await openProfileStep();

    fireEvent.click(screen.getByRole('button', { name: /Or pick by your role/ }));
    fireEvent.click(screen.getByTestId('profile-card-scheduler_planner'));
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
    await screen.findByRole('heading', { name: 'Your Modules' });
    expect(moduleSwitch('schedule_advanced').getAttribute('aria-checked')).toBe('true');

    fireEvent.click(screen.getByRole('button', { name: /Back/ }));
    await waitFor(() =>
      expect(
        screen.getByTestId('profile-card-scheduler_planner').getAttribute('aria-pressed'),
      ).toBe('true'),
    );
  });
});
