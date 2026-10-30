// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What one tap on Continue in the data step leaves behind: the demo the toggle
// has on, the reader's own language, and the market's currency on the account.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPatch: vi.fn() }));
vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return { ...actual, ...api };
});

const changeLanguage = vi.hoisted(() => vi.fn(() => Promise.resolve()));
vi.mock('@/app/i18n', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/app/i18n')>();
  return { ...actual, changeLanguage, detectCountryForLanguage: () => 'in' };
});

vi.mock('@/features/ai-estimator/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/ai-estimator/api')>();
  return {
    ...actual,
    aiEstimatorApi: {
      ...actual.aiEstimatorApi,
      embeddingModelStatus: vi.fn().mockRejectedValue(new Error('off')),
      installEmbeddingModel: vi.fn(),
    },
  };
});
vi.mock('@/features/costs/baseCatalog', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/costs/baseCatalog')>();
  return { ...actual, useBaseCatalog: () => ({ data: undefined }) };
});

import { StepDataSetup } from '../OnboardingWizard';
import { usePreferencesStore } from '@/stores/usePreferencesStore';

let accountCurrency = '';

function renderStep() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onNext = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <StepDataSetup onNext={onNext} onBack={() => undefined} selectedLang="en" backgroundLoad />
    </QueryClientProvider>,
  );
  return onNext;
}

const demoPosts = () => api.apiPost.mock.calls.filter(([p]) => String(p).startsWith('/demo/install/'));
const currencyPatches = () =>
  api.apiPatch.mock.calls.filter(([p, body]) => p === '/v1/users/me/preferences/' && body?.currency_code);

beforeEach(() => {
  localStorage.clear();
  accountCurrency = '';
  usePreferencesStore.getState().resetPreferences();
  changeLanguage.mockClear();
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  api.apiPatch.mockReset();
  api.apiGet.mockImplementation((path: string) =>
    path === '/v1/users/me/preferences/'
      ? Promise.resolve({ currency_code: accountCurrency })
      : Promise.reject(new Error(`no fake for GET ${path}`)),
  );
  // The cost-base job never finishes here; only what Continue starts matters.
  api.apiPost.mockImplementation((path: string) =>
    String(path).startsWith('/demo/install/') ? Promise.resolve({}) : new Promise(() => undefined),
  );
  api.apiPatch.mockResolvedValue({});
});

describe('StepDataSetup, one tap on Continue', () => {
  it('installs the demo the toggle has on while the base loads in the background', async () => {
    const onNext = renderStep();
    fireEvent.click(await screen.findByRole('button', { name: /^Continue/ }));
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    await waitFor(() => expect(demoPosts()).toHaveLength(1));
  });

  it('installs no demo when the reader switched it off', async () => {
    const onNext = renderStep();
    const toggles = await screen.findAllByRole('switch', { name: /Install Demo Project/ });
    fireEvent.click(toggles[0]!);
    fireEvent.click(screen.getByRole('button', { name: /^Continue/ }));
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(demoPosts()).toHaveLength(0);
  });

  it("keeps the reader's language instead of the market preset's", async () => {
    const onNext = renderStep();
    fireEvent.click(await screen.findByRole('button', { name: /^Continue/ }));
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(changeLanguage).not.toHaveBeenCalled();
  });

  it("puts the market's currency on an account that has none", async () => {
    const onNext = renderStep();
    fireEvent.click(await screen.findByRole('button', { name: /^Continue/ }));
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    await waitFor(() => expect(currencyPatches()).toHaveLength(1));
    expect(currencyPatches()[0]![1]).toEqual({ currency_code: 'INR' });
    await waitFor(() => expect(usePreferencesStore.getState().currency).toBe('INR'));
  });

  it('never overwrites a currency the account already chose', async () => {
    accountCurrency = 'USD';
    const onNext = renderStep();
    fireEvent.click(await screen.findByRole('button', { name: /^Continue/ }));
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    await waitFor(() => expect(api.apiGet).toHaveBeenCalledWith('/v1/users/me/preferences/'));
    expect(currencyPatches()).toHaveLength(0);
  });
});
