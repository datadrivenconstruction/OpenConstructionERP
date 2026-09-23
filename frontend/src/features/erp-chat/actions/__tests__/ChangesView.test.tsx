// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The Changes ledger: which request each filter and scope sends, how rows read,
 * and that the inline buttons act on the right proposal.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';

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
import { ChangesView } from '../ChangesView';
import { useChatActionStore } from '../useChatActions';
import type { ChatActionListResponse } from '../types';
import { appliedAction, makeAction, renderWithClient } from './fixtures';

function page(overrides: Partial<ChatActionListResponse> = {}): ChatActionListResponse {
  return {
    items: [
      makeAction({ id: 'w-1', created_at: '2026-09-23T09:00:00Z', updated_at: '2026-09-23T09:00:00Z' }),
      appliedAction({ id: 'a-1', created_at: '2026-09-22T15:00:00Z', decided_at: '2026-09-22T15:10:00Z', updated_at: '2026-09-22T15:10:00Z' }),
    ],
    total: 2,
    counts: { proposed: 1, applied: 1, rejected: 3, failed: 0, reverted: 0 },
    ...overrides,
  };
}

beforeEach(() => {
  useChatActionStore.getState().reset();
  navigateSpy.mockReset();
  vi.mocked(api.listChatActions).mockReset();
  vi.mocked(api.applyChatAction).mockReset();
  vi.mocked(api.listChatActions).mockResolvedValue(page());
});

describe('ChangesView requests', () => {
  it('asks for this project first, with no status filter', async () => {
    renderWithClient(<ChangesView projectId="p-1" projectName="Residential House" />);
    await waitFor(() => expect(api.listChatActions).toHaveBeenCalled());
    expect(vi.mocked(api.listChatActions).mock.calls[0]?.[0]).toEqual({ limit: 50, offset: 0, project_id: 'p-1' });
  });

  it('sends the status of the chosen filter and drops the project for All projects', async () => {
    renderWithClient(<ChangesView projectId="p-1" projectName="Residential House" />);
    await screen.findAllByTestId('changes-row');

    fireEvent.click(screen.getByTestId('changes-filter-proposed'));
    await waitFor(() =>
      expect(api.listChatActions).toHaveBeenLastCalledWith({ limit: 50, offset: 0, project_id: 'p-1', status: 'proposed' }),
    );

    fireEvent.click(screen.getByTestId('changes-filter-reverted'));
    await waitFor(() =>
      expect(api.listChatActions).toHaveBeenLastCalledWith({ limit: 50, offset: 0, project_id: 'p-1', status: 'reverted' }),
    );

    fireEvent.click(screen.getByTestId('changes-scope-all'));
    await waitFor(() => expect(api.listChatActions).toHaveBeenLastCalledWith({ limit: 50, offset: 0, status: 'reverted' }));

    fireEvent.click(screen.getByTestId('changes-filter-all'));
    await waitFor(() => expect(api.listChatActions).toHaveBeenLastCalledWith({ limit: 50, offset: 0 }));
  });

  it('without an active project shows every project and cannot narrow to one', async () => {
    renderWithClient(<ChangesView projectId={null} />);
    await waitFor(() => expect(api.listChatActions).toHaveBeenCalledWith({ limit: 50, offset: 0 }));
    expect(screen.getByTestId('changes-scope-project')).toBeDisabled();
    expect(screen.getByTestId('changes-scope-all')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByTestId('changes-full-history')).toBeNull();
  });
});

