// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const runSync = vi.fn().mockResolvedValue(null);
vi.mock('@/shared/lib/offline/recordSync', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/offline/recordSync')>(
    '@/shared/lib/offline/recordSync',
  );
  return {
    ...actual,
    runSync: (...a: unknown[]) => runSync(...a),
    refreshSyncCounts: vi.fn().mockResolvedValue(undefined),
    listConflicts: vi.fn().mockResolvedValue([]),
  };
});
vi.mock('@/shared/lib/api', () => ({ fetchWithAuth: vi.fn(), apiGet: vi.fn() }));

import { SyncStatusPill } from './SyncStatusPill';
import { patchOfflineSync, resetOfflineSyncStoreForTests } from '@/shared/lib/offline/offlineSyncStore';

function renderPill() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <SyncStatusPill />
    </QueryClientProvider>,
  );
}

const state = () => screen.getByTestId('sync-status-pill').getAttribute('data-state');

describe('SyncStatusPill', () => {
  beforeEach(() => {
    resetOfflineSyncStoreForTests();
    runSync.mockClear();
  });

  it('shows synced when nothing waits', () => {
    renderPill();
    expect(state()).toBe('online-synced');
    expect(screen.getByTestId('sync-status-label')).toHaveTextContent('Synced');
  });

  it('shows offline, ahead of pending work', () => {
    renderPill();
    act(() => patchOfflineSync({ online: false, pending: 3 }));
    expect(state()).toBe('offline');
    expect(screen.getByTestId('sync-status-label')).toHaveTextContent('Offline');
  });

  it('shows the waiting count and syncs on tap', () => {
    renderPill();
    act(() => patchOfflineSync({ pending: 2 }));
    expect(state()).toBe('pending');
    expect(screen.getByTestId('sync-status-label')).toHaveTextContent('2');
    runSync.mockClear();
    fireEvent.click(screen.getByTestId('sync-status-pill'));
    expect(runSync).toHaveBeenCalledWith({ manual: true });
  });

  it('uses the singular for one waiting change', () => {
    renderPill();
    act(() => patchOfflineSync({ pending: 1 }));
    expect(screen.getByTestId('sync-status-label')).toHaveTextContent(/^1 change waiting$/);
  });

  it('shows syncing while a drain runs', () => {
    renderPill();
    act(() => patchOfflineSync({ syncing: true, pending: 2 }));
    expect(state()).toBe('syncing');
  });

  it('shows an error with the refused changes, which can be dismissed', () => {
    renderPill();
    act(() =>
      patchOfflineSync({
        problems: [{ clientOpId: 'op-1', kind: 'punch', detail: 'title is required', httpStatus: 422 }],
      }),
    );
    expect(state()).toBe('error');
    fireEvent.click(screen.getByTestId('sync-status-pill'));
    expect(screen.getByTestId('sync-problems')).toHaveTextContent('title is required');
    fireEvent.click(screen.getByLabelText('Dismiss'));
    expect(state()).toBe('online-synced');
  });

  it('shows a conflict above everything else', () => {
    renderPill();
    act(() => patchOfflineSync({ online: false, syncing: true, pending: 2, conflicts: 1 }));
    expect(state()).toBe('conflict');
    expect(screen.getByTestId('sync-status-label')).toHaveTextContent('Needs merge');
  });

  it('keeps a 44px touch target', () => {
    renderPill();
    const cls = screen.getByTestId('sync-status-pill').className;
    expect(cls).toContain('min-h-[44px]');
    expect(cls).toContain('min-w-[44px]');
  });
});
