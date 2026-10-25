// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Moving between the wizard's steps: the stepper at the top opens every step
// the reader has reached, says why the others are closed, and stays usable
// while a ready-made pack installs in the background. Back and Next walk the
// same order the stepper shows.
//
// Run:  npx vitest run src/features/onboarding/__tests__/OnboardingStepper.test.tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { nextStep, previousStep, stepLock, STEP } from '../OnboardingStepper';

describe('which steps the stepper opens', () => {
  const reach = (over = {}) => ({ current: 1, maxReached: 1, packFlow: false, packReady: false, ...over });

  it('opens the steps already reached and closes the ones ahead', () => {
    expect(stepLock(0, reach())).toBeNull();
    expect(stepLock(1, reach())).toBeNull();
    expect(stepLock(2, reach())).toBe('ahead');
    expect(stepLock(6, reach())).toBe('ahead');
    expect(stepLock(4, reach({ current: 2, maxReached: 5 }))).toBeNull();
    expect(stepLock(6, reach({ current: 2, maxReached: 5 }))).toBe('ahead');
  });

  it('opens Profile, Modules and Appearance as soon as a pack install starts', () => {
    const r = reach({ packFlow: true });
    expect(stepLock(STEP.profile, r)).toBeNull();
    expect(stepLock(STEP.modules, r)).toBeNull();
    expect(stepLock(STEP.look, r)).toBeNull();
    // The pack brings its own data, and Finish must not overtake the install.
    expect(stepLock(STEP.data, r)).toBe('pack_data');
    expect(stepLock(STEP.finish, r)).toBe('pack_pending');
    expect(stepLock(STEP.finish, reach({ packFlow: true, packReady: true }))).toBeNull();
  });
});

describe('Next and Back', () => {
  it('Next skips Data after a pack install and only then', () => {
    expect(nextStep(STEP.look, false)).toBe(STEP.data);
    expect(nextStep(STEP.look, true)).toBe(STEP.finish);
    expect(nextStep(STEP.finish, false)).toBe(STEP.finish);
  });

  it('Back returns to the nearest step the reader was on', () => {
    const all = new Set([0, 1, 2, 3, 4, 5, 6]);
    expect(previousStep(6, all, false)).toBe(5);
    expect(previousStep(2, all, false)).toBe(1);
    expect(previousStep(1, all, false)).toBe(0);
    // Quick Start went from Start to Data without showing Profile and Modules.
    expect(previousStep(5, new Set([0, 1, 5]), false)).toBe(1);
    // After a pack install Data is not part of the way back.
    expect(previousStep(6, new Set([0, 1, 5, 6]), true)).toBe(1);
    expect(previousStep(6, new Set([0, 1, 4, 6]), true)).toBe(4);
  });
});

// ── The whole wizard ───────────────────────────────────────────────────────

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPatch: vi.fn(), apiDelete: vi.fn() }));
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual('@/shared/lib/api');
  return { ...actual, ...api };
});
const changeLanguage = vi.hoisted(() => vi.fn(() => Promise.resolve()));
vi.mock('@/app/i18n', async () => {
  const actual = await vi.importActual('@/app/i18n');
  return { ...actual, changeLanguage };
});
vi.mock('@/features/ai-estimator/api', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    aiEstimatorApi: {
      ...actual.aiEstimatorApi,
      embeddingModelStatus: vi.fn().mockRejectedValue(new Error('not in this test')),
      installEmbeddingModel: vi.fn(),
    },
  };
});
vi.mock('@/features/costs/baseCatalog', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useBaseCatalog: () => ({ data: undefined }) };
});
const { fetchInstalledPacks, fullInstallPackStream } = vi.hoisted(() => ({
  fetchInstalledPacks: vi.fn(),
  fullInstallPackStream: vi.fn(),
}));
vi.mock('../partnerPacksApi', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, fetchInstalledPacks, fullInstallPackStream };
});

import { OnboardingWizard } from '../OnboardingWizard';
import { useAuthStore } from '@/stores/useAuthStore';
import { useBackgroundInstallStore } from '@/stores/useBackgroundInstallStore';

const PACKS = [
  {
    slug: 'germany-de',
    type: 'country',
    partner_name: 'Germany Construction Pack',
    partner_url: null,
    pack_version: '1.0.0',
    description: '',
    default_locale: 'de',
    additional_locales: [],
    cwicr_regions: [],
    default_currency: 'EUR',
    default_tax_template: null,
    validation_rule_packs: [],
    default_modules: [],
    hidden_modules: [],
    branding: {},
    has_onboarding_script: false,
    metadata: { country: 'DE' },
  },
];

let releaseStream;
let languageReady;

beforeEach(() => {
  localStorage.clear();
  useBackgroundInstallStore.getState().dismiss();
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  fullInstallPackStream.mockReset();
  fetchInstalledPacks.mockResolvedValue({ installed: PACKS });
  api.apiGet.mockImplementation((path) => {
    if (path === '/v1/users/onboarding-presets/') return Promise.resolve([]);
    if (path === '/v1/users/me/onboarding/') return Promise.resolve({ completed: false, company_type: null });
    return Promise.reject(new Error(`no fake for GET ${path}`));
  });
  api.apiPost.mockResolvedValue({});
  // An install whose language step is released by the test and whose stream
  // stays open afterwards, the way a real cost database load does.
  languageReady = null;
  fullInstallPackStream.mockImplementation(
    (_slug, onEvent) =>
      new Promise((resolve) => {
        languageReady = () => onEvent({ type: 'step_done', step: 'locale', status: 'ok', detail: { locale: 'de' } });
        releaseStream = resolve;
      }),
  );
  useAuthStore.setState({ isAuthenticated: true, userRole: 'admin', userId: 'u1' });
});

