// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Picking a national market card in onboarding (the Turkish base priced into
// Paris, in French) used to store the card's region, which is the home base,
// so the job installed the plain Turkish base and the French text never
// landed. The pick now loads the base and then runs the market load for the
// card. When that second step fails the base is already in, so the wizard must
// keep the failure and a retry on screen rather than show the base as ready.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const { followCostDbLoad, loadBaseMarket, embeddingModelStatus } = vi.hoisted(() => ({
  followCostDbLoad: vi.fn(),
  loadBaseMarket: vi.fn(),
  embeddingModelStatus: vi.fn(),
}));

function variant(over = {}) {
  return {
    region: 'TR_NATIONAL',
    variant_id: 'TR_NATIONAL',
    base_region: 'TR_NATIONAL',
    market_catalog: '',
    active: false,
    market: 'Turkiye',
    city: 'National',
    language: 'Turkce',
    lang_code: 'tr',
    text_lang_code: 'tr',
    currency: 'TRY',
    flag: 'tr',
    positions: 22494,
    bundled: true,
    coefficient: false,
    loaded: false,
    loaded_positions: 0,
    ...over,
  };
}

const HOME = variant();
const PARIS = variant({
  variant_id: 'TR_NATIONAL:FR_PARIS_fr',
  market_catalog: 'FR_PARIS_fr',
  market: 'France',
  city: 'Paris',
  language: 'Francais',
  lang_code: 'fr',
  text_lang_code: 'fr',
  currency: 'EUR',
  flag: 'fr',
});

const CATALOG = {
  repo: 'x',
  total_bases: 2,
  total_families: 1,
  loaded_regions: [],
  families: [
    {
      // Keyed "china" so the family starts expanded.
      key: 'china',
      name: 'Turkiye (Birim Fiyat)',
      norm_system: 'Birim Fiyat',
      origin: 'Turkiye',
      origin_flag: 'tr',
      description: '',
      market_count: 2,
      repriceable_markets: 49,
      positions: 22494,
      loaded_count: 0,
      variants: [HOME, PARIS],
    },
  ],
};

vi.mock('@/features/ai-estimator/api', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    aiEstimatorApi: { ...actual.aiEstimatorApi, embeddingModelStatus, installEmbeddingModel: vi.fn() },
  };
});

vi.mock('@/features/costs/baseCatalog', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useBaseCatalog: () => ({ data: CATALOG }), loadBaseMarket };
});

vi.mock('../costDbLoad', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, followCostDbLoad };
});

import { StepDataSetup } from '../OnboardingWizard';

function renderStep() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StepDataSetup onNext={vi.fn()} onBack={() => undefined} selectedLang="en" backgroundLoad={false} />
    </QueryClientProvider>,
  );
}

async function clickParisCard() {
  const cards = await screen.findAllByTestId('base-variant-card');
  fireEvent.click(cards.find((el) => el.textContent?.includes('Paris')));
}

describe('StepDataSetup, a national market card', () => {
  beforeEach(() => {
    followCostDbLoad.mockReset();
    loadBaseMarket.mockReset();
    embeddingModelStatus.mockResolvedValue({ state: 'not_requested', enabled: false });
    followCostDbLoad.mockResolvedValue({
      outcome: 'completed',
      job: { id: 'j', kind: 'onboarding.load_cwicr', state: 'success', outcome: 'completed', pct: 100, total: 22494 },
    });
  });

  it('loads the base and then prices it into the picked card', async () => {
    loadBaseMarket.mockResolvedValue({ text_language: 'fr', text_language_requested: 'fr' });
    renderStep();

    await clickParisCard();
    fireEvent.click(screen.getByRole('button', { name: /Load Database/i }));

    await waitFor(() => expect(loadBaseMarket).toHaveBeenCalledTimes(1));
    expect(followCostDbLoad.mock.calls[0][0]).toBe('TR_NATIONAL');
    expect(loadBaseMarket.mock.calls[0][0].variant_id).toBe('TR_NATIONAL:FR_PARIS_fr');
  });

  it('keeps a failed market step on screen with its reason and a retry', async () => {
    loadBaseMarket.mockRejectedValueOnce(new Error("The 'fr' text of 'TR_NATIONAL' could not be loaded"));
    loadBaseMarket.mockResolvedValueOnce({ text_language: 'fr', text_language_requested: 'fr' });
    renderStep();

    await clickParisCard();
    fireEvent.click(screen.getByRole('button', { name: /Load Database/i }));

    const failed = await screen.findByTestId('onboarding-market-failed');
    expect(failed.textContent).toMatch(/could not be loaded/);
    fireEvent.click(screen.getByRole('button', { name: /Retry/i }));

    await waitFor(() => expect(loadBaseMarket).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByTestId('onboarding-market-failed')).toBeNull());
  });
});