describe('ChangesView rows', () => {
  it('shows counts on the filters and groups rows by day with who did what', async () => {
    renderWithClient(<ChangesView projectId="p-1" projectName="Residential House" />);
    const rows = await screen.findAllByTestId('changes-row');
    expect(rows).toHaveLength(2);

    expect(screen.getByTestId('changes-filter-proposed')).toHaveTextContent('Waiting1');
    expect(screen.getByTestId('changes-filter-rejected')).toHaveTextContent('Rejected3');
    expect(screen.getByTestId('changes-filter-all')).toHaveTextContent('All5');
    // Failed is only offered when something failed.
    expect(screen.queryByTestId('changes-filter-failed')).toBeNull();

    const applied = rows[1]!;
    expect(within(applied).getByTestId('changes-row-meta')).toHaveTextContent(/Asked by Anna Schmidt · approved by Ben Keller/);
    // Two days, two headings (today and yesterday relative to the fixtures).
    expect(screen.getByTestId('changes-view').querySelectorAll('h4')).toHaveLength(2);
  });

  it('applies a waiting row inline', async () => {
    vi.mocked(api.applyChatAction).mockResolvedValue(
      appliedAction({ id: 'w-1', updated_at: '2026-09-23T09:05:00Z' }),
    );
    renderWithClient(<ChangesView projectId="p-1" />);
    const rows = await screen.findAllByTestId('changes-row');
    fireEvent.click(within(rows[0]!).getByLabelText('Apply: Update BOQ position'));
    await waitFor(() => expect(api.applyChatAction).toHaveBeenCalledWith('w-1'));
    await waitFor(() => expect(rows[0]).toHaveAttribute('data-action-status', 'applied'));
  });

  it('expands a row into the full card', async () => {
    renderWithClient(<ChangesView projectId="p-1" />);
    const rows = await screen.findAllByTestId('changes-row');
    const toggle = rows[0]!.querySelector('button[aria-expanded="false"]') as HTMLButtonElement;
    fireEvent.click(toggle);
    expect(within(rows[0]!).getByTestId('action-proposal-card')).toBeInTheDocument();
    expect(within(rows[0]!).getByTestId('action-field-table')).toBeInTheDocument();
  });

  it('links to the full project history', async () => {
    renderWithClient(<ChangesView projectId="p-1" />);
    fireEvent.click(await screen.findByTestId('changes-full-history'));
    expect(navigateSpy).toHaveBeenCalledWith('/projects/p-1/timeline');
  });

  it('says what the ledger is for when it is empty', async () => {
    vi.mocked(api.listChatActions).mockResolvedValue({
      items: [],
      total: 0,
      counts: { proposed: 0, applied: 0, rejected: 0, failed: 0, reverted: 0 },
    });
    renderWithClient(<ChangesView projectId="p-1" />);
    expect(await screen.findByText('No changes yet')).toBeInTheDocument();
    expect(screen.getByTestId('changes-empty')).toHaveTextContent(/nothing is saved until someone applies it/);
  });

  it('offers Failed only while something failed', async () => {
    vi.mocked(api.listChatActions).mockResolvedValue(
      page({ counts: { proposed: 1, applied: 1, rejected: 3, failed: 2, reverted: 0 } }),
    );
    renderWithClient(<ChangesView projectId="p-1" />);
    const failed = await screen.findByTestId('changes-filter-failed');
    expect(failed).toHaveTextContent('Failed2');
    expect(screen.getByTestId('changes-filter-all')).toHaveTextContent('All7');
    fireEvent.click(failed);
    await waitFor(() =>
      expect(api.listChatActions).toHaveBeenLastCalledWith({ limit: 50, offset: 0, project_id: 'p-1', status: 'failed' }),
    );
  });

  it('stops at the most rows the server returns and says how to find older ones', async () => {
    vi.mocked(api.listChatActions).mockResolvedValue(page({ total: 500 }));
    renderWithClient(<ChangesView projectId="p-1" />);
    for (const limit of [100, 150, 200]) {
      const more = await screen.findByTestId('changes-show-more');
      await waitFor(() => expect(more).not.toBeDisabled());
      fireEvent.click(more);
      await waitFor(() =>
        expect(api.listChatActions).toHaveBeenLastCalledWith({ limit, offset: 0, project_id: 'p-1' }),
      );
    }
    expect(await screen.findByTestId('changes-capped')).toHaveTextContent(/Filter by status to find older ones/);
    expect(screen.queryByTestId('changes-show-more')).toBeNull();
  });

  it('offers more rows when the server holds more than it sent', async () => {
    vi.mocked(api.listChatActions).mockResolvedValue(page({ total: 120 }));
    renderWithClient(<ChangesView projectId="p-1" />);
    fireEvent.click(await screen.findByTestId('changes-show-more'));
    await waitFor(() =>
      expect(api.listChatActions).toHaveBeenLastCalledWith({ limit: 100, offset: 0, project_id: 'p-1' }),
    );
  });
});
