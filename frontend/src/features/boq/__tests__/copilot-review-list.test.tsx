// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The position copilot asks before it changes anything.
 *
 * Chat returns suggestions only; the review list decides what lands. These
 * tests pin the contract the estimator relies on: a chat turn writes nothing
 * and mirrors nothing into the grid, confident suggestions arrive checked but
 * unapplied, and only the suggestions the user accepts are sent to the review
 * endpoint, by index.
 */
import { describe, it, expect, vi, afterEach, beforeAll } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement } from 'react';

import { AIPositionCopilot } from '../AIPositionCopilot';
import { boqApi, type CopilotAction, type Position } from '../api';

beforeAll(() => {
  // jsdom has no scrollIntoView; the dock scrolls to the newest message.
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const POSITION = {
  id: 'pos-1',
  boq_id: 'boq-1',
  ordinal: '01.001',
  description: 'Concrete wall',
  unit: 'm3',
  quantity: 10,
  unit_rate: 100,
  total: 1000,
  metadata: {},
} as unknown as Position;

function action(
  action_type: CopilotAction['action_type'],
  payload: Record<string, unknown>,
  confidence: number,
): CopilotAction {
  return { action_type, payload, before: {}, confidence, source: null, status: 'needs_review' };
}

const ACTIONS: CopilotAction[] = [
  action('update_description', { description: 'RC wall C30/37' }, 0.95),
  action('set_quantity', { quantity: 42 }, 0.7),
];

function renderCopilot(onReviewApplied = vi.fn()) {
  vi.spyOn(boqApi, 'positionCopilotHistory').mockResolvedValue([]);
  vi.spyOn(boqApi, 'positionCopilotChat').mockResolvedValue({
    assistant_message: {
      id: 'msg-1',
      role: 'assistant',
      content: 'Two suggestions.',
      actions: ACTIONS,
      created_at: '2026-09-28T00:00:00Z',
    },
    actions: ACTIONS,
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    createElement(
      QueryClientProvider,
      { client },
      createElement(AIPositionCopilot, {
        boqId: 'boq-1',
        positionId: 'pos-1',
        position: POSITION,
        isOpen: true,
        onClose: () => {},
        onReviewApplied,
      }),
    ),
  );
  return onReviewApplied;
}

async function askForSuggestions() {
  const input = await screen.findByRole('textbox');
  fireEvent.change(input, { target: { value: 'tidy this' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  await screen.findByTestId('copilot-review-list');
}

describe('position copilot review list', () => {
  it('shows suggestions without applying them, confident ones preselected', async () => {
    const review = vi.spyOn(boqApi, 'positionCopilotReview');
    const onReviewApplied = renderCopilot();
    await askForSuggestions();

    expect(screen.getAllByTestId('copilot-action-card')).toHaveLength(2);
    const boxes = screen.getAllByRole('checkbox') as HTMLInputElement[];
    expect(boxes.map((b) => b.checked)).toEqual([true, false]);
    expect(review).not.toHaveBeenCalled();
    expect(onReviewApplied).not.toHaveBeenCalled();
  });

  it('applies only the accepted suggestion and mirrors the result once', async () => {
    const updated = { ...POSITION, quantity: 42 } as Position;
    const review = vi.spyOn(boqApi, 'positionCopilotReview').mockResolvedValue({
      position: updated,
      message: {
        id: 'msg-1',
        role: 'assistant',
        content: 'Two suggestions.',
        actions: [ACTIONS[0]!, { ...ACTIONS[1]!, status: 'applied' }],
        created_at: '2026-09-28T00:00:00Z',
      },
    });
    const onReviewApplied = renderCopilot();
    await askForSuggestions();

    fireEvent.click(screen.getAllByRole('button', { name: 'Accept' })[1]!);

    await waitFor(() => expect(onReviewApplied).toHaveBeenCalledTimes(1));
    expect(review).toHaveBeenCalledWith('pos-1', 'msg-1', [1], []);
    expect(onReviewApplied).toHaveBeenCalledWith(updated);
  });

  it('rejects all open suggestions without mirroring anything', async () => {
    const review = vi.spyOn(boqApi, 'positionCopilotReview').mockResolvedValue({
      position: POSITION,
      message: {
        id: 'msg-1',
        role: 'assistant',
        content: 'Two suggestions.',
        actions: ACTIONS.map((a) => ({ ...a, status: 'dismissed' as const })),
        created_at: '2026-09-28T00:00:00Z',
      },
    });
    const onReviewApplied = renderCopilot();
    await askForSuggestions();

    fireEvent.click(screen.getByRole('button', { name: 'Reject all' }));

    await waitFor(() => expect(review).toHaveBeenCalledWith('pos-1', 'msg-1', [], [0, 1]));
    await waitFor(() => expect(screen.queryAllByRole('button', { name: 'Accept' })).toHaveLength(0));
    expect(onReviewApplied).not.toHaveBeenCalled();
  });
});
