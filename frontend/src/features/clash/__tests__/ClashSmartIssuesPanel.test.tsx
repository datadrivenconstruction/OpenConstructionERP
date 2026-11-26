// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ClashSmartIssuesPanel UI tests.
 *
 * The panel fetches ``GET /v1/clash/issues`` via ``clashApi.issues`` and
 * mutates via ``clashApi.suppressIssue`` / ``clashApi.unsuppressIssue``; we
 * mock those three methods so the tests are fully offline. React Query
 * retries are disabled so error states surface synchronously (matches the
 * ClashRunDiffBadge / ClashCostImpactColumn test convention).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  render,
  screen,
  waitFor,
  cleanup,
  fireEvent,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ── clashApi stubs ──────────────────────────────────────────────────────────
vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    clashApi: {
      ...actual.clashApi,
      issues: vi.fn(),
      suppressIssue: vi.fn(),
      unsuppressIssue: vi.fn(),
    },
  };
});

import { clashApi, type ClashIssue, type ClashIssuePage } from '../api';
import { ClashSmartIssuesPanel } from '../ClashSmartIssuesPanel';

const issuesMock = clashApi.issues as unknown as ReturnType<typeof vi.fn>;
const suppressMock = clashApi.suppressIssue as unknown as ReturnType<
  typeof vi.fn
>;
const unsuppressMock = clashApi.unsuppressIssue as unknown as ReturnType<
  typeof vi.fn
>;

function makeIssue(over: Partial<ClashIssue> = {}): ClashIssue {
  return {
    id: 'issue-1',
    project_id: 'p-1',
    signature_hash: 'abcdef0123456789',
    status: 'persisted',
    first_seen_run_id: 'run-0',
    last_seen_run_id: 'run-1',
    resolved_run_id: null,
    missing_run_count: 0,
    assignee_id: null,
    due_date: null,
    priority: 'high',
    server_assigned_id: 'CLH-001',
    tags: [],
    signature_quality: 'strong',
    member_count: 4,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-10T00:00:00Z',
    ...over,
  };
}

function page(items: ClashIssue[], total = items.length): ClashIssuePage {
  return { items, total, offset: 0, limit: 50 };
}

function renderPanel(projectId = 'p-1') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ClashSmartIssuesPanel projectId={projectId} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ userRole: 'admin' } as never);
  cleanup();
});

describe('ClashSmartIssuesPanel', () => {
  it('lists smart issues with member counts', async () => {
    issuesMock.mockResolvedValue(
      page([
        makeIssue({ id: 'i1', server_assigned_id: 'CLH-001', member_count: 4 }),
        makeIssue({
          id: 'i2',
          server_assigned_id: 'CLH-002',
          member_count: 9,
          status: 'new',
        }),
      ]),
    );
    renderPanel('proj-X');
    await screen.findByTestId('clash-issue-row-i1');
    expect(issuesMock).toHaveBeenCalledWith('proj-X', {
      status: undefined,
      offset: 0,
      limit: 50,
    });
    expect(screen.getByText('CLH-001')).toBeInTheDocument();
    expect(screen.getByText('CLH-002')).toBeInTheDocument();
    expect(screen.getByTestId('clash-issue-row-i1').textContent).toContain('4');
  });

  it('re-queries with the status filter when a chip is clicked', async () => {
    issuesMock.mockResolvedValue(page([makeIssue({ id: 'i1' })]));
    renderPanel();
    await screen.findByTestId('clash-issue-row-i1');
    fireEvent.click(screen.getByTestId('clash-issues-filter-ignored'));
    await waitFor(() =>
      expect(issuesMock).toHaveBeenCalledWith('p-1', {
        status: 'ignored',
        offset: 0,
        limit: 50,
      }),
    );
  });

  it('suppresses an issue only after a non-empty reason is entered', async () => {
    issuesMock.mockResolvedValue(page([makeIssue({ id: 'i1', status: 'new' })]));
    suppressMock.mockResolvedValue(makeIssue({ id: 'i1', status: 'ignored' }));
    renderPanel();
    await screen.findByTestId('clash-issue-row-i1');

    // Open the inline reason input.
    fireEvent.click(screen.getByTestId('clash-issue-suppress-i1'));
    const confirm = (await screen.findByTestId(
      'clash-issue-confirm-suppress-i1',
    )) as HTMLButtonElement;
    // Disabled until a reason is typed.
    expect(confirm).toBeDisabled();

    fireEvent.change(screen.getByTestId('clash-issue-reason-i1'), {
      target: { value: '  known false positive  ' },
    });
    expect(confirm).not.toBeDisabled();
    fireEvent.click(confirm);

    await waitFor(() => expect(suppressMock).toHaveBeenCalled());
    // Reason is trimmed before send.
    expect(suppressMock).toHaveBeenCalledWith(
      'p-1',
      'i1',
      'known false positive',
    );
  });

  it('shows Unsuppress for an already-suppressed issue and calls the endpoint', async () => {
    issuesMock.mockResolvedValue(
      page([makeIssue({ id: 'i1', status: 'ignored' })]),
    );
    unsuppressMock.mockResolvedValue(makeIssue({ id: 'i1', status: 'persisted' }));
    renderPanel();
    await screen.findByTestId('clash-issue-row-i1');
    // No suppress button for a suppressed row; an unsuppress one instead.
    expect(screen.queryByTestId('clash-issue-suppress-i1')).toBeNull();
    fireEvent.click(screen.getByTestId('clash-issue-unsuppress-i1'));
    await waitFor(() => expect(unsuppressMock).toHaveBeenCalledWith('p-1', 'i1'));
  });

  it('renders an empty state when there are no issues', async () => {
    issuesMock.mockResolvedValue(page([]));
    renderPanel();
    await waitFor(() => expect(issuesMock).toHaveBeenCalled());
    expect(
      await screen.findByText('No smart issues'),
    ).toBeInTheDocument();
  });

  it('renders an error state with a retry on API failure', async () => {
    issuesMock.mockRejectedValue(new Error('boom'));
    renderPanel();
    expect(
      await screen.findByText('Could not load smart issues.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });

  it('does not call the API without a projectId', async () => {
    issuesMock.mockResolvedValue(page([]));
    renderPanel('');
    // give the effect a tick
    await Promise.resolve();
    expect(issuesMock).not.toHaveBeenCalled();
  });
});
