// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Move the slab pour by two days", said into the composer, comes back as a
 * card: old and new dates, the confidence, the activity it targets, and
 * nothing written until Apply; after Apply it can be undone.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => vi.fn() };
});

vi.mock('../api', () => ({
  listChatActions: vi.fn(),
  getChatAction: vi.fn(),
  patchChatAction: vi.fn(),
  applyChatAction: vi.fn(),
  rejectChatAction: vi.fn(),
  applyChatActionsBatch: vi.fn(),
  revertChatAction: vi.fn(),
}));

import * as api from '../api';
import { ActionProposalCard } from '../ActionProposalCard';
import { useChatActionStore } from '../useChatActions';
import { appliedAction, makeAction, renderWithClient } from './fixtures';
import type { ChatAction } from '../types';

function shift(overrides: Partial<ChatAction> = {}): ChatAction {
  return makeAction({
    id: 'act-shift',
    action_type: 'schedule.shift_activity',
    title: 'Move schedule activity',
    title_key: 'erp_chat.action.type.schedule.shift_activity',
    summary: null,
    subtitle: 'Master programme',
    confidence: 0.92,
    rationale: 'You asked to move the slab pour by two days.',
    fields: [
      {
        key: 'start_date',
        label_key: 'erp_chat.action.field.start_date',
        label: 'Start',
        kind: 'date',
        value: '2027-03-03',
        before: '2027-03-01',
        editable: true,
        required: true,
      },
      {
        key: 'end_date',
        label_key: 'erp_chat.action.field.end_date',
        label: 'Finish',
        kind: 'date',
        value: '2027-03-07',
        before: '2027-03-05',
        editable: true,
        required: true,
      },
    ],
    payload: { activity_id: 'a-1', start_date: '2027-03-03', end_date: '2027-03-07' },
    original_payload: { activity_id: 'a-1', start_date: '2027-03-03', end_date: '2027-03-07' },
    target: { entity_type: 'activity', entity_id: 'a-1', label: '3.4 Slab pour level 3', url: '/schedule?project_id=p-1' },
    notes: [
      {
        key: 'erp_chat.action.note.successors_not_moved',
        text: 'Only this activity moves. Activities linked to it keep their dates until the schedule is recalculated.',
        params: {},
        field: null,
        tone: 'info',
      },
    ],
    ...overrides,
  } as Partial<ChatAction>);
}

beforeEach(() => {
  useChatActionStore.getState().reset();
  for (const fn of Object.values(api)) vi.mocked(fn as (...args: unknown[]) => unknown).mockReset();
  vi.mocked(api.getChatAction).mockImplementation(async (id: string) => shift({ id }));
});

describe('a schedule move proposed from speech', () => {
  it('shows old and new start and finish, the confidence and the activity, and writes nothing yet', () => {
    renderWithClient(<ActionProposalCard action={shift()} />);
    expect(screen.getByRole('heading', { name: 'Move schedule activity' })).toBeInTheDocument();

    const table = screen.getByTestId('action-field-table');
    for (const key of ['start_date', 'end_date']) {
      const row = table.querySelector(`[data-field-key="${key}"]`) as HTMLElement;
      expect(row.dataset.changed).toBe('true');
      expect(within(row).getByTestId('field-before')).toBeInTheDocument();
      expect(within(row).getByTestId('field-after')).toBeInTheDocument();
    }
    expect(screen.getByText('92%')).toBeInTheDocument();
    expect(screen.getByText(/Only this activity moves/)).toBeInTheDocument();
    expect(screen.getByTestId('action-apply')).toBeEnabled();
    expect(screen.getByTestId('action-reject')).toBeEnabled();
    expect(api.applyChatAction).not.toHaveBeenCalled();
  });

  it('Apply sends the one change, and the applied card offers Undo', async () => {
    vi.mocked(api.applyChatAction).mockResolvedValue(
      appliedAction({ ...shift(), status: 'applied', can_apply: false, can_reject: false, can_edit: false, can_revert: true }),
    );
    renderWithClient(<ActionProposalCard action={shift()} />);
    fireEvent.click(screen.getByTestId('action-apply'));
    await waitFor(() => expect(api.applyChatAction).toHaveBeenCalledWith('act-shift'));
    expect(await screen.findByTestId('action-undo')).toBeInTheDocument();
  });
});