afterEach(() => {
  releaseStream?.();
  cleanup();
});

function renderWizard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/onboarding']}>
        <Routes>
          <Route path="/onboarding" element={<OnboardingWizard />} />
          <Route path="*" element={<span data-testid="elsewhere" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const heading = (name) => screen.findByRole('heading', { name });
const step = (i) => screen.getByTestId(`onboarding-step-${i}`);
const locked = (i) => step(i).getAttribute('aria-disabled') === 'true';

async function startPackInstall() {
  await heading('Welcome to OpenConstructionERP');
  fireEvent.click(screen.getByRole('button', { name: /Get Started/ }));
  await heading('How would you like to start?');
  fireEvent.click(screen.getByRole('button', { name: /Ready-made Pack/ }));
  fireEvent.click(await screen.findByTestId('ready-pack-tile-germany-de'));
  fireEvent.click(screen.getByTestId('ready-pack-install'));
  await waitFor(() => expect(fullInstallPackStream).toHaveBeenCalledTimes(1));
}

describe('the stepper in the wizard', () => {
  it('is a labelled list of buttons that marks the current step and closes the ones ahead', async () => {
    renderWizard();
    await heading('Welcome to OpenConstructionERP');
    expect(screen.getByRole('navigation', { name: 'Setup steps' })).toBeTruthy();
    expect(step(0).getAttribute('aria-current')).toBe('step');
    expect(step(1).getAttribute('aria-current')).toBeNull();
    expect(locked(1)).toBe(true);
    expect(step(3).getAttribute('title')).toBe('Finish the earlier steps first');
    // A closed step does nothing.
    fireEvent.click(step(3));
    expect(screen.getByRole('heading', { name: 'Welcome to OpenConstructionERP' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /Get Started/ }));
    await heading('How would you like to start?');
    expect(step(1).getAttribute('aria-current')).toBe('step');
    expect(locked(0)).toBe(false);
    // Back to the welcome screen by its dot, and forward again by the same.
    fireEvent.click(step(0));
    await heading('Welcome to OpenConstructionERP');
    expect(locked(1)).toBe(false);
    fireEvent.click(step(1));
    await heading('How would you like to start?');
  });

  it('opens Appearance while the pack installs, and keeps the one install', async () => {
    renderWizard();
    await startPackInstall();

    // Language is not ready yet: the look and the profile are open, Finish is
    // closed and says why, Data belongs to the pack.
    expect(locked(2)).toBe(false);
    expect(locked(3)).toBe(false);
    expect(locked(4)).toBe(false);
    expect(locked(5)).toBe(true);
    expect(locked(6)).toBe(true);
    expect(step(6).getAttribute('title')).toBe('Available once your pack has applied its language');
    expect(screen.getByTestId('ready-pack-finish').disabled).toBe(true);

    fireEvent.click(step(4));
    await heading('How your platform will look');
    expect(useBackgroundInstallStore.getState().install).not.toBeNull();

    // Back to the pack step: the same install, no second one, no grid.
    fireEvent.click(step(1));
    await screen.findByTestId('ready-pack-confirm');
    expect(screen.queryByTestId('ready-pack-install')).toBeNull();
    expect(fullInstallPackStream).toHaveBeenCalledTimes(1);

    // The language lands while the reader is on another step.
    fireEvent.click(step(2));
    await heading('What does your company do?');
    languageReady();
    await waitFor(() => expect(locked(6)).toBe(false));
    expect(screen.getByRole('heading', { name: 'What does your company do?' })).toBeTruthy();
  });

  it('offers Adjust appearance and Finish after the pack instead of forcing Finish', async () => {
    renderWizard();
    await startPackInstall();
    languageReady();

    await waitFor(() => expect(screen.getByTestId('ready-pack-finish').disabled).toBe(false));
    // The reader is still on the pack step.
    expect(step(1).getAttribute('aria-current')).toBe('step');

    fireEvent.click(screen.getByTestId('ready-pack-adjust-look'));
    await heading('How your platform will look');
    // Next after a pack skips Data and goes to Finish; Back returns to the look.
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }));
    await heading("You're All Set!");
    expect(step(6).getAttribute('aria-current')).toBe('step');
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    await heading('How your platform will look');
    expect(fullInstallPackStream).toHaveBeenCalledTimes(1);
  });

  it('goes straight to Finish from the pack step on request, and Back returns to it', async () => {
    renderWizard();
    await startPackInstall();
    languageReady();
    await waitFor(() => expect(screen.getByTestId('ready-pack-finish').disabled).toBe(false));
    fireEvent.click(screen.getByTestId('ready-pack-finish'));
    await heading("You're All Set!");
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    await screen.findByTestId('ready-pack-confirm');
  });
});
