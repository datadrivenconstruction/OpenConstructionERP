// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * Unit tests for MatchSuggestionsPanel.
 *
 * Strategy: stub the `./api` module so we control the network layer
 * deterministically, then drive the panel through accept/reject/refresh
 * flows via Testing Library.  React Query is wrapped via a fresh
 * QueryClient per test with retry disabled so errors surface immediately.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Mock the api module BEFORE importing the panel so the queries hooks
// pick up the spy.  The project's test setup also mocks i18next and
// react-router-dom globally (see src/test/setup.ts).
vi.mock('../api', () => ({
  matchElement: vi.fn(),
  submitMatchFeedback: vi.fn(),
}));

import { matchElement, submitMatchFeedback } from '../api';
import { MatchSuggestionsPanel } from '../MatchSuggestionsPanel';
import type { MatchResponse, MatchCandidate } from '../types';

/* ── Fixtures ──────────────────────────────────────────────────────────── */

function makeCandidate(over: Partial<MatchCandidate> = {}): MatchCandidate {
  return {
    code: '03.30.00',
    description: 'Concrete C30/37 wall, 240mm thick',
    unit: 'm2',
    unit_rate: 145.5,
    currency: 'EUR',
    score: 0.84,
    vector_score: 0.79,
    boosts_applied: { classifier_match: 0.05, unit_match: 0.0 },
    confidence_band: 'high',
    region_code: 'DE',
    source: 'cwicr',
    language: 'de',
    classification: { din276: '330' },
    reasoning: null,
    ...over,
  };
}

function makeResponse(over: Partial<MatchResponse> = {}): MatchResponse {
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
      makeCandidate(),
      makeCandidate({
        code: '04.20.00',
        description: 'Masonry wall',
        score: 0.62,
        confidence_band: 'medium',
      }),
      makeCandidate({
        code: '07.10.00',
        description: 'Insulation wrap',
        score: 0.28,
        confidence_band: 'low',
      }),
    ],
    translation_used: null,
    auto_linked: null,
    took_ms: 234,
    cost_usd: 0.0,
    ...over,
  };
}

function renderPanel(props: Partial<React.ComponentProps<typeof MatchSuggestionsPanel>> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MatchSuggestionsPanel
        source="bim"
        projectId="proj-1"
        rawElementData={{ description: 'wall' }}
        autoFetch
        {...props}
      />
    </QueryClientProvider>,
  );
}

/* ── Tests ─────────────────────────────────────────────────────────────── */

