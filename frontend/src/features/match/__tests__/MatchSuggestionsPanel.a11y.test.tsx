// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * Axe-core accessibility check for MatchSuggestionsPanel.  Renders the
 * panel in three meaningful states (loading, empty, populated) and
 * asserts no violations on each so future regressions surface.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { axe, toHaveNoViolations } from 'jest-axe';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../api', () => ({
  matchElement: vi.fn(),
  submitMatchFeedback: vi.fn(),
}));

import { matchElement, submitMatchFeedback } from '../api';
import { MatchSuggestionsPanel } from '../MatchSuggestionsPanel';
import type { MatchResponse } from '../types';

expect.extend(toHaveNoViolations);

function makeResponse(): MatchResponse {
  return {
    request: {
      envelope: {
        source: 'bim',
        source_lang: 'en',
        category: 'wall',
        description: 'wall',
        properties: {},
        quantities: {},
        unit_hint: null,
        classifier_hint: null,
      },
      project_id: 'proj-1',
      top_k: 5,
      use_reranker: false,
    },
    candidates: [
      {
        code: '03.30.00',
        description: 'Concrete wall',
        unit: 'm2',
        unit_rate: 145.5,
        currency: 'EUR',
        score: 0.84,
        vector_score: 0.79,
        boosts_applied: { classifier_match: 0.05 },
        confidence_band: 'high',
        region_code: 'DE',
        source: 'cwicr',
        language: 'de',
        classification: { din276: '330' },
        reasoning: null,
      },
    ],
    translation_used: null,
    auto_linked: null,
    took_ms: 234,
    cost_usd: 0.0,
  };
}

function renderPanel(autoFetch = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MatchSuggestionsPanel
        source="bim"
        projectId="proj-1"
        rawElementData={{ description: 'wall' }}
        autoFetch={autoFetch}
      />
    </QueryClientProvider>,
  );
}

describe('MatchSuggestionsPanel — a11y', () => {
  beforeEach(() => {
    vi.mocked(matchElement).mockReset();
    vi.mocked(submitMatchFeedback).mockReset();
    vi.mocked(submitMatchFeedback).mockResolvedValue(undefined);
  });

  it('has no axe violations in the empty state', async () => {
    vi.mocked(matchElement).mockResolvedValue({
      ...makeResponse(),
      candidates: [],
    });
    const { container, findByTestId } = renderPanel();
    await findByTestId('match-empty-state');
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('has no axe violations in the populated state', async () => {
    vi.mocked(matchElement).mockResolvedValue(makeResponse());
    const { container, findByTestId } = renderPanel();
    await findByTestId('match-candidate-03.30.00');
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('has no axe violations in the loading state', async () => {
    vi.mocked(matchElement).mockImplementation(
      () => new Promise(() => {}),
    );
    const { container, findByTestId } = renderPanel();
    await findByTestId('match-skeleton-list');
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('has no axe violations when autoFetch is disabled', async () => {
    const { container } = renderPanel(false);
    await waitFor(() => {
      // No fetch should have been called.
      expect(matchElement).not.toHaveBeenCalled();
    });
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
