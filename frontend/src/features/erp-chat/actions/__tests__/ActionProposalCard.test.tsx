// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The proposal card: what it shows before a decision, what each button sends,
 * and how a refused or failed write reads to the person who clicked.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { TFunction } from 'i18next';
import { ApiError } from '@/shared/lib/api';

const navigateSpy = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => navigateSpy };
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
import { ActionProposalCard, ActionProposalRenderer, undoConfirmMessage } from '../ActionProposalCard';
import { useChatActionStore } from '../useChatActions';
import { RENDERER_REGISTRY } from '../../full-page/right/renderers';
import { appliedAction, makeAction, renderWithClient } from './fixtures';

beforeEach(() => {
  useChatActionStore.getState().reset();
  navigateSpy.mockReset();
  for (const fn of Object.values(api)) vi.mocked(fn as (...args: unknown[]) => unknown).mockReset();
  vi.mocked(api.getChatAction).mockImplementation(async (id: string) => makeAction({ id }));
});

describe('before a decision', () => {
  it('shows the title, subtitle, every field and old -> new for the changed one', () => {
    renderWithClient(<ActionProposalCard action={makeAction()} />);
    expect(screen.getByRole('heading', { name: 'Update BOQ position' })).toBeInTheDocument();
    expect(screen.getByText('Structural works · Residential House')).toBeInTheDocument();
    expect(screen.getByText('Waiting for review')).toBeInTheDocument();

    const table = screen.getByTestId('action-field-table');
    expect(within(table).getByText('Concrete C30/37 for the level 3 slab')).toBeInTheDocument();
    const qtyRow = table.querySelector('[data-field-key="quantity"]') as HTMLElement;
    expect(qtyRow.dataset.changed).toBe('true');
    expect(within(qtyRow).getByTestId('field-before')).toHaveTextContent('80 m³');
    expect(within(qtyRow).getByTestId('field-after')).toHaveTextContent('120 m³');
    // An unchanged value is shown once, without a strike-through.
    const rateRow = table.querySelector('[data-field-key="unit_rate"]') as HTMLElement;
    expect(rateRow.dataset.changed).toBeUndefined();
    expect(within(rateRow).queryByTestId('field-before')).toBeNull();
  });

  it('says nothing is saved yet and explains the confidence on request', () => {
    renderWithClient(<ActionProposalCard action={makeAction()} />);
    expect(screen.getByText(/Nothing is saved until you click Apply/)).toBeInTheDocument();
    expect(screen.getByText('High confidence')).toBeInTheDocument();
    expect(screen.queryByText(/slab drawing gives 120/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Why?' }));
    expect(screen.getByText(/slab drawing gives 120/)).toBeInTheDocument();
  });

  it('tells a person who may not apply it why the button is missing', () => {
    renderWithClient(<ActionProposalCard action={makeAction({ can_apply: false, can_edit: false })} />);
    expect(screen.queryByTestId('action-apply')).toBeNull();
    expect(screen.getByText(/You cannot apply this change in this project/)).toBeInTheDocument();
  });

  it("gives the server's reason when it names one", () => {
    renderWithClient(
      <ActionProposalCard
        action={makeAction({
          can_apply: false,
          can_edit: false,
          blocked_reason_key: 'erp_chat.action.blocked.permission',
          blocked_reason:
            'You do not have permission to make this change. Someone with the right role in this project can apply it.',
        })}
      />,
    );
    expect(screen.getByTestId('action-blocked-reason')).toHaveTextContent(
      /Someone with the right role in this project can apply it/,
    );
  });

  it('shows a note under the field it is about, and a general note below the fields', () => {
    renderWithClient(
      <ActionProposalCard
        action={makeAction({
          notes: [
            {
              key: 'erp_chat.action.note.quantity_jump',
              text: 'The quantity grows by half.',
              params: {},
              field: 'quantity',
              tone: 'warning',
            },
            {
              key: 'erp_chat.action.note.total_recalculated',
              text: 'The bill total is recalculated.',
              params: {},
              field: null,
              tone: 'info',
            },
          ],
        })}
      />,
    );
    const table = screen.getByTestId('action-field-table');
    const qtyRow = table.querySelector('[data-field-key="quantity"]') as HTMLElement;
    const fieldNote = within(qtyRow).getByTestId('action-note');
    expect(fieldNote).toHaveTextContent('The quantity grows by half.');
    expect(fieldNote).toHaveAttribute('data-tone', 'warning');
    const notes = screen.getAllByTestId('action-note');
    expect(notes).toHaveLength(2);
    const general = notes.find((n) => n !== fieldNote)!;
    expect(general).toHaveTextContent('The bill total is recalculated.');
    expect(table).not.toContainElement(general);
  });
});

describe('Apply', () => {
  it('sends one request, then shows who applied it and opens the record in-app', async () => {
    vi.mocked(api.applyChatAction).mockResolvedValue(appliedAction());
    renderWithClient(<ActionProposalCard action={makeAction()} />);

    const apply = screen.getByTestId('action-apply');
    fireEvent.click(apply);
    fireEvent.click(apply);

    expect(await screen.findByText(/Applied by Ben Keller/)).toBeInTheDocument();
    expect(api.applyChatAction).toHaveBeenCalledTimes(1);
    expect(api.applyChatAction).toHaveBeenCalledWith('act-1');
    expect(screen.getByText('Applied')).toBeInTheDocument();
    expect(screen.queryByTestId('action-apply')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Open Position 03.012' }));
    expect(navigateSpy).toHaveBeenCalledWith('/boq/boq-9?highlight=pos-1');
  });

  it('shows the busy word while the request is in flight', async () => {
    let resolve!: (a: ReturnType<typeof appliedAction>) => void;
    vi.mocked(api.applyChatAction).mockImplementation(() => new Promise((r) => (resolve = r)));
    renderWithClient(<ActionProposalCard action={makeAction()} />);
    fireEvent.click(screen.getByTestId('action-apply'));
    expect(await screen.findAllByText('Applying…')).not.toHaveLength(0);
    expect(screen.getByTestId('action-reject')).toBeDisabled();
    resolve(appliedAction());
    expect(await screen.findByText(/Applied by Ben Keller/)).toBeInTheDocument();
  });

  it.each([
    ['locked', /bill of quantities is locked/],
    ['target_changed', /changed this record after the assistant prepared the change/],
  ])('explains a refused apply with code %s', async (code, message) => {
    vi.mocked(api.applyChatAction).mockRejectedValue(new ApiError(409, 'Conflict', { detail: { code, message: 'x' } }));
    renderWithClient(<ActionProposalCard action={makeAction()} />);
    fireEvent.click(screen.getByTestId('action-apply'));
    const alert = await screen.findByTestId('action-request-error');
    expect(alert).toHaveTextContent(message);
    // The card re-reads the server copy after a conflict.
    await waitFor(() => expect(api.getChatAction).toHaveBeenCalledWith('act-1'));
  });

  it('shows a failed write with its reason and a Retry', async () => {
    vi.mocked(api.applyChatAction).mockResolvedValue(
      appliedAction({ status: 'failed', error: 'Ordinal 03.012 already exists in this bill.', error_code: 'duplicate_ordinal', can_apply: true, can_edit: true, can_reject: true, can_revert: false, decided_by: null, decided_at: null, result: null }),
    );
    renderWithClient(<ActionProposalCard action={makeAction()} />);
    fireEvent.click(screen.getByTestId('action-apply'));
    expect(await screen.findByText('This change could not be applied')).toBeInTheDocument();
    expect(screen.getByText('Ordinal 03.012 already exists in this bill.')).toBeInTheDocument();
    const retry = screen.getByRole('button', { name: 'Retry' });
    vi.mocked(api.applyChatAction).mockResolvedValue(appliedAction({ updated_at: '2026-09-23T10:09:00Z' }));
    fireEvent.click(retry);
    await waitFor(() => expect(api.applyChatAction).toHaveBeenCalledTimes(2));
  });
});

describe('Edit', () => {
  it('sends only the keys the person changed, parsed in their convention', async () => {
    vi.mocked(api.patchChatAction).mockImplementation(async (id: string) =>
      makeAction({ id, edited: true, updated_at: '2026-09-23T10:03:00Z' }),
    );
    renderWithClient(<ActionProposalCard action={makeAction()} />);
    fireEvent.click(screen.getByTestId('action-edit'));
    const form = screen.getByTestId('action-edit-form');
    const qty = within(form).getByLabelText(/Quantity/);
    expect(qty).toHaveValue('120');
    fireEvent.change(qty, { target: { value: '1.234,5' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(api.patchChatAction).toHaveBeenCalledTimes(1));
    expect(api.patchChatAction).toHaveBeenCalledWith('act-1', { quantity: 1234.5 });
    await waitFor(() => expect(screen.queryByTestId('action-edit-form')).toBeNull());
    expect(screen.getByText('Edited by a person')).toBeInTheDocument();
  });

  it('sends nothing when nothing changed and closes the form', () => {
    renderWithClient(<ActionProposalCard action={makeAction()} />);
    fireEvent.click(screen.getByTestId('action-edit'));
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(api.patchChatAction).not.toHaveBeenCalled();
    expect(screen.queryByTestId('action-edit-form')).toBeNull();
  });

  it('keeps the form open and marks a required field left empty', () => {
    renderWithClient(<ActionProposalCard action={makeAction()} />);
    fireEvent.click(screen.getByTestId('action-edit'));
    const description = screen.getByLabelText(/Description/);
    fireEvent.change(description, { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(api.patchChatAction).not.toHaveBeenCalled();
    expect(screen.getByText('This field is required.')).toBeInTheDocument();
    expect(description).toHaveAttribute('aria-invalid', 'true');
  });

  it('shows server field errors under the matching input', async () => {
    vi.mocked(api.patchChatAction).mockRejectedValue(
      new ApiError(422, 'Unprocessable', { detail: [{ loc: ['body', 'payload', 'quantity'], msg: 'must be greater than 0' }] }),
    );
    renderWithClient(<ActionProposalCard action={makeAction()} />);
    fireEvent.click(screen.getByTestId('action-edit'));
    fireEvent.change(screen.getByLabelText(/Quantity/), { target: { value: '-5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByText('must be greater than 0')).toBeInTheDocument();
    expect(screen.getByTestId('action-edit-form')).toBeInTheDocument();
  });
});

describe('Reject and Undo', () => {
  it('rejects and shows who did it', async () => {
    vi.mocked(api.rejectChatAction).mockResolvedValue(
      makeAction({ status: 'rejected', decided_by: { id: 'u-2', name: 'Ben Keller' }, decided_at: '2026-09-23T10:04:00Z', can_apply: false, can_edit: false, can_reject: false, updated_at: '2026-09-23T10:04:00Z' }),
    );
    renderWithClient(<ActionProposalCard action={makeAction()} />);
    fireEvent.click(screen.getByTestId('action-reject'));
    expect(await screen.findByText(/Rejected by Ben Keller/)).toBeInTheDocument();
    expect(api.rejectChatAction).toHaveBeenCalledWith('act-1', undefined);
    // A rejected card folds its fields away until asked.
    expect(screen.queryByTestId('action-field-table')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Show details' }));
    expect(screen.getByTestId('action-field-table')).toBeInTheDocument();
  });

  it('confirms an undo, shows the side-effect hint, and explains a refusal', async () => {
    vi.mocked(api.revertChatAction).mockRejectedValue(
      new ApiError(409, 'Conflict', { detail: { code: 'changed_since_apply' } }),
    );
    vi.mocked(api.getChatAction).mockResolvedValue(appliedAction());
    renderWithClient(
      <ActionProposalCard action={appliedAction({ revert_hint_key: 'erp_chat.action.revert_hint.rfi_number' })} />,
    );
    fireEvent.click(screen.getByTestId('action-undo'));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent(/goes back to how it was/);
    expect(dialog).toHaveTextContent(/cannot be taken back automatically/);
    fireEvent.click(within(dialog).getByTestId('confirm-dialog-confirm'));

    await waitFor(() => expect(api.revertChatAction).toHaveBeenCalledWith('act-1', undefined));
    expect(await screen.findByTestId('action-request-error')).toHaveTextContent(/edited after the change was applied/);
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
  });
});

describe('undo wording', () => {
  const echoT = ((key: string, opts?: { defaultValue?: unknown }) =>
    String(opts?.defaultValue ?? key)) as unknown as TFunction;

  it('adds the side effect the server named to the confirmation', () => {
    const message = undoConfirmMessage(
      appliedAction({
        revert_hint_key: 'erp_chat.action.revert_hint.rfi_number',
        revert_hint: 'The RFI number stays taken.',
      }),
      echoT,
    );
    expect(message).toMatch(/goes back to how it was/);
    expect(message).toMatch(/The RFI number stays taken\.$/);
    expect(undoConfirmMessage(appliedAction(), echoT)).not.toMatch(/RFI/);
  });
});

describe('chat renderer registry', () => {
  it('renders action_proposal through the card, and says so when the payload is not a proposal', () => {
    expect(RENDERER_REGISTRY.action_proposal).toBe(ActionProposalRenderer);
    renderWithClient(<ActionProposalRenderer data={makeAction()} />);
    expect(screen.getByTestId('action-proposal-card')).toHaveAttribute('data-action-status', 'proposed');
  });

  it('shows a readable line for a payload that is not a proposal', () => {
    render(<ActionProposalRenderer data={{ nope: true }} />);
    expect(screen.getByText('This proposed change could not be shown.')).toBeInTheDocument();
  });

  it('prefers the newer copy from the store over a stale transcript snapshot', () => {
    useChatActionStore.getState().upsert(appliedAction());
    renderWithClient(<ActionProposalCard action={makeAction()} />);
    expect(screen.getByText(/Applied by Ben Keller/)).toBeInTheDocument();
  });
});
