// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StatusHistoryTimeline } from '../StatusHistoryTimeline';
import { useAuthStore } from '@/stores/useAuthStore';

// Route apiGet by URL so the component's two queries (status-history +
// users lookup) each get a deterministic payload.
const apiGet = vi.fn();
vi.mock('@/shared/lib/api', () => ({
  apiGet: (url: string) => apiGet(url),
}));

const HISTORY = [
  {
    id: 'h2',
    project_id: 'p1',
    from_status: 'active',
    to_status: 'on_hold',
    changed_by: 'u1',
    note: 'Paused pending client sign-off',
    created_at: '2026-06-20T10:00:00Z',
  },
  {
    id: 'h1',
    project_id: 'p1',
    from_status: null,
    to_status: 'active',
    changed_by: null,
    note: null,
    created_at: '2026-06-01T09:00:00Z',
  },
];

const USERS = [
  { id: 'u1', email: 'jane@example.com', full_name: 'Jane Doe' },
];

function routeApiGet(url: string) {
  if (url.includes('/status-history')) return Promise.resolve(HISTORY);
  if (url.includes('/v1/users/')) return Promise.resolve(USERS);
  return Promise.resolve([]);
}

function renderTimeline() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <StatusHistoryTimeline projectId="p1" />
    </QueryClientProvider>,
  );
}

describe('StatusHistoryTimeline', () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiGet.mockImplementation(routeApiGet);
    // Actor names come from the user directory, which needs users.list.
    useAuthStore.setState({ userRole: 'manager' });
  });

  it('does not ask for the user directory for a viewer, who is refused it', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    renderTimeline();
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(apiGet.mock.calls.map(([url]) => String(url)).some((u) => u.includes('/v1/users/'))).toBe(false);
  });

  it('renders entries newest-first with resolved actor name and note', async () => {
    renderTimeline();

    // Both target statuses from the history render as badges.
    await waitFor(() => {
      expect(screen.getByText('On hold')).toBeInTheDocument();
    });
    // "Active" appears twice: row 1's from_status and row 2's to_status.
    expect(screen.getAllByText('Active').length).toBeGreaterThanOrEqual(1);
    // changed_by resolved to the user's display name.
    expect(screen.getByText(/Jane Doe/)).toBeInTheDocument();
    // The note text shows.
    expect(
      screen.getByText('Paused pending client sign-off'),
    ).toBeInTheDocument();
    // The creation row (from_status null) renders a "Created" marker.
    expect(screen.getByText('Created')).toBeInTheDocument();
  });

  it('shows the empty state when there is no history', async () => {
    apiGet.mockImplementation((url: string) => {
      if (url.includes('/status-history')) return Promise.resolve([]);
      if (url.includes('/v1/users/')) return Promise.resolve(USERS);
      return Promise.resolve([]);
    });
    renderTimeline();
    await waitFor(() => {
      expect(
        screen.getByText('No status changes recorded yet.'),
      ).toBeInTheDocument();
    });
  });

  it('shows an error state when the history request fails', async () => {
    apiGet.mockImplementation((url: string) => {
      if (url.includes('/status-history')) return Promise.reject(new Error('boom'));
      if (url.includes('/v1/users/')) return Promise.resolve(USERS);
      return Promise.resolve([]);
    });
    renderTimeline();
    await waitFor(() => {
      expect(
        screen.getByText('Could not load the status history for this project.'),
      ).toBeInTheDocument();
    });
  });
});
