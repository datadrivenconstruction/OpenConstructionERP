// @ts-nocheck
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import type { QueuedOp } from '@/shared/lib/offline';
import { SyncQueuePanel, type SyncQueuePanelState } from './SyncQueuePanel';

const NOW = 1_000_000_000;

function op(over: Partial<QueuedOp> = {}): QueuedOp {
  return {
    seq: 1,
    clientOpId: 'op-1',
    method: 'POST',
    path: '/v1/field-diary/entries/',
    body: { x: 1 },
    kind: 'field.diary.entry',
    queuedAt: NOW - 5 * 60_000,
    retries: 0,
    ...over,
  };
}

function buildState(over: Partial<SyncQueuePanelState> = {}): SyncQueuePanelState {
  return {
    online: true,
    pendingOps: [],
    syncing: false,
    syncNow: vi.fn().mockResolvedValue(null),
    discard: vi.fn().mockResolvedValue(undefined),
    ...over,
  };
}

describe('SyncQueuePanel', () => {
  it('renders the empty state when nothing is queued', () => {
    render(<SyncQueuePanel state={buildState()} now={NOW} />);
    expect(screen.getByTestId('sync-queue-empty')).toBeInTheDocument();
    expect(screen.getByText('Everything is synced')).toBeInTheDocument();
    expect(screen.queryByTestId('sync-queue-list')).not.toBeInTheDocument();
    // Sync-now is disabled when empty.
    expect(screen.getByTestId('sync-queue-sync-now')).toBeDisabled();
  });

  it('lists pending and failing ops with type, relative time and status', () => {
    const state = buildState({
      pendingOps: [
        op({ clientOpId: 'a', kind: 'field.diary.entry', retries: 0, queuedAt: NOW - 5 * 60_000 }),
        op({ clientOpId: 'b', kind: 'field.crew.punch', retries: 3, queuedAt: NOW - 2 * 3_600_000 }),
      ],
    });
    render(<SyncQueuePanel state={state} now={NOW} />);

    const rows = screen.getAllByTestId('sync-queue-row');
    expect(rows).toHaveLength(2);
    // Failing op sorts first.
    expect(rows[0]).toHaveAttribute('data-status', 'failing');
    expect(rows[1]).toHaveAttribute('data-status', 'pending');

    // Failing row: friendly type label + retry status + relative time.
    expect(within(rows[0]).getByText('Crew punch')).toBeInTheDocument();
    expect(within(rows[0]).getByTestId('sync-queue-row-status')).toHaveTextContent('Retry 3');
    expect(within(rows[0]).getByText('2 h ago')).toBeInTheDocument();

    // Pending row: waiting status.
    expect(within(rows[1]).getByText('Diary entry')).toBeInTheDocument();
    expect(within(rows[1]).getByTestId('sync-queue-row-status')).toHaveTextContent('Waiting');
    expect(within(rows[1]).getByText('5 min ago')).toBeInTheDocument();

    // Total badge reflects the count.
    expect(screen.getByTestId('sync-queue-total')).toHaveTextContent('2');
  });

  it('calls discard with the op id when a row is dismissed', () => {
    const discard = vi.fn().mockResolvedValue(undefined);
    const state = buildState({ pendingOps: [op({ clientOpId: 'kill-me' })], discard });
    render(<SyncQueuePanel state={state} now={NOW} />);

    fireEvent.click(screen.getByTestId('sync-queue-dismiss'));
    expect(discard).toHaveBeenCalledWith('kill-me');
  });

  it('calls syncNow when the sync-now button is pressed', () => {
    const syncNow = vi.fn().mockResolvedValue(null);
    const state = buildState({ pendingOps: [op()], syncNow });
    render(<SyncQueuePanel state={state} now={NOW} />);

    fireEvent.click(screen.getByTestId('sync-queue-sync-now'));
    expect(syncNow).toHaveBeenCalledTimes(1);
  });

  it('disables sync-now and shows the offline hint when offline', () => {
    const state = buildState({ online: false, pendingOps: [op()] });
    render(<SyncQueuePanel state={state} now={NOW} />);

    expect(screen.getByTestId('sync-queue-sync-now')).toBeDisabled();
    expect(screen.getByTestId('sync-queue-connectivity')).toHaveAttribute('data-state', 'offline');
    expect(
      screen.getByText(/sync automatically when you reconnect/i),
    ).toBeInTheDocument();
  });

  it('summarises pending vs failing counts in the status line', () => {
    const state = buildState({
      pendingOps: [
        op({ clientOpId: 'a', retries: 0 }),
        op({ clientOpId: 'b', retries: 0 }),
        op({ clientOpId: 'c', retries: 1 }),
      ],
    });
    render(<SyncQueuePanel state={state} now={NOW} />);
    expect(screen.getByText('2 waiting, 1 need attention')).toBeInTheDocument();
  });
});

describe('SyncQueuePanel: offline gaps', () => {
  it('lists crew-time items beside the field queue and keeps them out of dismissal', () => {
    const state = buildState({
      pendingOps: [op({ clientOpId: 'a', kind: 'field.ncr' })],
      extraItems: [
        { clientOpId: 't1', kind: 'field_time', method: 'POST', path: '/x', queuedAt: NOW - 60_000, retries: 0, status: 'pending' },
      ],
    });
    render(<SyncQueuePanel state={state} now={NOW} />);
    expect(screen.getAllByTestId('sync-queue-row')).toHaveLength(2);
    expect(screen.getByTestId('sync-queue-total')).toHaveTextContent('2');
    expect(screen.getAllByTestId('sync-queue-dismiss')).toHaveLength(1);
    expect(screen.getByText('Non-conformance')).toBeInTheDocument();
    expect(screen.getByText('Crew time')).toBeInTheDocument();
  });

  it('explains an op the server refused as too old', () => {
    const state = buildState({
      lastResults: [{ clientOpId: 'z', kind: 'field.ncr', status: 'rejected', detail: 'op_too_old' }],
    });
    render(<SyncQueuePanel state={state} now={NOW} />);
    expect(screen.getByTestId('sync-queue-refused')).toHaveTextContent('Too old to sync (over 30 days)');
  });

  it('shows held captures of other users with export and a confirmed discard', () => {
    const discardHeld = vi.fn().mockResolvedValue(undefined);
    const exportHeld = vi.fn().mockResolvedValue('{}');
    const state = buildState({
      heldOps: [
        op({ clientOpId: 'h1', owner: { userId: 'u2', label: 'b@site.test' } }),
        op({ clientOpId: 'h2', owner: { userId: '' } }),
      ],
      exportHeld,
      discardHeld,
    });
    render(<SyncQueuePanel state={state} now={NOW} />);
    expect(screen.getByTestId('sync-queue-held')).toBeInTheDocument();
    expect(screen.getAllByTestId('sync-queue-held-owner')).toHaveLength(2);
    fireEvent.click(screen.getByTestId('sync-queue-held-discard'));
    expect(discardHeld).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('sync-queue-held-discard-yes'));
    expect(discardHeld).toHaveBeenCalledTimes(1);
  });

  it('shows no held section when nothing is held', () => {
    render(<SyncQueuePanel state={buildState({ heldOps: [] })} now={NOW} />);
    expect(screen.queryByTestId('sync-queue-held')).not.toBeInTheDocument();
  });
});
