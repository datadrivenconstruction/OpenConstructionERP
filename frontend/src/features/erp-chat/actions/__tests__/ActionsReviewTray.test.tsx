// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The review tray above the composer: it counts what is waiting, hands Review
 * back to the dock, and applies everything after one confirmation.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

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
import { ActionsReviewTray, revealFirstWaitingAction } from '../ActionsReviewTray';
import { useChatActionStore } from '../useChatActions';
import { useToastStore } from '@/stores/useToastStore';
import { appliedAction, makeAction, renderWithClient } from './fixtures';

const three = () => [
  makeAction({ id: 'a-1', title: 'Update BOQ position' }),
  makeAction({ id: 'a-2', action_type: 'task.create', title: 'Create task', title_key: null }),
  makeAction({ id: 'a-3', action_type: 'risk.create', title: 'Log risk', title_key: null, can_apply: false }),
];

beforeEach(() => {
  useChatActionStore.getState().reset();
  vi.mocked(api.applyChatActionsBatch).mockReset();
  vi.mocked(api.getChatAction).mockReset();
});

describe('ActionsReviewTray', () => {
  it('renders nothing, and needs no query client, when nothing is waiting', () => {
    const { container } = render(
      <ActionsReviewTray actions={[appliedAction({ id: 'x' })]} onReview={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
    const empty = render(<ActionsReviewTray actions={[]} onReview={() => {}} />);
    expect(empty.container).toBeEmptyDOMElement();
  });

  it('counts the waiting changes and hands Review back to the dock', () => {
    const onReview = vi.fn();
    renderWithClient(<ActionsReviewTray actions={three()} onReview={onReview} />);
    expect(screen.getByTestId('actions-review-tray-count')).toHaveTextContent('3 changes are waiting for your review');
    fireEvent.click(screen.getByTestId('actions-review-tray-review'));
    expect(onReview).toHaveBeenCalledTimes(1);
  });

  it('uses the singular for one waiting change', () => {
    renderWithClient(<ActionsReviewTray actions={[makeAction()]} onReview={() => {}} />);
    expect(screen.getByTestId('actions-review-tray-count')).toHaveTextContent('1 change is waiting for your review');
  });

  it('follows the shared store: a change applied elsewhere leaves the count', () => {
    renderWithClient(<ActionsReviewTray actions={three()} onReview={() => {}} />);
    act(() => {
      useChatActionStore.getState().upsert(appliedAction({ id: 'a-1' }), { force: true });
    });
    expect(screen.getByTestId('actions-review-tray-count')).toHaveTextContent('2 changes are waiting for your review');
  });

  it('confirms Apply all with the titles and applies only what this person may apply', async () => {
    vi.mocked(api.applyChatActionsBatch).mockResolvedValue({
      items: [appliedAction({ id: 'a-1' }), appliedAction({ id: 'a-2', action_type: 'task.create' })],
      errors: [],
    });
    const addToast = vi.spyOn(useToastStore.getState(), 'addToast');
    renderWithClient(<ActionsReviewTray actions={three()} onReview={() => {}} />);

    fireEvent.click(screen.getByTestId('actions-review-tray-apply-all'));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Apply 2 changes?');
    expect(dialog).toHaveTextContent(/Update BOQ position/);
    expect(dialog).toHaveTextContent(/Create task/);
    expect(dialog).not.toHaveTextContent(/Log risk/);
    expect(dialog).toHaveTextContent('1 change you cannot apply stays waiting.');

    fireEvent.click(within(dialog).getByTestId('confirm-dialog-confirm'));
    await waitFor(() => expect(api.applyChatActionsBatch).toHaveBeenCalledWith(['a-1', 'a-2']));
    // Only the one this person cannot apply is still waiting.
    await waitFor(() =>
      expect(screen.getByTestId('actions-review-tray-count')).toHaveTextContent('1 change is waiting for your review'),
    );
    await waitFor(() => expect(addToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success', title: '2 changes applied' })));
  });

  it('disappears once everything is applied, and still reports the result', async () => {
    const actions = [makeAction({ id: 'a-1' }), makeAction({ id: 'a-2' })];
    vi.mocked(api.applyChatActionsBatch).mockResolvedValue({
      items: [appliedAction({ id: 'a-1' }), appliedAction({ id: 'a-2', status: 'failed', error: 'Locked', can_revert: false })],
      errors: [],
    });
    const addToast = vi.spyOn(useToastStore.getState(), 'addToast');
    renderWithClient(<ActionsReviewTray actions={actions} onReview={() => {}} />);
    fireEvent.click(screen.getByTestId('actions-review-tray-apply-all'));
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByTestId('confirm-dialog-confirm'));
    await waitFor(() => expect(screen.queryByTestId('actions-review-tray')).toBeNull());
    await waitFor(() =>
      expect(addToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'warning', title: '1 of 2 changes applied' })),
    );
  });

  it('keeps a refused change waiting, with its reason, while the rest are applied', async () => {
    const actions = [makeAction({ id: 'a-1' }), makeAction({ id: 'a-2' })];
    vi.mocked(api.applyChatActionsBatch).mockResolvedValue({
      items: [appliedAction({ id: 'a-1' }), makeAction({ id: 'a-2', updated_at: '2026-09-23T10:01:00Z' })],
      errors: [
        {
          id: 'a-2',
          status_code: 409,
          code: 'locked',
          message: 'This bill of quantities is locked.',
          message_key: 'erp_chat.action.error.locked',
        },
      ],
    });
    vi.mocked(api.getChatAction).mockResolvedValue(makeAction({ id: 'a-2', updated_at: '2026-09-23T10:02:00Z' }));
    const addToast = vi.spyOn(useToastStore.getState(), 'addToast');
    renderWithClient(<ActionsReviewTray actions={actions} onReview={() => {}} />);
    fireEvent.click(screen.getByTestId('actions-review-tray-apply-all'));
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByTestId('confirm-dialog-confirm'));
    await waitFor(() =>
      expect(addToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'warning', title: '1 of 2 changes applied' })),
    );
    expect(screen.getByTestId('actions-review-tray-count')).toHaveTextContent('1 change is waiting for your review');
    expect(useChatActionStore.getState().errors['a-2']).toMatchObject({ code: 'locked', status: 409 });
  });
});

describe('revealFirstWaitingAction', () => {
  it('moves focus to the first card still waiting for a decision', () => {
    renderWithClient(
      <MemoryRouter>
        <ActionProposalCard action={appliedAction({ id: 'done' })} />
        <ActionProposalCard action={makeAction({ id: 'wait-1' })} />
        <ActionProposalCard action={makeAction({ id: 'wait-2' })} />
      </MemoryRouter>,
    );
    expect(revealFirstWaitingAction()).toBe(true);
    expect(document.activeElement).toBe(document.getElementById('erp-chat-action-wait-1'));
  });

  it('reports when there is no waiting card to show', () => {
    renderWithClient(
      <MemoryRouter>
        <ActionProposalCard action={appliedAction({ id: 'done' })} />
      </MemoryRouter>,
    );
    expect(revealFirstWaitingAction()).toBe(false);
  });
});
