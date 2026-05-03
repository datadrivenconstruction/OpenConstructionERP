// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * Phase 4 Accept-flow tests for MatchSuggestionsPanel.
 *
 * Strategy:
 *   - Stub `./api` so we control matchElement / submitMatchFeedback /
 *     acceptMatch deterministically.
 *   - Drive the panel through accept, auto-apply, and error flows.
 *   - The Phase 2 panel test file
 *     (`MatchSuggestionsPanel.test.tsx`) already covers the rendering
 *     contract — we only add scenarios that touch the BOQ wiring.
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
// pick up the spy.
vi.mock('../api', () => ({
  matchElement: vi.fn(),
  submitMatchFeedback: vi.fn(),
  acceptMatch: vi.fn(),
}));

import { matchElement, submitMatchFeedback, acceptMatch } from '../api';
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
    boosts_applied: { classifier_match: 0.05 },
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
        quantities: { area_m2: 37.5 },
        unit_hint: null,
        classifier_hint: null,
      },
      project_id: 'proj-1',
      top_k: 5,
      use_reranker: false,
    },
    candidates: [makeCandidate()],
    translation_used: null,
    auto_linked: null,
    took_ms: 234,
    cost_usd: 0.0,
    ...over,
  };
}

function renderPanel(
  props: Partial<React.ComponentProps<typeof MatchSuggestionsPanel>> = {},
) {
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

describe('MatchSuggestionsPanel — Phase 4 BOQ wiring', () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.mocked(matchElement).mockReset();
    vi.mocked(submitMatchFeedback).mockReset();
    vi.mocked(submitMatchFeedback).mockResolvedValue(undefined);
    vi.mocked(acceptMatch).mockReset();
    vi.mocked(acceptMatch).mockResolvedValue({
      position_id: 'pos-1',
      position_ordinal: 'AI-001',
      created: true,
      cost_link_created: true,
      bim_link_created: false,
      audit_entry_id: 'audit-1',
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('forwards the accepted candidate to the parent onAccept handler', async () => {
    vi.mocked(matchElement).mockResolvedValue(makeResponse());
    const onAccept = vi.fn().mockResolvedValue(undefined);

    renderPanel({ onAccept });

    const acceptBtn = await screen.findByTestId('match-accept-03.30.00');
    fireEvent.click(acceptBtn);

    await waitFor(() => {
      expect(onAccept).toHaveBeenCalledTimes(1);
    });
    expect(onAccept.mock.calls[0][0]).toMatchObject({ code: '03.30.00' });

    // Feedback still fires alongside the parent handler.
    await waitFor(() => {
      expect(submitMatchFeedback).toHaveBeenCalledTimes(1);
    });
  });

  it('does not auto-apply auto_linked when autoApplyLinks is false', async () => {
    const top = makeCandidate();
    vi.mocked(matchElement).mockResolvedValue(
      makeResponse({ auto_linked: top, candidates: [top] }),
    );
    const onAccept = vi.fn().mockResolvedValue(undefined);

    renderPanel({ onAccept, autoApplyLinks: false });

    // Banner is visible …
    expect(
      await screen.findByTestId('match-auto-linked-banner'),
    ).toBeInTheDocument();

    // … but onAccept is never called automatically.
    await new Promise((r) => setTimeout(r, 100));
    expect(onAccept).not.toHaveBeenCalled();
  });

  it('auto-applies auto_linked candidate after the confirmation delay', async () => {
    const top = makeCandidate({ code: 'AUTO-1' });
    vi.mocked(matchElement).mockResolvedValue(
      makeResponse({ auto_linked: top, candidates: [top] }),
    );
    const onAccept = vi.fn().mockResolvedValue(undefined);

    renderPanel({ onAccept, autoApplyLinks: true });

    await screen.findByTestId('match-candidate-AUTO-1');

    // Auto-apply fires after AUTO_APPLY_DELAY_MS (1500 ms). We allow
    // the natural delay plus a small slack — the test stays under
    // vitest's default 5 s timeout.
    await waitFor(
      () => {
        expect(onAccept).toHaveBeenCalledTimes(1);
      },
      { timeout: 4000 },
    );
    expect(onAccept.mock.calls[0][0]).toMatchObject({ code: 'AUTO-1' });
  }, 8000);

  it('does not auto-apply when the user already rejected the auto_linked candidate', async () => {
    const top = makeCandidate({ code: 'AUTO-2' });
    vi.mocked(matchElement).mockResolvedValue(
      makeResponse({
        auto_linked: top,
        candidates: [top, makeCandidate({ code: 'OTHER' })],
      }),
    );
    const onAccept = vi.fn().mockResolvedValue(undefined);

    renderPanel({ onAccept, autoApplyLinks: true });

    await screen.findByTestId('match-candidate-AUTO-2');

    // User rejects the auto-link target *before* the 1.5 s timer fires.
    fireEvent.click(screen.getByTestId('match-reject-AUTO-2'));

    // Wait past the auto-apply window with a small slack to be sure
    // the cancelled timer never fires onAccept.
    await new Promise((r) => setTimeout(r, 2000));
    expect(onAccept).not.toHaveBeenCalled();
  }, 8000);
});