describe('MatchSuggestionsPanel', () => {
  beforeEach(() => {
    vi.mocked(matchElement).mockReset();
    vi.mocked(submitMatchFeedback).mockReset();
    vi.mocked(submitMatchFeedback).mockResolvedValue(undefined);
  });

  afterEach(() => {
    cleanup();
  });

  it('renders the skeleton list while the match request is in flight', async () => {
    // Hold the promise open so the mutation stays pending.
    let resolvePromise!: (r: MatchResponse) => void;
    vi.mocked(matchElement).mockImplementation(
      () => new Promise<MatchResponse>((res) => { resolvePromise = res; }),
    );

    renderPanel();

    expect(await screen.findByTestId('match-skeleton-list')).toBeInTheDocument();

    // Cleanup: resolve the pending promise so React Query doesn't leak.
    resolvePromise(makeResponse({ candidates: [] }));
  });

  it('renders the empty state when the response has no candidates', async () => {
    vi.mocked(matchElement).mockResolvedValue(makeResponse({ candidates: [] }));

    renderPanel();

    expect(await screen.findByTestId('match-empty-state')).toBeInTheDocument();
    expect(
      screen.getByText('No matches found yet'),
    ).toBeInTheDocument();
  });

  it('renders candidate cards with their codes when results arrive', async () => {
    vi.mocked(matchElement).mockResolvedValue(makeResponse());

    renderPanel();

    expect(await screen.findByTestId('match-candidate-03.30.00')).toBeInTheDocument();
    expect(screen.getByTestId('match-candidate-04.20.00')).toBeInTheDocument();
    expect(screen.getByTestId('match-candidate-07.10.00')).toBeInTheDocument();
  });

  it('applies the high/medium/low confidence pill classes per band', async () => {
    vi.mocked(matchElement).mockResolvedValue(makeResponse());

    renderPanel();

    await screen.findByTestId('match-candidate-03.30.00');

    // Confidence pills are rendered with band-specific Tailwind classes; we
    // assert by aria-label which the component sets via translation.
    const high = screen.getAllByLabelText(/High confidence/i)[0];
    const medium = screen.getAllByLabelText(/Medium confidence/i)[0];
    const low = screen.getAllByLabelText(/Low confidence/i)[0];
    expect(high).toBeTruthy();
    expect(medium).toBeTruthy();
    expect(low).toBeTruthy();
  });

  it('calls onAccept and fires the feedback mutation when Accept is clicked', async () => {
    vi.mocked(matchElement).mockResolvedValue(makeResponse());
    const onAccept = vi.fn();

    renderPanel({ onAccept });

    const acceptBtn = await screen.findByTestId('match-accept-03.30.00');
    fireEvent.click(acceptBtn);

    await waitFor(() => {
      expect(onAccept).toHaveBeenCalledTimes(1);
    });
    expect(onAccept.mock.calls[0][0].code).toBe('03.30.00');

    // Feedback mutation must be invoked with that candidate as accepted.
    await waitFor(() => {
      expect(submitMatchFeedback).toHaveBeenCalledTimes(1);
    });
    const fbBody = vi.mocked(submitMatchFeedback).mock.calls[0][0];
    expect(fbBody.accepted_candidate?.code).toBe('03.30.00');
    expect(fbBody.user_chose_code).toBe('03.30.00');
    expect(fbBody.rejected_candidates).toEqual([]);
  });

  it('Reject hides the candidate locally without calling onAccept or feedback', async () => {
    vi.mocked(matchElement).mockResolvedValue(makeResponse());
    const onAccept = vi.fn();

    renderPanel({ onAccept });

    const rejectBtn = await screen.findByTestId('match-reject-04.20.00');
    fireEvent.click(rejectBtn);

    await waitFor(() => {
      expect(screen.queryByTestId('match-candidate-04.20.00')).toBeNull();
    });
    expect(onAccept).not.toHaveBeenCalled();
    expect(submitMatchFeedback).not.toHaveBeenCalled();
  });

  it('accumulates rejected codes and forwards them on accept', async () => {
    vi.mocked(matchElement).mockResolvedValue(makeResponse());

    renderPanel();

    fireEvent.click(await screen.findByTestId('match-reject-04.20.00'));
    fireEvent.click(await screen.findByTestId('match-reject-07.10.00'));
    fireEvent.click(await screen.findByTestId('match-accept-03.30.00'));

    await waitFor(() => {
      expect(submitMatchFeedback).toHaveBeenCalledTimes(1);
    });
    const fbBody = vi.mocked(submitMatchFeedback).mock.calls[0][0];
    const rejectedCodes = fbBody.rejected_candidates.map((c) => c.code).sort();
    expect(rejectedCodes).toEqual(['04.20.00', '07.10.00']);
  });

  it('toggles the AI reranker and re-fires the match call with use_reranker=true', async () => {
    vi.mocked(matchElement).mockResolvedValue(makeResponse());

    renderPanel();

    // Wait for the initial call to settle.
    await screen.findByTestId('match-candidate-03.30.00');
    expect(matchElement).toHaveBeenCalledTimes(1);
    expect(vi.mocked(matchElement).mock.calls[0][0].use_reranker).toBe(false);

    fireEvent.click(screen.getByTestId('match-rerank-toggle'));

    await waitFor(() => {
      expect(matchElement).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(matchElement).mock.calls[1][0].use_reranker).toBe(true);
  });

  it('refresh button re-fires the match call', async () => {
    vi.mocked(matchElement).mockResolvedValue(makeResponse());

    renderPanel();

    await screen.findByTestId('match-candidate-03.30.00');
    expect(matchElement).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId('match-refresh-button'));

    await waitFor(() => {
      expect(matchElement).toHaveBeenCalledTimes(2);
    });
  });

  it('reveals the boost breakdown tooltip on hover of the score badge', async () => {
    vi.mocked(matchElement).mockResolvedValue(makeResponse());

    renderPanel();

    const badge = await screen.findByTestId('match-score-badge-03.30.00');
    fireEvent.mouseEnter(badge.parentElement!);

    await waitFor(() => {
      expect(
        screen.getByTestId('match-boosts-tooltip-03.30.00'),
      ).toBeInTheDocument();
    });
    expect(screen.getByText('classifier_match')).toBeInTheDocument();
    expect(screen.getByText('+0.05')).toBeInTheDocument();
  });

  it('compact mode hides the unit / unit-rate row', async () => {
    vi.mocked(matchElement).mockResolvedValue(makeResponse());

    renderPanel({ compact: true });

    await screen.findByTestId('match-candidate-03.30.00');
    // In compact mode the per-unit string is not rendered.
    expect(screen.queryByText(/per m2/i)).toBeNull();
  });

  it('shows the auto-linked banner when response.auto_linked is set', async () => {
    const top = makeCandidate({ code: '99.99.99', description: 'top match' });
    vi.mocked(matchElement).mockResolvedValue(
      makeResponse({ auto_linked: top, candidates: [top] }),
    );

    renderPanel();

    expect(
      await screen.findByTestId('match-auto-linked-banner'),
    ).toBeInTheDocument();
  });

  it('shows the translation chip when translation_used.tier_used != fallback', async () => {
    vi.mocked(matchElement).mockResolvedValue(
      makeResponse({
        translation_used: {
          translated: 'wall',
          source_lang: 'de',
          target_lang: 'en',
          tier_used: 'lookup_muse',
          confidence: 1.0,
          cost_usd: null,
        },
      }),
    );

    renderPanel();

    expect(
      await screen.findByTestId('match-translation-chip'),
    ).toBeInTheDocument();
  });

  it('does NOT show the translation chip when tier_used is fallback', async () => {
    vi.mocked(matchElement).mockResolvedValue(
      makeResponse({
        translation_used: {
          translated: 'wall',
          source_lang: 'en',
          target_lang: 'en',
          tier_used: 'fallback',
          confidence: 0.0,
          cost_usd: null,
        },
      }),
    );

    renderPanel();

    await screen.findByTestId('match-candidate-03.30.00');
    expect(screen.queryByTestId('match-translation-chip')).toBeNull();
  });

  it('renders the rerank reasoning when provided', async () => {
    vi.mocked(matchElement).mockResolvedValue(
      makeResponse({
        candidates: [
          makeCandidate({ reasoning: 'Strong unit match (m2 ↔ m2).' }),
        ],
      }),
    );

    renderPanel();

    expect(
      await screen.findByTestId('match-reasoning-03.30.00'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Strong unit match (m2 ↔ m2).'),
    ).toBeInTheDocument();
  });

  it('does not auto-fetch when autoFetch=false', async () => {
    vi.mocked(matchElement).mockResolvedValue(makeResponse());

    renderPanel({ autoFetch: false });

    // Give React's effects a tick to settle.
    await new Promise((r) => setTimeout(r, 0));
    expect(matchElement).not.toHaveBeenCalled();
  });

  it('uses topK in the outgoing request body', async () => {
    vi.mocked(matchElement).mockResolvedValue(makeResponse());

    renderPanel({ topK: 12 });

    await screen.findByTestId('match-candidate-03.30.00');
    expect(vi.mocked(matchElement).mock.calls[0][0].top_k).toBe(12);
  });
});
